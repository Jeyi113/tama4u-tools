"""Local web editor: python3 -m tama4u edit [-p PORT]

Serves editor.html and two JSON endpoints; all format logic stays in
this package so the browser is a pure view layer.
"""
import base64
import collections
import json
import os
import struct
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import (character, charset, container, convert, destinations, items,
               sprites, vdp)

HTML_PATH = os.path.join(os.path.dirname(__file__), 'editor.html')
CHARA_DIR = os.path.join(os.path.dirname(__file__), 'charasprites')

# Mr.Blinky's acposeditor ships one reference tamagotchi per body type:
# <frame>.bmp is body type 1, <frame>_1/_2/_3.bmp are types 2/3/4.
# Frames are labelled 0-14; 11 is the sleeping frame and carries no
# accessory position.
CHARA_LABELS = list(range(15))


def chara_sprites():
    """[body_type][label] -> frame dict, or None when the BMPs are absent."""
    if not os.path.isdir(CHARA_DIR):
        return None
    out = []
    for bt in range(4):
        row = []
        for label in CHARA_LABELS:
            name = f'{label}.bmp' if bt == 0 else f'{label}_{bt}.bmp'
            path = os.path.join(CHARA_DIR, name)
            if not os.path.exists(path):
                row.append(None)
                continue
            f = sprites.bmp_to_frame(open(path, 'rb').read(), 0)
            row.append({'w': f.width, 'h': f.height,
                        'palette': f.palette, 'pixels': f.pixels})
        out.append(row)
    return out


def _iter_packets(packets):
    """Yield (path, packet) depth-first; path like [0] or [0, 1]."""
    def walk(pkt, path):
        yield path, pkt
        for i, child in enumerate(pkt.children):
            yield from walk(child, path + [i])
    for i, top in enumerate(packets):
        yield from walk(top, [i])


def _find(packets, path):
    pkt = packets[path[0]]
    for i in path[1:]:
        pkt = pkt.children[i]
    return pkt


