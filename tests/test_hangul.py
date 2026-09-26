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
