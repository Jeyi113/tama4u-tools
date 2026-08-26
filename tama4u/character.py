"""Download-character stat block (`_a2` packet, little-endian).

Every offset below was pinned by single-field diffs against
Mr.Blinky's "Tama 4U character data editor" v1.02 (2026-08-12).
"""
import os
import struct

OFF_GRAPHICS   = 0x208   # u16 — graphics index
# u16 LE, and *not* an opaque id: the high byte is a roster page that
# encodes gender (0x13 boy / 0x1B girl) and the low byte is the slot inside
# that page.  Verified on 69 4U characters — the 0x13 page holds Mametchi,
# Oyajitchi, Gozarutchi, Paankuntchi... and 0x1B holds Lovelitchi, Makiko,
# Furawatchi, Ichigo-chantchi...  Slots are sequential and unique.
# REVERT_ID is the id the device restores when the transformation ends;
# every official download sets it equal to TAMA_ID (69/69).
OFF_TAMA_ID    = 0x204   # u16 LE
OFF_REVERT_ID  = 0x206   # u16 LE
ROSTER_PAGE = {0x13: 'Boy', 0x1B: 'Girl'}
OFF_PERSONALITY = 0x20C  # u8
OFF_SKILLS     = 0x20D   # u8 x5
OFF_STAGE      = 0x212   # u8  (5 = download character)
OFF_WEIGHT_STD = 0x213   # u8  "Normal" weight
OFF_WEIGHT_MIN = 0x214   # u8
OFF_HUNGER_DEP = 0x215   # u8  hunger depletion rate
OFF_HAPPY_DEP  = 0x216   # u8  happiness depletion rate
OFF_SICKNESS   = 0x217   # u8  random sickness rate
OFF_WAKE       = 0x218   # u8  wake-up hour
OFF_SLEEP      = 0x219   # u8  sleep hour, STORED AS (displayed - 1)
OFF_GENDER     = 0x21A   # u8
OFF_BODY_TYPE  = 0x21B   # u8  1..3 -> clothes piece set 1..3
OFF_SEP_CLOTHES = 0x21C  # u8
OFF_SEP_ACCESSORY = 0x21E  # u8
OFF_BIRTH_MONTH = 0x220  # u8
OFF_BIRTH_DAY  = 0x221   # u8
OFF_LIKE_INDEX = 0x222   # u16
OFF_TRANSFORM_TYPE = 0x22E    # u16
OFF_TRANSFORM_SERIAL = 0x230  # u16
OFF_TRANSFORM_NAME = 0x232    # 10 slots, internal charset u16
OFF_NAME2      = 0x246   # 9 slots
OFF_DIALOGUE   = 0x272   # 14 slots x 150 bytes

GENDER = {0: 'Boy', 1: 'Girl'}
STAGE = {1: 'Baby', 2: 'Toddler', 3: 'Adult',
         4: 'Transform character', 5: 'Download character'}
# body type numbering differs between models
BODY_TYPE = {
    '4U': {0: 'Ignore', 1: 'Normal', 2: 'Kuchipatchi', 3: 'Neenetchi',
           4: 'Toddlers'},
    "P's": {1: 'Normal', 2: 'Kuchipatchi', 3: 'Monakatchi', 4: 'Doyatchi'},
}
TRANSFORM_TYPE = {0: 'Meal', 1: 'Snack', 2: 'Toy', 4: 'Clothes/accessory',
                  6: 'Minigame', 8: 'Outing'}

# like/dislike index (OFF_LIKE_INDEX).  0x41FF..0x5AFF pick a specific
# character (index 0..25); 0x4141..0x4146 pick a trait; 0x0000 = none.
_LIKE_CHARS = [
    'Mametchi', 'MameLabtchi', 'Naughty Mametchi', 'Kuchipatchi',
    'Kuchipatchin', 'JeanisKuchipa', 'Spacytchi', 'Kirari Spacy',
    'King Spacy', 'Kuromametchi', 'Kuromamesenpai', 'Otakuromame',
    'Orenetchi', 'Oreotonatchi', 'Memetchi', 'Gourmemequeen',
    'Memeobatchi', 'Himespetchi', 'Mamelove Himespetchi', 'Lovelitchi',
    'Lovelitchi Lovely Fire', 'PochaLovelitchi', 'Melodytchi',
    'Oyamelojitchi', 'Neenetchi', 'Slim Neene',
]
_LIKE_TRAITS = ['Likes elegance', 'Likes coolness', 'Likes ??? (4143)',
                'Likes ??? (4144)', 'Likes sports', 'Likes ??? (4146)']
