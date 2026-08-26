"""Disassembler for the Epson S1C33 core the P's runs on.

The download packs are mostly data, but outings, minigames and VDPs carry a
program blob, and that blob is S1C33 machine code.  What pins the family is
Mr.Blinky's translation scripts, which annotate their patch bytes with
mnemonics -- `c003 6876 ;xcmp %r6,0xc7` only works out if `ext` supplies the
high bits (imm13 3 << 6 | imm6 7 = 0xC7), which is exactly how the S1C33
extension prefix behaves.  The opcode map below follows the core manual's
table; 47 encoding/mnemonic pairs harvested from those scripts are the
regression test (`tests/test_s1c33.py`).

Instructions are 16 bits, stored little-endian.  `ext imm13` prefixes the
next instruction and widens its immediate: one ext gives imm19, two give
imm32, each shifting what came before up by 13.
"""
import struct

REG = [f'%r{i}' for i in range(16)]
SPECIAL = ['%psr', '%sp', '%alr', '%ahr', '%lco', '%lsa', '%lea', '%sor',
           '%ttbr', '%dp', '%usp', '%ssp', '%pc', '%s13', '%s14', '%s15']

# opcode (bits 15-8) -> (mnemonic, operand shape).  Shapes:
#   rs_rd   [7:4]=rs [3:0]=rd        rb_rd   [7:4]=base [3:0]=dest
#   rb_rs   [7:4]=base [3:0]=source  imm4_rd [7:4]=imm4 [3:0]=rd
#   rb_imm3 [7:4]=base [2:0]=imm3    rb      [7:4]=reg
_BYTE = {
    0x20: ('ld.b', 'ld_rb_rd'), 0x21: ('ld.b', 'ld_rbp_rd'),
    0x24: ('ld.ub', 'ld_rb_rd'), 0x25: ('ld.ub', 'ld_rbp_rd'),
    0x28: ('ld.h', 'ld_rb_rd'), 0x29: ('ld.h', 'ld_rbp_rd'),
    0x2C: ('ld.uh', 'ld_rb_rd'), 0x2D: ('ld.uh', 'ld_rbp_rd'),
    0x30: ('ld.w', 'ld_rb_rd'), 0x31: ('ld.w', 'ld_rbp_rd'),
    0x34: ('ld.b', 'st_rb_rs'), 0x35: ('ld.b', 'st_rbp_rs'),
    0x38: ('ld.h', 'st_rb_rs'), 0x39: ('ld.h', 'st_rbp_rs'),
    0x3C: ('ld.w', 'st_rb_rs'), 0x3D: ('ld.w', 'st_rbp_rs'),
    0x22: ('add', 'rs_rd'), 0x26: ('sub', 'rs_rd'), 0x2A: ('cmp', 'rs_rd'),
    0x2E: ('ld.w', 'rs_rd'),
    0x32: ('and', 'rs_rd'), 0x36: ('or', 'rs_rd'), 0x3A: ('xor', 'rs_rd'),
    0x3E: ('not', 'rs_rd'),
    0xA1: ('ld.b', 'rs_rd'), 0xA5: ('ld.ub', 'rs_rd'), 0x99: ('ld.h', 'rs_rd'),
    0xAD: ('ld.uh', 'rs_rd'),
    0xA0: ('ld.w', 'rs_sd'), 0xA4: ('ld.w', 'ss_rd'),
    0xB8: ('adc', 'rs_rd'), 0xBC: ('sbc', 'rs_rd'),
    0xA2: ('mlt.h', 'rs_rd'), 0xA6: ('mltu.h', 'rs_rd'),
    0xAA: ('mlt.w', 'rs_rd'), 0xAE: ('mltu.w', 'rs_rd'),
    0x8B: ('div0s', 'rs'), 0x8F: ('div0u', 'rs'), 0x93: ('div1', 'rs'),
    0x97: ('div2s', 'rs'), 0xB2: ('mac', 'rs'),
    0x88: ('srl', 'imm4_rd'), 0x89: ('srl', 'rs_rd'),
    0x8C: ('sll', 'imm4_rd'), 0x8D: ('sll', 'rs_rd'),
    0x90: ('sra', 'imm4_rd'), 0x91: ('sra', 'rs_rd'),
    0x94: ('sla', 'imm4_rd'), 0x95: ('sla', 'rs_rd'),
    0x98: ('rr', 'imm4_rd'), 0x99_1: (None, None),
    0x9C: ('rl', 'imm4_rd'), 0x9D: ('rl', 'rs_rd'),
    0xA8: ('btst', 'rb_imm3'), 0xAC: ('bclr', 'rb_imm3'),
    0xB0: ('bset', 'rb_imm3'), 0xB4: ('bnot', 'rb_imm3'),
    0x8A: ('scan0', 'rs_rd'), 0x8E: ('scan1', 'rs_rd'),
    0x92: ('swap', 'rs_rd'), 0x96: ('mirror', 'rs_rd'),
}
# `rr %rd,%rs` collides with ld.h in the byte map above; the manual gives
# ld.h %rd,%rs as 100'1001 (0x99) and rr %rd,%rs as 1001'1001, the same
# eight bits.  ld.h is by far the commoner of the two in real code.
_BYTE.pop(0x99_1, None)

