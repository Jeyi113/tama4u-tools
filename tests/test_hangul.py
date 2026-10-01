"""Hangul patch: code allocation and the hook assembly, without firmware files."""
import json
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from tama4u import hangul, s1c33  # noqa: E402

CS = json.load(open(os.path.join(os.path.dirname(__file__), '..', 'tama4u', 'charset-ps.json')))


def test_encode():
    assert hangul.encode('가', CS) == b'\xc7\x01'
    assert hangul.encode('힝', CS) == bytes([0xD9, 2349 - 9 * 245 + 1])
    # trails skip 0xD0-0xD8: glyph 206 is the last before the gap, 207 after
    assert hangul.code(206) == b'\xc7\xcf' and hangul.code(207) == b'\xc7\xd9'
    assert hangul.code(244) == b'\xc7\xfe' and hangul.code(245) == b'\xc8\x01'


def test_jamo_after_syllables():
    assert hangul.encode('ㄱ', CS) == hangul.code(2350)
    assert hangul.encode('ㅄ', CS) == hangul.code(2350 + 50)
    assert len(hangul.GLYPHS) <= 16 * hangul.PER


def test_codes_avoid_terminators():
    for g in range(len(hangul.GLYPHS)):
        lead, trail = hangul.code(g)
        assert trail not in (0x00, 0xFF) and not 0xD0 <= trail <= 0xD8
        assert lead in hangul.LEADS
    assert len({hangul.code(g) for g in range(len(hangul.GLYPHS))}) == len(hangul.GLYPHS)


def test_hooks_disassemble():
    code, lab = hangul._hooks()
    text = s1c33.text(code, base=hangul.BASE + hangul.CODE_AT)
    assert f'xld.w %r4,{hangul.BASE + hangul.TBL_AT:#x}' in text
    assert 'xsub %r5,0xc7' in text and 'xsub %r5,0xd9' in text
    assert '.word' not in text
    # far tail jumps back into the firmware (ext + jp, raw displacement)
    for src, dst in ((lab['KG_BIG'] + 6, 0x024019C6), (lab['KG_NO'], 0x02401BDC)):
        off = src - hangul.BASE - hangul.CODE_AT
        e, j = int.from_bytes(code[off:off + 2], 'little'), int.from_bytes(code[off + 2:off + 4], 'little')
        d = ((e & 0x1FFF) << 8 | j & 0xFF)
        d -= (1 << 21) if d & (1 << 20) else 0
        assert j >> 8 == 0x1E and src + 2 + 2 * d == dst
    assert lab['KGLYPH'] < lab['KADV'] < lab['KCENT']
    assert hangul.TBL_AT + 128 <= hangul.CODE_AT
    assert 'sra %r5,0x1' in text          # KCENT's centring tail


def test_safe_regions_avoid_storage():
    # data reset erases 0x2D0000-0x37FFFF and 0x570000-; downloads live there
    for lo, hi in hangul.SAFE:
        assert hi <= 0x2D0000 or (0x380000 <= lo and hi <= 0x570000)
    assert hangul.SAFE[2][0] <= hangul.TBL_AT < hangul.SAFE[2][1]


def test_name_tables():
    from tama4u import hangul_name as N
    pair, lst, dec = N.tables()
    assert len(pair) == 19 * 21 and sum(p != N.END for p in pair) == 354
    assert lst.count(N.END) == 354 and len(lst) - 354 == 2350
    # DECOMP round-trips every syllable through PAIR/LIST
    for g, v in enumerate(dec):
        ci, ji, ti = v & 31, v >> 5 & 31, v >> 10
        assert lst[pair[ci * 21 + ji] + ti] == g


def test_name_symbols_are_mono():
    from tama4u import hangul_name as N
    assert N.EMO == list(range(0x51, 0x6C))      # no 0xD0-0xD7 colour icons


def test_text_in_place_and_relocated():
    from tama4u import hangul_text as T
    rom = bytearray(0x560000)
    a, b = 0x538000, 0x538008                  # 'あい' (slot 4) and 'あいうえお' (slot 8)
    rom[a:a + 2] = b'\x01\x02'; rom[b:b + 5] = b'\x01\x02\x03\x04\x05'
    struct.pack_into('<I', rom, 0x538100, hangul.BASE + a)
    v = hangul.BASE + b                        # xld.w %r7,b at 0x400000
    struct.pack_into('<3H', rom, 0x400000, 0xC000 | v >> 19, 0xC000 | v >> 6 & 0x1FFF,
                     0x6C07 | (v & 0x3F) << 4)
    free = [0x55D000]

    def alloc(n):
        free[0] += n
        return free[0] - n
    got = T.apply(rom, {a: T.encode('가'), b: T.encode('거실 가기!')}, alloc)
    assert got == (1, 1) and rom[a:a + 4] == T.encode('가') + b'\0\0'
    new, rd = T._xld(rom, 0x400000)
    assert rd == 7 and rom[new - hangul.BASE:].startswith(T.encode('거실 가기!') + b'\0')
    assert T.encode('다/iDL') == hangul.code(hangul.KS.index(0xB4D9)) + b'\xff\xfa\xe3\xeb'



def test_half_space():
    from tama4u import hangul_text as T
    assert T.encode('가 나') == hangul.encode('가', CS) + hangul.code(hangul.HALF) + hangul.encode('나', CS)
    assert T.encode('\u3000') == b'\x6c'
    code, lab = hangul._hooks()
    assert 'KAH' in lab and 'KC_H9' in lab


