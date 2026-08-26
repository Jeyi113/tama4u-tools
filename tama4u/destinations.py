"""Per-model destination catalogue (packet bytes 0x4E-0x51).

Collected from the four download packs, cross-checked against the labels
Mr.Blinky's iDmakeDL prints for the same field.

iD L / P's / 4U use one fixed code per shop section.  **iD is different**:
its third byte is a per-item index, so only bytes 0, 1 and 3 identify the
section — changing the destination there must keep byte 2 intact.

Program packets (games, outings) sit on 0x14 / 0x94.  iD L, P's and 4U
tell the two apart inside the destination itself (0x5B games, 0x47
outings), but iD parks both on the same `14 02 00 00` and keeps the
category in a separate byte at 0x64: 0x37 games, 0x0F outings.  That is
what `extra` carries — an (offset, value) pair the packet must also
match, and that `set_destination` writes when you pick the category.
"""

# model -> [(label, code hex, mask hex[, (offset, value)])]
# mask marks the bytes that matter; the optional 4th element is a byte
# outside the destination that the category also depends on.
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
        ('게임센터 · 게임',    '14020000', 'ffffffff', (0x64, 0x37)),
        ('외출지',             '14020000', 'ffffffff', (0x64, 0x0F)),
    ],
    'iDL': _COMMON + [
        ('우편함 · 편지',          '81065101', 'ffffffff'),
        ('우편함 · 해피메일',      '81065202', 'ffffffff'),
        ('타마모리 · 액세서리 (P\'s용)', '81023500', 'ffffffff'),
        ('타마데파 · 씨앗',        '81082900', 'ffffffff'),
        ('타마데파 · 생활용품',    '81042902', 'ffffffff'),
        ('타마베이커리 · 간식',    '81010c02', 'ffffffff'),
        ('게임센터 · 게임',        '94025b01', 'ffffffff'),
        ('외출지',                 '94024702', 'ffffffff'),
    ],
    "P's": _COMMON + [
        ('보물상자 · 편지',        '81065101', 'ffffffff'),
        ('보물상자 · 스탬프카드',  '81065203', 'ffffffff'),
        ('통신놀이 · 레시피',      '81092900', 'ffffffff'),
        ('타마모리 · 액세서리 2',  '81023500', 'ffffffff'),
        ('게임센터 · 게임',        '94025b01', 'ffffffff'),
        ('외출지',                 '94024702', 'ffffffff'),
        ('VDP · 미해독 프로그램',  '94025b02', 'ffffffff'),
    ],
    '4U': _COMMON + [
        ('냉장고 직행 · 식사 (비매품)', '81010101', 'ffffffff'),
        ('냉장고 직행 · 간식 (비매품)', '81010102', 'ffffffff'),
        ('빙고 정의',              '81082900', 'ffffffff'),
        ('게임센터 · 게임',        '94025b01', 'ffffffff'),
        ('외출지',                 '94024702', 'ffffffff'),
        ('카드 · 캐릭터 프로그램', '94024803', 'ffffffff'),
    ],
}


def options(model):
    return CATALOG.get(model, CATALOG['4U'])


def extra_of(entry):
    return entry[3] if len(entry) > 3 else None


def match(model, code, raw=None):
    """Return the catalogue label for a packet's 4 destination bytes.

    `raw` is the whole packet; without it, entries that also depend on a
    byte outside the destination can only be reported when nothing else
    claims the code (iD's games and outings share one destination)."""
    pending = None
    for entry in options(model):
        label, tmpl, mask = entry[:3]
        t, m, c = bytes.fromhex(tmpl), bytes.fromhex(mask), bytes(code)
        if not all(not m[i] or t[i] == c[i] for i in range(4)):
            continue
        extra = extra_of(entry)
        if extra is None:
            return label
        off, val = extra
        if raw is not None:
            if len(raw) > off and raw[off] == val:
                return label
        elif pending is None:
            pending = label
    return pending


def apply(model, code, current):
    """Merge a chosen destination into the packet's existing bytes,
    preserving any byte the mask leaves free (iD's item index)."""
    for entry in options(model):
        label, tmpl, mask = entry[:3]
        if tmpl == code:
            t, m = bytes.fromhex(tmpl), bytes.fromhex(mask)
            return bytes(t[i] if m[i] else current[i] for i in range(4))
    return bytes.fromhex(code)


def extra_for(model, code, label=None):
    """The (offset, value) a chosen category also needs written, if any.

    Several categories can share one destination code, so the label picks
    between them when given."""
    for entry in options(model):
        if entry[1] != code:
            continue
        if label is not None and entry[0] != label:
            continue
        return extra_of(entry)
    return None
