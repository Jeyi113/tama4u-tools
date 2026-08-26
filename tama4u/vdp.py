"""Virtual Deco Pierce bundles (destination 94 02 5b 02).

A VDP is one P's download that installs a whole set at once -- a raisable
character plus its meals, toy, accessory, room, minigame and menu icons.

Each embedded item keeps the tail of an ordinary P's packet header, so the
reliable anchor is the destination itself:

    -2  u16 model signature (8D C0 on P's)
     0  4 bytes destination      <- anchor
    +4  8 bytes token
   +12  u16 BE serial
   +14  u16
   +16  item name

which is exactly 0x4C / 0x4E / 0x52 / 0x5A / 0x5C / 0x5E of a normal
packet.  Anchoring on the destination rather than on the name is what
finds the items whose name is kana -- the character's wardrobe and one of
the rooms were both missed while the scan keyed on Latin text.

The meals, the snack and the menu-icon set carry no destination anywhere
in the file, so they are reported by name and serial only rather than
guessed at.

The artwork is behind a packed stream covering everything after the loader
stub -- the sprite headers that turn up in the raw file are coincidences
inside it.  Both packers were read out of the loader with `tama4u.s1c33`,
and both emit 16-bit halfwords.

**vdp-001 to 008** use plain RLE with a halfword control word:

    ctrl > 0    ctrl halfwords follow literally
    ctrl < 0    low byte is the value, bits 8-14 the count: emit
                value:value ((ctrl >> 8) & 0x7F) + 1 times
    ctrl == 0   end

**vdp-009** switched to a byte control word and added back-references,
which is where the real gain is (2.3:1 against 1.8:1):

    ctrl > 0    one byte follows; emit it as byte:byte, ctrl+1 times
    ctrl < 0    -ctrl halfwords follow literally
    ctrl == 0   two bytes A,B follow; A == 0 ends the stream, else copy
                (A >> 4) + 1 halfwords from (A & 0xF, B) bytes back --
                a 12-bit negative distance into what has been emitted
"""
import collections
import re
import struct

from . import charset, container, destinations, items, s1c33, sprites

VDP_DEST = '94025b02'
LOADER_PREFIX = 'DecoPierce'

SIG_REL, DEST_LEN, TOKEN_REL = -2, 4, 4
SERIAL_REL, PAD_REL, NAME_REL = 12, 14, 16
PS_SIG = 0x8DC0
NAME_MAX = 14
# Names are drawn from this subset when scanning without a destination
# anchor; kana would match the program bytecode on nearly every offset.
NAME_CHARS = set('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 　★▽・♪＋')
MIN_NAME = 3
# Firmware patches (EP/RP/LCD tweak) share the VDP destination but carry no
# item set; their bytecode throws off dozens of nameless hits, so those are
# only worth showing when there are few enough to be real.
MAX_UNCONFIRMED = 12


# The loader stub sets its input pointer with `xld.w %rN,0x0200xxxx`.  The
# VDP is loaded at 0x02000000 -- the disassembly of vdp-009 says so
# outright, comparing the firmware version and then picking one of
# 0x2000068 / 0x20000a8 / 0x20000c8, which are its three adaptation tables
# at exactly those file offsets.  So the low half of any such immediate is
# a file offset, and one of them is where the stream starts.
LOAD_BASE = 0x02000000
STUB_END = 0x600            # the loader stub never runs past here
IMMEDIATE = re.compile(r'^x?ld\.w %r\d+,0x([0-9a-f]+)$')
# Each packer is identified by a few bytes of its run branch.
#   LZ  `sll %r10,0x8` then `or %r10,%r4`, building byte:byte
#   RLE `ld.b [%sp+0],%r2` twice, then the two opcodes that pull the count
#       out of the control word.  Those two (class 1 with op2 = 3) are not
#       in the core manual's table and piece-emu calls them undefined, so
#       the count is taken from the data instead: bits 8-14, +1, which is
#       what makes all nine VDPs decode into their advertised contents.
ROUTINES = (
    ('lz', bytes((0x8a, 0x8c, 0x4a, 0x36))),
    ('rle', bytes((0x02, 0x54, 0x12, 0x54, 0x12, 0x27, 0x92, 0x23))),
)
UNPACK_LIMIT = 1 << 20


def unpack_rle(raw, start, limit=UNPACK_LIMIT):
    """vdp-001..008: halfword control word, literal runs and byte runs."""
    out, ip = bytearray(), start
    while len(out) < limit and ip + 1 < len(raw):
        ctrl = struct.unpack_from('<h', raw, ip)[0]
        ip += 2
        if ctrl > 0:
            n = 2 * ctrl
            if ip + n > len(raw):
                break
            out += raw[ip:ip + n]
            ip += n
        elif ctrl < 0:
            u = ctrl & 0xFFFF
            v = u & 0xFF
            out += bytes((v, v)) * (((u >> 8) & 0x7F) + 1)
        else:
            break
    return bytes(out)


