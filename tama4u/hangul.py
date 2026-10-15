"""Korean (Hangul) patch for the P's firmware.

Glyphs: Galmuri11 / Galmuri9 (SIL OFL, BDF from the `galmuri` npm package) at
the kana pitch -- 12x14 cells, 10x9 small -- or Tamagotchi Some's own font.

Some (the Korean Meets, ARM, load base 0x20000000) stores its font in the
same loose-sprite codec as the colour family: 14x14 and 10x10 two-colour
strips.  A range table maps its 2-byte big-endian codes (EUC-KR for the
2,350 KS X 1001 syllables) to (strip pair, frame).

The P's text engine is one byte per character (0x00 ends, 0xFF breaks a
line) with no spare room for 2,350 syllables, so Hangul goes in as two
bytes: a lead from the codes the glyph lookup never uses (0xC7-0xCF,
0xD9-0xDF) and a trail 0x01-0xFE minus 0xD0-0xD7 -- an unpatched P's shows
a received Hangul name byte by byte, and 0xD0-0xD8 go to its 8-colour icon
strip (0xD8 an empty frame, same palette), which repaints the speech bubble.
245 glyphs per lead.  Existing kana/Latin/symbol codes are
untouched, so Japanese names and downloads keep working.

Patched (P's, CPU addresses; file offset = addr - 0x02000000):
  0x2401D02  putstr's glyph call -> KGLYPH (2-byte aware, else original)
  0x2401D2C  putstr's advance    -> KADV (Hangul pitch per font, skips trail)
The character limit putstr/drawstr take stays a character count (a syllable
is one): menus pass 8 and would cut Hangul at four if it spent two.  The
5-byte user name is followed by 0x130C, never written (0), which ends it.
  0x2401DBC  drawstr's centring  -> KCENT (pixel width, not strlen bytes)
Everything new lives in SAFE: 0xFF padding after the firmware image segments
that the data reset never erases (0x2D0000-0x37FFFF and 0x570000- are save
and download storage; an early prototype sat there and got wiped).  Pointer
table at 0x55CA00, code after it, strips packed into whatever fits.
"""
import struct

BASE = 0x02000000
LEADS = list(range(0xC7, 0xD0)) + list(range(0xD9, 0xE0))
PER = 245                  # glyphs per lead: trails 0x01-0xFE without 0xD0-0xD8
GAP = 9
KS = [(h << 8 | l) for h in range(0xB0, 0xC9) for l in range(0xA1, 0xFF)]
# Some's standalone jamo at 0xB001-0xB033, in its font order; shown while a
# syllable is being composed on the name screen.  Appended after KS so the
# syllable codes stay put.
CHO = 'ㄱㄴㄷㄹㅁㅂㅅㅇㅈㅊㅋㅌㅍㅎㄲㄸㅃㅆㅉ'
JUNG = 'ㅏㅑㅓㅕㅗㅛㅜㅠㅡㅣㅐㅒㅔㅖㅘㅙㅚㅝㅞㅟㅢ'
JAMO = CHO + JUNG + 'ㄳㄵㄶㄺㄻㄼㄽㄾㄿㅀㅄ'
GLYPHS = KS + [0xB001 + i for i in range(len(JAMO))] + [0, 0, 1]  # empty x2, cursor '_'
# The empty cell doubles as the Hangul space: putstr/drawstr advance it half
# a pitch (the firmware's own space 0x6C is a full kana cell).  UI text only;
# the name screen never enters it, so it is never sent over the link.
HALF = len(KS) + len(JAMO)
FULLB = HALF + 1           # full-pitch blank: an empty profile slot mid-text
CURSOR = HALF + 2          # '_': the idle empty slot blinks with it (profile editor)
# putstr calls of the profile/message page routine's common tail and of the
# message editor's line routine (call.d: its delay slot stays) -> KSUFX
KSUFX_AT = {0x0252810C: 'f8dfcdd6cf1c', 0x025260CE: 'f8dfddd6ee1d'}
SAFE = [(0x2AE600, 0x2D0000), (0x3DD800, 0x400000), (0x55CA00, 0x570000)]
TBL_AT, CODE_AT = 0x55CA00, 0x55CA80
GALMURI = '~/Downloads/galmuri'

# glyph weight per model (user's call): bold on P's/iD/iDL, thin on 4U
BOLD = {'ps': True, 'id': True, 'idl': True, '4u': False}


class SomeFont:
    PTRS, RANGES, SOME_BASE = 0x5427E0, 0x542D08, 0x20000000

    def __init__(self, data):
        self.d = data
        self.ent = [struct.unpack_from('<II', data, self.PTRS + 8 * k) for k in range(165)]
        self.rng, k = [], 0
        while True:
            s, e, bl, ix = struct.unpack_from('>HHBB', data, self.RANGES + 6 * k)
            if s > e or (self.rng and s < self.rng[-1][0]):
                break
            self.rng.append((s, e, bl, ix)); k += 1

    def glyph(self, code, big=True):
        """(w, h, 4bpp pixels) for a Some code, or None."""
        for s, e, bl, ix in self.rng:
            if s <= code <= e:
                if ix == 0xFF:
                    return None
                a = self.ent[ix][1 if big else 0] - self.SOME_BASE
                w, h, nc, _, n = self.d[a:a + 5]
                f, sz = (code & 0xFF) - bl, (w * h + 1) // 2
                if not 0 <= f < n:
                    return None
                p = a + 6 + 2 * nc + f * sz
                return w, h, self.d[p:p + sz]
        return None


