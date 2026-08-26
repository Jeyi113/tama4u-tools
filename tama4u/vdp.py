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

WHAT IS NOT DECODED: the pixel data.  Sprite record headers and palettes
are stored literally and read fine (w/h/colour count/01 FF, then a BGR565
palette whose slot 0 is the usual transparent green), but the pixels that
follow are packed: a 128x72 background leaves 2265 bytes where a literal
4bpp image needs 4608.  Reading them as 4bpp -- or through PackBits and
several run-length variants -- produces noise (vertical coherence 0.17-0.29
where a real background scores well above 0.7).  So the frames are flagged
`packed` and not drawn; drawing them is what made a loaded VDP look like
its sprites were all corrupt.
"""
import re

from . import charset, destinations, items, sprites

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

    Every one of them is packed.  `have`/`need` is reported because the
    shortfall is the clearest evidence (a 128x72 background leaves 2265
    bytes where 4bpp needs 4608), but the length is not the test: the last
    record in a file has nothing after it to be truncated by, so its span
    reaches `need` and it still decodes to noise.  Inside a VDP the pixels
    are packed, full stop."""
    raw, out = bytes(pkt.raw), []
    for rec in sprites.scan_loose(raw, lo=0x40):
        start, w, h, ncol, nf, avail = rec
        out.append({'offset': start, 'w': w, 'h': h, 'colors': ncol,
                    'frames': nf, 'have': avail,
                    'need': sprites.pixel_bytes(w, h, nf, ncol),
                    'packed': True})
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