def unpack(raw, start, limit=UNPACK_LIMIT):
    """vdp-009: byte control word with back-references."""
    out, ip = bytearray(), start
    while len(out) < limit and ip < len(raw):
        ctrl = raw[ip]
        ip += 1
        ctrl = ctrl - 256 if ctrl > 127 else ctrl
        if ctrl > 0:
            if ip >= len(raw):
                break
            v = raw[ip]
            ip += 1
            out += bytes((v, v)) * (ctrl + 1)
        elif ctrl < 0:
            n = 2 * -ctrl
            if ip + n > len(raw):
                break
            out += raw[ip:ip + n]
            ip += n
        else:
            if ip + 1 >= len(raw):
                break
            a, b = raw[ip], raw[ip + 1]
            ip += 2
            if a == 0:
                break
            dist = ((((0xFFFFFFF0 | a) << 8) | b) & 0xFFFFFFFF) - 0x100000000
            src = len(out) + dist
            if src < 0:
                break
            for _ in range((a >> 4) + 1):
                out += out[src:src + 2]
                src += 2
    return bytes(out)


MAX_LIT = 128
MAX_RUN = 128
MAX_MATCH = 16
WINDOW = 4096


def pack_rle(data):
    """The vdp-001..008 packer.  Byte-identical to Mr.Blinky's output."""
    out, lit, i = bytearray(), [], 0
    hw = [bytes(data[2 * k:2 * k + 2]) for k in range(len(data) // 2)]
    n = len(hw)
    while i < n:
        v = hw[i]
        if v[0] == v[1]:
            j = i
            while j < n and hw[j] == v and j - i < MAX_RUN:
                j += 1
            if j - i >= 2:
                out += struct.pack('<H', 0x8000 | ((j - i - 1) << 8) | v[0])
                i = j
                continue
        j = i
        while j < n and j - i < 0x7FFF:
            w = hw[j]
            if w[0] == w[1]:
                k = j
                while k < n and hw[k] == w and k - j < MAX_RUN:
                    k += 1
                if k - j >= 2:
                    break
            j += 1
        out += struct.pack('<H', j - i)
        for k in range(i, j):
            out += hw[k]
        i = j
    return bytes(out + b'\x00\x00')


def pack_lz(data):
    """The vdp-009 packer.  Not byte-identical -- a greedy matcher picks
    different matches than the original did -- but it round-trips and
    comes out smaller (24,426 bytes against 26,714 on vdp-009)."""
    hw = [bytes(data[2 * k:2 * k + 2]) for k in range(len(data) // 2)]
    n = len(hw)
    out, lit, index = bytearray(), [], collections.defaultdict(list)

    def flush():
        while lit:
            take = lit[:MAX_LIT]
            del lit[:len(take)]
            out.append((256 - len(take)) & 0xFF)
            for x in take:
                out.extend(x)

    i = 0
    while i < n:
        v = hw[i]
        run = 0
        if v[0] == v[1]:
            j = i
            while j < n and hw[j] == v and j - i < MAX_RUN:
                j += 1
            run = j - i
        best_len, best_d = 0, 0
        if i + 1 < n:
            for s in reversed(index[(hw[i], hw[i + 1])][-64:]):
                d = i - s
                if not 1 <= d <= WINDOW // 2:
                    continue
                L = 0
                while L < MAX_MATCH and i + L < n and hw[s + L] == hw[i + L]:
                    L += 1
                if L > best_len:
                    best_len, best_d = L, d
                if best_len >= MAX_MATCH:
                    break
        if run >= 3 and run >= best_len:
            flush()
            out.append(run - 1)
            out.append(v[0])
            step = run
        elif best_len >= 3:
            flush()
            field = 0x1000 - 2 * best_d
            out.extend((0x00, ((best_len - 1) << 4) | (field >> 8), field & 0xFF))
            step = best_len
        else:
            lit.append(v)
            step = 1
            if len(lit) >= MAX_LIT:
                flush()
        for k in range(i, i + step):
            if k + 1 < n:
                index[(hw[k], hw[k + 1])].append(k)
        i += step
    flush()
    return bytes(out + b'\x00\x00')


def repack(pkt, data):
    """Put an edited payload back, returning the new packet bytes.

    The stream keeps its start offset, so everything in front of it -- the
    header, the firmware adaptation tables, the loader stub -- is untouched
    and only the packet's declared size moves."""
    raw = bytes(pkt.raw)
    found = stream_start(raw)
    if found is None:
        raise ValueError('이 VDP의 압축 방식은 아직 해독되지 않았습니다')
    kind, start = found
    stream = (pack_lz if kind == 'lz' else pack_rle)(data)
    return raw[:start] + stream + b'\x00\x00'


def stream_start(raw):
    """(kind, offset) for the packer this file uses, or None."""
    for kind, sig in ROUTINES:
        at = raw.find(sig)
        if at >= 0:
            off = _pointer_before(raw, at)
            if off is not None:
                return kind, off
    return None


def _pointer_before(raw, at):
    """The last `xld.w %rN,0x0200xxxx` before `at` -- the input pointer.

    Not the first one in the stub: those are the firmware adaptation
    tables."""
    best = None
    for ins in s1c33.disasm(raw, max(0x40, at - 0x80), at):
        m = IMMEDIATE.match(ins.text)
        if not m:
            continue
        v = int(m.group(1), 16)
        if LOAD_BASE + 0x40 <= v < LOAD_BASE + len(raw):
            best = v - LOAD_BASE
    return best


def payload(pkt):
    """The unpacked body, or None when the packer is not one we read."""
    raw = bytes(pkt.raw)
    found = stream_start(raw)
    if found is None:
        return None
    kind, start = found
    return (unpack if kind == 'lz' else unpack_rle)(raw, start)


def is_vdp(pkt):
    dest = bytes(pkt.raw[items.OFF_DEST:items.OFF_DEST + 4]).hex()
    return dest == VDP_DEST


def _known_dests(model):
    out = {}
    for m in (model, 'iDL'):        # VDPs reuse an iD L shelf code
        for entry in destinations.options(m):
            out.setdefault(entry[1], entry[0])
    return out


def _name(raw, o, table):
    """The leading printable run only.

    These records do not pad the name field the way a standalone packet
    does (0x6C to all 14 slots), so binary follows the last letter with no
    terminator -- 'HERO　SET' would read as 'HERO　SETい'.  Keeping the run
    of name characters stops exactly where the name does, and returns
    nothing for the records whose name field never held one."""
    chars = []
    for k in range(NAME_MAX):
        if o + k >= len(raw):
            break
        ch = table.get(raw[o + k])
        if ch is None or ch not in NAME_CHARS:
            break
        chars.append(ch)
    return ''.join(chars).strip('　 ')


def contents(pkt):
    """Every item record the bundle carries, in file order.

    Read from the unpacked payload where there is one.  The raw file shows
    some of the same records -- an LZ stream emits them as literals, so
    they appear verbatim -- but only the payload has them all, and only
    there do their offsets line up with the sprites.  vdp-009 goes from 7
    confirmed records to 9 that way, picking up the two meals and the
    snack whose destinations the raw scan could not see.
    """
    data = payload(pkt)
    return _contents(data if data is not None else bytes(pkt.raw), pkt.model)


def _contents(raw, model):
    table = charset.load_table(model=model)
    known, out, claimed = _known_dests(model), [], set()

    for i in range(2, len(raw) - NAME_REL - 1):
        if raw[i] not in (0x81, 0x94) or raw[i:i + DEST_LEN].hex() not in known:
            continue
        if ((raw[i + SIG_REL] << 8) | raw[i + SIG_REL + 1]) != PS_SIG:
            continue
        dest = bytes(raw[i:i + DEST_LEN])
        out.append({
            'offset': i + SIG_REL, 'serial': (raw[i + SERIAL_REL] << 8) | raw[i + SERIAL_REL + 1],
            'name': _name(raw, i + NAME_REL, table), 'confirmed': True,
            'dest': dest.hex(), 'dest_label': known[dest.hex()],
        })
        claimed.update(range(i + SIG_REL, i + NAME_REL + NAME_MAX))

    for n in range(4, len(raw) - 2):
        if n in claimed or raw[n - 2] or raw[n - 1]:
            continue
        serial = (raw[n - 4] << 8) | raw[n - 3]
        if not serial:
            continue
        name = _name(raw, n, table)
        if len(name) < MIN_NAME or not re.search('[A-Z]', name):
            continue
        out.append({'offset': n - NAME_REL + SIG_REL, 'serial': serial,
                    'name': name, 'confirmed': False,
                    'dest': None, 'dest_label': None})

    if sum(1 for r in out if not r['confirmed']) > MAX_UNCONFIRMED:
        out = [r for r in out if r['confirmed']]
    return sorted(out, key=lambda r: r['offset'])


def sprite_records(pkt):
    """Sprite headers found in the bundle, with their palettes.

    Read from the unpacked payload, not the file: the records that show up
    in the raw bytes are coincidences inside the LZ77 stream."""
    data = payload(pkt)
    if data is None:
        return []
    out = []
    for rec in sprites.scan_loose(data, lo=0):
        start, w, h, ncol, nf, avail = rec
        need = sprites.pixel_bytes(w, h, nf, ncol)
        if avail < need:
            continue
        out.append({'offset': start, 'w': w, 'h': h, 'colors': ncol,
                    'frames': nf, 'need': need, 'loose': list(rec),
                    'frames_data': sprites.read_loose(data, rec)})
    return out


_SUB_CACHE = {}


def sub_packets(pkt):
    """(payload, base offset, packets) for a VDP's contents, or None.

    The payload is not a blob with records scattered through it -- it is a
    run of complete packets, `TAMAGO` header and all.  Parsing it with the
    container gives every field an ordinary download has, which is what
    makes the contents editable rather than merely listable."""
    if not is_vdp(pkt):
        return None
    key = (id(pkt), bytes(pkt.raw[:0x60]), pkt.size)
    if key in _SUB_CACHE:
        return _SUB_CACHE[key]
    data = payload(pkt)
    if data is None:
        return None
    base = data.find(container.MAGIC)
    if base < 0:
        return None
    try:
        _, packets, _ = container.parse_file(data[base:])
    except ValueError:
        return None
    got = (bytearray(data), base, packets)
    _SUB_CACHE.clear()          # one bundle at a time is all the editor needs
    _SUB_CACHE[key] = got
    return got


CHAR_DEST = '81033300'
ICON_DEST = '81042902'
STUB_MAX = 0x200            # a slot this small holds nothing but a 2x2 dummy


def content_label(sub, plain):
    """What a content packet really is, where the destination misleads.

    A VDP reuses shop codes for things that are not shop items:
      * the raisable character rides in a clothes-shop packet (0x81033300)
        -- every bundle has exactly one, always first, always 14,664 bytes,
        and its ANSI id says so outright ('Violetchi character')
      * the menu icon set sits on 0x81042902, which is daily necessities
        on iD L but icons here
      * vdp-009 carries two nameless stubs, one of them 272 bytes whose
        only sprite is a 2x2 dummy -- there is no content in it
    """
    dest = bytes(sub.raw[items.OFF_DEST:items.OFF_DEST + 4]).hex()
    if dest == CHAR_DEST:
        return '캐릭터 (육성)'
    if dest == ICON_DEST:
        return '메뉴 아이콘 세트'
    if sub.size <= STUB_MAX:
        return f'빈 슬롯 ({plain})'
    return plain


def write_subs(pkt, data, base, packets):
    """Fold edited content packets back and rebuild the stream.

    Recompressing changes the packet's length, so the size it declares at
    0x4A has to move with it -- otherwise the container reads the wrong
    extent back and the checksum lands in the wrong place."""
    for sub in packets:
        sub.fix_checksums()
        data[base + sub.offset:base + sub.offset + sub.size] = sub.raw
    out = bytearray(repack(pkt, bytes(data)))
    struct.pack_into('>H', out, container.OFF_PACKET_SIZE, len(out))
    return bytes(out)


def write_item(data, item, model):
    """Rewrite one content record's name and destination in the payload.

    Both fields are fixed-width in place -- the name pads to its 14 slots
    with the ideographic space, the way a standalone packet does -- so the
    payload never changes length and the stream stays the same shape."""
    off = item['offset']                       # signature offset
    table = charset.load_table(model=model)
    if item.get('dest'):
        code = bytes.fromhex(item['dest'])
        if len(code) != DEST_LEN:
            raise ValueError('행선지는 4바이트여야 합니다')
        data[off + 2:off + 2 + DEST_LEN] = code
    if 'name' in item:
        codes = charset.encode(item['name'][:NAME_MAX], table)
        codes += [charset.space_code(table)] * (NAME_MAX - len(codes))
        base = off + 2 + NAME_REL
        for k, c in enumerate(codes[:NAME_MAX]):
            data[base + k] = c & 0xFF


def attribute_sprites(records, banks):
    """Tag each sprite bank with the content record it belongs to.

    Both now come out of the same payload, so a bank belongs to the last
    record that starts before it."""
    for b in banks:
        owner = None
        for r in records:
            if r['offset'] <= b['offset']:
                owner = r
        b['vdp_item'] = (owner['name'] or f"0x{owner['offset']:05X}") if owner else None
        b['vdp_item_offset'] = owner['offset'] if owner else None
    return banks
