"""Long activity-diary entries for the Hangul P's.

A diary entry is one 8 KB flash sector (0x2570000 + n*0x2000, 24 of them):
text in its first 36 bytes, a header at +0x24, then the day's picture (the
sprites on screen when it was recorded; a busy scene such as the Tamamori
shop fills the sector past 0x1F00, so there is no free room in it).  The
recorder 0x241cb52 composes the entry (0x241cd22: sentence 0x2418a3c(idx)
from the 40-byte array at 0x2558370, names pasted over its 0x6C cells) into
a 36-byte stack buffer, so Hangul (2 bytes a syllable) got half of what kana
gets.

Patched:
  sentence array -> SAFE, 80-byte entries (0x2418a44 sll 3 -> 4, new base)
  0x241cbd6  right after the composer call -> jp DFIX (and jp back): no stack
             at all -- the recorder can run on a small task stack, and a hook
             that took stack there (a call, a buffer) corrupted the sprites the
             diary picture is saved from.  The composer writes the text into
             the recorder's frame (84 bytes; beyond the 36-byte field is
             scratch); DFIX drops 0x6C and, when the text is one of the array's
             sentences, cuts it to <= 33 bytes at a character boundary + NUL
             and puts MARK + its index after that NUL; other texts (names
             pasted in: the template fits 36 bytes) keep the whole field (the link and
             unpatched readers stop at the NUL)
  0x241c790  diary page's text pointer -> jp DVIEW: the array sentence when the
             sector's text carries MARK + index, else the 36-byte copy (names
             pasted in, entries from before the patch, other devices' data)
"""
import struct

from .hangul import BASE, _Asm, _xsub, JP, JREQ, JRNE, JRULE, JRUGT, JRULT, JRUGE, \
    ldub_rs, ldub_rb, ldw_rs, ldw_rb, add_i, add_rs, sub_i, cmp_i, cmp_rs, sub_rs, sll_i, ld_i

ARRAY, COUNT, OLD, NEW = 0x558370, 75, 40, 80
TEXT = NEW - 1                  # bytes before the NUL
LINES = 6                       # the diary page's text box
KEEP = 33                       # old field: text + NUL + MARK + index <= 36
MARK = 0xF7
SECTORS = 0x570000
FIX_AT, VIEW_AT = 0x41CBD6, 0x41C790   # after the composer call; the page's text

ldub_pi = lambda rd, rb: 0x2500 | rb << 4 | rd          # ld.ub rd,[rb]+
stb_pi = lambda rb, rs: 0x3500 | rb << 4 | rs           # ld.b [rb]+,rs
ldw_sp = lambda rd: 0xA410 | rd                         # ld.w rd,%sp


def _cmpx(a, rd, v):                                    # cmp rd,imm (0..4095)
    a.ext(v >> 6); a.w(cmp_i(rd, v & 0x3F))


