"""Hangul user-name entry for the P's name screen (Some-style jamo input).

The stock screen (inside 0x2524B10) edits five 1-byte kana slots.  With
2-byte Hangul the 5-byte name at RAM 0x1307 holds two syllables, so the
loop from 0x25251BE is replaced by KNAME: two 14px slots, each composed
cho -> jung -> jong from lists restricted to the 2,350 KS syllables.

Keys (event flags the firmware's key task sets):
  A 0x1450  idle: skip to next slot (last slot: finish) | composing: next candidate
  B 0x1451  idle: start composing | composing: confirm the stage
  C 0x1452  back one stage; idle on slot 2 -> slot 1
Only the current candidate shows in the slot: the bare initial while
choosing cho, the open syllable (가 갸 거 ...) for jung, the full syllable
for jong.  Name bytes = [syl1][syl2][0x6C]; an unused slot is 0x6C 0x6C.
"""
import struct

from . import hangul as H

NAME = 0x1307
OBJS = 0x84418            # slot object ids, one byte each
EV_A, EV_B, EV_C, EV_T = 0x1450, 0x1451, 0x1452, 0x1453
SLOT_Y = 0x4F
BLANK_SLOT = 0x6C

# Some's jamo order -> Unicode syllable-block indices
CHO_U = [0, 2, 3, 5, 6, 7, 9, 11, 12, 14, 15, 16, 17, 18, 1, 4, 8, 10, 13]
JUNG_U = [0, 2, 4, 6, 8, 12, 13, 17, 18, 20, 1, 3, 5, 7, 9, 10, 11, 14, 15, 16, 19]
JONG_U = [0, 1, 4, 7, 8, 16, 17, 19, 21, 22, 23, 24, 25, 26, 27, 2, 20,
          3, 5, 6, 9, 10, 11, 12, 13, 14, 15, 18]
END = 0xFFFF


def tables():
    """PAIR[19*21] u16 offsets into LIST (END = no syllable), LIST u16 glyph
    numbers per (cho, jung), jong order, END-terminated."""
    ks = {bytes([h, l]).decode('euc-kr'): g
          for g, (h, l) in enumerate((c >> 8, c & 0xFF) for c in H.KS)}
    pair, lst = [], []
    for c in CHO_U:
        for j in JUNG_U:
            gs = [ks[s] for t in JONG_U
                  if (s := chr(0xAC00 + (c * 21 + j) * 28 + t)) in ks]
            if gs:
                pair.append(len(lst)); lst += gs + [END]
            else:
                pair.append(END)
    return pair, lst


