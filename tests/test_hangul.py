"""Hangul patch: code allocation and the hook assembly, without firmware files."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from tama4u import hangul, s1c33  # noqa: E402

CS = json.load(open(os.path.join(os.path.dirname(__file__), '..', 'tama4u', 'charset-ps.json')))


def test_encode():
    assert hangul.encode('가', CS) == b'\xc7\x01'
    assert hangul.encode('힝', CS) == bytes([0xD9, 2350 - 9 * 254])
    # the device-verified boot menu pair
    assert hangul.encode('이어12', CS).hex() == 'cd18cc7c6e6f'
    assert hangul.encode('지우けす', CS).hex() == 'cda0ccd8090d'


def test_jamo_after_syllables():
    assert hangul.encode('ㄱ', CS) == hangul.code(2350)
    assert hangul.encode('ㅄ', CS) == hangul.code(2350 + 50)
    assert len(hangul.GLYPHS) <= 16 * 254


def test_codes_avoid_terminators():
    for g in range(len(hangul.GLYPHS)):
        lead, trail = hangul.LEADS[g // 254], g % 254 + 1
        assert trail not in (0x00, 0xFF) and lead not in (0x00, 0xFF)


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
    assert lab['KADV'] - lab['KGLYPH'] == 0x48
    assert hangul.TBL_AT + 128 <= hangul.CODE_AT
    assert 'sra %r5,0x1' in text          # KCENT's centring tail


def test_safe_regions_avoid_storage():
    # data reset erases 0x2D0000-0x37FFFF and 0x570000-; downloads live there
    for lo, hi in hangul.SAFE:
        assert hi <= 0x2D0000 or (0x380000 <= lo and hi <= 0x570000)
    assert hangul.SAFE[2][0] <= hangul.TBL_AT < hangul.SAFE[2][1]


def test_name_tables():
    from tama4u import hangul_name as N
    pair, lst = N.tables()
    assert len(pair) == 19 * 21 and sum(p != N.END for p in pair) == 354
    assert lst.count(N.END) == 354 and len(lst) - 354 == 2350
