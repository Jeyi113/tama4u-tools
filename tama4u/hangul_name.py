"""Hangul user-name entry for the P's name screen (Some-style jamo input).

The stock screen (inside 0x2524B10) edits five 1-byte kana slots.  With
2-byte Hangul the 5-byte name at RAM 0x1307 holds two syllables, so the
loop from 0x25251BE is replaced by KNAME: two Hangul slots, each composed
cho -> jung -> jong from lists restricted to the 2,350 KS syllables, and a
third 1-byte slot for one of the P's own mono symbols (EMO).  The 8x9 colour
icons 0xD0-0xD7 are left out: drawn in a speech bubble their 8-colour
palette overwrites the bubble's colours (seen on the emulator).

Keys (event flags the firmware's key task sets):
  A 0x1450  idle: skip to next slot (last slot: finish) | choosing: next candidate
  B 0x1451  idle: start choosing | choosing: confirm (emoticon: and finish)
  C 0x1452  back one stage; idle -> previous slot
Only the current candidate shows in the slot: the bare initial while
choosing cho, the open syllable (가 갸 거 ...) for jung, the full syllable
for jong.  Name bytes = [syl1][syl2][emo]; unused = 0x6C (0x6C 0x6C).
Editing resumes from what the slot already holds.
"""
import struct

from . import hangul as H

NAME = 0x1307
OBJS = 0x84418            # slot object ids, one byte each
EV_A, EV_B, EV_C, EV_T = 0x1450, 0x1451, 0x1452, 0x1453
SLOT_Y = 0x4F
BLANK_SLOT = 0x6C
# the 12x14 symbols 0x51-0x6B (0x6C is the blank)
EMO = list(range(0x51, 0x6C))

# Some's jamo order -> Unicode syllable-block indices
CHO_U = [0, 2, 3, 5, 6, 7, 9, 11, 12, 14, 15, 16, 17, 18, 1, 4, 8, 10, 13]
JUNG_U = [0, 2, 4, 6, 8, 12, 13, 17, 18, 20, 1, 3, 5, 7, 9, 10, 11, 14, 15, 16, 19]
JONG_U = [0, 1, 4, 7, 8, 16, 17, 19, 21, 22, 23, 24, 25, 26, 27, 2, 20,
          3, 5, 6, 9, 10, 11, 12, 13, 14, 15, 18]
END = 0xFFFF
FRESH = 31            # [4] while composing into an empty slot: no final to keep


def srl10(o, r):
    """r >>= 10 (S1C33 shift immediates go up to 8 only)."""
    o.w(0x8800 | 8 << 4 | r); o.w(0x8800 | 2 << 4 | r)


def tables():
    """PAIR[19*21] u16 offsets into LIST (END = no syllable), LIST u16 glyph
    numbers per (cho, jung), jong order, END-terminated; DECOMP[2350] u16 =
    cho | jung << 5 | jong << 10 (the final, 0-27), to resume editing a
    syllable: entering the final stage looks that final up in the (possibly
    new) cho/jung list, so changing the initial or medial keeps the final."""
    ks = {bytes([h, l]).decode('euc-kr'): g
          for g, (h, l) in enumerate((c >> 8, c & 0xFF) for c in H.KS)}
    pair, lst, dec = [], [], [0] * len(H.KS)
    for ci, c in enumerate(CHO_U):
        for ji, j in enumerate(JUNG_U):
            gt = [(ks[s], t) for t in JONG_U
                  if (s := chr(0xAC00 + (c * 21 + j) * 28 + t)) in ks]
            gs = [g for g, _ in gt]
            if gs:
                pair.append(len(lst)); lst += gs + [END]
                for g, t in gt:                         # the final itself, not its
                    dec[g] = ci | ji << 5 | t << 10     # place in this pair's list
            else:
                pair.append(END)
    return pair, lst, dec


class _Ops:
    """Emit helpers over an _Asm; labels get `pfx` so the jamo engine can be
    generated twice (name screen, profile editor) against one set of tables."""
    def __init__(s, a, pfx=''):
        s.a, s.pfx = a, pfx

    def w(s, v): s.a.w(v)
    def ext(s, v): s.a.ext(v)
    def L(s, n): s.a.L(s.pfx + n)

    def br(s, op, tgt, x=False):
        s.a.br(op, s.pfx + tgt if isinstance(tgt, str) else tgt, x)

    def ldub_off(s, rd, rb, off):
        if off:
            s.ext(off)
        s.w(H.ldub_rb(rd, rb))

    def stb(s, rb, rs, off=0):
        if off:
            s.ext(off)
        s.w(0x3400 | rb << 4 | rs)

    def li(s, rd, v):                                  # small/medium immediates
        if -32 <= v < 32:
            s.w(H.ld_i(rd, v))
        elif 0 <= v < (1 << 18):
            s.ext(v >> 6); s.w(H.ld_i(rd, v & 0x3F))
        else:
            s.a.li(rd, v)

    def far(s, op, tgt):                               # call/jp via r4 (IRAM etc.)
        s.a.li(4, tgt); s.w((0x0600 if op == 'call' else 0x0680) | 4)

    def local(s, rd, k): s.ldub_off(rd, 3, k)          # r3 = frame pointer
    def setl(s, k, rs): s.stb(3, rs, k)

    def lead_idx(s, reg, yes, no):
        w = s.w
        w(H.ldw_rs(7, reg)); H._xsub(s.a, 7, 0xC7); w(H.ldub_rs(7, 7)); w(H.cmp_i(7, 8)); s.br(H.JRULE, yes)
        w(H.ldw_rs(7, reg)); H._xsub(s.a, 7, 0xD9); w(H.ldub_rs(7, 7)); w(H.cmp_i(7, 6))
        s.br(H.JRUGT, no); w(H.add_i(7, 9)); s.br(H.JP, yes)


def slot_y(o, y):
    """Object r2's y = `y` (r4, r5 scratch)."""
    o.li(4, 0x1470); o.w(H.ldw_rs(5, 2)); o.w(H.ldub_rs(5, 5)); o.w(H.sll_i(5, 4)); o.w(H.add_rs(5, 4))
    o.li(4, y); o.ext(6); o.w(0x3800 | 5 << 4 | 4)       # ld.h [r5+6],r4