def test_profile_field_limits():
    from tama4u import hangul_text as T
    rom = bytearray(0x560000)
    rom[0x5580EC:0x5580F2] = b'\x01\x02\x03\x04\x05\x00'
    try:
        T.apply(rom, {0x5580EC: T.encode('물병자리')}, lambda n: 0x55D000)
    except ValueError:
        pass
    else:
        raise AssertionError('8-byte zodiac accepted')
    T.apply(rom, {0x5580EC: T.encode('쌍둥이')}, lambda n: 0x55D000)


def test_item_name_fixed_field():
    from tama4u import hangul_text as T
    rom = bytearray(0x560000)
    a = 0x3CF6A8
    rom[a:a + 14] = b'idn_gh15001_1\0'; rom[a + 0x26] = 0x3A
    n = a + T.ITEM_NAME
    rom[n:n + 12] = b'\x36\x33\x3c\x0e\x2e\x00\x00\x00\x00\x00\x00\x02'
    T.apply(rom, {n: T.encode('김밥')}, lambda k: 0x55D000)
    assert rom[n:n + 12] == T.encode('김밥').ljust(10, b'\0') + b'\x00\x02'
    try:
        T.apply(rom, {n: T.encode('함박스테이크요')}, lambda k: 0x55D000)
    except ValueError:
        pass
    else:
        raise AssertionError('over-long item name accepted')



def test_diary_lines():
    from tama4u import hangul_text as T
    # seen on the emulator: 공원 순찰을 / 했어! 오늘 / 도 평화로웠 / 어♪
    assert T.diary_lines('공원 순찰을했어! 오늘도 평화로웠어♪') == ['공원 순찰을', '했어! 오늘', '도 평화로웠', '어♪']


def test_diary_hooks_assemble():
    from tama4u import hangul_diary as D
    blk, lab, arr, cells = D.block(0x02560000)
    assert lab['DFIX'] == 0x02560000 and lab['DVIEW'] > lab['DFIX'] and lab['DNEXT'] > lab['DVIEW']
    assert arr % 4 == 0 and cells == arr + D.COUNT * D.NEW
    assert cells + D.COUNT * D.CELL == 0x02560000 + len(blk)
    wrap = blk[:len(D.assemble(0x02560000, arr, cells)[0])]
    words = struct.unpack(f'<{len(wrap) // 2}H', wrap)
    # no stack at all: no pushn/popn, sub/add %sp, call
    assert not any(w & 0xFFF0 in (0x0200, 0x0240) or w & 0xFC00 in (0x8400, 0x8000) or w >> 8 == 0x1C
                   for w in words)
    assert D.KEEP + 3 <= 36                                        # text + NUL + MARK + index


def test_diary_long_entries():
    from tama4u import hangul_diary as D
    T = __import__('tama4u.hangul_text', fromlist=['apply'])
    rom = bytearray(0x560000)
    arr = 0x500000
    long = T.encode('가' * 36)                                     # 6 lines, 72 bytes: fits
    assert T.apply(rom, {0x558370 + 40 * 3: long}, None, {}, diary=arr) == (1, 0)
    assert rom[arr + 80 * 3:arr + 80 * 4] == long.ljust(80, b'\0')
    for bad in (T.encode('가' * 37), bytes(range(1, 81))):        # 7th line / > 79 bytes
        try:
            T.apply(rom, {0x558370: bad}, None, {}, diary=arr)
            assert False
        except ValueError:
            pass


def test_diary_name_marks():
    from tama4u import hangul_text as T, hangul_diary as D
    b = T.encode_diary('①＆②함께 웃었어♪')
    assert b[:2] == bytes([D.TOKEN, 1]) and bytes([D.TOKEN, 2]) in b and b'\x6c' not in b
    assert T.encode_diary('     ＆     함께') == T.encode_diary('①＆②함께')   # old aligned form
    chars, used = T.template_chars(b, [(0, 5), (6, 5)])
    assert used == [1, 2] and chars == 3 + 1 + 3 + 7          # names count 3 each
    tab = D.cell_table(open(os.path.expanduser('~/Downloads/TMGC_PS.BIN'), 'rb').read()) \
        if os.path.exists(os.path.expanduser('~/Downloads/TMGC_PS.BIN')) else None
    if tab:
        k = [i for i in range(D.COUNT) if tab[D.CELL * i]][0]
        e = tab[D.CELL * k:D.CELL * (k + 1)]
        assert e[0] in (1, 2, 3) and e[3] == D.NAMES                 # first name stored at NAMES


def test_diary_cell_table_terminated():
    """Every name-cell entry ends in a 0xFF offset and has no 0-length cell:
    the recorder's copy loop runs a cell's length down to 0 (a 3-name entry
    without the terminator once read a 0 length and wrote through memory)."""
    from tama4u import hangul_diary as D
    path = os.path.expanduser('~/Downloads/TMGC_PS.BIN')
    if not os.path.exists(path):
        return
    t = D.cell_table(open(path, 'rb').read())
    for k in range(D.COUNT):
        e = t[D.CELL * k:D.CELL * (k + 1)]
        assert e[1 + 3 * e[0]] == 0xFF
        assert all(e[2 + 3 * i] > 0 for i in range(e[0]))