def embolden(w, h, g):
    """Widen strokes one pixel to the right (Some ink is 13px, cell 14)."""
    px = [(g[i // 2] >> (4 * (i % 2))) & 15 for i in range(w * h)]
    out = px[:]
    for y in range(h):
        for x in range(1, w):
            if px[y * w + x - 1] and not out[y * w + x]:
                out[y * w + x] = px[y * w + x - 1]
    return bytes(out[i] | out[i + 1] << 4 for i in range(0, w * h, 2))


def code(g):
    """Glyph number (index into GLYPHS) -> P's 2-byte code."""
    t = g % PER + 1
    return bytes([LEADS[g // PER], t + GAP if t >= 0xD0 else t])


class BdfFont:
    """Just the BDF bits the glyphs need: bbx, offsets, bitmap rows."""

    def __init__(self, path):
        import os
        self.g, cur = {}, None
        for line in open(os.path.expanduser(path), encoding='utf-8'):
            p = line.split()
            if not p:
                continue
            if p[0] == 'ENCODING':
                cur = {'rows': None}; enc = int(p[1])
            elif cur is None:
                continue
            elif p[0] == 'BBX':
                cur['bbx'] = tuple(map(int, p[1:5]))
            elif p[0] == 'BITMAP':
                cur['rows'] = []
            elif p[0] == 'ENDCHAR':
                self.g[enc] = cur; cur = None
            elif cur['rows'] is not None:
                cur['rows'].append((int(p[0], 16), len(p[0]) * 4))

    def cell(self, ch, w, h, base):
        """4bpp cell w x h, glyph bottom on row `base` (the kana baseline).
        Hangul syllables keep Galmuri's own placement (flush left in the 12px
        advance): centring each one by its 10 or 11px box shifted the narrow
        ones a pixel right, so lines starting with them looked indented.
        Jamo and the cursor stay centred.  In the 12px cell Galmuri11 leaves
        the two right columns empty, so every syllable moves 1px right
        (HANGUL_SHIFT): centred, and still one placement for all."""
        px = bytearray(w * h)
        if ch:
            bw, bh, bx, by = self.g[ord(ch)]['bbx']
            top = base - by - bh + 1
            if '가' <= ch <= '힣':                       # one uniform shift, not per glyph
                bx = max(0, bx)
                bx += HANGUL_SHIFT.get(w, 0) if bx + bw + HANGUL_SHIFT.get(w, 0) <= w else 0
            else:
                bx = (w - bw) // 2
            for r, (bits, nb) in enumerate(self.g[ord(ch)]['rows']):
                for x in range(bw):
                    if bits >> (nb - 1 - x) & 1:
                        yy, xx = top + r, bx + x
                        assert 0 <= yy < h and 0 <= xx < w, (ch, yy, xx)
                        px[yy * w + xx] = 1
        return bytes(px[i] | px[i + 1] << 4 for i in range(0, w * h, 2))


def glyph_char(c):
    """GLYPHS entry -> the character it draws ('' for the empty cell)."""
    if not c:
        return ''
    if c == 1:
        return '_'
    if c >= 0xB0A1:
        return bytes([c >> 8, c & 0xFF]).decode('euc-kr')
    return JAMO[c - 0xB001]


def bold_map(chars):
    """Bold copies of the syllables `chars` in the free glyph numbers after
    GLYPHS (16 leads hold 16 * PER): {syllable: glyph number}."""
    m = {ch: len(GLYPHS) + i for i, ch in enumerate(sorted(set(chars)))}
    assert len(GLYPHS) + len(m) <= 16 * PER, f'{len(m)} bold syllables: no room'
    return m


TRIM = 3                   # Galmuri11's 12x14 cells never use their top 3 rows: stored
                           # 12x11, drawn 3px lower (KGLYPH/KADV, the name slots)


def _trim(g, w=12):
    assert not any(g[:w // 2 * TRIM]), 'a glyph uses the trimmed rows'
    return (w, 14 - TRIM, g[w // 2 * TRIM:])


def glyph_sets(font, some_rom=None, bold=True, galmuri=GALMURI, bold_chars=()):
    """(big, small, kw, kws): per-GLYPHS (w, h, 4bpp) lists and advances.
    small None = draw the big glyphs for small text too.  `bold_chars` get
    Galmuri11-Bold glyphs after GLYPHS (bold_map order; small text keeps
    Galmuri9)."""
    if font == 'some':
        f = SomeFont(some_rom)
        w0, h0, _ = f.glyph(KS[0])
        big = [f.glyph(c) if c > 1 else (w0, h0, bytes((w0 * h0 + 1) // 2)) for c in GLYPHS]
        if bold:
            big = [(w, h, embolden(w, h, g)) for w, h, g in big]
        return big, None, 14, 14
    name = {'galmuri11': 'Galmuri11', 'galmuri11-bold': 'Galmuri11-Bold'}[font]
    b, sm = BdfFont(f'{galmuri}/{name}.bdf'), BdfFont(f'{galmuri}/Galmuri9.bdf')
    big = [_trim(b.cell(glyph_char(c), 12, 14, 13)) for c in GLYPHS]
    small = [(10, 9, sm.cell(glyph_char(c), 10, 9, 8)) for c in GLYPHS]
    if bold_chars:
        bb = BdfFont(f'{galmuri}/Galmuri11-Bold.bdf')
        for ch in bold_map(bold_chars):                 # small text: KGLYPH draws the plain one
            big.append(_trim(bb.cell(ch, 12, 14, 13)))
    return big, small, 12, 10


def encode(text, charset):
    """Text -> P's bytes: Hangul as lead/trail, the rest via the 1-byte charset."""
    rev = {v: int(k, 16) for k, v in charset.items()}
    out = bytearray()
    for ch in text:
        if '가' <= ch <= '힣':
            out += code(KS.index(int.from_bytes(ch.encode('euc-kr'), 'big')))
        elif ch in JAMO:
            out += code(len(KS) + JAMO.index(ch))
        else:
            out.append(rev[ch])
    return bytes(out)


class _Asm:
    """Just enough S1C33 to write the two hooks; branches resolve in 2 passes."""
    def __init__(s, org):
        s.org, s.items, s.labels = org, [], {}

    def L(s, n): s.items.append(('L', n))
    def w(s, v): s.items.append(('w', v))
    def ext(s, v): s.w(0xC000 | (v & 0x1FFF))
    def br(s, op, tgt, x=False): s.items.append(('br', op, tgt, x))

    def li(s, rd, v):                                   # xld.w rd,imm32
        s.ext(v >> 19); s.ext(v >> 6); s.w(0x6C00 | (v & 0x3F) << 4 | rd)

    def build(s):
        for last in (False, True):
            pc, out = s.org, []
            for it in s.items:
                if it[0] == 'L':
                    s.labels[it[1]] = pc; continue
                if it[0] == 'w':
                    out.append(it[1]); pc += 2; continue
                _, op, tgt, x = it
                t = s.labels.get(tgt, 0) if isinstance(tgt, str) else tgt
                if x:
                    d = (t - (pc + 2)) // 2
                    assert not last or -(1 << 20) <= d < (1 << 20)
                    out += [0xC000 | (d >> 8) & 0x1FFF, op << 8 | d & 0xFF]; pc += 4
                else:
                    d = (t - pc) // 2
                    assert not last or -128 <= d < 128, tgt
                    out.append(op << 8 | d & 0xFF); pc += 2
        return b''.join(struct.pack('<H', v) for v in out)


JRULE, JRUGT, JREQ, JRNE, CALL, JP, RET = 0x16, 0x10, 0x18, 0x1A, 0x1C, 0x1E, 0x0640
JRGE, JRULT, JRUGE, JRLE = 0x0A, 0x14, 0x12, 0x0E
BLANK = 0x6C               # the firmware's full-cell space
HANGUL_SHIFT = {12: 1}     # big cell: syllables 1px right (see BdfFont.cell)
ldub_rb = lambda rd, rb: 0x2400 | rb << 4 | rd
ldub_rs = lambda rd, rs: 0xA500 | rs << 4 | rd
ldw_rs = lambda rd, rs: 0x2E00 | rs << 4 | rd
ldw_rb = lambda rd, rb: 0x3000 | rb << 4 | rd
lduh_rb = lambda rd, rb: 0x2C00 | rb << 4 | rd
add_i = lambda rd, i: 0x6000 | (i & 0x3F) << 4 | rd
sub_i = lambda rd, i: 0x6400 | (i & 0x3F) << 4 | rd
cmp_i = lambda rd, i: 0x6800 | (i & 0x3F) << 4 | rd
add_rs = lambda rd, rs: 0x2200 | rs << 4 | rd
sll_i = lambda rd, i: 0x8C00 | i << 4 | rd
sra_i = lambda rd, i: 0x9000 | i << 4 | rd
cmp_rs = lambda rd, rs: 0x2A00 | rs << 4 | rd
sub_rs = lambda rd, rs: 0x2600 | rs << 4 | rd
ld_i = lambda rd, i: 0x6C00 | (i & 0x3F) << 4 | rd


def _xadd3(a, rd, v):                                   # add rd,imm32
    a.ext(v >> 19); a.ext(v >> 6); a.w(add_i(rd, v & 0x3F))


def _xsub(a, rd, v):
    a.ext(v >> 6); a.w(sub_i(rd, v))


def _lead_test(a, reg, yes, no):
    """Hangul lead in `reg` -> r5 = lead index, branch to `yes`; else `no`."""
    a.w(ldw_rs(5, reg)); _xsub(a, 5, 0xC7); a.w(ldub_rs(5, 5)); a.w(cmp_i(5, 8)); a.br(JRULE, yes)
    a.w(ldw_rs(5, reg)); _xsub(a, 5, 0xD9); a.w(ldub_rs(5, 5)); a.w(cmp_i(5, 6))
    a.br(JRUGT, no); a.w(add_i(5, 9)); a.br(JP, yes)


def _half_test(a, ptr, off, tmp, no):
    """r5 = lead index; falls through iff the pair at [ptr] is code(HALF)."""
    lead, trail = code(HALF)
    a.w(cmp_i(5, LEADS.index(lead))); a.br(JRNE, no)
    a.w(ldw_rs(tmp, ptr)); a.w(add_i(tmp, off)); a.w(ldub_rb(tmp, tmp))
    a.ext(trail >> 6); a.w(cmp_i(tmp, trail & 0x3F)); a.br(JRNE, no)


def _hooks(kw=12, kws=10, bold_src=(), bold_at=0, trim=0, labels=None):
    """`bold_src`: per bold glyph (bold_map order) the glyph number of its
    plain syllable -- small text draws that (no small bold strips); its
    (lead index, trail index) bytes go at CPU address `bold_at`."""
    a = _Asm(BASE + CODE_AT)
    # KGLYPH(r6 obj, r7, r8 code, r9 small flag; r1 = putstr's string pointer)
    a.L('KGLYPH')
    a.w(ldub_rb(4, 1))
    _lead_test(a, 4, 'KG_K', 'KG_NO')
    a.L('KG_K')
    a.w(ldw_rs(4, 1)); a.w(add_i(4, 1)); a.w(ldub_rb(8, 4)); a.w(sub_i(8, 1))
    a.ext(0xCF + GAP >> 6); a.w(cmp_i(8, 0xCF + GAP & 0x3F)); a.br(JRULT, 'KG_T')  # trails past
    a.w(sub_i(8, GAP))                                  # the skipped 0xD0-0xD8
    a.L('KG_T')
    a.w(ldub_rs(9, 9))
    if bold_src:                                        # small bold -> the plain glyph
        a.w(cmp_i(9, 0)); a.br(JREQ, 'KG_S')
        a.w(ldw_rs(4, 5)); a.w(sll_i(4, 8))             # r4 = lead * 245 + trail
        for _ in range(256 - PER):
            a.w(sub_rs(4, 5))
        a.w(add_rs(4, 8))
        _xsub(a, 4, len(GLYPHS)); a.br(JRULT, 'KG_S')   # (borrow: a plain glyph)
        a.w(sll_i(4, 1)); _xadd3(a, 4, bold_at)
        a.w(ldub_rb(5, 4)); a.ext(1); a.w(ldub_rb(8, 4))
    a.L('KG_S')
    a.w(sll_i(5, 2)); a.li(4, BASE + TBL_AT); a.w(add_rs(5, 4))
    a.w(cmp_i(9, 0)); a.br(JRNE, 'KG_SM')
    if trim:                                            # highlighted (attr 0x2000, the
        a.w(ldw_rs(4, 6)); a.w(ldub_rs(4, 4)); a.w(sll_i(4, 4)); a.ext(0x1470 >> 6); a.w(add_i(4, 0x1470 & 0x3F))
        a.ext(0xC); a.w(lduh_rb(9, 4)); a.ext(0x2000 >> 6); a.w(0x7000 | 9)   # blink/selection box):
        a.w(cmp_i(9, 0)); a.br(JREQ, 'KG_NB')           # a full 12x14 empty cell at the
        a.br(JP, 'KG_HL', x=True)
        a.L('KG_NB')
    if trim:                                            # big: the object 3px lower --
        a.w(ldw_rb(9, 5)); a.w(ldub_rs(6, 6)); a.w(ldub_rs(7, 7))           # after the glyph
        a.br(CALL, 0x024019C6, x=True)                  # call, so the cell it replaces
        a.ext(6); a.w(lduh_rb(4, 0)); a.w(add_i(4, trim)); a.ext(6); a.w(0x3800 | 0 << 4 | 4)   # is cleared
        a.w(RET)                                        # where it was (r0 = putstr's object)
    a.br(JP, 'KG_BIG')
    a.L('KG_SM')
    a.ext(1); a.w(add_i(5, 0))                          # xadd r5,64 -> small strips
    a.L('KG_BIG')
    a.w(ldw_rb(9, 5)); a.w(ldub_rs(6, 6)); a.w(ldub_rs(7, 7))
    a.br(JP, 0x024019C6, x=True)
    a.L('KG_NO')
    a.br(JP, 0x02401BDC, x=True)
    if trim:
        a.L('KG_HL')
        # inverted like the kana: first the empty 12x14 cell at the object's
        # own y (it inverts to a full box) and that rect refreshed now, then
        # the syllable itself inverted 3px lower; KRECT then leaves the box's
        # top rows alone.  r0 = putstr's object, r1 = its string pointer.
        a.li(9, (labels or {}).get('KBLOCK', 0))
        a.w(ld_i(8, 0)); a.w(ldub_rs(6, 6)); a.w(ldub_rs(7, 7))
        a.br(CALL, 0x024019C6, x=True)
        a.ext(6); a.w(lduh_rb(6, 0)); a.w(ldw_rs(7, 6)); a.w(add_i(7, 14))
        a.ext(4); a.w(lduh_rb(8, 0)); a.w(ldw_rs(9, 8)); a.w(add_i(9, 12))
        a.li(4, 0x84C); a.w(0x0604)                     # call %r4: refresh rows/cols
        a.w(ldub_rb(4, 1)); _lead_test(a, 4, 'KH_L', 'KH_X')
        a.L('KH_X')
        a.w(RET)
        a.L('KH_L')
        a.w(ldw_rs(4, 1)); a.w(add_i(4, 1)); a.w(ldub_rb(8, 4)); a.w(sub_i(8, 1))
        a.ext(0xCF + GAP >> 6); a.w(cmp_i(8, 0xCF + GAP & 0x3F)); a.br(JRULT, 'KH_T')
        a.w(sub_i(8, GAP))
        a.L('KH_T')
        a.w(sll_i(5, 2)); a.li(4, BASE + TBL_AT); a.w(add_rs(5, 4)); a.w(ldw_rb(9, 5))
        a.w(ldw_rs(6, 0)); a.li(4, 0x1470); a.w(sub_rs(6, 4)); a.w(sra_i(6, 4))   # object id
        a.w(0x5000 | 3 << 4 | 7)                        # r7 = putstr's word 2
        a.br(CALL, 0x024019C6, x=True)
        a.ext(6); a.w(lduh_rb(4, 0)); a.w(add_i(4, trim)); a.ext(6); a.w(0x3800 | 0 << 4 | 4)
        a.w(RET)
    # KADV(r5 small flag, r1 ptr, r0 obj) -> r4 = next x; steps r1 over a trail
    a.L('KADV')
    a.w(ldw_rs(6, 5))
    a.w(ldub_rb(4, 1))
    _lead_test(a, 4, 'KA_K', 'KA_N')
    a.L('KA_N')
    a.w(cmp_i(6, 0)); a.br(JRNE, 'KA9')
    a.w(ldub_rb(4, 1)); _xsub(a, 4, 0x6D); a.w(ldub_rs(4, 4)); a.w(cmp_i(4, 9)); a.br(JRULE, 'KA9')
    a.ext(4); a.w(lduh_rb(4, 0)); a.w(add_i(4, 12)); a.w(RET)
    a.L('KA9')
    a.ext(4); a.w(lduh_rb(4, 0)); a.w(add_i(4, 9)); a.w(RET)
    a.L('KA_K')
    if trim:
        a.w(cmp_i(6, 0)); a.br(JRNE, 'KA_K2')
        a.ext(9); a.w(ldub_rb(4, 0)); a.w(cmp_i(4, 14 - trim)); a.br(JRNE, 'KA_K2')   # the full-height
        a.ext(6); a.w(lduh_rb(4, 0)); a.w(sub_i(4, trim)); a.ext(6); a.w(0x3800 | 0 << 4 | 4)   # box: y kept
        a.w(ld_i(4, 14)); a.ext(9); a.w(0x3400 | 0 << 4 | 4)                       # ld.b [r0+9],r4: box 14 high
        a.L('KA_K2')
    _half_test(a, 1, 1, 4, 'KA_F')
    a.w(add_i(1, 1)); a.ext(4); a.w(lduh_rb(4, 0))
    a.w(cmp_i(6, 0)); a.br(JRNE, 'KAH'); a.w(add_i(4, kw // 2)); a.w(RET)
    a.L('KAH')
    a.w(add_i(4, kws // 2)); a.w(RET)
    a.L('KA_F')
    a.w(add_i(1, 1)); a.ext(4); a.w(lduh_rb(4, 0))
    a.w(cmp_i(6, 0)); a.br(JRNE, 'KAS'); a.w(add_i(4, kw)); a.w(RET)
    a.L('KAS')
    a.w(add_i(4, kws)); a.w(RET)
    if trim:
        # KRECT (putstr 0x2401D06, after the glyph call): r6..r7 = the rows
        # to redraw, y..y+h -- a trimmed glyph (h = 14 - trim) sits trim
        # lower, so from y - trim: the whole 14-row cell, as before
        a.L('KRECT')
        a.ext(6); a.w(ldub_rb(6, 0)); a.ext(9); a.w(ldub_rb(4, 0))
        a.w(ldw_rs(7, 6)); a.w(add_rs(7, 4)); a.w(ldub_rs(7, 7))
        a.w(cmp_i(4, 14 - trim)); a.br(JRNE, 'KR_X')
        a.ext(0xC); a.w(lduh_rb(5, 0)); a.ext(0x2000 >> 6); a.w(0x7000 | 5)   # highlighted: the
        a.w(cmp_i(5, 0)); a.br(JRNE, 'KR_X')            # box's top rows stay as drawn
        a.w(sub_i(6, trim))
        a.L('KR_X')
        a.w(RET)
    # KCENT(r9 str, r0 max chars, r1 small) -> r6 = chars for putstr, r5 = x.
    # Non-Hangul keeps drawstr's own 12/9px per character, so old layouts hold.
    a.L('KCENT')
    a.w(ldw_rs(4, 9)); a.w(ld_i(6, 0)); a.w(ld_i(8, 0))
    a.L('KC_L')
    a.w(cmp_rs(6, 0)); a.br(JRUGE, 'KC_D')
    a.w(ldub_rb(7, 4)); a.w(cmp_i(7, 0)); a.br(JREQ, 'KC_D')
    a.ext(3); a.w(cmp_i(7, 0x3F)); a.br(JREQ, 'KC_D')     # xcmp r7,0xff
    _lead_test(a, 7, 'KC_K', 'KC_N')
    a.L('KC_N')
    a.w(add_i(4, 1)); a.w(cmp_i(1, 0)); a.br(JRNE, 'KC_N9')
    a.w(add_i(8, 12)); a.br(JP, 'KC_NX')
    a.L('KC_N9')
    a.w(add_i(8, 9)); a.br(JP, 'KC_NX')
    a.L('KC_K')
    _half_test(a, 4, 1, 7, 'KC_F')
    a.w(add_i(4, 2)); a.w(cmp_i(1, 0)); a.br(JRNE, 'KC_H9')
    a.w(add_i(8, kw // 2)); a.br(JP, 'KC_NX')
    a.L('KC_H9')
    a.w(add_i(8, kws // 2)); a.br(JP, 'KC_NX')
    a.L('KC_F')
    a.w(add_i(4, 2)); a.w(cmp_i(1, 0)); a.br(JRNE, 'KC_K9')
    a.w(add_i(8, kw)); a.br(JP, 'KC_NX')
    a.L('KC_K9')
    a.w(add_i(8, kws))
    a.L('KC_NX')
    a.w(add_i(6, 1)); a.br(JP, 'KC_L')
    a.L('KC_D')
    a.w(cmp_rs(6, 0)); a.br(JRULE, 'KC_C')
    a.w(ldw_rs(6, 0))                                   # clamp to the budget
    a.L('KC_C')
    a.ext(2); a.w(ld_i(5, 0))                           # xld.w r5,0x80
    a.w(sub_rs(5, 8)); a.w(cmp_i(5, 0)); a.br(JRGE, 'KC_P')
    a.w(add_i(5, 1))                                    # round toward zero
    a.L('KC_P')
    a.w(sra_i(5, 1)); a.w(RET)


    # KSUFX: putstr (same registers and stack words) on a copy of the string
    # (<= 8 bytes) in which a trailing name + へ reads name + 께 and name + より
    # reads ー + name + ー: the message rows keep the stored kana suffixes, which a
    # Japanese partner reads from the same record.
    glead, gtrail = code(KS.index(int.from_bytes('께'.encode('euc-kr'), 'big')))
    a.L('KSUFX')
    a.w(0x0203); a.w(0x8406)                            # pushn %r3; sub %sp,6
    for k in range(3):                                  # caller words 0-2 (now at 11-13)
        a.w(0x5000 | (11 + k) << 4 | 4); a.w(0x5C00 | k << 4 | 4)
    a.w(0x5000 | 0 << 4 | 0)                            # r0 = str
    a.w(0xA411); a.w(add_i(1, 12)); a.w(0x5C00 | 0 << 4 | 1)   # r1 = buffer (sp+12) -> word 0
    a.w(ld_i(2, 0))
    a.L('KS_C')                                         # copy up to 8 bytes / NUL
    a.w(ldw_rs(4, 0)); a.w(add_rs(4, 2)); a.w(ldub_rb(4, 4))
    a.w(ldw_rs(5, 1)); a.w(add_rs(5, 2)); a.w(0x3400 | 5 << 4 | 4)
    a.w(cmp_i(4, 0)); a.br(JREQ, 'KS_E')
    a.w(add_i(2, 1)); a.w(cmp_i(2, 8)); a.br(JRULT, 'KS_C')
    a.w(ld_i(4, 0)); a.w(ldw_rs(5, 1)); a.w(add_rs(5, 2)); a.w(0x3400 | 5 << 4 | 4)
    a.L('KS_E')                                         # r3 -> last ink; r2 = changed
    a.w(ldw_rs(3, 1)); a.w(add_rs(3, 2)); a.w(ld_i(2, 0))
    a.L('KS_B')
    a.w(cmp_rs(3, 1)); a.br(JREQ, 'KS_GO')
    a.w(sub_i(3, 1)); a.w(ldub_rb(4, 3)); a.ext(BLANK >> 6); a.w(cmp_i(4, BLANK & 0x3F)); a.br(JREQ, 'KS_B')
    a.w(cmp_rs(3, 1)); a.br(JREQ, 'KS_GO')              # one character: no name
    a.w(cmp_i(4, 0x1D)); a.br(JRNE, 'KS_Y')            # ...へ -> ...께 (room: up to index 6)
    a.w(ldw_rs(5, 1)); a.w(add_i(5, 6)); a.w(cmp_rs(3, 5)); a.br(JRUGT, 'KS_GO')
    a.ext(glead >> 6); a.w(ld_i(4, glead & 0x3F)); a.w(0x3400 | 3 << 4 | 4)
    a.ext(gtrail >> 6); a.w(ld_i(4, gtrail & 0x3F)); a.ext(1); a.w(0x3400 | 3 << 4 | 4)
    a.w(ld_i(4, 0)); a.ext(2); a.w(0x3400 | 3 << 4 | 4)
    a.w(ld_i(2, 1)); a.br(JP, 'KS_GO')
    a.L('KS_Y')
    a.ext(0); a.w(cmp_i(4, 0x28)); a.br(JRNE, 'KS_GO')           # ...より -> ー...
    a.w(ldw_rs(5, 3)); a.w(sub_i(5, 1)); a.w(ldub_rb(4, 5)); a.ext(0); a.w(cmp_i(4, 0x26)); a.br(JRNE, 'KS_GO')
    a.w(cmp_rs(5, 1)); a.br(JREQ, 'KS_GO')
    a.ext(0x51 >> 6); a.w(ld_i(4, 0x51 & 0x3F)); a.w(0x3400 | 3 << 4 | 4)   # り -> ー
    a.w(ld_i(4, 0)); a.ext(1); a.w(0x3400 | 3 << 4 | 4)                      # ... NUL
    a.L('KS_S')                                         # shift the name right over よ
    a.w(sub_i(5, 1)); a.w(ldub_rb(4, 5)); a.ext(1); a.w(0x3400 | 5 << 4 | 4)
    a.w(cmp_rs(5, 1)); a.br(JRNE, 'KS_S')
    a.ext(0x51 >> 6); a.w(ld_i(4, 0x51 & 0x3F)); a.w(0x3400 | 1 << 4 | 4)
    a.w(ld_i(2, 1))
    a.L('KS_GO')                                        # unchanged: the caller's own string
    a.w(cmp_i(2, 0)); a.br(JRNE, 'KS_CALL'); a.w(0x5C00 | 0 << 4 | 0)    # ld.w [sp+0],r0
    a.L('KS_CALL')
    a.br(CALL, 0x02401CAE, x=True)
    a.w(0x8006); a.w(0x0243); a.w(RET)                  # add %sp,6; popn %r3
    if trim:
        a.L('KBLOCK')                                   # 12x14 empty glyph (highlight box)
        blk = bytes([12, 14, 2, 0, 1, 0xFF]) + b'\x07\xe0\x60\x00' + bytes(12 * 14 // 2)
        for k in range(0, len(blk), 2):
            a.w(blk[k] | blk[k + 1] << 8)
    return a.build(), a.labels


def _record(gs):
    w, h, _ = gs[0]
    return bytes([w, h, 2, 0, len(gs), 0xFF]) + b'\x07\xe0\x60\x00' + b''.join(g for *_, g in gs)


def build_ps(ps_rom, some_rom=None, font='galmuri11', bold=True, strings=None,
             name_ui=False, galmuri=GALMURI, bold_chars=(), long_diary=True):
    """Patched P's image.  `strings` = {file offset: P's bytes} (hangul_text:
    in place when it fits, else moved to SAFE with its references).
    `font`: galmuri11 | galmuri11-bold | some (bold = Some glyphs widened).
    `name_ui` swaps the user-name screen for Hangul jamo entry (hangul_name)."""
    rom = bytearray(ps_rom)
    for lo, hi in SAFE:
        assert all(b == 0xFF for b in rom[lo:hi]), f'{lo:#x} not blank'
    big, small, kw, kws = glyph_sets(font, some_rom, bold, galmuri, bold_chars)

    bsrc = [GLYPHS.index(int.from_bytes(ch.encode('euc-kr'), 'big'))
            for ch in sorted(bold_map(bold_chars))] if bold_chars and small else []
    trim = TRIM if big[0][1] == 14 - TRIM else 0
    n = len(_hooks(kw, kws, bsrc, BASE, trim)[0]) if bsrc else 0
    bold_at = BASE + CODE_AT + (n + 1 & ~1)
    lab0 = _hooks(kw, kws, bsrc, bold_at, trim)[1]     # pass 1: KBLOCK's address
    code, lab = _hooks(kw, kws, bsrc, bold_at, trim, lab0)
    while lab != lab0:                                  # immediates grew: settle
        lab0 = lab
        code, lab = _hooks(kw, kws, bsrc, bold_at, trim, lab0)
    if bsrc:
        code += b'\0' * (bold_at - BASE - CODE_AT - len(code)) + bytes(b for g in bsrc for b in divmod(g, PER))
    blocks = [code]
    if name_ui:
        from . import hangul_name
        norg = BASE + CODE_AT + (len(code) + 3 & ~3)
        nb, nlab = hangul_name.assemble(norg, pitch=kw, trim=trim)
        blocks.append(b'\0' * (norg - BASE - CODE_AT - len(code)) + nb)
    long_diary = bool(strings) and long_diary
    if long_diary:                                      # long diary entries
        from . import hangul_diary
        dorg = BASE + CODE_AT + (len(b''.join(blocks)) + 3 & ~3)
        db, dlab, darray, dcells = hangul_diary.block(dorg)
        blocks.append(b'\0' * (dorg - BASE - CODE_AT - len(b''.join(blocks))) + db)
    fixed = b''.join(blocks)
    cursor = [lo for lo, _ in SAFE]
    cursor[2] = CODE_AT + len(fixed)

    # strips, biggest first, first fit; each record 4-aligned after 2 zero bytes
    recs = []
    for k in range(16):
        part = slice(k * PER, (k + 1) * PER)
        if big[part]:
            recs.append((k, _record(big[part])))
            if small and small[part]:                   # (bold-only leads: none, see KGLYPH)
                recs.append((16 + k, _record(small[part])))
    ptrs = [0] * 32
    for slot, rec in sorted(recs, key=lambda r: -len(r[1])):
        for i, (lo, hi) in enumerate(SAFE):
            p = (cursor[i] + 5) & ~3
            if p + len(rec) <= hi:
                rom[p - 2:p] = b'\0\0'; rom[p:p + len(rec)] = rec
                ptrs[slot] = BASE + p; cursor[i] = p + len(rec)
                break
        else:
            raise ValueError(f'no room for strip {slot} ({len(rec)} B)')
    if not small:
        ptrs[16:] = ptrs[:16]
    rom[TBL_AT:TBL_AT + 128] = struct.pack('<32I', *ptrs)
    rom[CODE_AT:CODE_AT + len(fixed)] = fixed

    h = _Asm(0x02401D02); h.br(CALL, lab['KGLYPH'], x=True)
    b = h.build(); rom[0x401D02:0x401D02 + len(b)] = b
    h = _Asm(0x02401D2C)
    h.w(0x5035)                                         # ld.w r5,[sp+0x3] (original)
    h.br(CALL, lab['KADV'], x=True); h.br(JP, 0x02401D4C)
    b = h.build()
    rom[0x401D2C:0x401D4C] = b.ljust(0x20, b'\0')
    if 'KRECT' in lab:
        assert rom[0x401D06:0x401D16] == bytes.fromhex('06c0062406c0072409c00424472277a5'), 'putstr rect'
        h = _Asm(0x02401D06); h.br(CALL, lab['KRECT'], x=True)
        rom[0x401D06:0x401D16] = h.build().ljust(0x10, b'\0')
    for at, old_b in KSUFX_AT.items():                  # message rows: へ/より read 께/ー
        assert rom[at - BASE:at - BASE + 6] == bytes.fromhex(old_b), hex(at)
        op = 0x1D if old_b[-2:] == '1d' else CALL       # call.d keeps its delay slot
        for pad in (0, 2):                              # end exactly at at+6
            h = _Asm(at + pad); h.br(op, lab['KSUFX'], x=True); b = h.build()
            if pad + len(b) == 6:
                break
        assert pad + len(b) == 6, hex(at)
        rom[at - BASE:at - BASE + 6] = b'\0' * pad + b
    h = _Asm(0x02401DBC); h.br(CALL, lab['KCENT'], x=True); h.br(JP, 0x02401DF0)
    b = h.build()
    rom[0x401DBC:0x401DF0] = b.ljust(0x34, b'\0')
    if name_ui:
        h = _Asm(0x025251BE); h.br(JP, nlab['KNAME'], x=True)
        b = h.build(); rom[0x5251BE:0x5251BE + len(b)] = b
        hangul_name.patch_bg(rom, kw)
        m = hangul_name.MSG_EDIT - BASE                 # message editor -> HMSG
        assert rom[m:m + 4] == bytes.fromhex('03020684'), 'message editor'
        h = _Asm(hangul_name.MSG_EDIT); h.br(JP, nlab['HMSG'], x=True)
        b = h.build(); rom[m:m + len(b)] = b
        for f in hangul_name.PROF_FIELDS:              # profile text fields -> HPROF
            struct.pack_into('<I', rom, hangul_name.PROF_TABLE + 4 * f, nlab['HPROF'])
        for off, old, new in hangul_name.PROF_DRAW:
            assert struct.unpack_from('<H', rom, off)[0] == old, hex(off)
            struct.pack_into('<H', rom, off, new)
        for off in hangul_name.PROF_NUL:               # 4 bytes: ext + call PNUL
            assert rom[off:off + 4] == b'\x50\xc0\xc4\x6f', hex(off)
            h = _Asm(BASE + off); h.br(CALL, nlab['PNUL'], x=True)
            rom[off:off + 4] = h.build()

    if strings:
        from . import hangul_text

        def alloc(n):
            for i, (lo, hi) in enumerate(SAFE):
                if cursor[i] + n <= hi:
                    cursor[i] += n
                    return cursor[i] - n
            raise ValueError(f'no room for {n} B of text')
        refs = hangul_text.scan_refs(ps_rom)
        if long_diary:
            hangul_diary.patch(rom, dlab, darray - BASE, dcells - BASE)
        hangul_text.apply(rom, strings, alloc, refs, diary=darray - BASE if long_diary else None)
        if long_diary:
            hangul_diary.words(rom, ps_rom, strings)
    return bytes(rom)


def carry_save(old_rom, old_save, new_rom, sector=0x1000):
    """tamaemu's save.sav is the whole 8MB flash (ROM included) and wins over
    the .bin, so a save copied to a new build runs the old build.  New image =
    new_rom with every sector the device rewrote (old_save != old_rom) taken
    from old_save; asserts none of those touches what the patch changed."""
    out = bytearray(new_rom)
    for i in range(0, len(out), sector):
        if old_save[i:i + sector] != old_rom[i:i + sector]:
            assert old_rom[i:i + sector] == new_rom[i:i + sector] or \
                any(lo <= i < hi for lo, hi in ((0, 0x50000), (0x2D0000, 0x380000), (0x570000, len(out)))), hex(i)
            out[i:i + sector] = old_save[i:i + sector]
    # items the device holds are record copies in flash: rename them as the ROM
    from . import hangul_text
    rom_items = {v: k for k, v in hangul_text.item_names(new_rom).items()}
    for off, iid in hangul_text.item_names(out, 0x570000, len(out)).items():
        src = rom_items.get(iid)
        if src is not None:
            out[off:off + hangul_text.ITEM_NAME_LEN] = new_rom[src:src + hangul_text.ITEM_NAME_LEN]
    return bytes(out)


def debug_menu(rom):
    """Show the download menu's 'debug set' (entry 5).  Its visibility case at
    0x24FFC92 hides it unless port 0x300380 bit 6 reads 0 (a test pad); jump
    to the ordinary 'shown' path instead ([0xE62] = 6, return 1)."""
    rom = bytearray(rom)
    assert rom[0x4FFC92:0x4FFC96] == b'\x03\x1f\x65\x6c'
    rom[0x4FFC92:0x4FFC94] = struct.pack('<H', 0x1F00 | (0x2FFC88 - 0x2FFC92) // 2 & 0xFF)
    return bytes(rom)


def all_jobs(rom):
    """Test builds: every part-time job open.  0x2413016(job) checks the
    job's counter (park/cafe >9 at 0x13A9/0x13AC, depa/shop >1 at 0x13AA/
    0x13AB) -> return 1; 0x2413118 then also wants stage >3 and two flags
    before the 'recruiting' line -> jump straight to it (0x2413190)."""
    rom = bytearray(rom)
    assert rom[0x413016:0x41301A] == b'\x66\xa5\x16\x68'
    assert rom[0x413130:0x413132] == b'\x44\xa5'
    rom[0x413016:0x41301A] = struct.pack('<2H', 0x6C14, 0x0640)          # ld.w r4,1; ret
    rom[0x413130:0x413132] = struct.pack('<H', 0x1E00 | (0x413190 - 0x413130) // 2)
    return bytes(rom)


def all_outings(rom):
    """Test builds: every outing destination open.  0x2415e3c(idx) gives a
    destination's menu state (-1 hidden, 2 '???????', 1 greyed, 0 open).
    Secret base / amusement park / beach / fountain / outlook are gated on
    0x24081f8 = how many of flags 0x1A-0x39 are set (>0, >3, >9, >14, >19)
    -> pretend all 31; Eco Town wants flag 0x15 -> pretend set.  Life-stage
    and opening-hour checks stay."""
    rom = bytearray(rom)
    assert rom[0x415E52:0x415E56] == b'\x91\xdf\xd2\x1c'                 # scall 0x24081f8
    assert rom[0x415F62:0x415F66] == b'\x8c\xdf\xab\x1d'                 # scall.d 0x24078ba
    rom[0x415E52:0x415E56] = struct.pack('<2H', 0x6DF4, 0)              # ld.w r4,31; nop
    rom[0x415F62:0x415F66] = struct.pack('<2H', 0x6C14, 0)              # ld.w r4,1; nop
    return bytes(rom)
