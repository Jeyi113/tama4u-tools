"""Virtual Deco Pierce bundles (destination 94 02 5b 02).

A VDP is one P's download that installs a whole set at once -- a raisable
character plus its meals, toy, accessory, room, minigame and menu icons.
Mr.Blinky's release notes list the contents, and the body really does
carry them: each one keeps the tail of an ordinary packet header, so a
record ends

    [u16 BE serial][00 00][item name in the device charset]

which is exactly offsets 0x5A / 0x5C / 0x5E of a normal packet.  Where the
record also kept the bytes in front, the P's signature sits 18 bytes
before the name and the destination 16 -- that is what files the item
under its shop section, and it matches the release notes item for item.

The meals and the menu-icon set do not keep those front bytes (the VDP
patches them straight into the device's tables instead), so they are
reported without a destination rather than guessed at.

What is NOT decoded: most of the artwork.  A VDP holds only a handful of
plain sprite records -- the rest of its graphics sit in the program blob
in some packed form, and `sprites.scan_*` correctly finds nothing there.
"""
import re

from . import charset, destinations, items

VDP_DEST = '94025b02'
LOADER_PREFIX = 'DecoPierce'

SIG_REL, DEST_REL, TOKEN_REL, SERIAL_REL = -18, -16, -12, -4
PS_SIG = 0x8DC0
# Names are drawn from this subset; kana would match the program bytecode
# on nearly every offset.
NAME_CHARS = set('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 　★▽・♪＋')
MIN_NAME = 3
# Firmware patches (EP/RP/LCD tweak) share the VDP destination but carry no
# item set; their bytecode throws off dozens of unconfirmed hits, so those
# are only worth showing when there are few enough to be real.
MAX_UNCONFIRMED = 12


def is_vdp(pkt):
    dest = bytes(pkt.raw[items.OFF_DEST:items.OFF_DEST + 4]).hex()
    return dest == VDP_DEST


def _name_at(raw, o, table):
    j = o
    while j < len(raw) and table.get(raw[j]) in NAME_CHARS:
        j += 1
    text = charset.decode(raw[o:j], table).strip('　 ')
    return text if len(text) >= MIN_NAME and re.search('[A-Z]', text) else None


def contents(pkt):
    """Every item record the bundle carries, in file order.

    `confirmed` marks the ones that kept their signature and destination;
    the rest are reported by name and serial only."""
    raw, table = bytes(pkt.raw), charset.load_table(model=pkt.model)
    out = []
    for n in range(-SIG_REL, len(raw) - 2):
        if raw[n - 2] or raw[n - 1]:            # the u16 zero before the name
            continue
        serial = (raw[n - 4] << 8) | raw[n - 3]
        if not serial:
            continue
        name = _name_at(raw, n, table)
        if not name:
            continue
        dest = bytes(raw[n + DEST_REL:n + DEST_REL + 4])
        sig = (raw[n + SIG_REL] << 8) | raw[n + SIG_REL + 1]
        ok = sig == PS_SIG and dest[0] in items.PROGRAM_DESTS + (0x81,)
        out.append({
            'offset': n + SIG_REL, 'name_offset': n, 'serial': serial,
            'name': name, 'confirmed': ok,
            'dest': dest.hex() if ok else None,
            'dest_label': destinations.match(pkt.model, dest) if ok else None,
        })
    if sum(1 for r in out if not r['confirmed']) > MAX_UNCONFIRMED:
        out = [r for r in out if r['confirmed']]
    return out


def attribute_sprites(records, banks):
    """Tag each sprite bank with the record it follows."""
    starts = [(r['offset'], r['name']) for r in records]
    for b in banks:
        owner = None
        for off, name in starts:
            if off <= b['offset']:
                owner = name
        b['vdp_item'] = owner
    return banks
