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


def test_codes_avoid_terminators():
    for g in range(len(hangul.KS)):
        lead, trail = hangul.LEADS[g // 254], g % 254 + 1
        assert trail not in (0x00, 0xFF) and lead not in (0x00, 0xFF)


def test_hooks_disassemble():
    code, lab = hangul._hooks()
    text = s1c33.text(code, base=hangul.BASE + hangul.CODE_AT)
    assert 'xld.w %r4,0x2311000' in text
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
    assert hangul.CODE_AT + len(code) <= hangul.TBL_AT
    assert 'sra %r5,0x1' in text          # KCENT's centring tail
