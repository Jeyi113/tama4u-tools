"""Item stat block (offsets relative to packet start).

Confirmed on meals/snacks against Mr.Blinky's Tama Image Editor;
other categories share the same layout unless noted.
"""
import re
import struct

from . import destinations, models

OFF_PRICE = 0x76        # u16 BE
OFF_HUNGER = 0x7A       # u8 (meals/snacks)
OFF_FRIENDSHIP = 0x7B   # u8 — confirmed by editor diff 2026-08-12.
                        # meals ship 0 and snacks 2, which earlier looked
                        # like a meal/snack flag; the real meal/snack split
                        # lives in the destination code at 0x50.
OFF_LIKES = 0x94        # 8 bytes, 32 chars x 2 bits (bit0 like, bit1 dislike)
OFF_STATS = 0xB8        # u8 x5: Intelligence, Style, Charisma, Gourmet, Strength

# Destination is a 4-byte field at 0x4E-0x51 (labels below come from
# Mr.Blinky's iDmakeDL, which shows it verbatim; iD uses a 3-byte variant).
# Byte 0x4F is the section id: 01 food, 02 accessory, 03 clothes,
# 04 toy, 07 interior.
OFF_DEST = 0x4E

# iD packs a device/firmware code at 0x4C and two "also runs on" slots at
# 0xF8.  Both are constant within each shop folder (100% of the pack), so
# they identify the revision an item was built for rather than being noise.
#   cd80 original iD · 0dc0 Lovely Melody · 1dc0 a later iD revision
OFF_VERSION = 0x4C
OFF_COMPAT = 0xF8
VERSION_NAMES = {
    0xCD80: '오리지널 iD',
    0x0DC0: 'Lovely Melody',
    0x1DC0: 'iD 리비전 (1dc0)',
    0x0000: '없음',
}
# target -> (version code, two compat slots, observed catalogue slot range)
VERSION_PRESETS = {
    'cd80': dict(label='오리지널 iD', version=0xCD80, compat=[0x0000, 0x0000],
                 index_range=[0x01, 0x27]),
    '0dc0': dict(label='Lovely Melody', version=0x0DC0, compat=[0x0DC0, 0x1DC0],
                 index_range=[0xDE, 0xFE]),
    '1dc0': dict(label='iD 리비전 (1dc0)', version=0xCD80, compat=[0x1DC0, 0x1DC0],
                 index_range=[0x01, 0x27]),
}


def get_version(pkt):
    ver = struct.unpack_from('>H', pkt.raw, OFF_VERSION)[0]
    compat = list(struct.unpack_from('>HH', pkt.raw, OFF_COMPAT))
    return {'version': ver, 'compat': compat,
            'label': VERSION_NAMES.get(ver, f'0x{ver:04x}'),
            'index': pkt.raw[OFF_DEST + 2]}


def set_version(pkt, version=None, compat=None, index=None):
    if version is not None:
        struct.pack_into('>H', pkt.raw, OFF_VERSION, int(version) & 0xFFFF)
    if compat is not None:
        struct.pack_into('>HH', pkt.raw, OFF_COMPAT,
                         int(compat[0]) & 0xFFFF, int(compat[1]) & 0xFFFF)
    if index is not None:
        pkt.raw[OFF_DEST + 2] = int(index) & 0xFF
DESTINATIONS = {
    b'\x81\x01\x02\x01': 'Restaurant (meal)',
    b'\x81\x01\x0d\x02': 'Restaurant (snack)',
    b'\x81\x01\x01\x01': 'Fridge (meal, bundle reward)',
    b'\x81\x01\x01\x02': 'Fridge (snack, bundle reward)',
    b'\x81\x04\x2a\x01': 'TamaDepa (toys)',
    b'\x81\x03\x33\x00': 'TamaMori (clothes)',
    b'\x81\x02\x34\x00': 'TamaMori (accessory)',
    b'\x81\x07\x1f\x00': 'Gotchi Interior (wallpaper)',
    b'\x81\x08\x29\x00': 'Bingo definition',
    b'\x94\x02\x5b\x01': 'Minigame',
    b'\x94\x02\x47\x02': 'Outing definition',
    b'\x94\x02\x48\x03': 'Download character',
}