# opcode (bits 15-10) -> (mnemonic, shape) for the imm6 forms
_SIX = {
    0x10: ('ld.b', 'sp_rd'), 0x11: ('ld.ub', 'sp_rd'),
    0x12: ('ld.h', 'sp_rd'), 0x13: ('ld.uh', 'sp_rd'),
    0x14: ('ld.w', 'sp_rd'), 0x15: ('ld.b', 'sp_rs'),
    0x16: ('ld.h', 'sp_rs'), 0x17: ('ld.w', 'sp_rs'),
    0x18: ('add', 'imm6'), 0x19: ('sub', 'imm6'), 0x1A: ('cmp', 'sign6'),
    0x1B: ('ld.w', 'sign6'),
    0x1C: ('and', 'sign6'), 0x1D: ('or', 'sign6'), 0x1E: ('xor', 'sign6'),
    0x1F: ('not', 'sign6'),
    0x20: ('add', 'sp_imm10'), 0x21: ('sub', 'sp_imm10'),
}
# keyed by bits 15-9; bit 8 is the delayed-slot flag
_BRANCH = {0x04: 'jrgt', 0x05: 'jrge', 0x06: 'jrlt', 0x07: 'jrle',
           0x08: 'jrugt', 0x09: 'jruge', 0x0A: 'jrult', 0x0B: 'jrule',
           0x0C: 'jreq', 0x0D: 'jrne', 0x0E: 'call', 0x0F: 'jp'}


def _sign(v, bits):
    return v - (1 << bits) if v & (1 << (bits - 1)) else v


class Insn:
    __slots__ = ('offset', 'size', 'text', 'words')

    def __init__(self, offset, size, text, words):
        self.offset, self.size, self.text, self.words = offset, size, text, words

    def __repr__(self):
        return f'{self.offset:06X}  {self.text}'


