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

Name templates (link diaries): a link diary may be composed by either device
and sent as is, so DFIX stores it in the unpatched form (the original
sentence with the names, 0x6C dropped) and DVIEW's J_TRY finds which sentence
such a field was made from, lays the Korean template out with its names
(DNEXT).  Fields in the v64-v65 form (MARK2) still draw.  A game/food cell
(>= WORD bytes) is stored with the Japanese name and drawn with the Korean
one, through the pairs words() puts in the original array's free slots.
"""
import struct

from .hangul import BASE, HALF, code as _code, _Asm, _xsub, JP, JREQ, JRNE, JRULE, JRUGT, JRULT, JRUGE, \
    ldub_rs, ldub_rb, ldw_rs, ldw_rb, add_i, add_rs, sub_i, cmp_i, cmp_rs, sub_rs, sll_i, ld_i

ARRAY, COUNT, OLD, NEW = 0x558370, 75, 40, 80
TEXT = NEW - 1                  # bytes before the NUL
LINES = 6                       # the diary page's text box
KEEP = 33                       # old field: text + NUL + MARK + index <= 36
MARK = 0xF7                     # array sentence: NUL, MARK, index
MARK2 = 0xF6                    # name template: F[14] MARK2, F[15] k, names from F[16]
TOKEN = 0xFD                    # name token in a Korean template: TOKEN, j (1-3)
NAMES = 16                      # field offset of the stored names (<= 20 bytes)
CELL = 12                       # name-cell table entry: n, (o, l, s) x 3, pad
WORDS = 0xFE                    # original-array slot holding game/food names: WORDS, (jp NUL ko NUL)..., NUL
WORD = 8                        # cells this long hold a game/food name (shorter: a tamagotchi's)
SECTORS = 0x570000
HALF_CODE = _code(HALF)            # the Hangul space (lead, trail)
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


def _emit(a, at, p, n):
    """DNEXT: the n-byte character at [rp] (first byte in r10).  Lines before
    the one drawn (r9 left to skip) only count, 6 a line in r1; a Hangul space
    starting a line is dropped (as the sheet's diary rows drop it)."""
    if n == 2:
        lead, trail = HALF_CODE
        a.L(at)
        _cmpx(a, 10, lead); a.br(JRNE, at + 'C')
        ldub_d(a, 10, p, 1); _cmpx(a, 10, trail); a.br(JRNE, at + 'R')
        a.w(cmp_i(9, 0)); a.br(JREQ, at + 'E')
        a.w(cmp_i(1, 0)); a.br(JRNE, at + 'R')
        a.L(at + 'D')                                   # dropped
        a.w(add_i(p, 2)); a.br(JP, 'E_NEXT', x=True)
        a.L(at + 'E')
        a.w(cmp_i(8, 0)); a.br(JREQ, at + 'D')
        a.L(at + 'R')
        a.w(ldub_rb(10, p))
    else:
        a.L(at)
    a.L(at + 'C')
    a.w(cmp_i(9, 0)); a.br(JREQ, at + 'O')
    a.w(add_i(1, 1)); a.w(cmp_i(1, 6)); a.br(JRNE, at + 'A')
    a.w(ld_i(1, 0)); a.w(sub_i(9, 1))
    a.L(at + 'A')
    a.w(add_i(p, n)); a.br(JP, 'E_NEXT', x=True)
    a.L(at + 'O')
    a.w(stb_pi(4, 10))
    if n == 2:
        ldub_d(a, 10, p, 1); a.w(stb_pi(4, 10))
    a.w(add_i(p, n)); a.br(JP, 'E_EMIT', x=True)


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
    a.br(JP, 'D_STRIP', x=True)
    a.L('T_HIT')
    # k = r11: rebuild the ORIGINAL sentence around the pasted names, so the
    # field is what an unpatched P's stores (a link partner may be one; the
    # page lays it out in Korean again, see DVIEW); D_STRIP drops the cells' 0x6C
    a.w(ldw_rs(9, 11)); _mul(a, 9, 10, 12); _xadd(a, 9, cells + 1)
    a.w(ldw_rs(5, 11)); _mul(a, 5, 10, 5); a.w(sll_i(5, 3)); _xadd(a, 5, BASE + ARRAY)
    a.w(ldw_rs(6, 5)); a.w(ldw_sp(4))
    a.L('T_W')
    a.w(ldub_rb(10, 9)); a.w(ldw_rs(7, 6)); a.w(add_rs(7, 10))
    a.w(cmp_rs(5, 7)); a.br(JRNE, 'T_WL')
    # a game/food cell (>= WORD bytes) holding a WORDS Korean name: the
    # Japanese one instead.  r4 = the cell, r11 = its end; r12-r14 kept in
    # the frame's scratch (past the text, which is <= 40 bytes now)
    ldub_d(a, 8, 9, 1); a.w(cmp_i(8, WORD)); a.br(JRULT, 'T_WK', x=True)
    a.w(0x5D0C); a.w(0x5D1D); a.w(0x5D2E)               # ld.w [sp+0x40/44/48],r12-r14
    a.w(ldw_rs(11, 4)); a.w(add_rs(11, 8)); a.li(7, BASE + ARRAY)
    a.L('F_S')
    a.w(ldub_rb(10, 7)); _cmpx(a, 10, WORDS); a.br(JRNE, 'F_NS', x=True)
    a.w(ldw_rs(10, 7)); a.w(add_i(10, 1))
    a.L('F_E')
    a.w(ldub_rb(12, 10)); a.w(cmp_i(12, 0)); a.br(JREQ, 'F_NS', x=True)
    a.w(ldw_rs(14, 10))                                 # r14 = Japanese, r10 -> Korean
    a.L('F_J')
    a.w(ldub_pi(12, 10)); a.w(cmp_i(12, 0)); a.br(JRNE, 'F_J')
    a.w(ldw_rs(5, 4)); a.w(ldw_rs(8, 10))
    a.L('F_C')
    a.w(cmp_rs(5, 11)); a.br(JREQ, 'F_HIT', x=True)    # cell full: a cut name matches
    a.w(ldub_rb(12, 5)); a.w(cmp_i(12, 0)); a.br(JREQ, 'F_END')
    _cmpx(a, 12, 0x6C); a.br(JREQ, 'F_END')
    a.w(ldub_rb(13, 8)); a.w(cmp_rs(12, 13)); a.br(JRNE, 'F_NE')
    a.w(add_i(5, 1)); a.w(add_i(8, 1)); a.br(JP, 'F_C')
    a.L('F_END')
    a.w(cmp_rs(5, 4)); a.br(JREQ, 'F_NE')
    a.w(ldub_rb(13, 8)); a.w(cmp_i(13, 0)); a.br(JREQ, 'F_HIT')
    a.L('F_NE')
    a.w(ldub_pi(12, 10)); a.w(cmp_i(12, 0)); a.br(JRNE, 'F_NE')
    a.br(JP, 'F_E', x=True)
    a.L('F_NS')
    a.ext(0); a.w(add_i(7, OLD)); a.li(12, BASE + ARRAY + OLD * COUNT)
    a.w(cmp_rs(7, 12)); a.br(JRULT, 'F_S', x=True)
    a.w(0x510C); a.w(0x511D); a.w(0x512E)               # (no match) restore
    a.w(ldw_rs(5, 4)); a.w(ldw_sp(12)); a.w(sub_rs(5, 12)); a.w(add_rs(5, 6))
    a.w(0x510C)
    ldub_d(a, 8, 9, 1); a.br(JP, 'T_WC')
    a.L('F_HIT')                                        # Japanese name, 0x6C after it
    a.L('F_W')
    a.w(cmp_rs(4, 11)); a.br(JREQ, 'F_WD')
    a.w(ldub_rb(12, 14)); a.w(cmp_i(12, 0)); a.br(JRNE, 'F_WC')
    a.ext(0x6C >> 6); a.w(ld_i(12, 0x6C & 0x3F)); a.w(stb_pi(4, 12)); a.br(JP, 'F_W')
    a.L('F_WC')
    a.w(stb_pi(4, 12)); a.w(add_i(14, 1)); a.br(JP, 'F_W')
    a.L('F_WD')
    a.w(ldw_rs(5, 4)); a.w(ldw_sp(12)); a.w(sub_rs(5, 12)); a.w(add_rs(5, 6))
    a.w(0x510C); a.w(0x511D); a.w(0x512E)
    a.w(add_i(9, 3)); a.br(JP, 'T_W', x=True)
    a.L('T_WK')
    ldub_d(a, 8, 9, 1)                                  # a cell: keep the name, NUL -> 0x6C
    a.L('T_WC')
    a.w(ldub_rb(10, 4)); a.w(cmp_i(10, 0)); a.br(JRNE, 'T_WS')
    a.ext(0x6C >> 6); a.w(ld_i(10, 0x6C & 0x3F)); a.w(0x3400 | 4 << 4 | 10)   # ld.b [r4],r10
    a.L('T_WS')
    a.w(add_i(4, 1)); a.w(add_i(5, 1)); a.w(sub_i(8, 1)); a.w(cmp_i(8, 0)); a.br(JRNE, 'T_WC')
    a.w(add_i(9, 3)); a.br(JP, 'T_W')
    a.L('T_WL')
    a.w(ldub_pi(10, 5)); a.w(stb_pi(4, 10)); a.w(cmp_i(10, 0)); a.br(JRNE, 'T_W', x=True)

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
    a.br(JP, 'J_TRY', x=True)
    a.L('V_RAW')
    a.w(ldw_sp(1)); a.w(add_i(1, 0xC))
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
    a.w(ldw_sp(5)); a.w(add_i(5, 0xC))                  # template mode: F[13] line (-1..5), MARK2, k
    ldub_d(a, 6, 5, NAMES - 3); a.w(add_i(6, 1)); a.w(ldub_rs(6, 6)); a.w(cmp_i(6, LINES)); a.br(JRUGT, 'N_NORM')
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
    stb_d(a, 11, 9, NAMES - 3); a.w(ld_i(1, 0))         # r9 = lines to skip, r1 = their column
    ldub_d(a, 10, 11, NAMES - 1)
    a.w(ldw_rs(5, 10)); _mul(a, 5, 10, 5); a.w(sll_i(5, 4)); _xadd(a, 5, array)
    a.w(ld_i(6, 0)); a.w(ldw_rs(4, 11)); a.w(ld_i(8, 0))
    a.L('E_NEXT')
    a.w(cmp_i(6, 0)); a.br(JRNE, 'E_NAME')
    a.w(ldub_rb(10, 5)); a.w(cmp_i(10, 0)); a.br(JREQ, 'E_DONE', x=True)
    _cmpx(a, 10, TOKEN); a.br(JREQ, 'E_ENTER')
    _lead(a, 10, 'E_T2', 'E_T1')
    _emit(a, 'E_T1', 5, 1)
    _emit(a, 'E_T2', 5, 2)
    a.L('E_ENTER')                                      # TOKEN j: r6..r7 = name j in F
    ldub_d(a, 10, 5, 1)
    ldub_d(a, 7, 11, NAMES - 1); _mul(a, 7, 6, 12); _xadd(a, 7, cells)
    a.w(sub_i(10, 1)); _mul(a, 10, 6, 3)                # (j - 1) * 3
    a.w(add_rs(7, 10))
    ldub_d(a, 6, 7, 3); ldub_d(a, 10, 7, 2)
    a.w(add_rs(6, 11)); a.w(ldw_rs(7, 6)); a.w(add_rs(7, 10))
    a.w(ldub_rb(10, 6)); _cmpx(a, 10, WORDS); a.br(JRNE, 'E_NEXT', x=True)
    ldub_d(a, 10, 6, 1); ldub_d(a, 7, 6, 2)             # WORDS, slot, offset: its Korean
    _mul(a, 10, 6, 5); a.w(sll_i(10, 3)); _xadd(a, 10, BASE + ARRAY); a.w(add_rs(10, 7))
    a.w(ldw_rs(6, 10)); a.w(ldw_rs(7, 6)); a.ext(0); a.w(add_i(7, OLD))
    a.br(JP, 'E_NEXT', x=True)
    a.L('E_NAME')
    a.w(cmp_rs(6, 7)); a.br(JRUGE, 'E_NDONE')
    a.w(ldub_rb(10, 6)); a.w(cmp_i(10, 0)); a.br(JREQ, 'E_NDONE')
    _lead(a, 10, 'E_N2', 'E_N1')
    _emit(a, 'E_N1', 6, 1)
    _emit(a, 'E_N2', 6, 2)
    a.L('E_NDONE')
    a.w(ld_i(6, 0)); a.w(add_i(5, 2)); a.br(JP, 'E_NEXT', x=True)  # past TOKEN j
    a.L('E_EMIT')
    a.w(add_i(8, 1)); a.w(cmp_i(8, 6)); a.br(JRULT, 'E_NEXT', x=True)
    a.L('E_DONE')
    a.w(ld_i(10, 0)); a.w(0x3400 | 4 << 4 | 10)         # ld.b [r4],r10
    a.w(cmp_i(8, 0)); a.br(JREQ, 'N_END', x=True)
    a.w(ldw_rs(1, 11)); a.br(JP, BASE + LOOP_AT, x=True)

    # J_TRY (from DVIEW): a field in the unpatched form (names pasted into a
    # sentence and its 0x6C dropped: other devices' entries, and ours since
    # DFIX stores that) -> find the sentence k it was made from, the names'
    # place in F = sp+0xc, then F in template form for DNEXT (names moved to
    # their cells' field offsets s, last first: s >= the name's place unless
    # it is the only name).  No stack: the page's frame is full (60 bytes), so
    # the call-argument words [sp+0..2] hold the name records (start, length
    # at byte 3j), k (byte 2) and r12.  r11 = cell entry, r6 = the sentence,
    # r5 = in it, r4 = in F, r1 = F + 36 (a field cut there matches).
    a.L('J_TRY')
    a.w(0x5C2C)                                         # ld.w [sp+2],r12
    a.li(11, cells); a.li(6, BASE + ARRAY); a.w(ld_i(10, 0)); a.w(ldw_sp(7)); stb_d(a, 7, 10, 2)
    a.L('J_K')
    a.w(ldub_rb(10, 11)); a.w(cmp_i(10, 0)); a.br(JREQ, 'J_NK', x=True)
    a.w(ldw_sp(7)); a.w(ld_i(10, 0)); stb_d(a, 7, 10, 1); stb_d(a, 7, 10, 4); stb_d(a, 7, 10, 7)
    a.w(ldw_rs(9, 11)); a.w(add_i(9, 1)); a.w(ldw_rs(5, 6))
    a.w(ldw_sp(4)); a.w(add_i(4, 0xC)); a.w(ldw_rs(1, 4)); a.ext(0); a.w(add_i(1, 36))
    a.L('J_LOOP')
    a.w(ldub_rb(10, 9)); a.w(add_rs(10, 6)); a.w(cmp_rs(5, 10)); a.br(JREQ, 'J_NAME', x=True)
    a.w(ldub_rb(10, 5)); _cmpx(a, 10, 0x6C); a.br(JRNE, 'J_L1')
    a.w(add_i(5, 1)); a.br(JP, 'J_LOOP')
    a.L('J_L1')
    a.w(cmp_rs(4, 1)); a.br(JRUGE, 'J_HIT', x=True)
    a.w(ldub_rb(12, 4)); a.w(cmp_rs(12, 10)); a.br(JRNE, 'J_NK', x=True)
    a.w(cmp_i(10, 0)); a.br(JREQ, 'J_HIT', x=True)
    a.w(add_i(4, 1)); a.w(add_i(5, 1)); a.br(JP, 'J_LOOP')
    a.L('J_NAME')                                       # name at r4: ends (whole chars, <= the
    ldub_d(a, 10, 9, 1); a.w(add_rs(5, 10)); a.w(ldw_rs(7, 4))   # cell) where the text goes on
    a.L('J_ADV')
    a.w(ldub_rb(10, 7))
    _lead(a, 10, 'J_A2', 'J_A1')
    a.L('J_A2'); a.w(add_i(7, 2)); a.br(JP, 'J_AC')
    a.L('J_A1'); a.w(add_i(7, 1))
    a.L('J_AC')
    ldub_d(a, 10, 9, 1); a.w(add_rs(10, 4)); a.w(cmp_rs(7, 10)); a.br(JRUGT, 'J_NK', x=True)
    a.w(ldw_rs(3, 7)); a.w(ldw_rs(8, 5))
    a.L('J_S')
    ldub_d(a, 10, 9, 3); a.w(add_rs(10, 6)); a.w(cmp_rs(8, 10)); a.br(JREQ, 'J_QOK')
    a.w(ldub_rb(10, 8)); _cmpx(a, 10, 0x6C); a.br(JRNE, 'J_S1')
    a.w(add_i(8, 1)); a.br(JP, 'J_S')
    a.L('J_S1')
    a.w(cmp_rs(3, 1)); a.br(JRUGE, 'J_QOK')
    a.w(ldub_rb(12, 3)); a.w(cmp_rs(12, 10)); a.br(JRNE, 'J_ADV', x=True)
    a.w(cmp_i(10, 0)); a.br(JREQ, 'J_QOK')
    a.w(add_i(3, 1)); a.w(add_i(8, 1)); a.br(JP, 'J_S')
    a.L('J_QOK')                                        # record [sp + 3j] = start, length
    a.w(ldw_rs(10, 9)); a.w(sub_rs(10, 11)); a.w(sub_i(10, 1)); a.w(ldw_sp(3)); a.w(add_rs(10, 3))
    a.w(ldw_rs(8, 4)); a.w(sub_rs(8, 3)); a.w(sub_i(8, 0xC)); a.w(0x3400 | 10 << 4 | 8)  # ld.b [r10],r8
    a.w(ldw_rs(8, 7)); a.w(sub_rs(8, 4)); stb_d(a, 10, 8, 1)
    a.w(ldw_rs(4, 7)); a.w(add_i(9, 3)); a.br(JP, 'J_LOOP', x=True)
    a.L('J_NK')
    a.ext(0); a.w(add_i(11, CELL)); a.ext(0); a.w(add_i(6, OLD))
    a.w(ldw_sp(7)); ldub_d(a, 10, 7, 2); a.w(add_i(10, 1)); stb_d(a, 7, 10, 2)
    _cmpx(a, 10, COUNT); a.br(JRULT, 'J_K', x=True)
    a.w(0x502C)                                         # ld.w r12,[sp+2]
    a.br(JP, 'V_RAW', x=True)
    a.L('J_HIT')                                        # move the names, last first
    a.w(ldub_rb(10, 11)); a.w(sub_i(10, 1)); _mul(a, 10, 8, 3); a.w(ldw_rs(9, 11)); a.w(add_i(9, 1))
    a.w(add_rs(9, 10))
    a.L('M_J')
    a.w(ldw_rs(10, 9)); a.w(sub_rs(10, 11)); a.w(sub_i(10, 1)); a.w(ldw_sp(3)); a.w(add_rs(10, 3))
    a.w(add_i(3, 0xC)); a.w(ldw_rs(5, 3))               # r3 = src, r5 = dst (F + ...)
    a.w(ldub_rb(8, 10)); a.w(add_rs(3, 8))
    ldub_d(a, 8, 9, 2); a.w(add_rs(5, 8))
    ldub_d(a, 8, 10, 1); ldub_d(a, 7, 9, 1); a.w(sub_rs(7, 8))   # r8 = length, r7 = padding
    a.w(cmp_i(8, 0)); a.br(JREQ, 'M_PAD')
    a.w(cmp_rs(5, 3)); a.br(JRUGT, 'M_BACK')
    a.L('M_FWD')
    a.w(ldub_pi(4, 3)); a.w(stb_pi(5, 4)); a.w(sub_i(8, 1)); a.w(cmp_i(8, 0)); a.br(JRNE, 'M_FWD')
    a.br(JP, 'M_PAD')
    a.L('M_BACK')
    a.w(add_rs(3, 8)); a.w(add_rs(5, 8)); a.w(ldw_rs(10, 5))
    a.L('M_BK')
    a.w(sub_i(3, 1)); a.w(sub_i(5, 1)); a.w(ldub_rb(4, 3)); a.w(0x3400 | 5 << 4 | 4)   # ld.b [r5],r4
    a.w(sub_i(8, 1)); a.w(cmp_i(8, 0)); a.br(JRNE, 'M_BK')
    a.w(ldw_rs(5, 10))
    a.L('M_PAD')
    a.w(ld_i(4, 0))
    a.L('M_PZ')
    a.w(cmp_i(7, 0)); a.br(JREQ, 'M_W')
    a.w(stb_pi(5, 4)); a.w(sub_i(7, 1)); a.br(JP, 'M_PZ')
    # a game/food cell holding a WORDS Japanese name: [WORDS][slot][offset]
    # of its Korean (r4 = the name in F, r1 = its end, r7 = slot, r3 = its number)
    a.L('M_W')
    ldub_d(a, 8, 9, 1); a.w(cmp_i(8, WORD)); a.br(JRULT, 'M_NX', x=True)
    a.w(ldw_sp(4)); a.w(add_i(4, 0xC)); ldub_d(a, 10, 9, 2); a.w(add_rs(4, 10))
    a.w(ldw_rs(1, 4)); a.w(add_rs(1, 8)); a.li(7, BASE + ARRAY); a.w(ld_i(3, 0))
    a.L('W_S')
    a.w(ldub_rb(10, 7)); _cmpx(a, 10, WORDS); a.br(JRNE, 'W_NS', x=True)
    a.w(ldw_rs(10, 7)); a.w(add_i(10, 1))
    a.L('W_E')
    a.w(ldub_rb(8, 10)); a.w(cmp_i(8, 0)); a.br(JREQ, 'W_NS', x=True)
    a.w(ldw_rs(5, 4))
    a.L('W_C')
    a.w(ldub_rb(8, 10)); a.w(cmp_rs(5, 1)); a.br(JRNE, 'W_C1')
    a.w(cmp_i(8, 0)); a.br(JREQ, 'W_HIT', x=True); a.br(JP, 'W_NE')
    a.L('W_C1')
    a.w(ldub_rb(6, 5)); a.w(cmp_rs(6, 8)); a.br(JRNE, 'W_NE')
    a.w(cmp_i(8, 0)); a.br(JREQ, 'W_HIT', x=True)
    a.w(add_i(5, 1)); a.w(add_i(10, 1)); a.br(JP, 'W_C')
    a.L('W_NE')                                         # past this Japanese, then its Korean
    a.w(ldub_pi(8, 10)); a.w(cmp_i(8, 0)); a.br(JRNE, 'W_NE')
    a.L('W_NK')
    a.w(ldub_pi(8, 10)); a.w(cmp_i(8, 0)); a.br(JRNE, 'W_NK')
    a.br(JP, 'W_E', x=True)
    a.L('W_NS')
    a.ext(0); a.w(add_i(7, OLD)); a.w(add_i(3, 1)); _cmpx(a, 3, COUNT); a.br(JRULT, 'W_S', x=True)
    a.br(JP, 'M_NX', x=True)
    a.L('W_HIT')
    a.w(add_i(10, 1)); a.w(sub_rs(10, 7))
    a.ext(WORDS >> 6); a.w(ld_i(8, WORDS & 0x3F)); a.w(stb_pi(4, 8)); a.w(stb_pi(4, 3)); a.w(stb_pi(4, 10))
    a.L('M_NX')
    a.w(ldw_rs(10, 11)); a.w(add_i(10, 1)); a.w(cmp_rs(9, 10)); a.br(JREQ, 'M_END')
    a.w(sub_i(9, 3)); a.br(JP, 'M_J', x=True)
    a.L('M_END')                                        # F[0..13) 0, line -1, MARK2, k
    a.w(ldw_sp(4)); a.w(add_i(4, 0xC)); a.w(ldw_rs(5, 4)); a.w(add_i(5, NAMES - 3)); a.w(ld_i(10, 0))
    a.L('M_Z')
    a.w(stb_pi(4, 10)); a.w(cmp_rs(4, 5)); a.br(JRULT, 'M_Z')
    a.ext(0xFF >> 6); a.w(ld_i(10, 0xFF & 0x3F)); a.w(stb_pi(4, 10))
    a.ext(MARK2 >> 6); a.w(ld_i(10, MARK2 & 0x3F)); a.w(stb_pi(4, 10))
    a.w(ldw_sp(7)); ldub_d(a, 10, 7, 2); a.w(stb_pi(4, 10))
    a.w(0x502C)                                         # ld.w r12,[sp+2]
    a.w(ld_i(3, 0x20 - 0xB)); a.br(JP, 'DNEXT', x=True)
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


GAMES = (0x5390B0, 0x5390B8, 0x5390C0, 0x5390CC,       # the link play menu's games, and
         0x539108, 0x539EC4, 0x539ECC)                  # the names its results use
FOODS = (0x3CF000, 0x3DE000)                            # built-in food names


def words(rom, ps_rom, strings):
    """Japanese/Korean pairs of the names a link diary's game/food cell gets
    (whichever device composed it) into the original array's slots that
    are no name template (nothing reads those since patch()): WORDS, then
    jp NUL ko NUL ..., NUL.  Returns the pairs written."""
    pairs, seen = [], set()
    for a in sorted(strings):
        if a in GAMES or FOODS[0] <= a < FOODS[1]:
            jp, ko = ps_rom[a:a + 40].split(b'\0')[0], strings[a].split(b'\0')[0]
            if jp and ko and jp != ko and len(jp) <= 9 and jp not in seen:
                seen.add(jp); pairs.append((jp, ko))
    slots = [k for k in range(COUNT) if not name_cells(ps_rom[ARRAY + OLD * k:ARRAY + OLD * (k + 1)].split(b'\0')[0])]
    todo = list(pairs)
    for k in slots:
        b = bytearray([WORDS])
        while todo and len(b) + len(todo[0][0]) + len(todo[0][1]) + 3 <= OLD:
            jp, ko = todo.pop(0); b += jp + b'\0' + ko + b'\0'
        rom[ARRAY + OLD * k:ARRAY + OLD * (k + 1)] = bytes(b).ljust(OLD, b'\0')
    assert not todo, f'{len(todo)} names left over'
    return pairs


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
