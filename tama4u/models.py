"""Per-model packet layout.

The container (TAMAGO magic, u16 sizes, sum16 checksum) and the sprite
codec are identical on every colour Tamagotchi; only a few field
offsets and the item-name encoding differ.  The model is identified by
the UTF-16 download name prefix, e.g. "DL_T4US_<name>.jpg".

    prefix     model              ansi id prefix
    DL_MDP_    iD                 (none)
    DL_iDLS_   iD L               id2_
    DL_iDNS_   P's                idn_
    DL_T4US_   4U / 4U+           t4u_
    DL_APL_    Tamagotchi P app   (none)

The trailing letter before "_" is the packet class: S = item,
A = character, C = clothes.
"""

# Stat-block offsets per model, all pinned by corpus correlation against
# Mr.Blinky's iDmakeDL screens (2026-08-12).  P's and 4U share one layout
# shifted by 0x0A; iD L keeps the same price/anim/hunger/friendship slots
# as P's but parks its (much larger) like mask right after friendship and
# has no stats; iD is its own, more compact arrangement.
#
#   anim   : u8 pair, toys only (built-in animation program id)
#   likes  : `likes_slots` characters, 2 bits each, packed low-bits-first
#            from `likes`.  iD carries 11 characters (22 bits = 0x68-0x6A
#            low six bits; slot 11 is never set anywhere in the pack and
#            0x6B is a separate byte), every later model 32.  iD L keeps
#            three zero bytes after its mask (0x7A-0x7C) and an unrelated
#            sparse field at 0x7D-0x80; those are not part of the mask.
#   stats  : u8 x5 (intelligence/style/charisma/gourmet/strength), P's onward
LAYOUTS = {
    'iD':  dict(name=0x5A, width=1, slots=9, price=0x66, bank=0x100,
                hunger=0x6C, friendship=0x6D, anim=None,
                likes=0x68, likes_slots=11, stats=None),
    'iDL': dict(name=0x5E, width=1, slots=14, price=0x6C, bank=0x100,
                hunger=0x70, friendship=0x71, anim=0x6E,
                likes=0x72, likes_slots=32, stats=None),
    "P's": dict(name=0x5E, width=1, slots=14, price=0x6C, bank=0x100,
                hunger=0x70, friendship=0x71, anim=0x6E,
                likes=0x8A, likes_slots=32, stats=0xAE),
    '4U':  dict(name=0x5E, width=2, slots=9,  price=0x76, bank=0x200,
                hunger=0x7A, friendship=0x7B, anim=0x78,
                likes=0x94, likes_slots=32, stats=0xB8),
}
DEFAULT = '4U'

_PREFIX = {
    'MDP': 'iD',
    'iDL': 'iDL',
    'iDN': "P's",
    'T4U': '4U',
    'APL': 'iD',       # phone app items follow the iD layout
}


def detect(unicode_name):
    """'DL_T4US_カップラーメン.jpg' -> ('4U', 'S')."""
    if not unicode_name.startswith('DL_'):
        return DEFAULT, 'S'
    head = unicode_name[3:].split('_', 1)[0]
    if not head:
        return DEFAULT, 'S'
    cls = head[-1] if head[-1] in 'SAC' else 'S'
    key = head[:-1] if head[-1] in 'SAC' else head
    return _PREFIX.get(key, _PREFIX.get(head, DEFAULT)), cls


# u16 at 0x4C.  This is the *authoritative* model marker: the download-name
# prefix only says which device the transfer app targets, and roughly a
# third of the packs ship one model's packet under another's name
# (`itemidlps_*` = iD L packets P's also accepts, `t4ups_*` = P's packets
# with a 4U download name).  Reading the layout off the prefix put those
# files' fields at the wrong offsets.
SIGNATURES = {
    0xCD80: 'iD',      # original iD
    0x0DC0: 'iD',      # Lovely Melody
    0x1DC0: 'iD',      # later iD revision
    0xCDC0: 'iD',      # rare iD variant (5 files)
    0x2DC0: 'iDL',
    0x8DC0: "P's",
    0x0101: '4U',
}

# Byte 0xFF is a device compatibility bitmask, not padding.  Mr.Blinky's
# own file names prove it: every `itemidlps_*` packet (iD L + P's) carries
# 3, `itemidl*` 1, `itemps*` 2.  iD predates the field and always writes 0.
COMPAT_BIT = {'iDL': 0x01, "P's": 0x02, '4U': 0x10}
OFF_COMPAT_MASK = 0xFF


def from_signature(sig):
    return SIGNATURES.get(sig)


def layout(model):
    return LAYOUTS.get(model, LAYOUTS[DEFAULT])
