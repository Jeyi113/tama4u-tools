"""Long activity-diary entries for the Hangul P's.

A diary entry is one 8 KB flash sector (0x2570000 + n*0x2000, 24 of them):
text in its first 36 bytes, a header at +0x24, per-day data after it (the
link export sends the first 0x17FC bytes).  The recorder 0x241cb52 composes
the entry (0x241cd22: sentence 0x2418a3c(idx) from the 40-byte array at
0x2558370, names pasted over its 0x6C cells) into a 36-byte stack buffer, so
Hangul (2 bytes a syllable) got half of what kana gets.

Patched:
  sentence array -> SAFE, 80-byte entries (0x2418a44 sll 3 -> 4, new base)
  0x241cbd0  recorder's composer call -> DWRAP: compose into 128 bytes, drop
             0x6C, give the recorder a copy cut at a character boundary (<=35
             bytes, the old field) and program the whole text at sector+0x1F00
             (free: the sector is blank when an entry is recorded, and the
             sector rotation copies whole 64 KB blocks)
  0x241c790  diary page's text pointer -> DVIEW: sector+0x1F00 if written,
             else the 36-byte copy (entries from before the patch, other
             devices' data)
"""
import struct

from .hangul import BASE, _Asm, _xsub, CALL, JP, JREQ, JRNE, JRULE, JRUGT, RET, \
    ldub_rs, ldub_rb, ldw_rs, ldw_rb, add_i, sub_i, cmp_i, cmp_rs, sub_rs, sll_i, ld_i

ARRAY, COUNT, OLD, NEW = 0x558370, 75, 40, 80
TAIL = 0x1F00                   # sector offset of the full text
TEXT = NEW - 1                  # bytes before the NUL
LINES = 6                       # the diary page's text box
COMPOSE, FLASH_ON, FLASH_OFF, PROGRAM = 0x0241CD22, 0x024FE312, 0x024FE30E, 0x00000BC4
REC_CALL, VIEW_AT = 0x41CBD0, 0x41C790

ldub_pi = lambda rd, rb: 0x2500 | rb << 4 | rd          # ld.ub rd,[rb]+
stb_pi = lambda rb, rs: 0x3500 | rb << 4 | rs           # ld.b [rb]+,rs
or_rs = lambda rd, rs: 0x3600 | rs << 4 | rd
ldw_sp = lambda rd: 0xA410 | rd                         # ld.w rd,%sp
PUSHN3, POPN3 = 0x0203, 0x0243
FRAME = 0x20                                            # words: 128-byte buffer


def _far(a, tgt, reg=9):                                # call beyond +-2 MB
    a.li(reg, tgt); a.w(0x0600 | reg)


