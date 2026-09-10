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

from . import (character, charset, container, convert, create, destinations,
               items, sprites, vdp)

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


def _iter_packets(packets, extra=b''):
    """Yield (path, packet) depth-first; path like [0] or [0, 1].

    A VDP's contents are whole packets inside its packed stream, so they
    are walked too, under a 'vdp' step -- [0, 'vdp', 2].  That way every
    one of them gets the ordinary item treatment: price, hunger,
    friendship, the like grid and the five stats all read and write
    through the same code as a standalone download."""
    def walk(pkt, path):
        yield path, pkt
        for i, child in enumerate(pkt.children):
            yield from walk(child, path + [i])
        subs = vdp.sub_packets(pkt, extra)
        if subs:
            for i, sub in enumerate(subs[2]):
                yield from walk(sub, path + ['vdp', i])
            # older change pierces keep their bodies as bare banks with no
            # packet header, so the content walk above misses them
            if not any(vdp.is_char_content(s) for s in subs[2]):
                for i, body in enumerate(vdp.bare_bodies(subs[0], subs[1],
                                                         model=pkt.model)):
                    yield path + ['vdpbody', i], body['packet']
    for i, top in enumerate(packets):
        yield from walk(top, [i])


def _find(packets, path):
    pkt = packets[path[0]]
    for i in path[1:]:
        if i == 'vdp':
            raise KeyError('vdp')       # handled by the caller
        pkt = pkt.children[i]
    return pkt


def _partner_packets(partners):
    """Continuations in the order their names end in, and their streams.

    A VDP+ ships in two or three files; the stream is one run split across
    them, so it only unpacks when they are concatenated in part order --
    Ciao read 1+2+3 gives 23 contents with every checksum good, 1+3+2 gives
    12.  Files handed over in any order are sorted here."""
    parsed = []
    for raw in partners or []:
        pj, ppk, pt = container.parse_file(raw)
        if vdp.is_part(ppk[0]):
            parsed.append((vdp.part_index(ppk[0]) or 99, pj, ppk, pt))
    parsed.sort(key=lambda x: x[0])
    return [(pj, ppk, pt) for _i, pj, ppk, pt in parsed]


def _part_gap(others):
    """True when the continuations skip a number.

    `others` is what _partner_packets already returned -- reparsing them
    here would double the work on every keystroke-driven reparse.

    Part 1 is the file being edited, so the rest should be 2, 3, ...  A
    hole is worth naming because the truncation check can miss it: Ciao
    read as 1+3 stops at 12 contents but the last one's checksum happens to
    be good, so nothing else says the bundle is incomplete."""
    idx = sorted(vdp.part_index(ppk[0]) or 0 for _pj, ppk, _pt in others)
    return idx != list(range(2, 2 + len(idx)))