def describe(data):
    jpeg, packets, trailing = container.parse_file(data)
    out = {'jpeg_b64': base64.b64encode(jpeg).decode(), 'packets': []}
    for path, pkt in _iter_packets(packets):
        table = charset.load_table(model=pkt.model)
        info = {
            'model': pkt.model,
            'name_slots': pkt.layout['slots'],
            # class C = a character's own wardrobe/body packet nested inside
            # the character.  It carries a clothes-shop destination code as
            # boilerplate but is never routed anywhere, so its shop fields
            # (destination/price/stats/likes) are meaningless.
            'packet_class': pkt.packet_class,
            'is_wardrobe': pkt.packet_class == 'C',
            'stats_verified': (items.stats_verified(pkt)
                               and pkt.packet_class == 'S'),
            'path': path,
            'ansi_id': pkt.ansi_id,
            'kind': items.effective_kind(pkt),
            'section': pkt.section,
            'serial': pkt.serial,
            'unicode_name': pkt.unicode_name,
            'name': charset.decode(pkt.item_name_codes, table),
            'size': pkt.size,
            'dest': bytes(pkt.raw[items.OFF_DEST:items.OFF_DEST + 4]).hex(),
            'dest_label': items.get_destination(pkt),
            'dest_options': [{'label': e[0], 'code': e[1]}
                             for e in destinations.options(pkt.model)],
            'is_item': (not character.is_character(pkt)
                        and not items.is_program(pkt)
                        and (items.effective_kind(pkt) in items.BANK_OFFSETS
                             or pkt.model != '4U')),
        }
        if pkt.model == 'iD':
            info['version'] = items.get_version(pkt)
            info['version_presets'] = items.VERSION_PRESETS
        info['compat'] = items.get_compat(pkt)
        info['convert'] = {m: convert.plan(pkt, m)
                           for m in ('iD', 'iDL', "P's", '4U') if m != pkt.model}
        if info['is_item'] and not info['is_wardrobe']:
            info['price'] = items.get_price(pkt)      # verified on every model
        if not info['is_item']:
            # programs have no shop fields, but their destination is what
            # files a game under the Game Center
            info['fields'] = sorted(items.editable_fields(pkt))
        if info['is_item'] and info['stats_verified']:
            anim = items.get_anim(pkt)
            info['fields'] = sorted(items.editable_fields(pkt))
            info['likes_slots'] = items.likes_slots(pkt)
            info['likes_offset'] = pkt.layout['likes']
            info['likes_labels'] = items.like_labels(pkt)
            info['likes_roster'] = items.like_roster(pkt)
            info.update(hunger=items.get_hunger(pkt),
                        friendship=items.get_friendship(pkt),
                        likes=items.get_likes_raw(pkt),
                        stats=items.get_stats(pkt),
                        anim_a=anim[0], anim_b=anim[1])
        info['opaque'] = pkt.kind in items.OPAQUE_KINDS
        if info['is_item'] and pkt.section == items.SECTION_MAIL:
            width = pkt.layout['width']
            bank = None
            try:
                bank = sprites.scan_banks(pkt.raw, 0x60)[0][0]
            except IndexError:
                pass
            if bank:
                lo, hi = items.letter_text_range(pkt, bank)
                body = charset.scan_texts(pkt.raw, table, lo=lo, hi=hi,
                                          min_len=3, width=width)
                for i, g in enumerate(charset.group_runs(body, width)):
                    info.setdefault('texts', []).append(
                        {'parts': g['parts'], 'chars': g['chars'],
                         'text': g['text'], 'width': width,
                         'label': '편지 본문' if i == 0 else f'편지 본문 {i + 1}'})
        if items.effective_kind(pkt) == 'ac' and pkt.packet_class == 'S':
            # wear positions: 4 body types x 14 frame rows of (x, y)
            rows = items.get_acc_positions(pkt)
            if rows is not None:
                info['acc_pos'] = [[list(xy) for xy in r] for r in rows]
                info['acc_rows'] = items.ACC_ROW_TO_POSE
        # collect sprite banks: fixed offset for plain items; for program/
        # definition packets (gm, dlode, rec, minigames with odd ids) scan
        # the packet's own region for count-banks, then loose records
        banks = []
        if info['is_item']:
            off = items.bank_offset(pkt)
            try:
                frames, _ = sprites.parse_bank(pkt.raw, off)
                if frames:
                    banks.append({'offset': off, 'frames': frames})
            except (ValueError, IndexError, struct.error):
                pass
        if info['is_item'] and not banks:
            # iD / iD L / P's park some banks away from the model's usual
            # offset (games, photo studio, letters).  Fall back to a scan
            # so those files still show their sprites.
            for o, end, frames in sprites.scan_banks(pkt.raw, 0x40):
                banks.append({'offset': o, 'frames': frames})
            if not banks:
                for rec in sprites.scan_loose(pkt.raw):
                    banks.append({'offset': rec[0], 'loose': list(rec),
                                  'frames': sprites.read_loose(pkt.raw, rec)})
        if not info['is_item']:
            covered = [(c.offset, c.offset + c.size) for c in pkt.children]
            spans = list(covered)
            own = lambda a, b: not any(s <= a < e or s < b <= e
                                       for s, e in covered)
            # collect count-banks *and* loose records: program packets often
            # carry both, and taking only the first kind hid up to 50 of a
            # file's sprites (P's outings and VDPs)
            for o, end, frames in sprites.scan_banks(pkt.raw):
                if own(o, end):
                    banks.append({'offset': o, 'frames': frames})
                    covered.append((o, end))
                    spans.append((o, end))
            for rec in sprites.scan_loose(pkt.raw):
                start, w, h, ncol, nf, avail = rec
                end = start + 6 + 2 * ncol + avail
                if own(start, end):
                    banks.append({'offset': start, 'loose': list(rec),
                                  'frames': sprites.read_loose(pkt.raw, rec)})
                    covered.append((start, end))
                    spans.append((start, end))
            if character.is_character(pkt):
                # known structure: 14 fixed dialogue slots, 75 chars each
                info['texts'] = []
                for i, label in enumerate(character.DIALOGUE_LABELS):
                    off = character.OFF_DIALOGUE + i * 150
                    codes = [struct.unpack_from('>H', pkt.raw, off + 2 * k)[0]
                             for k in range(75)]
                    info['texts'].append({
                        'offset': off, 'chars': 75, 'label': label, 'width': 2,
                        'text': charset.decode(codes, table).strip('\u3000')})
                info['body_type'] = pkt.raw[character.OFF_BODY_TYPE]
                info['char_stats'] = character.get_stats(pkt)
                cs = info['char_stats']
                accpos = character.get_acc_positions(pkt)
                info['char_extra'] = {
                    'acc_pos': ([[list(xy) for xy in r] for r in accpos]
                                if accpos else None),
                    'acc_rows': character.ACC_ROW_TO_FRAME,
                    'tama_roster': character.roster(cs['tama_id']),
                    'revert_roster': character.roster(cs['revert_id']),
                    # the item's name is stored right there in the packet at
                    # 0x232 -- the serial index was ambiguous because serials
                    # restart per shop section
                    'transform_name': charset.decode(
                        [struct.unpack_from('>H', pkt.raw,
                                            character.OFF_TRANSFORM_NAME + 2 * i)[0]
                         for i in range(10)], table).strip('\u3000').strip(),
                    'name2': charset.decode(
                        [struct.unpack_from('>H', pkt.raw,
                                            character.OFF_NAME2 + 2 * i)[0]
                         for i in range(pkt.layout['slots'])], table),
                }
                info['char_enums'] = {
                    'gender': character.GENDER,
                    'stage': character.STAGE,
                    'body_type': character.body_types(pkt.model),
                    'transform_type': character.TRANSFORM_TYPE,
                    'like_index': character.LIKE_INDEX,
                }
            else:
                # dialogue is 1 byte/char on iD/iD L/P's and 2 on 4U, and it
                # only lives in the gaps between sprite records
                width = pkt.layout['width']
                gaps = items.text_gaps(spans, pkt.size)
                ratio = sum(b - a for a, b in gaps) / max(1, pkt.size)
                texts = []
                if items.scans_text(pkt) and ratio <= items.MAX_TEXT_GAP_RATIO:
                    for lo, hi in gaps:
                        if hi - lo < 8:
                            continue
                        texts += [
                            r for r in charset.scan_texts(
                                pkt.raw, table, lo=lo, hi=hi,
                                min_len=4 if width == 2 else 6, width=width)
                            if items.plausible_run(r[2], width)]
                if texts:
                    groups = charset.group_runs(texts, width,
                                                max_gap=items.DIALOGUE_MAX_GAP)
                    # Some files store a line twice (the P's travel packets
                    # keep a second copy right after the first) or reuse one
                    # phrase in several entries.  That is the file's own
                    # content, not a scan artefact -- but editing one copy
                    # and not the others leaves stale text on the device, so
                    # each block says how many copies it has.
                    seen = collections.Counter(g['text'] for g in groups)
                    nth = collections.Counter()
                    info['texts'] = []
                    for i, g in enumerate(groups):
                        n = seen[g['text']]
                        nth[g['text']] += 1
                        label = f"대사 {i + 1}"
                        if n > 1:
                            label += f" · 중복 {nth[g['text']]}/{n}"
                        info['texts'].append(
                            {'parts': g['parts'], 'chars': g['chars'],
                             'text': g['text'], 'width': width,
                             'dup_count': n, 'label': label})
        if banks:
            info['banks'] = [{'offset': b['offset'],
                              'loose': b.get('loose'),
                              'frames': [{'slot': f.slot_size, 'w': f.width,
                                          'h': f.height, 'palette': f.palette,
                                          'pixels': f.pixels}
                                         for f in b['frames']]}
                             for b in banks]
        if vdp.is_vdp(pkt):
            info['vdp'] = vdp.contents(pkt)
            recs = vdp.sprite_records(pkt)
            info['vdp_sprites'] = [{k: v for k, v in r.items()
                                    if k != 'frames_data'} for r in recs]
            if recs:
                # the packed stream is what actually holds the artwork; the
                # records sitting in the raw file are coincidences inside it
                info['banks'] = [
                    {'offset': r['offset'], 'loose': None, 'unpacked': True,
                     'frames': [{'slot': f.slot_size, 'w': f.width,
                                 'h': f.height, 'palette': f.palette,
                                 'pixels': f.pixels} for f in r['frames_data']]}
                    for r in recs]
            vdp.attribute_sprites(info['vdp'], info.get('banks') or [])
        out['packets'].append(info)
    return out