# sprite bank location per packet kind.  Accessories put a wear-position
# table at 0x200 (u16 unknown + 56 (x,y) byte pairs) and the bank at 0x5C2.
# gm/dlode/rec keep banks at code-determined offsets -> use sprites.scan_banks.
BANK_OFFSETS = {'gh': 0x200, 'oy': 0x200, 'as': 0x200, 'fk': 0x200,
                'bg': 0x200, 'lv': 0x200, 'ac': 0x5C2}

# room backgrounds are opaque: palette[0] is a real color, not transparent
OPAQUE_KINDS = ('bg', 'lv')

# toys reference two built-in animation programs (usually equal; e.g.
# watermelon-cutting-set uses 61/67).  Zero for every other item kind.
OFF_ANIM_A = 0x78
OFF_ANIM_B = 0x79


def get_anim(pkt):
    o = pkt.layout.get('anim')
    return (pkt.raw[o], pkt.raw[o + 1]) if o else (0, 0)


def set_anim(pkt, a, b):
    o = pkt.layout.get('anim')
    if o:
        pkt.raw[o] = int(a) & 0xFF
        pkt.raw[o + 1] = int(b) & 0xFF


def get_destination(pkt):
    four = bytes(pkt.raw[OFF_DEST:OFF_DEST + 4])
    return (destinations.match(pkt.model, four, pkt.raw)
            or DESTINATIONS.get(four)
            or f'unknown({four.hex(" ")})')


# Which fields a category actually uses.  Mirrors what iDmakeDL greys out
# per item type (screens captured for iD / iD L / P's, 2026-08-12);
# the 5 stats only exist from P's onward.
# shop section (packet 0x4F) -> the kind letters used elsewhere
SECTION_MAIL = 6
SECTION_KIND = {1: 'gh', 2: 'ac', 3: 'fk', 4: 'as', 6: 'mail', 7: 'bg'}


def effective_kind(pkt):
    """kind from the ASCII id, falling back to the section byte (iD)."""
    return pkt.kind if pkt.kind != '?' else SECTION_KIND.get(pkt.section, '?')


# Outings, minigames and character definitions are programs, not shop
# items: their body is code with sprite records and dialogue scattered
# through it, and the stat block offsets mean nothing.  The destination's
# first byte separates them.
# 0x94 on iD L / P's / 4U; iD parks its outings on 0x14.
PROGRAM_DESTS = (0x94, 0x14)
# 94 02 5b 02 is a program blob we have not decoded (VDPs, LCD tweaks).
# Its body is compressed, so any "text" a 1-byte charset finds there is an
# artifact -- scanning it produced 50-240 nonsense blocks per file.
OPAQUE_PROGRAM_DEST = '94025b02'
# Dialogue lives in the slivers between sprite records.  When those gaps add
# up to more than this share of the packet the body is code we cannot read,
# not a sprites+dialogue layout: real outings sit at 1-5%, undecoded blobs
# at 22-99%.
MAX_TEXT_GAP_RATIO = 0.20
# Runs one byte apart are line breaks inside one speech; a wider gap means a
# new speaker.  Merging across those (the letter body's max_gap of 8) glued a
# whole outing's cast into a single paragraph.
DIALOGUE_MAX_GAP = 2
# Real Japanese does not repeat the same kana four times running; a program
# blob does it constantly.
_REPEAT = re.compile(r'([^\u3000 ])\1{3,}')


def is_program(pkt):
    return pkt.raw[OFF_DEST] in PROGRAM_DESTS


def scans_text(pkt):
    return bytes(pkt.raw[OFF_DEST:OFF_DEST + 4]).hex() != OPAQUE_PROGRAM_DEST


def plausible_run(text, width):
    return width == 2 or not _REPEAT.search(text)


def text_gaps(spans, size, start=0x60):
    """Byte ranges that can hold dialogue: outside every sprite record and
    nested packet, and after the first one.

    The leading blob is program code.  On the 1-byte models every code byte
    decodes to *some* kana, so scanning it returns hundreds of nonsense
    runs; skipping it is what makes those models readable at all.
    """
    if not spans:
        return [(start, size)]
    spans = sorted(spans)
    out, cur = [], spans[0][0]
    for a, b in spans:
        if a > cur:
            out.append((cur, a))
        cur = max(cur, b)
    if cur < size - 2:
        out.append((cur, size - 2))
    return out