def describe(data, partner=None):
    """`partner` is the rest of a VDP+ -- one continuation or a list of
    them.  Their streams are appended so the bundle unpacks whole."""
    jpeg, packets, trailing = container.parse_file(data)
    extra = b''
    if partner is not None and not isinstance(partner, (list, tuple)):
        partner = [partner]
    others = _partner_packets(partner)
    for _pj, ppk, _pt in others:
        extra += vdp.part_stream(ppk[0])
    part_gap = _part_gap(others)
    out = {'jpeg_b64': base64.b64encode(jpeg).decode(), 'packets': []}
    for path, pkt in _iter_packets(packets, extra):
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
            'ansi_num': pkt.ansi_num,
            'kind': items.effective_kind(pkt),
            'section': pkt.section,
            'serial': pkt.serial,
            'unicode_name': pkt.unicode_name,
            'name': charset.decode(pkt.item_name_codes, table),
            'size': pkt.size,
            'dest': bytes(pkt.raw[items.OFF_DEST:items.OFF_DEST + 4]).hex(),
            # the model/firmware signature sits right in front of the
            # destination, and it is what makes the field differ between
            # models that share a category code: 레스토랑 · 식사 is
            # 8dc0 81010201 on P's but 0101 81010201 on 4U, and iD splits
            # further by firmware (cd80 vs 0dc0).
            'dest_sig': bytes(pkt.raw[container.OFF_TYPE_SIG:
                                      container.OFF_TYPE_SIG + 2]).hex(),
            'dest_label': (vdp.content_label(pkt, items.get_destination(pkt))
                           if 'vdp' in path
                           else ('VDP+ 뒷부분 (압축 스트림)' if vdp.is_part(pkt)
                                 else items.get_destination(pkt))),
            # the mask travels with the code so the UI can show iD's free
            # per-item index byte as ** instead of a misleading 00
            'dest_options': [{'label': e[0], 'code': e[1], 'mask': e[2]}
                             for e in destinations.options(pkt.model)],
            'is_item': (not character.is_character(pkt)
                        and not items.is_program(pkt)
                        and (items.effective_kind(pkt) in items.BANK_OFFSETS
                             or pkt.model != '4U')),
        }
        # a VDP character body sits on the clothes shelf and reads as kind
        # 'fk', but its 28 frames are poses, not wearable pieces -- the
        # body-type composite would slice them as 4 sets of 7
        in_vdp = 'vdp' in path or 'vdpbody' in path
        info['pose_bank'] = vdp.is_char_content(pkt) if in_vdp else False
        # everything on that shelf inside a bundle belongs to one specific
        # character, body or change dress alike, so composing it onto the
        # generic reference tamagotchi says nothing -- the composite is for
        # shop clothes, which fit every body
        info['char_shelf'] = (in_vdp and bytes(
            pkt.raw[items.OFF_DEST:items.OFF_DEST + 4]).hex() == vdp.CHAR_DEST)
        if pkt.model == 'iD':
            info['version'] = items.get_version(pkt)
            info['version_presets'] = items.VERSION_PRESETS
        info['compat'] = items.get_compat(pkt)
        period = items.get_period(pkt)
        if period is not None:
            info['period'] = period
        # iD studio costumes and accessories come in firmware-specific lines,
        # and a costume is cut for one body -- both matter when picking a file
        if pkt.model == 'iD':
            label = items.get_destination(pkt)
            if label in ('사진관 · 의상', '타마모리 · 액세서리'):
                info['id_line'] = {
                    'label': label,
                    'firmware': items.VERSION_NAMES.get(
                        items.get_version(pkt)['version'], '?'),
                }
                if label == '사진관 · 의상':
                    try:
                        frames, _ = sprites.parse_bank(
                            pkt.raw, items.bank_offset(pkt))
                        info['id_line']['gender'] = items.studio_gender(
                            pkt, len(frames))
                    except Exception:
                        pass
        info['convert'] = {m: convert.plan(pkt, m)
                           for m in ('iD', 'iDL', "P's", '4U') if m != pkt.model}
        if info['is_item'] and not info['is_wardrobe']:
            info['price'] = items.get_price(pkt)      # verified on every model
        if not info['is_item']:
            # programs have no shop fields, but their destination is what
            # files a game under the Game Center
            info['fields'] = sorted(items.editable_fields(pkt))
            if items.is_program(pkt):
                # the sprite layout is the engine -- two different games
                # built on one carry the same set
                shape = create.game_shape(pkt)
                if shape:
                    info['game_shape'] = shape
                if items.get_destination(pkt) == '외출지':
                    cast = create.outing_cast(pkt)
                    if cast:
                        cast['gifts'] = len(pkt.children or [])
                        info['outing'] = cast
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
                # A character is two packets: this card, and the body
                # nested at 0xB00.  Their ASCII ids share one number and
                # the body repeats it as its serial (68/68 in the 4U pack),
                # so the screen edits the number once and writes both.
                if pkt.children:
                    body = pkt.children[0]
                    info['char_body'] = {
                        'path': path + [0],
                        'ansi_id': body.ansi_id,
                        'ansi_num': body.ansi_num,
                        'serial': body.serial,
                        'name': charset.decode(body.item_name_codes, table),
                    }
                info['char_enums'] = {
                    'stage': character.STAGE,
                    'personality': character.PERSONALITY,
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
        if vdp.is_part(pkt):
            info['vdp_part'] = {'stream': len(vdp.part_stream(pkt))}
        if vdp.is_vdp(pkt) and len(path) == 1:
            # summary of the bundle's contents; each one is also a real
            # packet in this list, under a 'vdp' path step
            got = vdp.sub_packets(pkt, extra)
            info['vdp_truncated'] = vdp.truncated(pkt, extra)
            info['vdp_merged'] = bool(extra)
            info['vdp_part_gap'] = part_gap
            # A VDP+ part 1 is a bundle whose item name ends in a digit --
            # true of all 20 VDP+ releases and of none of the 50 plain
            # pierces (VDP*NNN*).  The truncation check alone is not enough
            # to offer the loader: a bundle read short can still end on a
            # content whose checksum happens to be good.
            info['vdp_multipart'] = vdp.part_index(pkt) is not None
            info['vdp'] = [] if got is None else [
                {'index': k,
                 'name': charset.decode(sub.item_name_codes,
                                        charset.load_table(model=sub.model)
                                        ).rstrip('\u3000'),
                 'label': vdp.content_label(sub, items.get_destination(sub)),
                 'model': sub.model, 'size': sub.size, 'serial': sub.serial,
                 'dest': bytes(sub.raw[items.OFF_DEST:items.OFF_DEST + 4]).hex(),
                 'dest_sig': bytes(sub.raw[container.OFF_TYPE_SIG:
                                           container.OFF_TYPE_SIG + 2]).hex(),
                 'price': items.get_price(sub),
                 'sprites': len(sprites.scan_loose(sub.raw, lo=0x40))}
                for k, sub in enumerate(got[2])]
            if got is not None:
                # the raising conditions, from the payload's 4 KB prefix
                where = {sub.serial: k for k, sub in enumerate(got[2])}
                info['vdp_dest_name'] = vdp.dest_name(got[0], model=pkt.model)
                info['vdp_chars'] = [
                    dict(c, item_index=where.get(c['item_serial']))
                    for c in vdp.char_blocks(got[0], model=pkt.model)]
                # tie each raisable character to its block so that selecting
                # the character itself shows its conditions, rather than only
                # the bundle as a whole
                n = 0
                for row, sub in zip(info['vdp'], got[2]):
                    row['char_index'] = n if vdp.is_char_content(sub) else None
                    n += vdp.is_char_content(sub)
                # bare change bodies (anniversary) join the list too, on
                # their own 'vdpbody' path so a click reaches the synthetic
                # packet the walker made for them
                if not any(vdp.is_char_content(s) for s in got[2]):
                    for k, body in enumerate(
                            vdp.bare_bodies(got[0], got[1], model=pkt.model)):
                        info['vdp'].append({
                            'bare': True, 'bindex': k, 'char_index': k,
                            'name': body['name'],
                            'label': '캐릭터 (육성)', 'model': pkt.model,
                            'size': vdp.BODY_STRIDE, 'serial': 0,
                            'dest': vdp.CHAR_DEST, 'dest_sig': '',
                            'price': 0, 'sprites': 0})
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


def _apply_fields(pkt, edit):
    """Every field edit for one packet.  Shared by top-level packets
    and by the content packets inside a VDP, so a bundled item is
    edited exactly like a standalone download."""
    table = charset.load_table(model=pkt.model)
    if 'serial' in edit:
        pkt.set_serial(int(edit['serial']))
    if edit.get('ansi_num') is not None:
        pkt.set_ansi_num(int(edit['ansi_num']))
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
    if 'period' in edit and edit['period']:
        items.set_period(pkt, edit['period'])
    if 'stats' in edit:
        items.set_stats(pkt, edit['stats'])
    if 'acc_pos' in edit:
        items.set_acc_positions(pkt, edit['acc_pos'])
    if 'char_stats' in edit:
        character.set_stats(pkt, edit['char_stats'])
    if 'transform_name' in edit:
        # null-pad: the field is read until a terminator and Name 2 sits
        # right after it, so a space-padded tail runs the two names together
        charset.write_text(pkt.raw, character.OFF_TRANSFORM_NAME, 10,
                           edit['transform_name'], table, 2, pad=0)
    if 'char_acc_pos' in edit:
        character.set_acc_positions(pkt, edit['char_acc_pos'])
    if 'name2' in edit:
        charset.write_text(pkt.raw, character.OFF_NAME2,
                           pkt.layout['slots'], edit['name2'], table, 2, pad=0)
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
        frames = _bank_frames(bank)
        # in-place rewrite must not change the bank's byte length.  Where
        # the caller wants a frame bigger than its slot it asks for that
        # explicitly, and _resize_banks handles it before we get here.
        old_end = sprites.parse_bank(pkt.raw, off)[1]
        blob_len = 2 + sum(2 + f.slot_size for f in frames)
        if off + blob_len != old_end:
            raise ValueError('bank size mismatch — frame slots must be kept')
        sprites.write_bank(pkt.raw, frames, off)


def _bank_frames(bank):
    return [sprites.Frame(f['slot'], f['w'], f['h'],
                          [tuple(c) for c in f['palette']], f['pixels'])
            for f in bank['frames']]


def _resize_banks(packets, edits):
    """Rewrite banks whose frames no longer fit their slots.

    A bigger frame makes the packet longer, which invalidates its 0x4A,
    every enclosing 0x4A and every top-level 0x32.  Splicing through
    replace_packet fixes the first two; the delta returned here is what
    the caller shifts the 0x32s by.  Only banks marked `grow` are
    considered, so an ordinary edit still fails loudly rather than
    quietly moving everything after the bank.
    """
    delta = 0
    for edit in edits:
        path = list(edit['path'])
        if 'vdp' in path or 'vdpchar' in path:
            continue            # packed stream; repacked wholesale instead
        for bank in edit.get('banks', []):
            if not bank.get('grow'):
                continue
            pkt = _find(packets, path)
            off = bank['offset']
            if bank.get('loose'):
                # a loose record has no slot prefix and sits in a program's
                # sprite tail; rebuild it at whatever size and splice, moving
                # every record after it.  Only its own header carries the
                # dimensions, so a sequential reader follows along -- but code
                # that points at a later record by address will not, which is
                # why the UI warns before offering this on an outing.
                rec = tuple(bank['loose'])
                old_len = sprites.loose_span(rec)
                fr = bank['frames']
                blob = sprites.encode_loose(fr[0]['w'], fr[0]['h'],
                                            [tuple(c) for c in fr[0]['palette']],
                                            [f['pixels'] for f in fr])
                if len(blob) == old_len:
                    continue                  # same size; in-place path has it
                raw = bytearray(pkt.raw)
                raw[off:off + old_len] = blob
            else:
                old_end = sprites.parse_bank(pkt.raw, off)[1]
                blob = sprites.encode_bank(_bank_frames(bank), grow=True)
                if off + len(blob) == old_end:
                    continue                  # fits; the in-place path has it
                raw = bytearray(pkt.raw)
                raw[off:old_end] = blob
            struct.pack_into('>H', raw, container.OFF_PACKET_SIZE, len(raw))
            # replace_packet re-parses from these bytes, so the new Packet
            # would consider itself untouched and keep the checksum that
            # belonged to the shorter body.  Seal it here instead; the
            # change then ripples out and the parents reseal themselves.
            struct.pack_into('>H', raw, len(raw) - 2,
                             container.sum16(raw[:-2]))
            grew = len(raw) - len(pkt.raw)
            delta += grew
            replace_packet(packets, path, bytes(raw))
            # the slots just moved, so the in-place write must not re-run
            bank['done'] = True
            # every later bank on this packet -- the outing's other loose
            # records, still sent for their unchanged in-place rewrite --
            # now sits `grew` bytes further along, so move its offset with it
            for other in edit.get('banks', []):
                if other is bank or other.get('offset', 0) <= off:
                    continue
                other['offset'] += grew
                if other.get('loose'):
                    other['loose'] = [other['loose'][0] + grew, *other['loose'][1:]]
    for edit in edits:
        if 'banks' in edit:
            edit['banks'] = [b for b in edit['banks'] if not b.get('done')]
    return delta

def apply_edits(data, edits, new_jpeg=None, partner=None):
    """`partner` is a VDP+'s continuations -- one file or a list.  With
    them, edits reach the whole bundle and the result comes back as a list
    of files, part 1 first."""
    jpeg, packets, trailing = container.parse_file(data)
    if partner is not None and not isinstance(partner, (list, tuple)):
        partner = [partner]
    others = _partner_packets(partner)
    extra = b''.join(vdp.part_stream(ppk[0]) for _pj, ppk, _pt in others)
    # packet swaps first: they rebuild Packet objects the later edits use
    swaps = [e for e in edits
             if (e.get('replace_b64') or e.get('convert'))
             and 'vdp' not in e['path']]
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
            new = srcpkts[0]
            # a donor from another model has its sprite bank, name encoding
            # and destination in different places, so it is converted before
            # it goes in rather than pushed in as raw bytes
            if e.get('convert_to') and new.model != e['convert_to']:
                new = convert.convert(new, e['convert_to'])
            replace_packet(packets, e['path'], bytes(new.raw))
        delta = sum(p.size for p in packets) - before
        for p in packets:
            p.shift_declared_size(delta)
        edits = [e for e in edits if e not in swaps]
    if new_jpeg is not None and new_jpeg != jpeg:
        delta = len(new_jpeg) - len(jpeg)
        for pkt in packets:
            pkt.shift_declared_size(delta)
        jpeg = new_jpeg
    # a frame that outgrew its slot lengthens the packet, so this runs
    # before the field edits (which need the re-parsed Packet objects)
    grew = _resize_banks(packets, edits)
    if grew:
        for pkt in packets:
            pkt.shift_declared_size(grew)
    for edit in edits:
        path = list(edit['path'])
        if 'vdp' in path or 'vdpchar' in path or 'vdpbody' in path:
            continue                # collected below
        _apply_fields(_find(packets, path), edit)
    # VDP contents live inside the packed stream: unpack once per
    # bundle, apply everything, then rebuild the stream once.  The
    # raising conditions sit in the same payload, so they ride along
    # rather than costing a second unpack-repack.
    groups = collections.defaultdict(lambda: ([], [], [], []))
    for edit in edits:
        path = list(edit['path'])
        placed = False
        for step, bucket in (('vdp', 0), ('vdpchar', 1), ('vdpbody', 3)):
            if step in path:
                k = path.index(step)
                groups[tuple(path[:k])][bucket].append((path[k + 1], edit))
                placed = True
                break
        # the destination name lives in the payload, not in the packet, so
        # it has to ride the same unpack even when nothing else changed
        if not placed and edit.get('vdp_dest_name') is not None:
            groups[tuple(path)][2].append(edit)
    for top, (jobs, charjobs, namejobs, bodyjobs) in groups.items():
        pkt = _find(packets, list(top))
        got = vdp.sub_packets(pkt, extra)
        if got is None:
            raise ValueError('이 VDP는 아직 압축을 풀 수 없습니다')
        if vdp.truncated(pkt, extra):
            # repacking what we can see would drop everything that lives in
            # the other part -- the stream ends mid-content, so the contents
            # past the cut are simply not here to write back
            raise ValueError(
                'VDP+의 뒷부분이 없습니다 — 짝 파일을 함께 불러오지 않으면 '
                '나머지 내용물이 사라집니다')
        payload, base, subs = got
        for idx, edit in jobs:
            if edit.get('replace_b64'):
                # swap one content for a whole downloaded item; the payload
                # is reassembled around it, so the sizes need not match
                src = base64.b64decode(edit['replace_b64'])
                _, srcpkts, _ = container.parse_file(src)
                donor = srcpkts[0]
                if edit.get('convert_to') and donor.model != edit['convert_to']:
                    donor = convert.convert(donor, edit['convert_to'])
                subs[idx] = vdp.fit_content(subs[idx], donor)
                continue
            _apply_fields(subs[idx], edit)
        for idx, edit in charjobs:
            vdp.write_char_block(payload, idx, edit, model=pkt.model)
        for edit in namejobs:
            vdp.write_dest_name(payload, edit['vdp_dest_name'], model=pkt.model)
        # bare change bodies live in the payload prefix, before the first
        # content; patch their bank in place and the assemble below carries
        # it across untouched, leaving the blank header alone
        if bodyjobs:
            bodies = vdp.bare_bodies(payload, base, model=pkt.model)
            for bidx, edit in bodyjobs:
                if bidx >= len(bodies):
                    continue
                body = bodies[bidx]
                _apply_fields(body['packet'], edit)      # writes into syn.raw
                bank = body['packet'].raw[vdp.BODY_HEADER:]
                lo = body['off'] + vdp.BODY_HEADER
                payload[lo:lo + len(bank)] = bank
        before = pkt.size
        # Rebuild the Packet objects from the new bytes rather than writing
        # into pkt.raw in place: a compressed stream can spell TAMAGO by
        # accident, so pkt may carry a spurious nested child parsed from the
        # old layout.  Left in place, build_file's checksum pass would then
        # splice that stale child back at its old offset and corrupt the new
        # stream -- which is exactly what broke a two-part edit (easter).
        if extra:
            # split back across the parts: each fills to 32,768 bytes and
            # the rest goes to the next
            blob = vdp.assemble(payload, base, subs)
            cuts = vdp.repack_split(pkt, [o[1][0] for o in others], blob)
            replace_packet(packets, list(top), bytes(cuts[0]))
            for (_pj, opk, _pt), chunk in zip(others, cuts[1:]):
                opk[0] = container.Packet(bytes(chunk), 0)
                opk[0].children = []
        else:
            replace_packet(packets, list(top),
                           bytes(vdp.write_subs(pkt, payload, base, subs)))
        pkt = _find(packets, list(top))
        # the compressed stream can spell TAMAGO by chance, so the re-parsed
        # part may carry a spurious child; drop it so the checksum pass does
        # not splice stale bytes over the new stream (easter's part 1)
        pkt.children = []
        # the whole file's declared size follows the packet's
        for q in packets:
            q.shift_declared_size(pkt.size - before)
    out = container.build_file(jpeg, packets, trailing)
    if others:
        return [out] + [container.build_file(pj, opk, pt)
                        for pj, opk, pt in others]
    return out


def _partners_from(req):
    """`partner_b64` (one) or `partners_b64` (several), decoded."""
    many = req.get('partners_b64')
    if many:
        return [base64.b64decode(b) for b in many]
    one = req.get('partner_b64')
    return [base64.b64decode(one)] if one else None


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
        elif self.path == '/api/blueprints':
            # what "만들기" can offer: category list per model
            def spec(m, lab):
                if lab in create.FROM_BASE:
                    # no blueprint: the body comes from a file the user picks
                    return {'label': lab, 'frames': [], 'colors': 16,
                            'needs_base': create.FROM_BASE[lab],
                            'next_serial': create.next_serial(m, lab)}
                geometry, colors = create.blueprint(m, lab)
                row = {'label': lab, 'frames': geometry, 'colors': colors,
                       'next_serial': create.next_serial(m, lab)}
                if lab == create.TOY_LABEL:
                    # the frame count is the animation, so it is a choice
                    row['counts'] = create.toy_counts()
                    row['default_count'] = create.TOY_DEFAULT
                    row['shapes'] = {n: {'frames': create.TOY_SHAPES[n][0],
                                         'anim': create.toy_anim(n)}
                                     for n in create.toy_counts()}
                return row
            out = {m: [spec(m, lab) for lab in create.categories(m)]
                   for m in ('iD', 'iDL', "P's", '4U')}
            self._send(200, json.dumps(out, ensure_ascii=False).encode())
        else:
            self._send(404, b'{}')

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
        try:
            if self.path == '/api/parse':
                # raw bytes, or JSON when a VDP+ partner comes along
                if body[:1] == b'{':
                    req = json.loads(body)
                    data = base64.b64decode(req['file_b64'])
                    out = describe(data, _partners_from(req))
                else:
                    out = describe(body)
                self._send(200, json.dumps(out).encode())
            elif self.path == '/api/create':
                req = json.loads(body)
                if req['label'] in create.FROM_BASE:
                    # a game or an outing is machine code; the body comes
                    # from a download the user already has
                    if not req.get('base_b64'):
                        raise ValueError(
                            f'{create.FROM_BASE[req["label"]]}은(는) 프로그램이라 '
                            f'바탕이 될 파일이 필요합니다')
                    pkt = create.from_base(
                        base64.b64decode(req['base_b64']),
                        req['model'], req['label'],
                        name=req.get('name', ''),
                        serial=int(req['serial']) if req.get('serial') else None)
                    self._send(200, create.build_file(pkt), 'image/jpeg')
                    return
                nframes = req.get('nframes')
                fields = dict(req.get('fields') or {})
                if req['label'] == create.TOY_LABEL:
                    # a toy without the animation its frame count expects
                    # would play the wrong one
                    fields.setdefault('anim', create.toy_anim(
                        nframes or create.TOY_DEFAULT))
                pkt = create.new_item(
                    req['model'], req['label'],
                    name=req.get('name', ''), serial=int(req.get('serial', 0)),
                    fields=fields,
                    frames=create.blank_frames(req['model'], req['label'],
                                               req.get('colors'), nframes))
                out = create.build_file(pkt)
                self._send(200, out, 'image/jpeg')
                return
            elif self.path == '/api/build':
                req = json.loads(body)
                data = base64.b64decode(req['file_b64'])
                nj = req.get('jpeg_b64')
                parts_in = _partners_from(req)
                built = apply_edits(data, req['edits'],
                                    base64.b64decode(nj) if nj else None,
                                    parts_in)
                if isinstance(built, list):
                    # a VDP+ comes back as the whole set, part 1 first
                    self._send(200, json.dumps({'parts_b64': [
                        base64.b64encode(b).decode() for b in built]}).encode())
                    return
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