def _engine1(o, tab, nh, base, term, blank=(BLANK_SLOT, BLANK_SLOT), sym=True):
    """NORM, GLYPH_OF, PAIROFF.  Text = nh Hangul pairs from `base(rd)`, then
    one symbol byte; `term`: also NUL the byte after it (profile field);
    `blank`: the pair an empty slot gets; `sym` False: no symbol byte."""
    w, L, br, ext, li, local = o.w, o.L, o.br, o.ext, o.li, o.local

    # ---- NORM: non-Hangul slots -> 0x6C 0x6C, symbol byte -> 0x6C ---------
    L('NORM')
    for k in range(0, 2 * nh, 2):
        base(5); o.ldub_off(4, 5, k); o.lead_idx(4, f'N_OK{k}', f'N_BL{k}')
        L(f'N_BL{k}')
        li(4, blank[0]); o.stb(5, 4, k)
        if blank[1] != blank[0]:
            li(4, blank[1])
        o.stb(5, 4, k + 1)
        L(f'N_OK{k}')
    if sym:
        base(5); o.ldub_off(4, 5, 2 * nh)              # keep a symbol
        w(H.ldw_rs(7, 4)); H._xsub(o.a, 7, 0x51); w(H.ldub_rs(7, 7)); w(H.cmp_i(7, 0x1A)); br(H.JRULE, 'N_E')
        li(4, BLANK_SLOT); o.stb(5, 4, 2 * nh)
        L('N_E')
    if term:
        li(4, 0); o.stb(5, 4, 2 * nh + 1)
    w(H.RET)

    # ---- GLYPH_OF(r6 = slot) -> r8 = glyph number shown in that slot ------
    L('GLYPH_OF')
    local(4, 0); w(H.cmp_rs(4, 6)); br(H.JRNE, 'G_STORED')
    local(4, 1); w(H.cmp_i(4, 0)); br(H.JREQ, 'G_STORED')
    # initial stage: the initial alone; medial stage of a stored syllable
    # ([4] = its final, not FRESH): the syllable with that final kept
    w(H.cmp_i(4, 1)); br(H.JRNE, 'G_JUNG')
    local(8, 2); ext(len(H.KS) >> 6); w(H.add_i(8, len(H.KS) & 0x3F)); w(H.RET)
    L('G_JUNG')
    br(H.CALL, 'PAIROFF', x=True)                      # r5 = &LIST[off]
    local(4, 1); w(H.cmp_i(4, 2)); br(H.JRNE, 'G_TI')
    local(4, 4); w(H.cmp_i(4, FRESH)); br(H.JREQ, 'G_LIST')
    br(H.JP, 'FINDJ')
    L('G_TI')
    local(4, 4); w(H.sll_i(4, 1)); w(H.add_rs(5, 4))
    L('G_LIST')
    w(H.lduh_rb(8, 5)); w(H.RET)

    # ---- FINDJ(r5 = &LIST[off]) -> r8 = that list's syllable with final [4],
    # else its first (no final) ----------------------------------------------
    L('FINDJ')
    local(7, 4); w(H.lduh_rb(8, 5))
    L('FJ_L')
    w(H.lduh_rb(4, 5)); ext(END >> 6); w(H.cmp_i(4, END & 0x3F)); br(H.JREQ, 'FJ_R')
    o.a.li(9, tab.get('DECOMP', 0)); w(H.add_rs(9, 4)); w(H.add_rs(9, 4)); w(H.lduh_rb(9, 9))
    srl10(o, 9); w(H.cmp_rs(9, 7)); br(H.JREQ, 'FJ_F')
    w(H.add_i(5, 2)); br(H.JP, 'FJ_L')
    L('FJ_F')
    w(H.ldw_rs(8, 4))
    L('FJ_R')
    w(H.RET)
    L('G_STORED')                                      # decode text[2*slot]
    base(5); w(H.add_rs(5, 6)); w(H.add_rs(5, 6))
    w(H.ldub_rb(4, 5)); o.lead_idx(4, 'G_DEC', 'G_BLANK')
    L('G_BLANK')
    li(8, H.HALF); w(H.RET)
    L('G_DEC')                                         # r7 = lead index
    o.ldub_off(8, 5, 1); w(H.sub_i(8, 1))
    ext(0xCF + H.GAP >> 6); w(H.cmp_i(8, 0xCF + H.GAP & 0x3F)); br(H.JRULT, 'G_T'); w(H.sub_i(8, H.GAP))
    L('G_T')                                           # + lead * 245 (256-8-2-1)
    w(H.ldw_rs(4, 7)); w(H.sll_i(4, 8)); w(H.add_rs(8, 4))
    w(H.ldw_rs(4, 7)); w(H.sll_i(4, 3)); w(H.sub_rs(8, 4))
    w(H.ldw_rs(4, 7)); w(H.sll_i(4, 1)); w(H.sub_rs(8, 4))
    w(H.sub_rs(8, 7)); w(H.RET)

    # ---- PAIROFF -> r5 = &LIST[PAIR[ci*21+ji]], r4 = that offset -----------
    L('PAIROFF')
    local(4, 2); w(H.ldw_rs(5, 4)); w(H.sll_i(5, 4)); w(H.add_rs(5, 4))
    w(H.add_rs(5, 4)); w(H.add_rs(5, 4)); w(H.add_rs(5, 4)); w(H.add_rs(5, 4))  # ci*21
    local(4, 3); w(H.add_rs(5, 4)); w(H.sll_i(5, 1))
    o.a.li(4, tab.get('PAIR', 0))
    w(H.add_rs(5, 4)); w(H.lduh_rb(4, 5))
    w(H.sll_i(4, 1)); o.a.li(5, tab.get('LIST', 0)); w(H.add_rs(5, 4))
    w(H.RET)