def editable_fields(pkt):
    kind, model, lay = effective_kind(pkt), pkt.model, pkt.layout
    if is_program(pkt):
        # a program has no shop fields, but it does have a destination --
        # that is what puts a game in the Game Center
        return {'dest'}
    if pkt.section == SECTION_MAIL:
        # letters / happy mail carry a message where shop items keep their
        # stat block, so none of the shop fields apply
        return {'text'}
    f = {'price', 'dest'}
    if kind in ('gh', 'oy'):
        f |= {'hunger', 'friendship'}
    elif kind == 'as' and model != 'iD':
        # iDmakeDL greys friendship out for iD toys; those bytes carry the
        # animation program there instead
        f.add('friendship')
    if kind not in ('bg', 'lv') and not (model == 'iD' and kind == 'as'):
        # iD toys shift their whole record (price lands on 0x6C), so the
        # like mask is not where food keeps it — leave it alone until the
        # offset is confirmed.
        f.add('likes')
    if lay.get('stats') is not None:
        f.add('stats')
    if kind == 'as' and lay.get('anim') is not None:
        f.add('anim')
    return f


# Accessory wear positions: 4 body types x 14 frames of (x, y) centres,
# body-type-major.  Frame rows are labelled 0-10, 12, 13, 14 — the sleeping
# frame (11) carries no position.  Centre of the screen is (64, 50);
# smaller x/y move the accessory left/up.
#
# Accessory packets open with a u16 BE length at the body start, then the
# position block, then the sprite bank:
#   table = body + 2
#   bank  = body + 2 + <that length>
# 4U/iD L carry 960 bytes there (only the first 112 are used = 4x14 pairs);
# iD carries 784 (392 pairs — it has far more character variants).
ACC_POS_REL = 0x02
ACC_FRAMES = 14
ACC_BODY_TYPES = 4
ACC_FRAME_LABELS = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 13, 14]
# position row -> character sprite frame in the pose bank
ACC_ROW_TO_POSE = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 14, 15]


def letter_text_range(pkt, bank):
    """(start, end) of a mail packet's message.

    The body always sits immediately before the sprite bank: iD keeps its
    bank at the usual body offset and puts the text in the header area,
    while iD L/P's push the bank out and fill body..bank with the message.
    """
    body = pkt.layout['bank']
    return (body, bank) if bank > body else (0x60, body)


def acc_pos_offset(pkt):
    return pkt.layout['bank'] + ACC_POS_REL


ACC_BLOCK_LENS = (784, 960)     # iD / everyone else


def acc_block_len(pkt):
    """0 when the packet has no wear-coordinate table.

    Not every section-2 packet carries one — roughly half the shop's
    "accessories" are ordinary items whose bank starts right at the body
    offset, so the u16 there is a frame count instead.  The two values are
    far apart (784/960 vs a handful of frames), so read it, don't guess."""
    o = pkt.layout['bank']
    if o + 2 > pkt.size:            # nested reward packets can be tiny
        return 0
    n = struct.unpack_from('>H', pkt.raw, o)[0]
    return n if n in ACC_BLOCK_LENS else 0


def get_acc_positions(pkt):
    """[body_type][row] -> (x, y), or None when the table does not fit.

    A nested reward accessory can be shorter than the block it would need,
    so check before reading rather than trusting the section byte."""
    base = acc_pos_offset(pkt)
    if base + 2 * ACC_BODY_TYPES * ACC_FRAMES > pkt.size:
        return None
    return [[(pkt.raw[base + 2 * (b * ACC_FRAMES + i)],
              pkt.raw[base + 2 * (b * ACC_FRAMES + i) + 1])
             for i in range(ACC_FRAMES)] for b in range(ACC_BODY_TYPES)]


def set_acc_positions(pkt, table):
    base = acc_pos_offset(pkt)
    for b, rows in enumerate(table[:ACC_BODY_TYPES]):
        for i, (x, y) in enumerate(rows[:ACC_FRAMES]):
            o = base + 2 * (b * ACC_FRAMES + i)
            pkt.raw[o] = int(x) & 0xFF
            pkt.raw[o + 1] = int(y) & 0xFF

# character grid, column-major = internal character id order
CHARACTERS = [
    'Mametchi', 'Rightchi', 'Knightchi', 'Takutotchi', 'Nandetchi',
    'Kuchipatchi', 'Doyatchi', 'Gotchimotchi',
    'Shirimotchi', 'Charatchi', 'Monakatchi', 'Mogumogutchi', 'Spacytchi',
    'Karakutchi', 'Atchitchi', 'Yumemitchi',
    'Kiraritchi', 'Himespetchi', 'Warutsutchi', 'Amiamitchi', 'Memetchi',
    'Chokomakatchi', 'Yukinkotchi', 'Hoshigalutchi',
    'Chouchoutchi', 'Harputchi', 'Patitchi', 'Kiramotchi', 'Furifuritchi',
    'Amakutchi', 'Julietchi', 'Pekopekotchi',
]