def _one(w, ext, next_is_delay=False):
    """Decode one 16-bit word.  `ext` is the accumulated ext value or None."""
    hi8, hi6 = w >> 8, w >> 10
    rs, rd = (w >> 4) & 0xF, w & 0xF
    imm6, imm4 = (w >> 4) & 0x3F, (w >> 4) & 0xF

    def wide(base, bits):
        """imm6/sign8 widened by the ext prefixes that came before."""
        if ext is None:
            return base
        return (ext << bits) | (base & ((1 << bits) - 1))

    if hi6 == 0x30 or (w >> 13) == 0b110:
        return 'ext', f'ext 0x{w & 0x1FFF:x}'

    if (hi8 >> 1) in _BRANCH:
        name = _BRANCH[hi8 >> 1]
        d = '.d' if (hi8 & 1) else ''
        # the operand is the raw displacement field, the way the manual and
        # an assembler write it; multiply by two for a byte offset
        disp = _sign(w & 0xFF, 8) if ext is None else wide(w & 0xFF, 8)
        return 'branch', f'{name}{d} 0x{disp & 0xFFFFFFFF:x}'

    if hi6 in _SIX:
        name, shape = _SIX[hi6]
        if shape == 'sp_rd':
            return 'ok', f'{name} {REG[rd]},[%sp+0x{wide(imm6, 6):x}]'
        if shape == 'sp_rs':
            return 'ok', f'{name} [%sp+0x{wide(imm6, 6):x}],{REG[rd]}'
        if shape == 'sp_imm10':
            return 'ok', f'{name} %sp,0x{(w & 0x3FF) << 2:x}'
        val = wide(imm6, 6) if ext is not None else (
            _sign(imm6, 6) if shape == 'sign6' else imm6)
        pre = 'x' if ext is not None else ''
        return 'ok', f'{pre}{name} {REG[rd]},0x{val & 0xFFFFFFFF:x}'

    if hi8 in _BYTE:
        name, shape = _BYTE[hi8]
        off = f'+0x{ext << 0:x}' if ext is not None else ''
        if shape == 'rs_rd':
            return 'ok', f'{name} {REG[rd]},{REG[rs]}'
        if shape == 'rs_sd':
            return 'ok', f'{name} {SPECIAL[rd]},{REG[rs]}'
        if shape == 'ss_rd':
            return 'ok', f'{name} {REG[rd]},{SPECIAL[rs]}'
        if shape == 'ld_rb_rd':
            return 'ok', f'{name} {REG[rd]},[{REG[rs]}{off}]'
        if shape == 'ld_rbp_rd':
            return 'ok', f'{name} {REG[rd]},[{REG[rs]}]+'
        if shape == 'st_rb_rs':
            return 'ok', f'{name} [{REG[rs]}{off}],{REG[rd]}'
        if shape == 'st_rbp_rs':
            return 'ok', f'{name} [{REG[rs]}]+,{REG[rd]}'
        if shape == 'imm4_rd':
            return 'ok', f'{name} {REG[rd]},0x{imm4:x}'
        if shape == 'rb_imm3':
            return 'ok', f'{name} [{REG[rs]}],0x{w & 7:x}'
        if shape == 'rs':
            return 'ok', f'{name} {REG[rs]}'

    fixed = {0x0000: 'nop', 0x0080: 'halt', 0x0040: 'slp',
             0x0400: 'brk', 0x0440: 'retd', 0x04C0: 'reti',
             0x9B00: 'div3s'}
    if w in fixed:
        return 'ok', fixed[w]
    if hi8 in (0x06, 0x07):
        sub, d = (w >> 4) & 0xF, '.d' if (hi8 & 1) else ''
        if sub == 0 and (w & 0xF) == 0 and hi8 == 0x06:
            return 'ok', f'ret{d}'
        if sub == 0:
            return 'ok', f'call{d} {REG[w & 0xF]}'
        if sub == 8:
            return 'ok', f'jp{d} {REG[w & 0xF]}'
        if sub == 4:
            return 'ok', f'ret{d}'
    if hi8 == 0x02:
        return 'ok', (f'pushn {REG[w & 0xF]}' if (w >> 4) & 0xF == 0
                      else f'popn {REG[w & 0xF]}')
    return 'bad', f'.word 0x{w:04x}'


def disasm(raw, start=0, end=None, base=0):
    """Decode a byte range into Insn objects.

    `base` is the address the range is loaded at, used only for printing."""
    end = len(raw) if end is None else end
    out, o = [], start
    while o + 2 <= end:
        ext, words, first = None, [], o
        while True:
            if o + 2 > end:
                # ran off the end mid-prefix: the exts were data after all
                for k, w in enumerate(words):
                    out.append(Insn(base + first + 2 * k, 2,
                                    f'.word 0x{w:04x}', (w,)))
                return out
            w = struct.unpack_from('<H', raw, o)[0]
            words.append(w)
            o += 2
            kind, text = _one(w, ext)
            if kind != 'ext':
                out.append(Insn(base + first, o - first, text, tuple(words)))
                break
            ext = (w & 0x1FFF) if ext is None else ((ext << 13) | (w & 0x1FFF))
            if len(words) <= 2:        # at most two ext prefixes
                continue
            # three ext words in a row is not a real instruction
            out.append(Insn(base + first, 2, f'.word 0x{words[0]:04x}',
                            (words[0],)))
            o = first + 2
            break
    return out


def text(raw, start=0, end=None, base=0):
    lines = []
    for ins in disasm(raw, start, end, base):
        enc = ' '.join(f'{w:04x}' for w in ins.words)
        lines.append(f'{ins.offset:06X}  {enc:<14} {ins.text}')
    return '\n'.join(lines)