def _code(a, tab, pitch):
    """KNAME and helpers into _Asm `a`; `tab` = addresses of PAIR/LIST from a
    first pass (a.li is fixed-size, so the layout does not move)."""
    w, L, br, ext = a.w, a.L, a.br, a.ext
    ldub_off = lambda rd, rb, off: (ext(off), w(H.ldub_rb(rd, rb))) if off else w(H.ldub_rb(rd, rb))
    stb = lambda rb, rs, off=0: (ext(off), w(0x3400 | rb << 4 | rs)) if off else w(0x3400 | rb << 4 | rs)

    def li(rd, v):                                     # small/medium immediates
        if -32 <= v < 32:
            w(H.ld_i(rd, v))
        elif 0 <= v < (1 << 18):
            ext(v >> 6); w(H.ld_i(rd, v & 0x3F))
        else:
            a.li(rd, v)

    def far(op, tgt):                                  # call/jp via r4 (IRAM etc.)
        a.li(4, tgt); w((0x0600 if op == 'call' else 0x0680) | 4)

    def local(rd, k): ldub_off(rd, 3, k)               # r3 = frame pointer
    def setl(k, rs): stb(3, rs, k)

    # ---- KNAME: entered by jp from 0x25251BE, never returns ----------------
    L('KNAME')
    w(0x8402)                                          # sub %sp,8 (locals)
    w(0xA413)                                          # ld.w %r3,%sp
    li(4, 0)
    for k in range(8):
        setl(k, 4)
    # two slots centred, the other three off screen
    for k, x in enumerate(slot_x(pitch) + (200, 200, 200)):
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
    far('call', 0xA18)
    br(H.CALL, 0x025096CA, x=True)
    br(H.CALL, 0x0240049A, x=True)
    local(4, 6); w(H.cmp_i(4, 0)); br(H.JRNE, 'FINISH')
    br(H.JP, 'LOOP', x=True)
    L('FINISH')
    br(H.CALL, 'NORM', x=True)
    li(5, NAME); w(H.ldub_rb(4, 5)); lead_idx(a, 4, 'F_OK', 'F_1')
    L('F_1')
    ldub_off(4, 5, 2); lead_idx(a, 4, 'F_OK', 'F_EMPTY')
    L('F_EMPTY')                                       # empty name: stay
    li(4, 0); setl(6, 4); setl(0, 4); br(H.JP, 'LOOP', x=True)
    L('F_OK')
    w(0x8002)                                          # add %sp,8
    br(H.JP, 0x0252545E, x=True)

    # ---- NORM: non-Hangul slots -> 0x6C 0x6C, byte 4 = 0x6C ---------------
    L('NORM')
    for k in (0, 2):
        li(5, NAME); ldub_off(4, 5, k); lead_idx(a, 4, f'N_OK{k}', f'N_BL{k}')
        L(f'N_BL{k}')
        li(4, BLANK_SLOT); stb(5, 4, k); stb(5, 4, k + 1)
        L(f'N_OK{k}')
    li(5, NAME); li(4, BLANK_SLOT); stb(5, 4, 4)
    w(H.RET)

    # ---- GLYPH_OF(r6 = slot) -> r8 = glyph number shown in that slot ------
    L('GLYPH_OF')
    local(4, 0); w(H.cmp_rs(4, 6)); br(H.JRNE, 'G_STORED')
    local(4, 1); w(H.cmp_i(4, 0)); br(H.JREQ, 'G_STORED')
    w(H.cmp_i(4, 1)); br(H.JRNE, 'G_JUNG')
    local(8, 2); ext(len(H.KS) >> 6); w(H.add_i(8, len(H.KS) & 0x3F)); w(H.RET)
    L('G_JUNG')
    br(H.CALL, 'PAIROFF', x=True)                      # r5 = &LIST[off]
    local(4, 1); w(H.cmp_i(4, 2)); br(H.JREQ, 'G_LIST')
    local(4, 4); w(H.sll_i(4, 1)); w(H.add_rs(5, 4))
    L('G_LIST')
    w(H.lduh_rb(8, 5)); w(H.RET)
    L('G_STORED')                                      # decode name[2*slot]
    li(5, NAME); w(H.add_rs(5, 6)); w(H.add_rs(5, 6))
    w(H.ldub_rb(4, 5)); lead_idx(a, 4, 'G_DEC', 'G_BLANK')
    L('G_BLANK')
    li(8, len(H.GLYPHS) - 1); w(H.RET)
    L('G_DEC')                                         # r7 = lead index
    ldub_off(8, 5, 1); w(H.sub_i(8, 1))
    w(H.ldw_rs(4, 7)); w(H.sll_i(4, 8)); w(H.add_rs(8, 4))
    w(H.ldw_rs(4, 7)); w(H.sll_i(4, 1)); w(H.sub_rs(8, 4)); w(H.RET)

    # ---- PAIROFF -> r5 = &LIST[PAIR[ci*21+ji]], r4 = that offset -----------
    L('PAIROFF')
    local(4, 2); w(H.ldw_rs(5, 4)); w(H.sll_i(5, 4)); w(H.add_rs(5, 4))
    w(H.add_rs(5, 4)); w(H.add_rs(5, 4)); w(H.add_rs(5, 4)); w(H.add_rs(5, 4))  # ci*21
    local(4, 3); w(H.add_rs(5, 4)); w(H.sll_i(5, 1))
    a.li(4, tab.get('PAIR', 0))
    w(H.add_rs(5, 4)); w(H.lduh_rb(4, 5))
    w(H.sll_i(4, 1)); a.li(5, tab.get('LIST', 0)); w(H.add_rs(5, 4))
    w(H.RET)

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
    ext(254 >> 6); w(H.cmp_i(8, 254 & 0x3F)); br(H.JRULT, 'D_GO')
    ext(254 >> 6); w(H.sub_i(8, 254 & 0x3F)); w(H.add_i(5, 1)); br(H.JP, 'D_DIV')
    L('D_GO')
    w(H.sll_i(5, 2)); a.li(4, H.BASE + H.TBL_AT); w(H.add_rs(5, 4)); w(H.ldw_rb(9, 5))
    w(H.ldw_rs(6, 2)); li(7, 0x20)
    br(H.CALL, 0x024019C6, x=True)
    w(0x0242)                                          # popn %r2
    w(H.RET)

    L('REFRESH')
    li(6, 0); br(H.CALL, 'DRAW', x=True)
    li(6, 1); br(H.CALL, 'DRAW', x=True)
    w(H.RET)

    # ---- keys ---------------------------------------------------------------
    L('KEY_A')
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
    a.li(4, tab.get('PAIR', 0)); w(H.add_rs(5, 4)); w(H.lduh_rb(4, 5))
    w(H.RET)

    L('KEY_B')
    local(4, 1); w(H.cmp_i(4, 0)); br(H.JRNE, 'B_1')
    li(4, 1); setl(1, 4); li(4, 0); setl(2, 4); w(H.RET)
    L('B_1')
    w(H.cmp_i(4, 1)); br(H.JRNE, 'B_2')
    li(4, 2); setl(1, 4); li(4, 20); setl(3, 4)        # A_2N steps to the first valid
    br(H.JP, 'A_2N', x=True)
    L('B_2')
    w(H.cmp_i(4, 2)); br(H.JRNE, 'B_3')
    li(4, 3); setl(1, 4); li(4, 0); setl(4, 4); w(H.RET)
    L('B_3')                                           # commit syllable
    local(6, 0); br(H.CALL, 'GLYPH_OF', x=True)        # r8 = glyph
    li(5, 0)
    L('B_DIV')
    ext(254 >> 6); w(H.cmp_i(8, 254 & 0x3F)); br(H.JRULT, 'B_ENC')
    ext(254 >> 6); w(H.sub_i(8, 254 & 0x3F)); w(H.add_i(5, 1)); br(H.JP, 'B_DIV')
    L('B_ENC')                                         # lead = LEADS[r5]
    w(H.cmp_i(5, 9)); br(H.JRULT, 'B_L1'); ext(0xD9 - 9 >> 6); w(H.add_i(5, (0xD9 - 9) & 0x3F)); br(H.JP, 'B_L2')
    L('B_L1')
    ext(0xC7 >> 6); w(H.add_i(5, 0xC7 & 0x3F))
    L('B_L2')
    local(6, 0); li(7, NAME); w(H.add_rs(7, 6)); w(H.add_rs(7, 6))
    stb(7, 5); w(H.add_i(8, 1)); stb(7, 8, 1)
    li(4, 0); setl(1, 4)
    L('NEXTSLOT')
    local(4, 0); w(H.cmp_i(4, 0)); br(H.JRNE, 'NS_END')
    li(4, 1); setl(0, 4); w(H.RET)
    L('NS_END')
    li(4, 1); setl(6, 4); w(H.RET)

    L('KEY_C')
    local(4, 1); w(H.cmp_i(4, 0)); br(H.JREQ, 'C_0')
    w(H.sub_i(4, 1)); setl(1, 4); w(H.RET)
    L('C_0')
    li(4, 0); setl(0, 4); w(H.RET)

    # ---- tables -------------------------------------------------------------
    pair, lst = tables()
    L('PAIR')
    for v in pair:
        w(v)
    L('LIST')
    for v in lst:
        w(v)


