"""Per-model destination catalogue (packet bytes 0x4E-0x51).

Collected from the four download packs, cross-checked against the labels
Mr.Blinky's iDmakeDL prints for the same field.

iD L / P's / 4U use one fixed code per shop section.  **iD is different**:
its third byte is a per-item index, so only bytes 0, 1 and 3 identify the
section — changing the destination there must keep byte 2 intact.
"""

# model -> [(label, code hex, mask hex)] ; mask marks the bytes that matter
_COMMON = [
    ('레스토랑 · 식사',        '81010201', 'ffffffff'),
    ('레스토랑 · 간식',        '81010d02', 'ffffffff'),
    ('타마데파 · 장난감',      '81042a01', 'ffffffff'),
    ('타마모리 · 옷',          '81033300', 'ffffffff'),
    ('타마모리 · 액세서리',    '81023400', 'ffffffff'),
    ('고치 인테리어 · 방',     '81071f00', 'ffffffff'),
]

CATALOG = {
    'iD': [
        ('레스토랑 · 식사',    '01010001', 'ffff00ff'),
        ('레스토랑 · 간식',    '01010003', 'ffff00ff'),
        ('타마데파 · 장난감',  '01040001', 'ffff00ff'),
        ('타마모리 · 액세서리', '01020000', 'ffff00ff'),
        ('고치 인테리어 · 방', '01070000', 'ffff00ff'),
        ('사진관 · 의상',      '02030001', 'ffff00ff'),
        ('우편함 · 편지',      '01060000', 'ffffffff'),
    ],
    'iDL': _COMMON + [
        ('우편함 · 편지',          '81065101', 'ffffffff'),
        ('우편함 · 해피메일',      '81065202', 'ffffffff'),
        ('타마모리 · 액세서리 (P\'s용)', '81023500', 'ffffffff'),
        ('타마데파 · 씨앗',        '81082900', 'ffffffff'),
        ('타마데파 · 생활용품',    '81042902', 'ffffffff'),
        ('타마베이커리 · 간식',    '81010c02', 'ffffffff'),
    ],
    "P's": _COMMON + [
        ('보물상자 · 편지',        '81065101', 'ffffffff'),
        ('보물상자 · 스탬프카드',  '81065203', 'ffffffff'),
        ('통신놀이 · 레시피',      '81092900', 'ffffffff'),
        ('타마모리 · 액세서리 2',  '81023500', 'ffffffff'),
    ],
    '4U': _COMMON + [
        ('냉장고 직행 · 식사 (비매품)', '81010101', 'ffffffff'),
        ('냉장고 직행 · 간식 (비매품)', '81010102', 'ffffffff'),
        ('빙고 정의',              '81082900', 'ffffffff'),
        ('미니게임',               '94025b01', 'ffffffff'),
    ],
}


def options(model):
    return CATALOG.get(model, CATALOG['4U'])


def match(model, code):
    """Return the catalogue label for a packet's 4 destination bytes."""
    for label, tmpl, mask in options(model):
        t, m, c = bytes.fromhex(tmpl), bytes.fromhex(mask), bytes(code)
        if all(not m[i] or t[i] == c[i] for i in range(4)):
            return label
    return None


def apply(model, code, current):
    """Merge a chosen destination into the packet's existing bytes,
    preserving any byte the mask leaves free (iD's item index)."""
    for label, tmpl, mask in options(model):
        if tmpl == code:
            t, m = bytes.fromhex(tmpl), bytes.fromhex(mask)
            return bytes(t[i] if m[i] else current[i] for i in range(4))
    return bytes.fromhex(code)