def assemble(org):
    a = _Asm(org)
    # DWRAP(r6 = recorder's 36-byte buffer, r8 = arg); r0 = event, r3 = sector
    a.L('DWRAP')
    a.w(PUSHN3); a.w(0x8400 | FRAME)
    a.w(ldw_rs(1, 6)); a.w(ldw_sp(6)); a.w(ldw_rs(7, 0))
    a.br(CALL, COMPOSE, x=True)
    a.w(ldw_rs(2, 4))                                   # composer's result
    a.w(ldw_sp(4)); a.w(ldw_sp(5))                      # drop 0x6C cells in place
    a.L('D_CMP')
    a.w(ldub_pi(6, 4)); a.ext(0x6C >> 6); a.w(cmp_i(6, 0x6C & 0x3F)); a.br(JREQ, 'D_CMP')
    a.w(stb_pi(5, 6)); a.w(cmp_i(6, 0)); a.br(JRNE, 'D_CMP')
    a.w(ldw_sp(4)); a.w(ldw_rs(5, 1)); a.ext(0); a.w(ld_i(7, 35))  # old field: whole chars
    a.L('D_CHR')
    a.w(ldub_rb(6, 4)); a.w(cmp_i(6, 0)); a.br(JREQ, 'D_FLASH')
    a.w(ldw_rs(9, 6)); _xsub(a, 9, 0xC7); a.w(ldub_rs(9, 9)); a.w(cmp_i(9, 8)); a.br(JRULE, 'D_TWO')
    a.w(ldw_rs(9, 6)); _xsub(a, 9, 0xD9); a.w(ldub_rs(9, 9)); a.w(cmp_i(9, 6)); a.br(JRULE, 'D_TWO')
    a.w(ld_i(8, 1)); a.br(JP, 'D_LEN')
    a.L('D_TWO'); a.w(ld_i(8, 2))
    a.L('D_LEN')
    a.w(cmp_rs(8, 7)); a.br(JRUGT, 'D_FLASH'); a.w(sub_rs(7, 8))
    a.L('D_CPY')
    a.w(ldub_pi(6, 4)); a.w(stb_pi(5, 6)); a.w(sub_i(8, 1)); a.w(cmp_i(8, 0)); a.br(JRNE, 'D_CPY')
    a.br(JP, 'D_CHR')
    a.L('D_FLASH')                                      # r1 = sector + TAIL, r0 = text
    a.w(ldw_rs(1, 3)); a.w(sll_i(1, 13)); a.li(4, BASE + 0x570000 + TAIL); a.w(0x2241)  # add r1,r4
    a.w(ldw_sp(0))
    a.br(CALL, FLASH_ON, x=True)
    a.L('D_PROG')
    a.w(ldub_rb(4, 0)); a.ext(1); a.w(ldub_rb(7, 0)); a.w(sll_i(7, 8)); a.w(or_rs(7, 4))
    a.w(ldw_rs(6, 1)); a.li(8, BASE); _far(a, PROGRAM)
    a.w(cmp_i(4, 0)); a.br(JRNE, 'D_DONE')
    a.w(ldub_rb(4, 0)); a.w(cmp_i(4, 0)); a.br(JREQ, 'D_DONE')
    a.ext(1); a.w(ldub_rb(4, 0)); a.w(cmp_i(4, 0)); a.br(JREQ, 'D_DONE')
    a.w(add_i(0, 2)); a.w(add_i(1, 2)); a.br(JP, 'D_PROG')
    a.L('D_DONE')
    a.br(CALL, FLASH_OFF, x=True)
    a.w(0x8000 | FRAME); a.w(POPN3); a.w(ldw_rs(4, 2)); a.w(RET)

    # DVIEW: r1 = text to draw, r4 = its first byte (caller's frame = sp + 4)
    a.L('DVIEW')
    a.w(ldw_sp(4)); a.w(add_i(4, 4))
    a.ext(0x34); a.w(ldw_rb(1, 4))                      # [sp+0xd] = sector index
    a.w(sll_i(1, 13)); a.li(5, BASE + 0x570000 + TAIL); a.w(0x2251)  # add r1,r5
    a.w(ldub_rb(5, 1)); a.ext(0xFF >> 6); a.w(cmp_i(5, 0xFF & 0x3F)); a.br(JRNE, 'V_USE')
    a.w(ldw_rs(1, 4)); a.w(add_i(1, 0xC))
    a.L('V_USE')
    a.w(ldub_rb(4, 1)); a.w(RET)
    code = a.build()
    return code, dict(a.labels)


def patch(rom, lab, array):
    """Hook the recorder and the diary page; move the sentences to `array`
    (file offset, COUNT * NEW bytes)."""
    for k in range(COUNT):
        src = ARRAY + OLD * k
        s = rom[src:src + OLD].split(b'\0')[0]
        rom[array + NEW * k:array + NEW * (k + 1)] = s.ljust(NEW, b'\0')
    assert rom[0x418A44:0x418A4C] == bytes.fromhex('318c4ac00dd6046f'), 'sentence lookup'
    rom[0x418A44:0x418A46] = struct.pack('<H', sll_i(1, 4))          # idx * 80
    v = BASE + array
    rom[0x418A46:0x418A4C] = struct.pack('<3H', 0xC000 | v >> 19 & 0x1FFF,
                                         0xC000 | v >> 6 & 0x1FFF, 0x6C04 | (v & 0x3F) << 4)
    assert rom[REC_CALL:REC_CALL + 6] == bytes.fromhex('00c0a81d072e'), 'recorder call'
    h = _Asm(BASE + REC_CALL); h.br(CALL, lab['DWRAP'], x=True); h.w(0)
    rom[REC_CALL:REC_CALL + 6] = h.build()
    assert rom[VIEW_AT:VIEW_AT + 14] == bytes.fromhex('11a400c0036ec444242a3019c160'), 'diary page'
    h = _Asm(BASE + VIEW_AT); h.br(CALL, lab['DVIEW'], x=True)
    h.ext(0); h.w(0x6E03)                               # xld.w r3,0x20
    h.w(cmp_rs(4, 2)); h.br(JREQ, BASE + 0x41C7FA); h.w(0)
    rom[VIEW_AT:VIEW_AT + 14] = h.build()