def lead_idx(a, reg, yes, no):
    """Like hangul._lead_test but leaves the lead index in r7 (r5 kept)."""
    w = a.w
    w(H.ldw_rs(7, reg)); H._xsub(a, 7, 0xC7); w(H.ldub_rs(7, 7)); w(H.cmp_i(7, 8)); a.br(H.JRULE, yes)
    w(H.ldw_rs(7, reg)); H._xsub(a, 7, 0xD9); w(H.ldub_rs(7, 7)); w(H.cmp_i(7, 6))
    a.br(H.JRUGT, no); w(H.add_i(7, 9)); a.br(H.JP, yes)


BG = 0x1B3F98              # name window, 128x72 6-colour, drawn at y=0x1C
BOX_ROWS, BOX_COLOUR = range(0x4F - 0x1C, 0x4F - 0x1C + 14), 5


def slot_x(pitch):
    x0 = 64 - (pitch + 2 + pitch) // 2               # two cells, 2px apart
    return x0, x0 + pitch + 2


def patch_bg(rom, pitch):
    """Repaint the window's five green boxes as two, under the KNAME slots."""
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


def assemble(org, pitch=12):
    """(bytes, labels) for KNAME + tables at CPU address `org`."""
    a = H._Asm(org); _code(a, {}, pitch); a.build()
    b = H._Asm(org); _code(b, a.labels, pitch)
    return b.build(), b.labels