def _engine2(o, tab, nh, base, back, sym=True):
    """KEY_A/KEY_B/KEY_C, PAIRRAW, NEXTSLOT.  Slot nh is the symbol slot.
    Locals: [0] slot [1] stage [2] ci [3] ji [4] ti [6] done [7] symbol index.
    `back`: C on the idle first slot sets done = 2 (leave backwards);
    `sym` False: no symbol slot, the last Hangul slot finishes."""
    w, L, br, ext, li, local, setl, stb = o.w, o.L, o.br, o.ext, o.li, o.local, o.setl, o.stb
    L('KEY_A')
    if sym:
        local(4, 0); w(H.cmp_i(4, nh)); br(H.JRNE, 'A_K')
        local(4, 1); w(H.cmp_i(4, 0)); br(H.JRNE, 'A_E'); br(H.JP, 'NEXTSLOT', x=True)
        L('A_E')                                       # next emoticon
        local(4, 7); w(H.add_i(4, 1)); ext(len(EMO) >> 6); w(H.cmp_i(4, len(EMO) & 0x3F))
        br(H.JRULT, 'A_ES'); li(4, 0)
        L('A_ES')
        setl(7, 4); w(H.RET)
    L('A_K')
    local(4, 1); w(H.cmp_i(4, 0)); br(H.JRNE, 'A_1')
    br(H.JP, 'NEXTSLOT', x=True)
    L('A_1')
    w(H.cmp_i(4, 1)); br(H.JRNE, 'A_2')
    local(4, 2); w(H.add_i(4, 1)); w(H.cmp_i(4, 19)); br(H.JRULT, 'A_1S'); li(4, 0)
    L('A_1S')
    setl(2, 4); w(H.RET)
    L('A_2')
    w(H.cmp_i(4, 2)); br(H.JRNE, 'A_3')
    L('A_2N')                                          # next jung with syllables
    local(4, 3); w(H.add_i(4, 1)); w(H.cmp_i(4, 21)); br(H.JRULT, 'A_2S'); li(4, 0)
    L('A_2S')
    setl(3, 4); br(H.CALL, 'PAIRRAW', x=True)
    ext(END >> 6); w(H.cmp_i(4, END & 0x3F)); br(H.JREQ, 'A_2N')
    w(H.RET)
    L('A_3')
    local(4, 4); w(H.add_i(4, 1)); setl(4, 4)
    br(H.CALL, 'PAIROFF', x=True); local(4, 4); w(H.sll_i(4, 1)); w(H.add_rs(5, 4))
    w(H.lduh_rb(4, 5)); ext(END >> 6); w(H.cmp_i(4, END & 0x3F)); br(H.JRNE, 'A_3R')
    li(4, 0); setl(4, 4)
    L('A_3R')
    w(H.RET)

    L('PAIRRAW')                                       # r4 = PAIR[ci*21+ji]
    local(4, 2); w(H.ldw_rs(5, 4)); w(H.sll_i(5, 4)); w(H.add_rs(5, 4))
    w(H.add_rs(5, 4)); w(H.add_rs(5, 4)); w(H.add_rs(5, 4)); w(H.add_rs(5, 4))
    local(4, 3); w(H.add_rs(5, 4)); w(H.sll_i(5, 1))
    o.a.li(4, tab.get('PAIR', 0)); w(H.add_rs(5, 4)); w(H.lduh_rb(4, 5))
    w(H.RET)

    L('KEY_B')
    if sym:
        local(4, 0); w(H.cmp_i(4, nh)); br(H.JRNE, 'B_K')
        local(4, 1); w(H.cmp_i(4, 0)); br(H.JRNE, 'B_EC')
        # emoticon slot: start from the one already there (or the first)
        li(4, 0); setl(7, 4)
        base(5); o.ldub_off(6, 5, 2 * nh); o.a.li(5, tab.get('EMO', 0)); li(7, 0)
        L('B_ES')
        w(H.lduh_rb(4, 5)); w(H.cmp_rs(4, 6)); br(H.JREQ, 'B_EF')
        w(H.add_i(5, 2)); w(H.add_i(7, 1)); ext(len(EMO) >> 6); w(H.cmp_i(7, len(EMO) & 0x3F))
        br(H.JRULT, 'B_ES'); br(H.JP, 'B_E1')
        L('B_EF')
        setl(7, 7)
        L('B_E1')
        li(4, 1); setl(1, 4); w(H.RET)
        L('B_EC')                                          # commit emoticon, finish
        local(4, 7); w(H.sll_i(4, 1)); o.a.li(5, tab.get('EMO', 0)); w(H.add_rs(5, 4))
        w(H.lduh_rb(4, 5)); base(5); stb(5, 4, 2 * nh)
        li(4, 0); setl(1, 4); li(4, 1); setl(6, 4); w(H.RET)
    L('B_K')
    local(4, 1); w(H.cmp_i(4, 0)); br(H.JRNE, 'B_1')
    # start: resume from the syllable already in the slot, else from ㄱ/ㅏ/none
    local(6, 0); br(H.CALL, 'GLYPH_OF', x=True)        # st 0 -> stored glyph
    li(4, 0); setl(2, 4); setl(3, 4); li(4, FRESH); setl(4, 4)   # empty: FRESH
    ext(len(H.KS) >> 6); w(H.cmp_i(8, len(H.KS) & 0x3F)); br(H.JRUGE, 'B_0S')
    o.a.li(5, tab.get('DECOMP', 0)); w(H.add_rs(5, 8)); w(H.add_rs(5, 8)); w(H.lduh_rb(4, 5))
    w(H.ldw_rs(5, 4)); w(0x7000 | 31 << 4 | 5); setl(2, 5)          # and r5,31
    w(H.ldw_rs(5, 4)); w(0x8800 | 5 << 4 | 5); w(0x7000 | 31 << 4 | 5); setl(3, 5)
    w(H.ldw_rs(5, 4)); srl10(o, 5); setl(4, 5)
    L('B_0S')
    li(4, 1); setl(1, 4); w(H.RET)
    L('B_1')
    w(H.cmp_i(4, 1)); br(H.JRNE, 'B_2')
    li(4, 2); setl(1, 4)
    br(H.CALL, 'PAIRRAW', x=True)                      # keep ji if still valid
    ext(END >> 6); w(H.cmp_i(4, END & 0x3F)); br(H.JREQ, 'B_1R')
    w(H.RET)
    L('B_1R')
    li(4, 20); setl(3, 4)                              # A_2N steps to the first valid
    br(H.JP, 'A_2N', x=True)
    L('B_2')
    w(H.cmp_i(4, 2)); br(H.JRNE, 'B_3')
    li(4, 3); setl(1, 4)
    br(H.CALL, 'PAIROFF', x=True); local(7, 4); li(6, 0)   # [4] = the final: find it
    L('B_2L')                                          # in this list -> its place
    w(H.lduh_rb(4, 5)); ext(END >> 6); w(H.cmp_i(4, END & 0x3F)); br(H.JREQ, 'B_2R')
    o.a.li(9, tab.get('DECOMP', 0)); w(H.add_rs(9, 4)); w(H.add_rs(9, 4)); w(H.lduh_rb(9, 9))
    srl10(o, 9); w(H.cmp_rs(9, 7)); br(H.JREQ, 'B_2K')
    w(H.add_i(6, 1)); w(H.add_i(5, 2)); br(H.JP, 'B_2L')
    L('B_2R')
    li(6, 0)                                           # no such final here: none
    L('B_2K')
    setl(4, 6); w(H.RET)
    L('B_3')                                           # commit syllable
    local(6, 0); br(H.CALL, 'GLYPH_OF', x=True)        # r8 = glyph
    li(5, 0)
    L('B_DIV')
    ext(H.PER >> 6); w(H.cmp_i(8, H.PER & 0x3F)); br(H.JRULT, 'B_ENC')
    ext(H.PER >> 6); w(H.sub_i(8, H.PER & 0x3F)); w(H.add_i(5, 1)); br(H.JP, 'B_DIV')
    L('B_ENC')                                         # lead = LEADS[r5]
    w(H.cmp_i(5, 9)); br(H.JRULT, 'B_L1'); ext(0xD9 - 9 >> 6); w(H.add_i(5, (0xD9 - 9) & 0x3F)); br(H.JP, 'B_L2')
    L('B_L1')
    ext(0xC7 >> 6); w(H.add_i(5, 0xC7 & 0x3F))
    L('B_L2')
    local(6, 0); base(7); w(H.add_rs(7, 6)); w(H.add_rs(7, 6))
    stb(7, 5); w(H.add_i(8, 1))
    ext(0xD0 >> 6); w(H.cmp_i(8, 0xD0 & 0x3F)); br(H.JRULT, 'B_T'); w(H.add_i(8, H.GAP))
    L('B_T')
    stb(7, 8, 1)
    li(4, 0); setl(1, 4)
    L('NEXTSLOT')
    local(4, 0); w(H.cmp_i(4, nh if sym else nh - 1)); br(H.JRUGE, 'NS_END')
    w(H.add_i(4, 1)); setl(0, 4); w(H.RET)
    L('NS_END')
    li(4, 1); setl(6, 4); w(H.RET)

    L('KEY_C')
    local(4, 1); w(H.cmp_i(4, 0)); br(H.JREQ, 'C_0')
    w(H.cmp_i(4, 3)); br(H.JRNE, 'C_1')                # leaving the final stage: [4]
    br(H.CALL, 'PAIROFF', x=True); local(4, 4)          # back from a place to the final
    w(H.sll_i(4, 1)); w(H.add_rs(5, 4)); w(H.lduh_rb(4, 5))
    o.a.li(9, tab.get('DECOMP', 0)); w(H.add_rs(9, 4)); w(H.add_rs(9, 4)); w(H.lduh_rb(9, 9))
    srl10(o, 9); setl(4, 9); li(4, 3)
    L('C_1')
    w(H.sub_i(4, 1)); setl(1, 4); w(H.RET)
    L('C_0')
    local(4, 0); w(H.cmp_i(4, 0)); br(H.JREQ, 'C_R')
    w(H.sub_i(4, 1)); setl(0, 4)
    if back:
        w(H.RET)
        L('C_R')
        li(4, 2); setl(6, 4)
    else:
        L('C_R')
    w(H.RET)


