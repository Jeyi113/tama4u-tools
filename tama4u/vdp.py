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
import re
import struct

from . import charset, destinations, items, s1c33, sprites

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

    `confirmed` marks the ones anchored on a real destination; the rest are
    reported by name and serial only."""
    raw, table = bytes(pkt.raw), charset.load_table(model=pkt.model)
    known, out, claimed = _known_dests(pkt.model), [], set()

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
                    'frames': nf, 'need': need,
                    'frames_data': sprites.read_loose(data, rec)})
    return out


def attribute_sprites(records, banks):
    """Tag each sprite bank with the record it follows."""
    for b in banks:
        owner = None
        for r in records:
            if r['offset'] <= b['offset']:
                owner = r['name'] or f"0x{r['offset']:05X}"
        b['vdp_item'] = owner
    return banks
