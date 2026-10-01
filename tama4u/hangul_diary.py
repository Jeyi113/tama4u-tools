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
MARK = 0xF7                     # array sentence: NUL, MARK, index
MARK2 = 0xF6                    # name template: F[14] MARK2, F[15] k, names from F[16]
TOKEN = 0xFD                    # name token in a Korean template: TOKEN, j (1-3)
NAMES = 16                      # field offset of the stored names (<= 20 bytes)
NAMES_TMP = 0x38                # recorder frame scratch for them
CELL = 12                       # name-cell table entry: n, (o, l, s) x 3, pad
SECTORS = 0x570000
FIX_AT, VIEW_AT = 0x41CBD6, 0x41C790   # after the composer call; the page's text
NEXT_AT, LOOP_AT, END_AT = 0x41C7F2, 0x41C79E, 0x41C7FA   # the page's line loop

ldub_pi = lambda rd, rb: 0x2500 | rb << 4 | rd          # ld.ub rd,[rb]+
stb_pi = lambda rb, rs: 0x3500 | rb << 4 | rs           # ld.b [rb]+,rs
ldw_sp = lambda rd: 0xA410 | rd                         # ld.w rd,%sp


def _cmpx(a, rd, v):                                    # cmp rd,imm (0..4095)
    a.ext(v >> 6); a.w(cmp_i(rd, v & 0x3F))


def _xadd(a, rd, v):                                    # add rd,imm32
    a.ext(v >> 19); a.ext(v >> 6); a.w(add_i(rd, v & 0x3F))


def _mul(a, rd, t, n):                                  # rd = rd * n (3, 5, 6, 12), t scratch
    a.w(ldw_rs(t, rd))
    if n == 3:
        a.w(sll_i(rd, 1)); a.w(add_rs(rd, t))
    elif n == 5:
        a.w(sll_i(rd, 2)); a.w(add_rs(rd, t))
    elif n == 6:
        a.w(sll_i(rd, 1)); a.w(add_rs(rd, t)); a.w(sll_i(rd, 1))
    elif n == 12:
        a.w(sll_i(rd, 1)); a.w(add_rs(rd, t)); a.w(sll_i(rd, 2))


def _lead(a, rd, two, one):                             # Hangul lead byte in rd? (rd kept)
    _cmpx(a, rd, 0xC7); a.br(JRULT, one); _cmpx(a, rd, 0xCF); a.br(JRULE, two)
    _cmpx(a, rd, 0xD9); a.br(JRULT, one); _cmpx(a, rd, 0xDF); a.br(JRULE, two)
    a.br(JP, one)


stb_d = lambda a, rb, rs, off: (a.ext(off), a.w(0x3400 | rb << 4 | rs))   # ld.b [rb+off],rs
ldub_d = lambda a, rd, rb, off: (a.ext(off), a.w(ldub_rb(rd, rb)))        # ld.ub rd,[rb+off]