def assemble(org, array=0):
    """Hooks at `org`; `array` = CPU address of the 80-byte sentence array."""
    a = _Asm(org)
    # DFIX: jumped to (no call: the recorder may run on a small task stack)
    # right after the untouched composer call, at 0x241cbd6.  Live: r1-r3
    # (the recorder's), sp = its frame, whose first 80 bytes now hold the
    # composed text (only the first 36 are the field; the rest is scratch the
    # recorder fills later); r4 = the composer's result, which the recorder
    # copies to r0 a few instructions on.  Free: r0, r4-r11.
    a.L('DFIX')
    a.w(ldw_rs(0, 4))
    a.w(ldw_sp(9))                                      # r9 = the text
    a.w(ldw_rs(4, 9)); a.w(ldw_rs(5, 9))                # drop 0x6C cells in place
    a.L('D_CMP')
    a.w(ldub_pi(6, 4)); _cmpx(a, 6, 0x6C); a.br(JREQ, 'D_CMP')
    a.w(stb_pi(5, 6)); a.w(cmp_i(6, 0)); a.br(JRNE, 'D_CMP')
    # r10 = index of the array sentence equal to the text, 0xFF if none
    a.li(8, array); a.w(ld_i(10, 0))
    a.L('D_FIND')
    a.w(ldw_rs(4, 9)); a.w(ldw_rs(5, 8))
    a.L('D_EQ')
    a.w(ldub_pi(6, 4)); a.w(ldub_pi(7, 5)); a.w(cmp_rs(6, 7)); a.br(JRNE, 'D_NEXT')
    a.w(cmp_i(6, 0)); a.br(JRNE, 'D_EQ'); a.br(JP, 'D_KEEP')
    a.L('D_NEXT')
    a.ext(NEW >> 6); a.w(add_i(8, NEW & 0x3F)); a.w(add_i(10, 1))
    _cmpx(a, 10, COUNT); a.br(JRULT, 'D_FIND')
    a.ext(0xFF >> 6); a.w(ld_i(10, 0xFF & 0x3F))
    a.L('D_KEEP')                                       # r4 = cut: whole chars, <= KEEP bytes
    a.w(ldw_rs(4, 9)); a.ext(0); a.w(ld_i(7, KEEP))     # (no index to add: the whole field)
    _cmpx(a, 10, 0xFF); a.br(JRNE, 'D_CHR'); a.ext(0); a.w(ld_i(7, 36))
    a.L('D_CHR')
    a.w(ldub_rb(6, 4)); a.w(cmp_i(6, 0)); a.br(JREQ, 'D_CUT')
    a.w(ldw_rs(11, 6)); _xsub(a, 11, 0xC7); a.w(ldub_rs(11, 11)); a.w(cmp_i(11, 8)); a.br(JRULE, 'D_TWO')
    a.w(ldw_rs(11, 6)); _xsub(a, 11, 0xD9); a.w(ldub_rs(11, 11)); a.w(cmp_i(11, 6)); a.br(JRULE, 'D_TWO')
    a.w(ld_i(8, 1)); a.br(JP, 'D_LEN')
    a.L('D_TWO'); a.w(ld_i(8, 2))
    a.L('D_LEN')
    a.w(cmp_rs(8, 7)); a.br(JRUGT, 'D_CUT'); a.w(sub_rs(7, 8)); a.w(add_rs(4, 8))
    a.br(JP, 'D_CHR')
    a.L('D_CUT')                                        # zero [cut, 36), then MARK + index
    a.w(ldw_rs(11, 4)); a.w(ldw_rs(5, 9)); a.ext(0); a.w(add_i(5, 36)); a.w(ld_i(6, 0))
    a.L('D_ZERO')
    a.w(stb_pi(4, 6)); a.w(cmp_rs(4, 5)); a.br(JRULT, 'D_ZERO')
    _cmpx(a, 10, 0xFF); a.br(JREQ, 'D_END')
    a.w(add_i(11, 1)); a.ext(MARK >> 6); a.w(ld_i(6, MARK & 0x3F))
    a.w(stb_pi(11, 6)); a.w(stb_pi(11, 10))
    a.L('D_END')                                        # the two replaced instructions
    a.w(ldw_rs(4, 0)); a.w(ldw_sp(6)); a.w(add_i(6, 0x24))
    a.br(JP, BASE + FIX_AT + 4, x=True)

    # DVIEW: jumped to from 0x241c790 (the page's own frame, sp unchanged):
    # r1 = text to draw, r4 = its first byte, then back to 0x241c794
    a.L('DVIEW')
    a.w(ldw_sp(4))
    a.ext(0x34); a.w(ldw_rb(1, 4))                      # [sp+0xd] = sector index
    a.w(sll_i(1, 13)); a.li(5, BASE + SECTORS); a.w(0x2251)  # add r1,r5
    a.ext(0); a.w(ld_i(6, KEEP + 1))
    a.L('V_SCAN')
    a.w(ldub_pi(5, 1)); a.w(cmp_i(5, 0)); a.br(JREQ, 'V_NUL')
    a.w(sub_i(6, 1)); a.w(cmp_i(6, 0)); a.br(JRNE, 'V_SCAN'); a.br(JP, 'V_OLD')
    a.L('V_NUL')
    a.w(ldub_pi(5, 1)); _cmpx(a, 5, MARK); a.br(JRNE, 'V_OLD')
    a.w(ldub_rb(5, 1)); _cmpx(a, 5, COUNT); a.br(JRUGE, 'V_OLD')
    a.w(ldw_rs(6, 5)); a.w(sll_i(6, 2)); a.w(0x2256)    # add r6,r5: idx * 5
    a.w(sll_i(6, 4))                                    # idx * 80
    a.li(1, array); a.w(0x2261)                         # add r1,r6
    a.br(JP, 'V_USE')
    a.L('V_OLD')
    a.w(ldw_rs(1, 4)); a.w(add_i(1, 0xC))
    a.L('V_USE')
    a.w(ldub_rb(4, 1))
    a.br(JP, BASE + VIEW_AT + 4, x=True)
    return a.build(), dict(a.labels)


def block(org):
    """Hooks + room for the sentence array right after them (4-aligned):
    (bytes, labels, array CPU address)."""
    n = len(assemble(org)[0])
    array = org + n + 3 & ~3
    code, lab = assemble(org, array)
    return code + bytes(array - org - n) + bytes(COUNT * NEW), lab, array


def patch(rom, lab, array):
    """Hook the recorder and the diary page (jumps, no calls); copy the
    sentences into `array` (file offset of block()'s array)."""
    for k in range(COUNT):
        src = ARRAY + OLD * k
        s = rom[src:src + OLD].split(b'\0')[0]
        rom[array + NEW * k:array + NEW * (k + 1)] = s.ljust(NEW, b'\0')
    assert rom[0x418A44:0x418A4C] == bytes.fromhex('318c4ac00dd6046f'), 'sentence lookup'
    rom[0x418A44:0x418A46] = struct.pack('<H', sll_i(1, 4))          # idx * 80
    v = BASE + array
    rom[0x418A46:0x418A4C] = struct.pack('<3H', 0xC000 | v >> 19 & 0x1FFF,
                                         0xC000 | v >> 6 & 0x1FFF, 0x6C04 | (v & 0x3F) << 4)
    assert rom[FIX_AT:FIX_AT + 4] == bytes.fromhex('16a44662'), 'after the composer call'
    h = _Asm(BASE + FIX_AT); h.br(JP, lab['DFIX'], x=True)          # ld.w r6,sp; add r6,0x24
    rom[FIX_AT:FIX_AT + 4] = h.build()
    assert rom[VIEW_AT:VIEW_AT + 14] == bytes.fromhex('11a400c0036ec444242a3019c160'), 'diary page'
    h = _Asm(BASE + VIEW_AT); h.br(JP, lab['DVIEW'], x=True)
    h.ext(0); h.w(0x6E03)                               # xld.w r3,0x20
    h.w(cmp_rs(4, 2)); h.br(JREQ, BASE + 0x41C7FA); h.w(0)
    rom[VIEW_AT:VIEW_AT + 14] = h.build()