def _code(a, tab, pitch, trim=0):
    """KNAME and helpers into _Asm `a`; `tab` = addresses of PAIR/LIST from a
    first pass (a.li is fixed-size, so the layout does not move)."""
    o = _Ops(a)
    w, L, br, ext, li, local, setl, stb = o.w, o.L, o.br, o.ext, o.li, o.local, o.setl, o.stb
    ldub_off = o.ldub_off
    base = lambda rd: li(rd, NAME)

    # ---- KNAME: entered by jp from 0x25251BE, never returns ----------------
    L('KNAME')
    w(0x8402)                                          # sub %sp,8 (locals)
    w(0xA413)                                          # ld.w %r3,%sp
    li(4, 0)
    for k in range(8):
        setl(k, 4)
    # three slots centred, the other two off screen
    for k, x in enumerate(slot_x(pitch) + (200, 200)):
        li(5, OBJS); ldub_off(6, 5, k); li(7, x); li(8, SLOT_Y)
        br(H.CALL, 0x02401B28, x=True)
    br(H.CALL, 'NORM', x=True)

    L('LOOP')
    # idle/sleep handling, as the stock loop head (0x25251BE-0x252520E)
    li(0, 0)
    li(5, 0x146C); w(H.ldub_rb(4, 5)); w(H.cmp_i(4, 0)); br(H.JREQ, 'W_IDLE')
    li(4, 0x300786)
    for step in (0, 8, 0x10, 0x10):
        if step:
            w(H.add_i(4, step) if step < 32 else 0)
        w(0x3840)                                      # ld.h [%r4],%r0
    br(H.CALL, 0x0240A4AA, x=True)
    li(5, 0x146C); w(H.ldub_rb(4, 5)); w(H.cmp_i(4, 0)); br(H.JREQ, 'W_BEEP')
    L('W_SLP')
    w(0x0040)                                          # slp
    li(5, 0x146C); w(H.ldub_rb(4, 5)); w(H.cmp_i(4, 0)); br(H.JRNE, 'W_SLP')
    L('W_BEEP')
    li(6, 0x1F4); br(H.CALL, 0x02529048, x=True); br(H.JP, 'W_DONE')
    L('W_IDLE')
    br(H.CALL, 0x0240A5B4, x=True)
    L('W_DONE')
    # blink tick
    li(5, EV_T); w(H.ldub_rb(4, 5)); ext(0); w(0x7000 | 0x20 << 4 | 4)   # xand r4,0x20
    w(H.cmp_i(4, 0)); br(H.JREQ, 'K_A')
    local(4, 5); w(H.add_i(4, 1)); setl(5, 4)
    w(0xAC55)                                          # bclr [%r5],0x5
    # keys
    for flag, name, nxt in ((EV_A, 'KEY_A', 'K_B'), (EV_B, 'KEY_B', 'K_C'), (EV_C, 'KEY_C', 'K_R')):
        L({'KEY_A': 'K_A', 'KEY_B': 'K_B', 'KEY_C': 'K_C'}[name])
        li(5, flag); w(H.ldub_rb(4, 5)); w(H.cmp_i(4, 0)); br(H.JREQ, nxt)
        li(4, 0); stb(5, 4)
        br(H.CALL, name, x=True)
    L('K_R')
    br(H.CALL, 'REFRESH', x=True)
    o.far('call', 0xA18)
    br(H.CALL, 0x025096CA, x=True)
    br(H.CALL, 0x0240049A, x=True)
    local(4, 6); w(H.cmp_i(4, 0)); br(H.JRNE, 'FINISH')
    br(H.JP, 'LOOP', x=True)
    L('FINISH')
    br(H.CALL, 'NORM', x=True)
    li(5, NAME); w(H.ldub_rb(4, 5)); o.lead_idx(4, 'F_OK', 'F_1')
    L('F_1')
    ldub_off(4, 5, 2); o.lead_idx(4, 'F_OK', 'F_2')
    L('F_2')
    ldub_off(4, 5, 4); ext(BLANK_SLOT >> 6); w(H.cmp_i(4, BLANK_SLOT & 0x3F)); br(H.JRNE, 'F_OK')
    L('F_EMPTY')                                       # empty name: stay
    li(4, 0); setl(6, 4); setl(0, 4); br(H.JP, 'LOOP', x=True)
    L('F_OK')
    w(0x8002)                                          # add %sp,8
    br(H.JP, 0x0252545E, x=True)

    _engine1(o, tab, 2, base, False)

    # ---- DRAW(r6 = slot) ----------------------------------------------------
    L('DRAW')
    w(0x0202)                                          # pushn %r2
    w(H.ldw_rs(0, 6))
    br(H.CALL, 'GLYPH_OF', x=True); w(H.ldw_rs(1, 8))  # r1 = glyph
    li(7, 0); local(4, 0); w(H.cmp_rs(4, 0)); br(H.JRNE, 'D_ATTR')
    local(4, 5); w(0x7000 | 1 << 4 | 4); w(H.cmp_i(4, 0)); br(H.JREQ, 'D_ATTR')
    ext(0x2000 >> 6); w(H.ld_i(7, 0))
    L('D_ATTR')
    li(5, OBJS); w(H.add_rs(5, 0)); w(H.ldub_rb(6, 5)); w(H.ldw_rs(2, 6))
    br(H.CALL, 0x02401E1C, x=True)
    w(H.ldw_rs(8, 1)); li(5, 0)
    L('D_DIV')
    ext(H.PER >> 6); w(H.cmp_i(8, H.PER & 0x3F)); br(H.JRULT, 'D_GO')
    ext(H.PER >> 6); w(H.sub_i(8, H.PER & 0x3F)); w(H.add_i(5, 1)); br(H.JP, 'D_DIV')
    L('D_GO')
    w(H.sll_i(5, 2)); a.li(4, H.BASE + H.TBL_AT); w(H.add_rs(5, 4)); w(H.ldw_rb(9, 5))
    if trim:
        # blink-on (the attribute set above): a full 12x14 empty cell at the
        # slot's own y, so the highlight fills the green box -- the trimmed
        # glyph would light only its 11 lower rows
        local(4, 0); w(H.cmp_rs(4, 0)); br(H.JRNE, 'D_N')
        local(4, 5); w(0x7000 | 1 << 4 | 4); w(H.cmp_i(4, 0)); br(H.JREQ, 'D_N')
        li(9, tab.get('BLOCK', 0)); li(8, 0)
        w(H.ldw_rs(6, 2)); li(7, 0x20)
        br(H.CALL, 0x024019C6, x=True)
        slot_y(o, SLOT_Y); br(H.JP, 'D_END')
        L('D_N')
    w(H.ldw_rs(6, 2)); li(7, 0x20)
    br(H.CALL, 0x024019C6, x=True)
    slot_y(o, SLOT_Y + trim)                            # (trimmed glyph: lower)
    L('D_END')
    w(0x0242)                                          # popn %r2
    w(H.RET)

    # ---- DRAW_E: the emoticon slot, through the stock 1-byte lookup ---------
    L('DRAW_E')
    w(0x0202)                                          # pushn %r2
    li(7, 0); local(4, 0); w(H.cmp_i(4, 2)); br(H.JRNE, 'E_ATTR')
    local(4, 5); w(0x7000 | 1 << 4 | 4); w(H.cmp_i(4, 0)); br(H.JREQ, 'E_ATTR')
    ext(0x2000 >> 6); w(H.ld_i(7, 0))
    L('E_ATTR')
    li(5, OBJS); ldub_off(6, 5, 2); w(H.ldw_rs(2, 6))
    br(H.CALL, 0x02401E1C, x=True)
    local(4, 0); w(H.cmp_i(4, 2)); br(H.JRNE, 'E_STORED')
    local(4, 1); w(H.cmp_i(4, 0)); br(H.JREQ, 'E_STORED')
    local(4, 7); w(H.sll_i(4, 1)); a.li(5, tab.get('EMO', 0)); w(H.add_rs(5, 4))
    w(H.lduh_rb(1, 5)); br(H.JP, 'E_POS')
    L('E_STORED')
    li(5, NAME); ldub_off(1, 5, 4)
    L('E_POS')
    w(H.ldw_rs(6, 2)); li(7, 0x20); w(H.ldw_rs(8, 1)); li(9, 0)
    br(H.CALL, 0x02401BDC, x=True)
    if trim:
        slot_y(o, SLOT_Y)                               # (a stock glyph: as placed)
    w(0x0242)                                          # popn %r2
    w(H.RET)

    L('REFRESH')
    li(6, 0); br(H.CALL, 'DRAW', x=True)
    li(6, 1); br(H.CALL, 'DRAW', x=True)
    br(H.CALL, 'DRAW_E', x=True)
    w(H.RET)

    _engine2(o, tab, 2, base, False)

    # ---- tables -------------------------------------------------------------
    pair, lst, dec = tables()
    L('PAIR')
    for v in pair:
        w(v)
    L('LIST')
    for v in lst:
        w(v)
    L('DECOMP')
    for v in dec:
        w(v)
    L('EMO')
    for v in EMO:
        w(v)
    L('BLOCK')                                         # 12x14 empty cell (blink-on)
    blk = bytes([12, 14, 2, 0, 1, 0xFF]) + b'\x07\xe0\x60\x00' + bytes(12 * 14 // 2)
    for k in range(0, len(blk), 2):
        w(blk[k] | blk[k + 1] << 8)

    _profile(a, tab)
    _message(a, tab)


# ---- message to a friend -----------------------------------------------------
# 0x2525946 copies the message record to a work buffer (text at +8: 4 lines of
# 8 bytes), draws the page and calls the character editor 0x2525B30(r6 buffer,
# r7 record) -- up/down through kana a byte at a time; it returns 0 (keep the
# text), -1 (asks whether to stop editing) or -2 (screen off).  Each line is
# drawn by 0x252603A(r6 line 1-4, r7 buffer, r8 record) through putstr.
# HMSG replaces 0x2525B30: 16 two-byte cells (4 a line, so no syllable crosses
# a line), composed as on the name screen; after the 19 initials the candidate
# list offers a symbol (the name screen's 0x51-0x6B, stored as [sym][0x6C]) and
# 끝 (finish).  Empty cells in the middle are FULLB; trailing ones end as NUL.
MSG_EDIT, MSG_LINE, MSG_FLUSH = 0x02525B30, 0x0252603A, 0xA18
MSG_SLEEP = (0x025290DC, 0x025290E6)
MSG_CELLS = 16
M_SYM, M_END = 19, 20                    # stage-1 candidates after the initials


def _message(a, tab):
    o = _Ops(a, 'M_')
    w, L, br, ext, li, local, setl, stb = o.w, o.L, o.br, o.ext, o.li, o.local, o.setl, o.stb
    nh = MSG_CELLS
    lead, trail = H.code(H.FULLB)
    clead, ctrail = H.code(H.CURSOR)
    klead, ktrail = H.code(H.KS.index(int.from_bytes('끝'.encode('euc-kr'), 'big')))
    base = lambda rd: w(H.ldw_rs(rd, 2))              # r2 = the text (buffer + 8)

    def slotptr(rd):                                   # rd = &text[2*slot]
        local(6, 0); base(rd); w(H.add_rs(rd, 6)); w(H.add_rs(rd, 6))

    def put(rd, b0, b1):                               # [rd] = b0 b1 (r4)
        li(4, b0); stb(rd, 4); li(4, b1); stb(rd, 4, 1)

    a.L('HMSG')
    w(0x0203)                                          # pushn %r3
    w(0x8403)                                          # sub %sp,3 (12 bytes of locals)
    w(0xA413)                                          # ld.w %r3,%sp
    w(H.ldw_rs(1, 6)); w(H.ldw_rs(2, 6)); w(H.add_i(2, 8)); w(H.ldw_rs(0, 7))
    li(4, 0)
    for k in range(12):
        setl(k, 4)
    for f in (EV_A, EV_B, EV_C):
        li(5, f); stb(5, 4)
    li(5, 0x145C); li(4, 0x1E); stb(5, 4)
    li(4, 1); setl(10, 4)
    br(H.CALL, 'NORM2', x=True)

    L('LOOP')
    li(5, 0x146C); w(H.ldub_rb(4, 5)); w(H.cmp_i(4, 0)); br(H.JRNE, 'SLEEPX', x=True)
    br(H.CALL, 0x0240A5B4, x=True)                     # idle until the next interrupt
    li(5, EV_T); w(H.ldub_rb(4, 5)); ext(0); w(0x7000 | 0x20 << 4 | 4)   # xand r4,0x20
    w(H.cmp_i(4, 0)); br(H.JREQ, 'K_A')
    local(4, 5); w(H.add_i(4, 1)); setl(5, 4)
    w(0xAC55)                                          # bclr [%r5],0x5
    li(4, 1); setl(10, 4)
    for flag, name, nxt in ((EV_A, 'MA', 'K_B'), (EV_B, 'MB', 'K_C'), (EV_C, 'MC', 'K_R')):
        L({'MA': 'K_A', 'MB': 'K_B', 'MC': 'K_C'}[name])
        li(5, flag); w(H.ldub_rb(4, 5)); w(H.cmp_i(4, 0)); br(H.JREQ, nxt)
        li(4, 0); stb(5, 4)
        li(5, 0x145C); li(4, 0x1E); stb(5, 4)          # keep the idle timer up
        li(4, 1); setl(10, 4); setl(5, 4)              # redraw, blink phase: cursor first
        br(H.CALL, name, x=True)
    L('K_R')
    local(4, 10); w(H.cmp_i(4, 0)); br(H.JREQ, 'NODRAW')
    li(4, 0); setl(10, 4)
    br(H.CALL, 'REFRESH', x=True)
    o.far('call', MSG_FLUSH)
    L('NODRAW')
    local(4, 6); w(H.cmp_i(4, 0)); br(H.JRNE, 'OUT', x=True)
    br(H.JP, 'LOOP', x=True)

    L('OUT')                                           # done 1: keep (0), 2: back (-1)
    br(H.CALL, 'TRIM2', x=True)
    for line in range(1, 5):
        li(6, line); br(H.CALL, 'LINE', x=True)
    o.far('call', MSG_FLUSH)
    local(5, 6); li(4, 0); w(H.cmp_i(5, 2)); br(H.JRNE, 'RET'); li(4, -1)
    L('RET')
    w(0x8003)                                          # add %sp,3
    w(0x0243)                                          # popn %r3
    w(H.RET)
    L('SLEEPX')                                        # screen off: as the stock editor
    br(H.CALL, 'TRIM2', x=True)
    li(6, 0); br(H.CALL, MSG_SLEEP[0], x=True); br(H.CALL, MSG_SLEEP[1], x=True)
    li(4, -2); br(H.JP, 'RET')

    L('LINE')                                          # draw line r6 (1-4)
    w(H.ldw_rs(7, 1)); w(H.ldw_rs(8, 0)); br(H.JP, MSG_LINE, x=True)

    # ---- REFRESH: preview the cell in the text, draw its line, put it back --
    L('REFRESH')
    slotptr(7)
    o.ldub_off(4, 7, 0); setl(8, 4); o.ldub_off(4, 7, 1); setl(9, 4)
    local(4, 1); w(H.cmp_i(4, 0)); br(H.JREQ, 'R_BL')
    # editing: the candidate blinks too (shown right after a key: phase 1)
    local(4, 5); w(0x7000 | 1 << 4 | 4); w(H.cmp_i(4, 0)); br(H.JREQ, 'R_HIDE')
    local(4, 1); w(H.cmp_i(4, 5)); br(H.JRNE, 'R_1')
    local(4, 7); ext(0x51 >> 6); w(H.add_i(4, 0x51 & 0x3F)); stb(7, 4); li(4, BLANK_SLOT); stb(7, 4, 1)
    br(H.JP, 'R_DRAW')
    L('R_1')
    w(H.cmp_i(4, 1)); br(H.JRNE, 'R_G')
    local(4, 2); w(H.cmp_i(4, M_SYM)); br(H.JRNE, 'R_1E')
    put(7, 0x51, BLANK_SLOT); br(H.JP, 'R_DRAW')
    L('R_1E')
    w(H.cmp_i(4, M_END)); br(H.JRNE, 'R_G')
    put(7, klead, ktrail); br(H.JP, 'R_DRAW')
    L('R_G')
    local(6, 0); br(H.CALL, 'GLYPH_OF', x=True)
    slotptr(7); br(H.CALL, 'ENC', x=True); br(H.JP, 'R_DRAW')
    L('R_BL')                                          # idle: blink on odd phases
    local(4, 5); w(0x7000 | 1 << 4 | 4); w(H.cmp_i(4, 0)); br(H.JREQ, 'R_DRAW')
    br(H.CALL, 'BLANK', x=True); w(H.cmp_i(4, 0)); br(H.JREQ, 'R_HIDE')
    slotptr(7); put(7, clead, ctrail); br(H.JP, 'R_DRAW')
    L('R_HIDE')
    slotptr(7); put(7, lead, trail)
    L('R_DRAW')
    local(6, 0); w(H.sra_i(6, 2) if hasattr(H, 'sra_i') else 0x8C26); w(H.add_i(6, 1))
    br(H.CALL, 'LINE', x=True)
    slotptr(7); local(4, 8); stb(7, 4); local(4, 9); stb(7, 4, 1)
    w(H.RET)

    # ---- BLANK: r4 = 1 if the cell at slot is empty (FULLB, 0x6C or NUL) ----
    L('BLANK')
    slotptr(5); w(H.ldub_rb(6, 5)); li(4, 1)
    w(H.cmp_i(6, 0)); br(H.JREQ, 'BL_R')
    li(7, BLANK_SLOT); w(H.cmp_rs(6, 7)); br(H.JREQ, 'BL_R')
    li(7, lead); w(H.cmp_rs(6, 7)); br(H.JRNE, 'BL_N')
    o.ldub_off(6, 5, 1); li(7, trail); w(H.cmp_rs(6, 7)); br(H.JREQ, 'BL_R')
    L('BL_N')
    li(4, 0)
    L('BL_R')
    w(H.RET)

    # ---- ENC(r8 glyph, r7 dest): the 2-byte code --------------------------
    L('ENC')
    li(5, 0)
    L('E_DIV')
    ext(H.PER >> 6); w(H.cmp_i(8, H.PER & 0x3F)); br(H.JRULT, 'E_ENC')
    ext(H.PER >> 6); w(H.sub_i(8, H.PER & 0x3F)); w(H.add_i(5, 1)); br(H.JP, 'E_DIV')
    L('E_ENC')
    w(H.cmp_i(5, 9)); br(H.JRULT, 'E_L1'); ext(0xD9 - 9 >> 6); w(H.add_i(5, (0xD9 - 9) & 0x3F)); br(H.JP, 'E_L2')
    L('E_L1')
    ext(0xC7 >> 6); w(H.add_i(5, 0xC7 & 0x3F))
    L('E_L2')
    stb(7, 5); w(H.add_i(8, 1))
    ext(0xD0 >> 6); w(H.cmp_i(8, 0xD0 & 0x3F)); br(H.JRULT, 'E_T'); w(H.add_i(8, H.GAP))
    L('E_T')
    stb(7, 8, 1); w(H.RET)

    # ---- NORM2: cells -> syllable, [symbol][0x6C] or FULLB -----------------
    L('NORM2')
    base(5); li(6, nh)
    L('N2')
    w(H.ldub_rb(4, 5)); o.lead_idx(4, 'N2_NX', 'N2_S')
    L('N2_S')
    w(H.ldw_rs(7, 4)); H._xsub(a, 7, 0x51); w(H.ldub_rs(7, 7)); w(H.cmp_i(7, 0x1A)); br(H.JRUGT, 'N2_B')
    o.ldub_off(4, 5, 1); w(H.cmp_i(4, 0)); br(H.JREQ, 'N2_SP')
    li(7, BLANK_SLOT); w(H.cmp_rs(4, 7)); br(H.JRNE, 'N2_B')
    L('N2_SP')
    li(4, BLANK_SLOT); stb(5, 4, 1); br(H.JP, 'N2_NX')
    L('N2_B')
    put(5, lead, trail)
    L('N2_NX')
    w(H.add_i(5, 2)); w(H.sub_i(6, 1)); w(H.cmp_i(6, 0)); br(H.JRNE, 'N2')
    w(H.RET)

    # ---- TRIM2: trailing empty cells -> NUL NUL ----------------------------
    L('TRIM2')
    li(4, nh - 1); setl(0, 4)
    L('T2')
    br(H.CALL, 'BLANK', x=True); w(H.cmp_i(4, 0)); br(H.JREQ, 'T2_E')
    slotptr(5); put(5, 0, 0)
    local(4, 0); w(H.cmp_i(4, 0)); br(H.JREQ, 'T2_E'); w(H.sub_i(4, 1)); setl(0, 4); br(H.JP, 'T2')
    L('T2_E')
    w(H.RET)

    # ---- keys: the symbol / 끝 candidates around the jamo engine ------------
    L('MA')
    local(4, 1); w(H.cmp_i(4, 5)); br(H.JRNE, 'MA1')
    local(4, 7); w(H.add_i(4, 1)); w(H.cmp_i(4, len(EMO))); br(H.JRULT, 'MA_S'); li(4, 0)
    L('MA_S')
    setl(7, 4); w(H.RET)
    L('MA1')
    w(H.cmp_i(4, 1)); br(H.JRNE, 'KEY_A', x=True)
    local(4, 2)
    for k, nxt in ((18, M_SYM), (M_SYM, M_END), (M_END, 0)):
        w(H.cmp_i(4, k)); br(H.JRNE, f'MA_{k}'); li(4, nxt); setl(2, 4); w(H.RET)
        L(f'MA_{k}')
    br(H.JP, 'KEY_A', x=True)

    L('MB')
    local(4, 1); w(H.cmp_i(4, 0)); br(H.JRNE, 'MB1')
    slotptr(5); w(H.ldub_rb(4, 5)); H._xsub(a, 4, 0x51); w(H.ldub_rs(4, 4)); w(H.cmp_i(4, 0x1A))
    br(H.JRUGT, 'KEY_B', x=True)
    li(4, 1); setl(1, 4); li(4, M_SYM); setl(2, 4); w(H.RET)   # a symbol cell: at 기호
    L('MB1')
    w(H.cmp_i(4, 1)); br(H.JRNE, 'MB5')
    local(4, 2); w(H.cmp_i(4, M_SYM)); br(H.JRNE, 'MB_E')
    slotptr(5); w(H.ldub_rb(4, 5)); H._xsub(a, 4, 0x51); w(H.ldub_rs(4, 4)); w(H.cmp_i(4, 0x1A))
    br(H.JRULE, 'MB_SI'); li(4, 0)
    L('MB_SI')
    setl(7, 4); li(4, 5); setl(1, 4); w(H.RET)
    L('MB_E')
    w(H.cmp_i(4, M_END)); br(H.JRNE, 'KEY_B', x=True)
    li(4, 0); setl(1, 4); li(4, 1); setl(6, 4); w(H.RET)        # 끝: keep the text
    L('MB5')
    w(H.cmp_i(4, 5)); br(H.JRNE, 'KEY_B', x=True)
    slotptr(5); local(4, 7); ext(0x51 >> 6); w(H.add_i(4, 0x51 & 0x3F)); stb(5, 4)
    li(4, BLANK_SLOT); stb(5, 4, 1)
    li(4, 0); setl(1, 4); br(H.JP, 'NEXTSLOT', x=True)

    L('MC')
    local(4, 1); w(H.cmp_i(4, 5)); br(H.JRNE, 'KEY_C', x=True)
    li(4, 1); setl(1, 4); w(H.RET)

    _engine1(o, tab, nh, base, False, blank=(lead, trail), sym=False)
    _engine2(o, tab, nh, base, True, sym=False)





# ---- profile free-text fields ------------------------------------------------
# The profile editor (state machine from 0x2526C4A, record in r1) dispatches on
# the field index through the jump table at 0x25582F8; fields 3-7 (hobby,
# dream, food, subject, person) share one kana editor at 0x252729E.  Each field
# is 8 bytes at record+8*field+8 and is copied to friends with the profile.
# HPROF replaces that editor: 4 Hangul slots filling the 8 bytes, previewed by
# writing the candidate into the field and redrawing through the page routine
# 0x2527B20 without its cursor (it draws the cursor cell as a 1-byte glyph).
# The slot waiting for X blinks: '_' if empty, else its syllable on/off;
# while composing the candidate shows steadily.
# The page routine copies a field to an 8-byte stack buffer with NUL -> 0x6C
# (7 bytes for pages 8 and 12) and draws it by character count, so a Hangul
# field ran on into the frame; PROF_DRAW keeps the NUL, copies all 8 bytes and
# calls PNUL after each loop to end the buffer (the byte after it is the low
# byte of the saved record pointer, not read again before the routine returns).
# Empty slots in the middle are the
# full-pitch blank FULLB; trailing ones end as 0x6C so an empty field keeps its
# grey placeholder.
PROF_TABLE = 0x5582F8        # file offset of the field jump table
PROF_FIELDS = range(3, 8)
_DISPATCH, _RETURN, _SLEEP, _DRAWPG = 0x02526C76, 0x0252751A, 0x025274FC, 0x02527B20
_FR = 3                      # HPROF's local words (12 bytes) below the caller's frame
PROF_DRAW = [(0x527E94, 0x1B09, 0x1F09), (0x527EB8, 0x6866, 0x6876),   # page 8
             (0x528044, 0x1B09, 0x1F09),                               # pages 9-11
             (0x5280AE, 0x1B09, 0x1F09), (0x5280D2, 0x6866, 0x6876)]   # page 12
PROF_NUL = [0x527EC0, 0x52806E, 0x5280DA]  # 'xld.w %r4,0x143c' after each loop -> call PNUL


def _profile(a, tab):
    """HPROF: entered through the field jump table with the caller's frame
    (words [3] page, [4] field, [5] start column) and r1 = the record."""
    o = _Ops(a, 'P_')
    w, L, br, ext, li, local, setl, stb = o.w, o.L, o.br, o.ext, o.li, o.local, o.setl, o.stb
    nh = 4
    lead, trail = H.code(H.FULLB)
    base = lambda rd: w(H.ldw_rs(rd, 2))              # r2 = the field
    ldc = lambda rd, k: w(0x5000 | k << 4 | rd)        # caller word k (after add sp)
    stc = lambda k, rs: w(0x5C00 | k << 4 | rs)

    def slotptr(rd):                                   # rd = &field[2*slot]
        local(6, 0); base(rd); w(H.add_rs(rd, 6)); w(H.add_rs(rd, 6))

    a.L('HPROF')
    w(0x8400 | _FR)                                    # sub %sp,3
    w(0xA413)                                          # ld.w %r3,%sp
    li(4, 0)
    for k in range(12):
        setl(k, 4)
    w(0x5000 | (4 + _FR) << 4 | 4)                     # r4 = field
    w(H.ldw_rs(5, 4)); w(H.add_i(5, 5)); w(H.cmp_i(4, 3)); br(H.JRNE, 'PG')
    li(5, 8)                                           # page id: 8, or field+5
    L('PG')
    setl(11, 5)
    w(H.sll_i(4, 3)); w(H.add_rs(4, 1)); w(H.add_i(4, 8)); w(H.ldw_rs(2, 4))
    li(4, 0)
    for f in (EV_A, EV_B, EV_C):
        li(5, f); stb(5, 4)
    li(5, 0x145C); li(4, 0x1E); stb(5, 4)
    li(4, 1); setl(10, 4)                              # draw once
    br(H.CALL, 'NORM', x=True)

    L('LOOP')
    li(5, 0x146C); w(H.ldub_rb(4, 5)); w(H.cmp_i(4, 0)); br(H.JRNE, 'SLEEPX', x=True)
    br(H.CALL, 0x0240A5B4, x=True)                     # idle until the next interrupt
    li(5, EV_T); w(H.ldub_rb(4, 5)); ext(0); w(0x7000 | 0x20 << 4 | 4)   # xand r4,0x20
    w(H.cmp_i(4, 0)); br(H.JREQ, 'K_A')
    local(4, 5); w(H.add_i(4, 1)); setl(5, 4)
    w(0xAC55)                                          # bclr [%r5],0x5
    li(4, 1); setl(10, 4)
    for flag, name, nxt in ((EV_A, 'KEY_A', 'K_B'), (EV_B, 'KEY_B', 'K_C'), (EV_C, 'KEY_C', 'K_R')):
        L({'KEY_A': 'K_A', 'KEY_B': 'K_B', 'KEY_C': 'K_C'}[name])
        li(5, flag); w(H.ldub_rb(4, 5)); w(H.cmp_i(4, 0)); br(H.JREQ, nxt)
        li(4, 0); stb(5, 4)
        li(5, 0x145C); li(4, 0x1E); stb(5, 4)          # keep the idle timer up
        li(4, 1); setl(10, 4); setl(5, 4)              # redraw, blink phase: cursor first
        br(H.CALL, name, x=True)
    L('K_R')
    local(4, 10); w(H.cmp_i(4, 0)); br(H.JREQ, 'NODRAW')
    li(4, 0); setl(10, 4)
    br(H.CALL, 'REFRESH', x=True)
    o.far('call', 0xA18)
    L('NODRAW')
    local(4, 6); w(H.cmp_i(4, 0)); br(H.JRNE, 'OUT', x=True)
    br(H.JP, 'LOOP', x=True)

    # ---- leaving: final draw, then the stock editor's own exits -------------
    L('OUT')
    li(4, 0); setl(1, 4); setl(5, 4)                   # stage idle, no blink
    br(H.CALL, 'NORM', x=True); br(H.CALL, 'TRIM', x=True)
    br(H.CALL, 'REFRESH', x=True); o.far('call', 0xA18)
    local(4, 6)
    w(0x8000 | _FR)                                    # add %sp,3
    w(H.cmp_i(4, 2)); br(H.JREQ, 'BACK')
    ldc(4, 4); w(H.add_i(4, 1)); stc(4, 4); li(4, 0); stc(5, 4)   # next field
    ldc(5, 3); w(H.cmp_i(5, 0)); br(H.JRNE, 'FIN1')
    ldc(4, 4); w(H.cmp_i(4, 4)); br(H.JREQ, 'RET0'); br(H.JP, _DISPATCH, x=True)
    L('FIN1')
    ldc(4, 4); w(H.cmp_i(4, 8)); br(H.JREQ, 'RET0'); br(H.JP, _DISPATCH, x=True)
    L('RET0')
    li(4, 0); br(H.JP, _RETURN, x=True)
    L('BACK')                                          # C on the first slot
    ldc(5, 3); w(H.cmp_i(5, 0)); br(H.JREQ, 'BK')
    ldc(4, 4); w(H.cmp_i(4, 4)); br(H.JRNE, 'BK')
    li(4, -1); br(H.JP, _RETURN, x=True)               # first field of page 2: cancel
    L('BK')
    ldc(4, 4); w(H.sub_i(4, 1)); stc(4, 4); li(4, 0); stc(5, 4)
    br(H.JP, _DISPATCH, x=True)
    L('SLEEPX')                                        # screen off: as the stock editor
    br(H.CALL, 'NORM', x=True); br(H.CALL, 'TRIM', x=True)
    w(0x8000 | _FR); li(3, 0); br(H.JP, _SLEEP, x=True)

    # ---- REFRESH: preview the slot in the field, draw, put it back ----------
    L('REFRESH')
    slotptr(7)
    o.ldub_off(4, 7, 0); setl(8, 4); o.ldub_off(4, 7, 1); setl(9, 4)
    local(4, 1); w(H.cmp_i(4, 0)); br(H.JREQ, 'R_BL')
    # editing: the candidate blinks too (shown right after a key: phase 1)
    li(8, H.FULLB); local(4, 5); w(0x7000 | 1 << 4 | 4); w(H.cmp_i(4, 0)); br(H.JREQ, 'R_PUT')
    local(6, 0); br(H.CALL, 'GLYPH_OF', x=True)
    slotptr(7); br(H.CALL, 'ENC', x=True); br(H.JP, 'R_DRAW')
    L('R_BL')                                          # idle: blink on odd phases
    local(4, 5); w(0x7000 | 1 << 4 | 4); w(H.cmp_i(4, 0)); br(H.JREQ, 'R_DRAW')
    local(6, 0); br(H.CALL, 'GLYPH_OF', x=True)
    li(4, H.FULLB); w(H.cmp_rs(8, 4)); br(H.JREQ, 'R_CUR')
    li(4, H.HALF); w(H.cmp_rs(8, 4)); br(H.JREQ, 'R_CUR')
    li(8, H.FULLB); br(H.JP, 'R_PUT')                  # a syllable: hide it
    L('R_CUR')
    li(8, H.CURSOR)
    L('R_PUT')
    slotptr(7); br(H.CALL, 'ENC', x=True)
    L('R_DRAW')
    local(6, 11); li(7, 0); li(8, -1); w(H.ldw_rs(9, 1))
    br(H.CALL, _DRAWPG, x=True)
    slotptr(7); local(4, 8); stb(7, 4); local(4, 9); stb(7, 4, 1)
    w(H.RET)

    # ---- ENC(r8 glyph, r7 dest): the 2-byte code --------------------------
    L('ENC')
    li(5, 0)
    L('E_DIV')
    ext(H.PER >> 6); w(H.cmp_i(8, H.PER & 0x3F)); br(H.JRULT, 'E_ENC')
    ext(H.PER >> 6); w(H.sub_i(8, H.PER & 0x3F)); w(H.add_i(5, 1)); br(H.JP, 'E_DIV')
    L('E_ENC')
    w(H.cmp_i(5, 9)); br(H.JRULT, 'E_L1'); ext(0xD9 - 9 >> 6); w(H.add_i(5, (0xD9 - 9) & 0x3F)); br(H.JP, 'E_L2')
    L('E_L1')
    ext(0xC7 >> 6); w(H.add_i(5, 0xC7 & 0x3F))
    L('E_L2')
    stb(7, 5); w(H.add_i(8, 1))
    ext(0xD0 >> 6); w(H.cmp_i(8, 0xD0 & 0x3F)); br(H.JRULT, 'E_T'); w(H.add_i(8, H.GAP))
    L('E_T')
    stb(7, 8, 1); w(H.RET)

    # ---- TRIM: trailing FULLB pairs -> 0x6C 0x6C (empty field = all 0x6C) --
    L('TRIM')
    base(5)
    for k in reversed(range(0, 2 * nh, 2)):
        o.ldub_off(4, 5, k); ext(lead >> 6); w(H.cmp_i(4, lead & 0x3F)); br(H.JRNE, 'T_END')
        o.ldub_off(4, 5, k + 1); ext(trail >> 6); w(H.cmp_i(4, trail & 0x3F)); br(H.JRNE, 'T_END')
        li(4, BLANK_SLOT); o.stb(5, 4, k); o.stb(5, 4, k + 1)
    L('T_END')
    w(H.RET)

    _engine1(o, tab, nh, base, False, blank=(lead, trail), sym=False)
    _engine2(o, tab, nh, base, True, sym=False)

    # ---- PNUL: end the page routine's field buffer (r9) after 8 bytes ------
    a.L('PNUL')
    li(4, 0); stb(9, 4, 8)
    o.a.li(4, 0x143C); w(H.RET)                        # the instruction it replaced


def lead_idx(a, reg, yes, no):
    """Like hangul._lead_test but leaves the lead index in r7 (r5 kept)."""
    w = a.w
    w(H.ldw_rs(7, reg)); H._xsub(a, 7, 0xC7); w(H.ldub_rs(7, 7)); w(H.cmp_i(7, 8)); a.br(H.JRULE, yes)
    w(H.ldw_rs(7, reg)); H._xsub(a, 7, 0xD9); w(H.ldub_rs(7, 7)); w(H.cmp_i(7, 6))
    a.br(H.JRUGT, no); w(H.add_i(7, 9)); a.br(H.JP, yes)


BG = 0x1B3F98              # name window, 128x72 6-colour, drawn at y=0x1C
BOX_ROWS, BOX_COLOUR = range(0x4F - 0x1C, 0x4F - 0x1C + 14), 5


def slot_x(pitch):
    x0 = 64 - (3 * pitch + 4) // 2                   # three cells, 2px apart
    return x0, x0 + pitch + 2, x0 + 2 * (pitch + 2)


def patch_bg(rom, pitch):
    """Repaint the window's five green boxes as three, under the KNAME slots."""
    w, h, nc = rom[BG], rom[BG + 1], rom[BG + 2]
    p = BG + 6 + 2 * nc

    def put(x, y, v):
        i = y * w + x
        b = rom[p + i // 2]
        rom[p + i // 2] = (b & 0xF0 | v) if i % 2 == 0 else (b & 0x0F | v << 4)
    for y in BOX_ROWS:
        for x in range(30, 98):                      # stock boxes: x 30..97
            put(x, y, 0)
        for x0 in slot_x(pitch):
            for x in range(x0, x0 + pitch):
                put(x, y, BOX_COLOUR)


def assemble(org, pitch=12, trim=0):
    """(bytes, labels) for KNAME + tables at CPU address `org`; `trim`: rows
    cut off the top of the big glyphs (the slot is drawn that much lower)."""
    # table addresses are loaded with immediates whose length depends on the
    # value: pass until the labels stop moving (two passes left DECOMP read
    # 4 bytes early -> a stored syllable resumed as the wrong jamo)
    tab = {}
    for _ in range(8):
        a = H._Asm(org); _code(a, tab, pitch, trim); out = a.build()
        if a.labels == tab:
            return out, a.labels
        tab = a.labels
    raise AssertionError('KNAME labels do not settle')


# ---- friend card names ---------------------------------------------------------
# The friend list card (0x241B62A..0x241B672) draws the friend's 5-byte name a
# byte per cell: cell i is an object at x 28 + 12i, y 0x51, given its glyph by
# the stock 1-byte lookup 0x2401BDC(r6 obj, r7 0x68, r8 code) -- a Korean
# partner's 2-byte syllables came out as two kana.  CARD replaces that call:
# it walks the name from the start (a Hangul pair is one cell) to find what
# cell r1 shows, and draws a syllable with the big glyph strips (3px lower,
# the trimmed glyphs), anything else through the stock lookup, empty cells as
# 0x6C; an empty Hangul slot (0x6C 0x6C at byte 0 or 2) is one cell, as on
# the name screen.  At the call r5 = name + r1 - 4 (the byte is [r5+4]).
CARD_CALL, CARD_OLD = 0x41B668, '32dfb91d'


def friend_card(rom, src, at, trim=H.TRIM):
    """Write CARD at file offset `at`, hook the card's glyph call."""
    if bytes(src[CARD_CALL:CARD_CALL + 4]).hex() != CARD_OLD:
        raise ValueError('friend card: unexpected bytes')
    a = H._Asm(H.BASE + at)
    w, L, br = a.w, a.L, a.br
    a.L('CARD')
    w(0x0203)                                           # pushn %r3
    w(H.ldw_rs(0, 6)); w(H.ldw_rs(2, 5)); w(H.sub_rs(2, 1)); w(H.add_i(2, 4))   # r0 obj, r2 name
    w(H.ld_i(3, 0)); w(H.ld_i(6, 0))                    # r3 byte j, r6 cell
    L('C_SCAN')
    w(H.cmp_i(3, 5)); br(H.JRUGE, 'C_BLANK')
    w(H.ldw_rs(4, 2)); w(H.add_rs(4, 3)); w(H.ldub_rb(4, 4))
    w(H.cmp_rs(6, 1)); br(H.JREQ, 'C_AT')
    a.ext(H.BLANK >> 6); w(H.cmp_i(4, H.BLANK & 0x3F)); br(H.JRNE, 'C_INK')
    w(H.ldw_rs(5, 3)); w(0x7000 | 1 << 4 | 5); w(H.cmp_i(5, 0)); br(H.JRNE, 'C_S1')   # odd j
    w(H.cmp_i(3, 4)); br(H.JRUGE, 'C_S1')
    w(H.ldw_rs(5, 2)); w(H.add_rs(5, 3)); w(H.add_i(5, 1)); w(H.ldub_rb(5, 5))
    a.ext(H.BLANK >> 6); w(H.cmp_i(5, H.BLANK & 0x3F)); br(H.JREQ, 'C_S2')    # empty slot: 1 cell
    br(H.JP, 'C_S1')
    L('C_INK')
    H._lead_test(a, 4, 'C_S2', 'C_S1')
    L('C_S2')
    w(H.cmp_i(3, 4)); br(H.JRUGE, 'C_S1'); w(H.add_i(3, 1))
    L('C_S1')
    w(H.add_i(3, 1)); w(H.add_i(6, 1)); br(H.JP, 'C_SCAN')
    L('C_AT')
    w(H.ldub_rs(8, 4))
    H._lead_test(a, 8, 'C_HAN', 'C_STOCK')
    L('C_HAN')                                          # r5 = lead index
    w(H.cmp_i(3, 4)); br(H.JRUGE, 'C_STOCK')
    w(H.ldw_rs(4, 2)); w(H.add_rs(4, 3)); w(H.add_i(4, 1)); w(H.ldub_rb(8, 4)); w(H.sub_i(8, 1))
    a.ext(0xCF + H.GAP >> 6); w(H.cmp_i(8, 0xCF + H.GAP & 0x3F)); br(H.JRULT, 'C_T')
    w(H.sub_i(8, H.GAP))
    L('C_T')
    w(H.sll_i(5, 2)); a.li(4, H.BASE + H.TBL_AT); w(H.add_rs(5, 4)); w(H.ldw_rb(9, 5))
    w(H.ldw_rs(6, 0)); a.li(7, 0x68)
    br(H.CALL, 0x024019C6, x=True)
    a.li(4, 0x1470); w(H.ldw_rs(5, 0)); w(H.sll_i(5, 4)); w(H.add_rs(5, 4))   # obj y += trim
    a.ext(6); w(H.lduh_rb(4, 5)); w(H.add_i(4, trim)); a.ext(6); w(0x3800 | 5 << 4 | 4)
    br(H.JP, 'C_END')
    L('C_BLANK')
    a.li(8, H.BLANK)
    L('C_STOCK')
    w(H.ldw_rs(6, 0)); a.li(7, 0x68); w(H.ld_i(9, 0))
    br(H.CALL, 0x02401BDC, x=True)
    L('C_END')
    w(0x0243)                                           # popn %r3
    w(H.RET)
    code = a.build()
    rom[at:at + len(code)] = code
    j = H._Asm(H.BASE + CARD_CALL); j.br(H.CALL, a.labels['CARD'], x=True)
    rom[CARD_CALL:CARD_CALL + 4] = j.build()            # its delay slot (ld.w r9,r0) now runs after
    return len(code)