LIKE_INDEX = {0x0000: 'No likes and dislikes'}
for _i, _n in enumerate(_LIKE_CHARS):
    LIKE_INDEX[((0x41 + _i) << 8) | 0xFF] = _n
for _i, _n in enumerate(_LIKE_TRAITS):
    LIKE_INDEX[0x4141 + _i] = _n


def body_types(model='4U'):
    return BODY_TYPE.get(model, BODY_TYPE['4U'])


DIALOGUE_LABELS = [
    'Birthday', 'Marry proposal', 'Hungry', 'Play', 'Dress-up',
    'Upset (park camping)', 'Goodbye (good end)', 'Goodbye (bad end)',
    'Hobby skill rnd NFC4', 'Dream job rnd NFC3', 'Fav.food rnd NFC2',
    'Best friend rnd NFC1', 'Random talk 1', 'Random talk 2',
]

_U8 = {
    'graphics': None, 'personality': OFF_PERSONALITY, 'stage': OFF_STAGE,
    'weight_std': OFF_WEIGHT_STD, 'weight_min': OFF_WEIGHT_MIN,
    'hunger_dep': OFF_HUNGER_DEP, 'happy_dep': OFF_HAPPY_DEP,
    'sickness': OFF_SICKNESS, 'wake': OFF_WAKE, 'gender': OFF_GENDER,
    'body_type': OFF_BODY_TYPE, 'sep_clothes': OFF_SEP_CLOTHES,
    'sep_accessory': OFF_SEP_ACCESSORY,
    'birth_month': OFF_BIRTH_MONTH, 'birth_day': OFF_BIRTH_DAY,
}
_U16 = {'tama_id': OFF_TAMA_ID, 'revert_id': OFF_REVERT_ID,
        'graphics': OFF_GRAPHICS, 'like_index': OFF_LIKE_INDEX,
        'transform_type': OFF_TRANSFORM_TYPE,
        'transform_serial': OFF_TRANSFORM_SERIAL}


def get_stats(pkt):
    out = {k: pkt.raw[o] for k, o in _U8.items() if o is not None}
    out.update({k: struct.unpack_from('<H', pkt.raw, o)[0]
                for k, o in _U16.items()})
    out['skills'] = list(pkt.raw[OFF_SKILLS:OFF_SKILLS + 5])
    out['sleep'] = pkt.raw[OFF_SLEEP] + 1        # displayed value
    return out


def set_stats(pkt, stats):
    for k, o in _U8.items():
        if o is not None and k in stats:
            pkt.raw[o] = int(stats[k]) & 0xFF
    for k, o in _U16.items():
        if k in stats:
            struct.pack_into('<H', pkt.raw, o, int(stats[k]) & 0xFFFF)
    if 'skills' in stats:
        for i, v in enumerate(stats['skills'][:5]):
            pkt.raw[OFF_SKILLS + i] = int(v) & 0xFF
    if 'sleep' in stats:
        pkt.raw[OFF_SLEEP] = (int(stats['sleep']) - 1) & 0xFF


_INDEX = None


def item_index(model):
    """serial -> item name, harvested from the download packs."""
    global _INDEX
    if _INDEX is None:
        import json
        path = os.path.join(os.path.dirname(__file__), 'itemindex.json')
        try:
            _INDEX = json.load(open(path, encoding='utf-8'))
        except Exception:
            _INDEX = {}
    return _INDEX.get(model, {})


def item_name(model, serial):
    return item_index(model).get(str(serial))