def replace_packet(packets, path, new_raw):
    """Swap the packet at `path` for `new_raw`.

    A nested packet lives inside its parent's bytes, so the parent has to
    be spliced and its u16 size field rewritten before it is re-parsed.
    """
    if len(path) == 1:
        packets[path[0]] = container.Packet(new_raw, 0)
        return
    parent = _find(packets, path[:-1])
    child = parent.children[path[-1]]
    raw = bytearray(parent.raw)
    raw[child.offset:child.offset + child.size] = new_raw
    struct.pack_into('>H', raw, container.OFF_PACKET_SIZE, len(raw))
    replace_packet(packets, path[:-1], bytes(raw))


def apply_edits(data, edits, new_jpeg=None):
    jpeg, packets, trailing = container.parse_file(data)
    # packet swaps first: they rebuild Packet objects the later edits use
    swaps = [e for e in edits if e.get('replace_b64') or e.get('convert')]
    if swaps:
        before = sum(p.size for p in packets)
        for e in swaps:
            if e.get('convert'):
                pkt = _find(packets, e['path'])
                new = convert.convert(pkt, e['convert'], e.get('serial'))
                replace_packet(packets, e['path'], bytes(new.raw))
                continue
            src = base64.b64decode(e['replace_b64'])
            _, srcpkts, _ = container.parse_file(src)
            replace_packet(packets, e['path'], bytes(srcpkts[0].raw))
        delta = sum(p.size for p in packets) - before
        for p in packets:
            p.shift_declared_size(delta)
        edits = [e for e in edits
                 if not (e.get('replace_b64') or e.get('convert'))]
    if new_jpeg is not None and new_jpeg != jpeg:
        delta = len(new_jpeg) - len(jpeg)
        for pkt in packets:
            pkt.shift_declared_size(delta)
        jpeg = new_jpeg
    for edit in edits:
        pkt = _find(packets, edit['path'])
        table = charset.load_table(model=pkt.model)
        if 'serial' in edit:
            pkt.set_serial(int(edit['serial']))
        if 'name' in edit:
            pkt.set_item_name_codes(charset.encode(edit['name'], table))
        if 'unicode_name' in edit:
            pkt.set_unicode_name(edit['unicode_name'])
        if 'price' in edit:
            items.set_price(pkt, int(edit['price']))
        if 'hunger' in edit:
            items.set_hunger(pkt, edit['hunger'])
        if 'friendship' in edit:
            items.set_friendship(pkt, edit['friendship'])
        if 'dest' in edit:
            items.set_destination(pkt, edit['dest'], edit.get('dest_label'))
        if 'likes' in edit:
            items.set_likes_raw(pkt, edit['likes'])
        if 'stats' in edit:
            items.set_stats(pkt, edit['stats'])
        if 'acc_pos' in edit:
            items.set_acc_positions(pkt, edit['acc_pos'])
        if 'char_stats' in edit:
            character.set_stats(pkt, edit['char_stats'])
        if 'transform_name' in edit:
            charset.write_text(pkt.raw, character.OFF_TRANSFORM_NAME, 10,
                               edit['transform_name'], table, 2)
        if 'char_acc_pos' in edit:
            character.set_acc_positions(pkt, edit['char_acc_pos'])
        if 'name2' in edit:
            charset.write_text(pkt.raw, character.OFF_NAME2,
                               pkt.layout['slots'], edit['name2'], table, 2)
        if 'version' in edit:
            v = edit['version']
            items.set_version(pkt, v.get('version'), v.get('compat'),
                              v.get('index'))
        if 'compat' in edit:
            items.set_compat(pkt, edit['compat'])
        if 'anim_a' in edit:
            items.set_anim(pkt, edit['anim_a'], edit.get('anim_b', edit['anim_a']))
        for t in edit.get('texts', []):
            if t.get('parts'):
                charset.write_grouped(pkt.raw, [tuple(p) for p in t['parts']],
                                      t['text'], table, t.get('width', 2))
            else:
                charset.write_text(pkt.raw, t['offset'], t['chars'],
                                   t['text'], table, t.get('width', 2))
        for bank in edit.get('banks', []):
            off = bank['offset']
            if bank.get('loose'):
                sprites.write_loose(pkt.raw, tuple(bank['loose']),
                                    [tuple(c) for c in bank['frames'][0]['palette']],
                                    [f['pixels'] for f in bank['frames']])
                continue
            frames = [sprites.Frame(f['slot'], f['w'], f['h'],
                                    [tuple(c) for c in f['palette']],
                                    f['pixels']) for f in bank['frames']]
            # in-place rewrite must not change the bank's byte length
            old_end = sprites.parse_bank(pkt.raw, off)[1]
            blob_len = 2 + sum(2 + f.slot_size for f in frames)
            if off + blob_len != old_end:
                raise ValueError('bank size mismatch — frame slots must be kept')
            sprites.write_bank(pkt.raw, frames, off)
    return container.build_file(jpeg, packets, trailing)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype='application/json'):
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ('/', '/index.html'):
            self._send(200, open(HTML_PATH, 'rb').read(),
                       'text/html; charset=utf-8')
        elif self.path == '/api/charasprites':
            data = chara_sprites()
            self._send(200 if data else 404, json.dumps(data or {}).encode())
        elif self.path.startswith('/api/list?dir='):
            # localhost convenience: enumerate .jpg files in a folder so the
            # UI (and scripted checks) can walk a download pack
            from urllib.parse import unquote
            d = unquote(self.path.split('=', 1)[1])
            try:
                names = []
                for root, _, files in os.walk(d):
                    for n in sorted(files):
                        if n.lower().endswith(('.jpg', '.jpeg')):
                            names.append(os.path.join(root, n))
                self._send(200, json.dumps(sorted(names)).encode())
            except OSError as exc:
                self._send(400, json.dumps({'error': str(exc)}).encode())
        elif self.path.startswith('/api/readfile?path='):
            # localhost convenience: open a .jpg straight from disk
            from urllib.parse import unquote
            path = unquote(self.path.split('=', 1)[1])
            if not path.lower().endswith(('.jpg', '.jpeg')):
                self._send(400, b'{"error":"jpg only"}')
                return
            try:
                self._send(200, open(path, 'rb').read(),
                           'application/octet-stream')
            except OSError as exc:
                self._send(400, json.dumps({'error': str(exc)}).encode())
        else:
            self._send(404, b'{}')

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
        try:
            if self.path == '/api/parse':
                out = describe(body)
                self._send(200, json.dumps(out).encode())
            elif self.path == '/api/build':
                req = json.loads(body)
                data = base64.b64decode(req['file_b64'])
                nj = req.get('jpeg_b64')
                built = apply_edits(data, req['edits'],
                                    base64.b64decode(nj) if nj else None)
                # sanity: no packet may come out worse than it went in.
                # A few retail files ship a stale nested checksum, so
                # compare against the input rather than demanding all-ok.
                _, before, _ = container.parse_file(data)
                _, after, _ = container.parse_file(built)
                was_bad = {p.ansi_id for _, p in _iter_packets(before)
                           if not p.checksum_ok()}
                for _, pkt in _iter_packets(after):
                    if not pkt.checksum_ok() and pkt.ansi_id not in was_bad:
                        raise RuntimeError('internal error: bad checksum after build')
                self._send(200, built, 'application/octet-stream')
            else:
                self._send(404, b'{}')
        except Exception as exc:  # surface as editor toast
            self._send(400, json.dumps({'error': str(exc)}).encode())


def serve(port=8477):
    srv = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    url = f'http://127.0.0.1:{port}/'
    print(f'tama4u editor: {url}  (Ctrl+C to stop)')
    try:
        webbrowser.open(url)
    except Exception:
        pass
    srv.serve_forever()