def assemble(org, array=0, cells=0):
    """Hooks at `org`; `array` = CPU address of the 80-byte sentence array,
    `cells` = of the name-cell table (CELL bytes an entry, see patch())."""
    a = _Asm(org)
    # DFIX: jumped to (no call: the recorder may run on a small task stack)
    # right after the untouched composer call, at 0x241cbd6.  Live: r1-r3
    # (the recorder's), sp = its frame, whose first 80 bytes now hold the
    # composed text (only the first 36 are the field; the rest is scratch the
    # recorder fills later); r4 = the composer's result, which the recorder
    # copies to r0 a few instructions on.  Free: r0, r4-r11.
    a.L('DFIX')
    a.w(ldw_rs(0, 4))
    # ---- name templates: the composer pasted names over the ORIGINAL
    # sentence's cells; find the template k whose bytes match outside them
    a.w(ld_i(11, 0))
    a.L('T_K')
    a.w(ldw_rs(6, 11)); _mul(a, 6, 10, 12); _xadd(a, 6, cells)
    a.w(ldub_rb(10, 6)); a.w(cmp_i(10, 0)); a.br(JREQ, 'T_NK', x=True)
    a.w(ldw_rs(5, 11)); _mul(a, 5, 10, 5); a.w(sll_i(5, 4)); _xadd(a, 5, array)
    a.w(ldw_sp(4)); a.w(ldw_rs(9, 6)); a.w(add_i(9, 1))  # r9 -> cell (o, l, s)
    a.L('T_CELL')
    a.w(ldub_rb(10, 9)); a.w(ldw_sp(7)); a.w(add_rs(7, 10)); ldub_d(a, 8, 9, 1)
    a.L('T_CMP')
    a.w(cmp_rs(4, 7)); a.br(JRNE, 'T_BYTE')
    a.w(add_rs(4, 8)); a.w(add_rs(5, 8)); a.w(add_i(9, 3)); a.br(JP, 'T_CELL')
    a.L('T_BYTE')
    a.w(ldub_rb(10, 4)); a.w(ldub_rb(6, 5)); a.w(cmp_rs(10, 6)); a.br(JRNE, 'T_NK', x=True)
    a.w(cmp_i(6, 0)); a.br(JREQ, 'T_HIT', x=True)
    a.w(add_i(4, 1)); a.w(add_i(5, 1)); a.br(JP, 'T_CMP')
    a.L('T_NK')
    a.w(add_i(11, 1)); _cmpx(a, 11, COUNT); a.br(JRULT, 'T_K', x=True)
    a.br(JP, 'D_STRIP')
    a.L('T_HIT')                                        # k = r11: names -> sp+0x38 (field order)
    a.w(ldw_rs(9, 11)); _mul(a, 9, 10, 12); _xadd(a, 9, cells + 1)
    a.L('T_X')
    a.w(ldub_rb(10, 9)); _cmpx(a, 10, 0xFF); a.br(JREQ, 'T_XD', x=True)
    a.w(ldw_sp(4)); a.w(add_rs(4, 10))                  # src = sp + o
    ldub_d(a, 10, 9, 2); a.w(ldw_sp(5)); a.w(add_rs(5, 10)); a.ext(0); a.w(add_i(5, NAMES_TMP - NAMES))
    ldub_d(a, 8, 9, 1); a.w(cmp_i(8, 0)); a.br(JREQ, 'T_XN')   # (never: no 0-length cell)
    a.L('T_XB')
    a.w(ldub_pi(10, 4)); _cmpx(a, 10, 0x6C); a.br(JRNE, 'T_XS'); a.w(ld_i(10, 0))
    a.L('T_XS')
    a.w(stb_pi(5, 10)); a.w(sub_i(8, 1)); a.w(cmp_i(8, 0)); a.br(JRNE, 'T_XB')
    a.L('T_XN')
    a.w(add_i(9, 3)); a.br(JP, 'T_X', x=True)
    a.L('T_XD')                                         # field: zero, names, MARK2, k
    a.w(ldw_sp(4)); a.w(ldw_sp(5)); a.ext(0); a.w(add_i(5, 36)); a.w(ld_i(10, 0))
    a.L('T_Z')
    a.w(stb_pi(4, 10)); a.w(cmp_rs(4, 5)); a.br(JRULT, 'T_Z')
    a.w(ldw_sp(4)); a.ext(0); a.w(add_i(4, NAMES_TMP)); a.w(ldw_sp(5)); a.w(add_i(5, NAMES))
    a.w(ld_i(8, 36 - NAMES))
    a.L('T_C')
    a.w(ldub_pi(10, 4)); a.w(stb_pi(5, 10)); a.w(sub_i(8, 1)); a.w(cmp_i(8, 0)); a.br(JRNE, 'T_C')
    a.w(ldw_sp(4)); a.ext(MARK2 >> 6); a.w(ld_i(10, MARK2 & 0x3F))
    stb_d(a, 4, 10, NAMES - 2); stb_d(a, 4, 11, NAMES - 1)
    # prefix for other readers: the template up to its first name, whole chars
    a.w(ldw_rs(5, 11)); _mul(a, 5, 10, 5); a.w(sll_i(5, 4)); _xadd(a, 5, array)
    a.w(ldw_sp(4)); a.w(ld_i(7, 12))
    a.L('T_P')
    a.w(ldub_rb(6, 5)); a.w(cmp_i(6, 0)); a.br(JREQ, 'D_END', x=True)    # NUL or a name token
    _cmpx(a, 6, TOKEN); a.br(JREQ, 'D_END', x=True)
    _lead(a, 6, 'T_P2', 'T_P1')
    a.L('T_P2'); a.w(ld_i(8, 2)); a.br(JP, 'T_PL')
    a.L('T_P1'); a.w(ld_i(8, 1))
    a.L('T_PL')
    a.w(cmp_rs(8, 7)); a.br(JRUGT, 'D_END', x=True); a.w(sub_rs(7, 8))
    a.L('T_PC')
    a.w(ldub_pi(10, 5)); a.w(stb_pi(4, 10)); a.w(sub_i(8, 1)); a.w(cmp_i(8, 0)); a.br(JRNE, 'T_PC')
    a.br(JP, 'T_P')

    a.L('D_STRIP')
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
    _cmpx(a, 10, 0xFF); a.br(JREQ, 'D_END', x=True)
    a.w(add_i(11, 1)); a.ext(MARK >> 6); a.w(ld_i(6, MARK & 0x3F))
    a.w(stb_pi(11, 6)); a.w(stb_pi(11, 10))
    a.L('D_END')                                        # the two replaced instructions
    a.w(ldw_rs(4, 0)); a.w(ldw_sp(6)); a.w(add_i(6, 0x24))
    a.br(JP, BASE + FIX_AT + 4, x=True)

    # DVIEW: jumped to from 0x241c790 (the page's own frame, sp unchanged):
    # r1 = text to draw, r4 = its first byte, then back to 0x241c794; a name
    # template (MARK2) draws through DNEXT line by line instead
    a.L('DVIEW')
    a.w(ldw_sp(4))
    a.ext(0x34); a.w(ldw_rb(1, 4))                      # [sp+0xd] = sector index
    a.w(sll_i(1, 13)); a.li(5, BASE + SECTORS); a.w(0x2251)  # add r1,r5
    ldub_d(a, 5, 1, NAMES - 3); a.w(cmp_i(5, 0)); a.br(JRNE, 'V_N', x=True)
    ldub_d(a, 5, 1, NAMES - 2); _cmpx(a, 5, MARK2); a.br(JRNE, 'V_N', x=True)
    ldub_d(a, 5, 1, NAMES - 1); _cmpx(a, 5, COUNT); a.br(JRUGE, 'V_N', x=True)
    a.w(ldw_sp(5)); a.w(add_i(5, 0xC)); a.ext(0xFF >> 6); a.w(ld_i(6, 0xFF & 0x3F))
    stb_d(a, 5, 6, NAMES - 3)                           # line -1: DNEXT draws line 0
    a.w(ld_i(3, 0x20 - 0xB)); a.br(JP, 'DNEXT', x=True)
    a.L('V_N')
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

    # DNEXT: jumped to from the page's line loop (0x241c7f2): r1 = what putstr
    # left, r0/r2/r3 the loop's.  A name template is laid out a line at a
    # time into the page's text buffer F = sp+0xc: line n = 6 characters after
    # skipping 6n of (template with the stored names spliced in for its
    # TOKEN j); F[13] = n, F[14] MARK2, F[15] k, F[16..35] the names.  6 lines max.
    a.L('DNEXT')
    a.w(add_i(3, 0xB))                                  # the loop's own y step
    a.w(ldw_sp(4)); a.ext(0x34); a.w(ldw_rb(5, 4)); a.w(sll_i(5, 13)); _xadd(a, 5, BASE + SECTORS)
    ldub_d(a, 6, 5, NAMES - 3); a.w(cmp_i(6, 0)); a.br(JRNE, 'N_NORM')
    ldub_d(a, 6, 5, NAMES - 2); _cmpx(a, 6, MARK2); a.br(JRNE, 'N_NORM')
    ldub_d(a, 6, 5, NAMES - 1); _cmpx(a, 6, COUNT); a.br(JRULT, 'N_TPL', x=True)
    a.L('N_NORM')
    a.w(ldub_rb(4, 1)); a.w(cmp_i(4, 0)); a.br(JREQ, 'N_END', x=True)
    a.br(JP, BASE + LOOP_AT, x=True)
    a.L('N_END')
    a.br(JP, BASE + END_AT, x=True)
    a.L('N_TPL')
    a.w(ldw_sp(11)); a.w(add_i(11, 0xC))
    ldub_d(a, 9, 11, NAMES - 3); a.w(add_i(9, 1)); a.w(ldub_rs(9, 9))
    a.w(cmp_i(9, LINES)); a.br(JRUGE, 'N_END', x=True)
    stb_d(a, 11, 9, NAMES - 3); _mul(a, 9, 10, 6)       # r9 = characters to skip
    ldub_d(a, 10, 11, NAMES - 1)
    a.w(ldw_rs(5, 10)); _mul(a, 5, 10, 5); a.w(sll_i(5, 4)); _xadd(a, 5, array)
    a.w(ld_i(6, 0)); a.w(ldw_rs(4, 11)); a.w(ld_i(8, 0))
    a.L('E_NEXT')
    a.w(cmp_i(6, 0)); a.br(JRNE, 'E_NAME')
    a.w(ldub_rb(10, 5)); a.w(cmp_i(10, 0)); a.br(JREQ, 'E_DONE', x=True)
    _cmpx(a, 10, TOKEN); a.br(JREQ, 'E_ENTER')
    _lead(a, 10, 'E_T2', 'E_T1')
    a.L('E_T1')
    a.w(cmp_i(9, 0)); a.br(JREQ, 'E_T1C'); a.w(sub_i(9, 1)); a.w(add_i(5, 1)); a.br(JP, 'E_NEXT', x=True)
    a.L('E_T1C')
    a.w(stb_pi(4, 10)); a.w(add_i(5, 1)); a.br(JP, 'E_EMIT', x=True)
    a.L('E_T2')
    a.w(cmp_i(9, 0)); a.br(JREQ, 'E_T2C'); a.w(sub_i(9, 1)); a.w(add_i(5, 2)); a.br(JP, 'E_NEXT', x=True)
    a.L('E_T2C')
    a.w(stb_pi(4, 10)); ldub_d(a, 10, 5, 1); a.w(stb_pi(4, 10)); a.w(add_i(5, 2)); a.br(JP, 'E_EMIT', x=True)
    a.L('E_ENTER')                                      # TOKEN j: r6..r7 = name j in F
    ldub_d(a, 10, 5, 1)
    ldub_d(a, 7, 11, NAMES - 1); _mul(a, 7, 6, 12); _xadd(a, 7, cells)
    a.w(sub_i(10, 1)); _mul(a, 10, 6, 3)                # (j - 1) * 3
    a.w(add_rs(7, 10))
    ldub_d(a, 6, 7, 3); ldub_d(a, 10, 7, 2)
    a.w(add_rs(6, 11)); a.w(ldw_rs(7, 6)); a.w(add_rs(7, 10))
    a.br(JP, 'E_NEXT', x=True)
    a.L('E_NAME')
    a.w(cmp_rs(6, 7)); a.br(JRUGE, 'E_NDONE')
    a.w(ldub_rb(10, 6)); a.w(cmp_i(10, 0)); a.br(JREQ, 'E_NDONE')
    _lead(a, 10, 'E_N2', 'E_N1')
    a.L('E_N1')
    a.w(cmp_i(9, 0)); a.br(JREQ, 'E_N1C'); a.w(sub_i(9, 1)); a.w(add_i(6, 1)); a.br(JP, 'E_NEXT', x=True)
    a.L('E_N1C')
    a.w(stb_pi(4, 10)); a.w(add_i(6, 1)); a.br(JP, 'E_EMIT', x=True)
    a.L('E_N2')
    a.w(cmp_i(9, 0)); a.br(JREQ, 'E_N2C'); a.w(sub_i(9, 1)); a.w(add_i(6, 2)); a.br(JP, 'E_NEXT', x=True)
    a.L('E_N2C')
    a.w(stb_pi(4, 10)); ldub_d(a, 10, 6, 1); a.w(stb_pi(4, 10)); a.w(add_i(6, 2)); a.br(JP, 'E_EMIT', x=True)
    a.L('E_NDONE')
    a.w(ld_i(6, 0)); a.w(add_i(5, 2)); a.br(JP, 'E_NEXT', x=True)  # past TOKEN j
    a.L('E_EMIT')
    a.w(add_i(8, 1)); a.w(cmp_i(8, 6)); a.br(JRULT, 'E_NEXT', x=True)
    a.L('E_DONE')
    a.w(ld_i(10, 0)); a.w(0x3400 | 4 << 4 | 10)         # ld.b [r4],r10
    a.w(cmp_i(8, 0)); a.br(JREQ, 'N_END', x=True)
    a.w(ldw_rs(1, 11)); a.br(JP, BASE + LOOP_AT, x=True)
    return a.build(), dict(a.labels)