# The character's own accessory (wardrobe frames 23-26) DOES carry wear
# coordinates -- they sit at the very end of the parent packet, *after* the
# nested wardrobe packet, in exactly the accessory-item format:
# 4 body types x 14 frames x (x, y), 112 bytes.  17 of 69 4U characters use
# it; the rest leave it zero and fall back to a plain top-left overlay.
# All four body-type rows are identical, since a character has one body.
ACC_TAIL_LEN = 4 * 14 * 2
ACC_ROW_LEN = 14 * 2        # one body type
# coordinate row -> wardrobe pose frame (1-based).  Rows 12/13 are the two
# 44x52 poses, which is why they are the rows that differ from the rest.
ACC_ROW_TO_FRAME = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 14, 15]
# pose frame -> which accessory frame is drawn on it
ACC_FRAME_FOR_POSE = {1: 23, 2: 23, 3: 23, 4: 23, 5: 23, 6: 23, 11: 23,
                      7: 24, 8: 24, 9: 24, 10: 24,
                      13: 25, 14: 26, 15: 26}


def acc_tail_offset(pkt):
    """(offset, length) of the wear table, or None.

    68 of 69 characters leave exactly 112 bytes, but fk00024_1-yumemitchi
    ships 108 -- its last body-type row is two pairs short.  Requiring an
    exact 112 dropped that file's table entirely, so accept anything from
    one full row up to the full table and read what is actually there.
    """
    if not pkt.children:
        return None
    end = max(c.offset + c.size for c in pkt.children)
    tail = pkt.size - 2 - end
    return (end, tail) if ACC_ROW_LEN <= tail <= ACC_TAIL_LEN else None


def get_acc_positions(pkt):
    """[body_type][row] -> (x, y); None when the packet has no table.

    A character has one body type, so the four rows are identical in every
    retail file; entries past a short tail fall back to row 0 rather than
    reading zeros.
    """
    got = acc_tail_offset(pkt)
    if got is None:
        return None
    o, length = got
    tail = pkt.raw[o:o + length]
    if not any(tail):
        return None
    def pair(k):
        return (tail[2 * k], tail[2 * k + 1]) if 2 * k + 1 < length else None
    base = [pair(i) or (64, 42) for i in range(14)]
    return [[pair(b * 14 + i) or base[i] for i in range(14)] for b in range(4)]


def set_acc_positions(pkt, table):
    got = acc_tail_offset(pkt)
    if got is None:
        raise ValueError('this packet has no wear-coordinate table')
    o, length = got
    for b, rows in enumerate(table[:4]):
        for i, (x, y) in enumerate(rows[:14]):
            k = 2 * (b * 14 + i)
            if k + 1 >= length:          # short tail: nothing to write into
                continue
            pkt.raw[o + k] = int(x) & 0xFF
            pkt.raw[o + k + 1] = int(y) & 0xFF


def roster(value):
    """Split a tama/revert id into its roster page + slot."""
    page, slot = (value >> 8) & 0xFF, value & 0xFF
    return {'page': page, 'slot': slot,
            'gender': ROSTER_PAGE.get(page), 'value': value}


def set_roster(pkt, off, gender=None, slot=None):
    cur = struct.unpack_from('<H', pkt.raw, off)[0]
    page = cur >> 8
    if gender is not None:
        for p, g in ROSTER_PAGE.items():
            if g == gender:
                page = p
    if slot is None:
        slot = cur & 0xFF
    struct.pack_into('<H', pkt.raw, off, (page << 8) | (int(slot) & 0xFF))


# 0x272 + 14 dialogue slots x 150 bytes
CHAR_MIN_SIZE = OFF_DIALOGUE + 14 * 150


def is_character(pkt):
    """The 0x50-0x51 signature alone is not enough: those two bytes are the
    tail of the destination code, so an iD item whose destination happens to
    end 48 03 matches it.  A character also has to be big enough to hold the
    stat block and all 14 dialogue slots."""
    return pkt.type_sig[4:6] == b'\x48\x03' and pkt.size >= CHAR_MIN_SIZE