def price_offset(pkt):
    """4U keeps price at 0x76; iD/iD L/P's sit lower (models.LAYOUTS).

    iD is the odd one out: its record shape depends on the shop section,
    and toys put the price where food keeps hunger/friendship (0x6C).
    Verified on the pack — iD toys read 500/800/1200/1800 there, and
    garbage (0/4/256) at the usual 0x66.
    """
    if pkt.model == 'iD' and effective_kind(pkt) == 'as':
        return 0x6C
    return pkt.layout['price']


def get_price(pkt):
    return struct.unpack_from('>H', pkt.raw, price_offset(pkt))[0]


def set_price(pkt, value):
    struct.pack_into('>H', pkt.raw, price_offset(pkt), value)


def bank_offset(pkt):
    """Sprite bank start.  Accessories keep the wear-coordinate table where
    the bank would normally be, so their bank sits further in."""
    n = acc_block_len(pkt)
    return pkt.layout['bank'] + ACC_POS_REL + n if n else pkt.layout['bank']


def stats_verified(pkt):
    """Every model's stat block is mapped now (see models.LAYOUTS)."""
    return True


def get_likes(pkt):
    likes, dislikes = [], []
    if pkt.model != '4U':      # character order only mapped for 4U
        return likes, dislikes
    for c in range(32):
        two = (pkt.raw[pkt.layout['likes'] + c // 4] >> ((c % 4) * 2)) & 3
        if two & 1:
            likes.append(CHARACTERS[c])
        if two & 2:
            dislikes.append(CHARACTERS[c])
    return likes, dislikes


def set_likes(pkt, likes=(), dislikes=()):
    buf = bytearray(8)
    for names, bit in ((likes, 1), (dislikes, 2)):
        for name in names:
            c = CHARACTERS.index(name)
            buf[c // 4] |= bit << ((c % 4) * 2)
    pkt.raw[pkt.layout['likes']:pkt.layout['likes'] + 8] = buf


STAT_KEYS = ('intelligence', 'style', 'charisma', 'gourmet', 'strength')


def get_stats(pkt):
    o = pkt.layout.get('stats')
    if o is None:
        return dict.fromkeys(STAT_KEYS, 0)
    return dict(zip(STAT_KEYS, pkt.raw[o:o + 5]))


def set_stats(pkt, stats):
    o = pkt.layout.get('stats')
    if o is None:
        return
    for i, key in enumerate(STAT_KEYS):
        if key in stats:
            pkt.raw[o + i] = int(stats[key]) & 0xFF


def get_hunger(pkt):
    return pkt.raw[pkt.layout['hunger']]


def get_friendship(pkt):
    return pkt.raw[pkt.layout['friendship']]


def set_friendship(pkt, value):
    pkt.raw[pkt.layout['friendship']] = int(value) & 0xFF


def set_hunger(pkt, value):
    pkt.raw[pkt.layout['hunger']] = int(value) & 0xFF


def set_destination(pkt, code, label=None):
    """code: a catalogue entry (8-char hex) or raw 4 bytes.  iD keeps its
    per-item index byte, so the write goes through destinations.apply.
    `label` picks between categories that share one code (iD games vs
    outings)."""
    cur = bytes(pkt.raw[OFF_DEST:OFF_DEST + 4])
    if isinstance(code, (bytes, bytearray)):
        code = bytes(code).hex()
    merged = destinations.apply(pkt.model, code, cur)
    if len(merged) != 4:
        raise ValueError('destination must be 4 bytes')
    pkt.raw[OFF_DEST:OFF_DEST + 4] = merged
    # iD keeps games and outings on one destination and splits them at
    # 0x64, so picking the category has to write that byte too
    extra = destinations.extra_for(pkt.model, code, label)
    if extra and len(pkt.raw) > extra[0]:
        pkt.raw[extra[0]] = extra[1]
    pkt.raw[0x73] = 0x02 if code[1] == 0x01 else 0x00   # food section flag


# Like-mask rosters, pinned by 44 files that differ only in which pair of
# characters is set (6_ID/IDL/ps_호불호, 2026-08-26).  Every one of the 44
# re-encodes byte-identically from the table below, with no slot claimed by
# two names.  None marks a slot the pack uses but no labelled file covers.
#
# P's turned out to be the 4U roster in the same order (only the
# romanisation differs: Rightchi/Rightchi, Takutotchi/Takutotchi,
# Atchitchi/Atchitchi, Warutsutchi/Warutsutchi, Chokomakatchi/Chokomakatchi,
# Hoshigalutchi/Hoshigalutchi, Chouchoutchi/Chouchoutchi, Harputchi/Harputchi),
# so the two share one list.
ID_ROSTER = [
    'Mametchi', 'Kuromametchi', 'Gozarutchi', 'Kuchipatchi',
    'Kikitchi', 'Lovelitchi', 'Chamametchi', 'Makiko',
    'Memetchi', 'Furawatchi', 'Uwasatchi', None,
    'Melodytchi', None, None, None,
]

# 0-31 is the roster every iD L firmware shares; 32-46 is used by the pack
# but no labelled file reaches it; 47-57 and 71-73 are what the
# 15th-anniversary and Spacy line-ups add.  58-70 is never set anywhere.
IDL_ROSTER = [
    'Mametchi', 'Kuromametchi', 'Shinshitchi', 'Peintotchi',
    'Kuishinbotchi', 'Kuchipatchi', 'Shoototchi', 'Gozarutchi',
    'Sunopotchi', 'Kikitchi', 'Bokutchi', 'Guriguritchi',
    'Spacytchi', 'Herotchi', 'Meistertchi', 'Lovelitchi',
    'Melodytchi', 'Moriritchi', 'Chamametchi', 'Memetchi',
    'Perotchi', 'Shigurehimetchi', 'Makiko', 'Pitchipitchi',
    'Furawatchi', 'Ponpontchi', 'Agetchi', 'Watawatatchi',
    'Naturatchi', 'Uwasatchi', 'Madonnatchi', 'Giragiratchi',
] + [None] * 15 + [
    'Oyajitchi', 'Otogitchi', 'Prince Tamahiko', 'Akahanatchi',
    'Nonopotchi', 'Racequeentchi', 'Mimitchi', 'Himetchi',
    'Momotchi', 'Princess Tamahiko', 'Antoinetchi',
] + [None] * 13 + [
    'Pipospetchi', 'Akaspetchi', 'Himespetchi',
]

ROSTERS = {'iD': ID_ROSTER, 'iDL': IDL_ROSTER, "P's": CHARACTERS,
           '4U': CHARACTERS}


def like_labels(pkt):
    """Button captions for the like grid; None where the slot is unnamed."""
    n = likes_slots(pkt)
    r = ROSTERS.get(pkt.model, [])
    return [r[c] if c < len(r) else None for c in range(n)]


def like_roster(pkt):
    """Named slots only, for the hint under the grid."""
    return [x for x in ROSTERS.get(pkt.model, []) if x] or None


def get_compat(pkt):
    """Which devices will accept this packet (byte 0xFF bitmask).

    Nested reward packets can be shorter than 0x100 bytes, so the field is
    not always present."""
    mask = (pkt.raw[models.OFF_COMPAT_MASK]
            if pkt.size > models.OFF_COMPAT_MASK else 0)
    return {'mask': mask,
            'models': [m for m, bit in models.COMPAT_BIT.items() if mask & bit]}


def set_compat(pkt, model_list):
    mask = 0
    for m in model_list:
        mask |= models.COMPAT_BIT.get(m, 0)
    pkt.raw[models.OFF_COMPAT_MASK] = mask


def likes_slots(pkt):
    return pkt.layout['likes_slots']


def get_likes_raw(pkt):
    """Per character slot: 0 none, 1 like, 2 dislike (internal id order)."""
    o = pkt.layout['likes']
    return [(pkt.raw[o + c // 4] >> ((c % 4) * 2)) & 3
            for c in range(likes_slots(pkt))]


def set_likes_raw(pkt, values):
    """Read-modify-write, so bits outside the roster stay untouched.

    iD only owns 22 of the 32 bits at 0x68; blindly rewriting all four
    bytes would wipe the unrelated byte at 0x6B."""
    o = pkt.layout['likes']
    for c, v in enumerate(values[:likes_slots(pkt)]):
        shift = (c % 4) * 2
        byte = pkt.raw[o + c // 4] & ~(3 << shift)
        pkt.raw[o + c // 4] = byte | ((int(v) & 3) << shift)