def block(org):
    """Hooks + the sentence array + the name-cell table after them
    (4-aligned): (bytes, labels, array CPU address, cells CPU address)."""
    n = len(assemble(org)[0])
    array = org + n + 3 & ~3
    cells = array + COUNT * NEW
    code, lab = assemble(org, array, cells)
    return code + bytes(array - org - n) + bytes(COUNT * NEW + COUNT * CELL), lab, array, cells


def name_cells(entry):
    """(offset, length) of a sentence's name cells: runs of 3+ 0x6C."""
    import re
    return [(m.start(), m.end() - m.start()) for m in re.finditer(rb'\x6c{3,}', entry)]


def cell_table(rom):
    """CELL bytes per sentence, from the ORIGINAL array (where the composer
    pastes the names): n, then (offset, length, field offset) per cell
    (0xFF offset: none), names packed from field byte NAMES."""
    out = bytearray()
    for k in range(COUNT):
        cl = name_cells(rom[ARRAY + OLD * k:ARRAY + OLD * (k + 1)].split(b'\0')[0])
        assert sum(ln for _, ln in cl) <= 36 - NAMES and len(cl) <= 3, k
        e, s = [len(cl)], NAMES
        for off, ln in cl:
            e += [off, ln, s]; s += ln
        e += [0xFF, 0, 0] * (3 - len(cl)) + [0xFF]      # always ends in a 0xFF offset
        out += bytes(e).ljust(CELL, b'\0')
    return bytes(out)


def patch(rom, lab, array, cells):
    """Hook the recorder and the diary page (jumps, no calls); copy the
    sentences into `array` and the name-cell table into `cells` (file
    offsets of block()'s)."""
    rom[cells:cells + COUNT * CELL] = cell_table(rom)
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
    assert rom[NEXT_AT:NEXT_AT + 8] == bytes.fromhex('14240468d41bb360'), 'line loop'
    h = _Asm(BASE + NEXT_AT); h.br(JP, lab['DNEXT'], x=True); h.w(0); h.w(0)
    rom[NEXT_AT:NEXT_AT + 8] = h.build()
