"""Hand-laid sprite drafts (rewrites entries of tama4u/sprites-ps-ko.json).

    python3 tools/sprite_fix.py P045 P014

Each job edits the current draft (or the ROM original when there is none).
"""
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from tama4u.hangul import BdfFont

ROM = open(os.path.expanduser('~/Downloads/TMGC_PS.BIN'), 'rb').read()
G = os.path.expanduser('~/Downloads/galmuri')
JS = os.path.join(os.path.dirname(__file__), '..', 'tama4u', 'sprites-ps-ko.json')


class Spr:
    def __init__(s, pid, a, patches):
        s.a = a; s.w, s.h, s.nc, _, s.n, _ = ROM[a:a + 6]
        off = a + 6 + 2 * s.nc
        raw = bytes.fromhex(patches[pid]['pixels']) if pid in patches else ROM[off:off + s.n * s.w * s.h // 2]
        per = s.w * s.h // 2
        s.f = [[[(raw[k * per + (y * s.w + x) // 2] >> 4) if x & 1 else raw[k * per + (y * s.w + x) // 2] & 15
                 for x in range(s.w)] for y in range(s.h)] for k in range(s.n)]

    def pixels(s):
        return b''.join(bytes(r[x] | r[x + 1] << 4 for x in range(0, s.w, 2)) for f in s.f for r in f).hex()

    def put(s, pts, ox, oy, c, k=0):
        for x, y in pts:
            if 0 <= ox + x < s.w and 0 <= oy + y < s.h:
                s.f[k][oy + y][ox + x] = c


def glyph(font, ch, emb=False):
    """(w, h, by, pixels) of one BDF glyph; emb: +1px to the right."""
    g = font.g[ord(ch)]; bw, bh, bx, by = g['bbx']
    pts = {(x, r) for r, (bits, nb) in enumerate(g['rows']) for x in range(bw) if bits >> (nb - 1 - x) & 1}
    if emb:
        pts |= {(x + 1, y) for x, y in pts}; bw += 1
    return bw, bh, by, pts


def shrink(w, h, pts):
    """One pixel smaller each way: drop a repeated (else emptiest) row and column."""
    def drop(n, line):
        same = [i for i in range(1, n) if line(i) == line(i - 1)]
        if same:
            return min(same, key=lambda i: abs(i - n / 2))
        return min(range(n), key=lambda i: (len(line(i)), abs(i - n / 2)))
    r = drop(h, lambda i: {x for x, y in pts if y == i})
    pts = {(x, y - (y > r)) for x, y in pts if y != r}
    c = drop(w, lambda i: {y for x, y in pts if x == i})
    pts = {(x - (x > c), y) for x, y in pts if x != c}
    return w - 1, h - 1, pts


def text(font, s_, gap=1, emb=False):
    """Baseline-aligned run: (width, height, pixels)."""
    gl = [(6, 0, 0, set()) if ch == ' ' else glyph(font, ch, emb) for ch in s_]
    asc = max(bh + by for bw, bh, by, p in gl)
    pts, x = set(), 0
    for bw, bh, by, p in gl:
        top = asc - by - bh
        pts |= {(x + px, top + py) for px, py in p}; x += bw + gap
    return x - gap, max(y for _, y in pts) + 1, pts


def ring(pts):
    return {(x + dx, y + dy) for x, y in pts for dx in (-1, 0, 1) for dy in (-1, 0, 1)} - pts


def rows_with(f, c, x0, y0, x1, y1):
    return [y for y in range(y0, y1) if any(f[y][x] == c for x in range(x0, x1))]


def bands(rows):
    out = []
    for y in rows:
        if out and y == out[-1][1] + 1: out[-1][1] = y
        else: out.append([y, y])
    return out


def orig_frame(a):
    w, h, nc = ROM[a], ROM[a + 1], ROM[a + 2]; off = a + 6 + 2 * nc
    return [[(ROM[off + (y * w + x) // 2] >> 4) if x & 1 else ROM[off + (y * w + x) // 2] & 15
             for x in range(w)] for y in range(h)]


def recentre_line(s, txt, area, navy=5, bg=1):
    """Replace the Korean in `area` by one line `txt`, centred on the
    original (Japanese) text block of that area."""
    x0, y0, x1, y1 = area; f = s.f[0]; o = orig_frame(s.a)
    ys = rows_with(o, navy, x0, y0, x1, y1)
    xs = [x for y in ys for x in range(x0, x1) if o[y][x] == navy]
    cy, cx = (ys[0] + ys[-1] + 1) / 2, (min(xs) + max(xs) + 1) / 2
    for y in range(y0, y1):
        for x in range(x0, x1):
            if f[y][x] == navy: f[y][x] = bg
    FB = BdfFont(f'{G}/Galmuri11-Bold.bdf')
    w, h, pts = text(FB, txt)
    s.put(pts, round(cx - w / 2), round(cy - h / 2), navy)


def p045(s):
    """Tamatomo count screen.  The firmware draws the count ("00") at x 3..19,
    y 50..62 of this picture, so 타마토모 (Galmuri11-Bold, 1px smaller) has to end
    above it and 인 (Galmuri9 bold, 1px smaller) sits under it where 人 stood.
    The rainbow column ♥드림-타운♥의 (Galmuri7, 1px smaller, 5x4 hearts)
    spans the same rows as 타마토모."""
    FB, F9, F7 = (BdfFont(f'{G}/Galmuri{n}.bdf') for n in ('11-Bold', '9', '7'))
    f = s.f[0]
    for y in range(s.h):
        for x in range(25): f[y][x] = 1
    heart = {(1, 0), (3, 0), (0, 1), (1, 1), (2, 1), (3, 1), (4, 1), (1, 2), (2, 2), (3, 2), (2, 3)}
    y = 2
    for ch in '타마토모':
        bw, bh, by, pts = glyph(FB, ch)
        w, h, pts = shrink(bw, bh, pts)
        s.put(pts, 8 - w // 2, y, 2); y += h + 1
    bottom = y - 2                                     # last row of 모
    items = []
    for ch in '♥드림-타운♥의':
        if ch == '♥': items.append((5, 4, heart))
        elif ch == '-': items.append((1, 3, {(0, 0), (0, 1), (0, 2)}))
        else:
            bw, bh, by, pts = glyph(F7, ch); items.append(shrink(bw, bh, pts))
    n = len(items) - 1                                 # spare rows spread over the gaps
    spare = bottom - 2 + 1 - sum(h for w, h, p in items)
    gaps = [spare * (i + 1) // n - spare * i // n for i in range(n)] + [0]
    y = 2
    for (w, h, pts), c, g in zip(items, [3, 5, 6, 7, 4, 8, 9, 2], gaps):
        s.put(pts, 19 - w // 2, y, c); y += h + g
    bw, bh, by, pts = glyph(F9, '인', emb=True)
    w, h, pts = shrink(bw, bh, pts)
    s.put(pts, 12 - w // 2, 71 - h, 2)                 # where 人 stood (x 7..16, y 64..70)


def p014(s):
    """Logo kana -> 다마고치 in the menu's own regular glyphs and 12px cells,
    so it lines up with the 다마고치 iDL line under it (sprite x0 = menu text x - 0)."""
    FR = BdfFont(f'{G}/Galmuri11.bdf')
    f = s.f[0]
    for y in range(s.h):
        for x in range(60): f[y][x] = 0
    for i, ch in enumerate('다마고치'):
        bw, bh, bx, by = FR.g[ord(ch)]['bbx']
        pts = glyph(FR, ch)[3]
        s.put(pts, 12 * i + max(0, bx) + 1, 12 - by - bh + 1, 1)


def p034(s):
    """링크중…: one line, centred between the two original lines."""
    recentre_line(s, '링크중…', (4, 4, 124, 39))


def p035(s):
    recentre_line(s, '링크 실패', (4, 4, 124, 39))


def p040(s):
    """Lines left-aligned on the leftmost one."""
    f = s.f[0]; navy, bg = 5, 1
    bs = [b for b in bands(rows_with(f, navy, 4, 4, 124, 68))]
    lefts = [min(x for y in range(b0, b1 + 1) for x in range(4, 124) if f[y][x] == navy) for b0, b1 in bs]
    L = min(lefts)
    for (b0, b1), lx in zip(bs, lefts):
        d = lx - L
        for y in range(b0, b1 + 1):
            row = f[y]
            for x in range(4, 124):
                if row[x] == navy:
                    row[x] = bg
                    row[x - d] = navy


def p054(s):
    """Text + sweat drop centred as one group."""
    f = s.f[0]
    xs = [x for row in f for x, c in enumerate(row) if c]
    d = (min(xs) + (s.w - 1 - max(xs))) // 2 - min(xs)
    for row in f:
        old = row[:]
        for x in range(s.w):
            row[x] = old[x - d] if 0 <= x - d < s.w else 0


def outlined(s, txt, box, fill, edge, clear, font_gap=1):
    """Erase colours `clear` in box, draw txt (Galmuri11-Bold) in `fill` with a
    1px `edge` outline, centred on the box."""
    x0, y0, x1, y1 = box; f = s.f[0]
    for y in range(y0, y1):
        for x in range(x0, x1):
            if f[y][x] in clear: f[y][x] = 0
    FB = BdfFont(f'{G}/Galmuri11-Bold.bdf')
    w, h, pts = text(FB, txt, font_gap)
    if w > x1 - x0 - 2:
        w, h, pts = text(FB, txt, 0)
    ox, oy = round((x0 + x1) / 2 - w / 2), round((y0 + y1) / 2 - h / 2)
    s.put(ring(pts), ox, oy, edge); s.put(pts, ox, oy, fill)
    return w


def p051(s):
    """すたーと!! (red, white edge) -> 스타-트!!"""
    print('  P051 width', outlined(s, '스타-트!!', (17, 10, 80, 26), 4, 3, (3, 4)))


def p052(s):
    """よぉーい… (purple, white edge) -> 준-비…"""
    print('  P052 width', outlined(s, '준-비…', (2, 0, 64, 14), 2, 1, (1, 2)))


def p053(s):
    """おめでとう (white on the red streamer, vertical) -> 축하해요! ; each glyph
    centred on the streamer's red span at its own rows (the streamer slants)."""
    f = s.f[0]; red, white = 7, 9
    for y in range(4, 70):
        for x in range(48, 82):
            if f[y][x] == white: f[y][x] = red
    FB = BdfFont(f'{G}/Galmuri11-Bold.bdf')
    gl = [glyph(FB, ch) for ch in '축하해요!']
    tot = sum(g[1] for g in gl) + (len(gl) - 1) * 1
    y = 6 + (61 - tot) // 2
    for bw, bh, by, pts in gl:
        mid = y + bh // 2
        span = [x for x in range(40, 90) if f[mid][x] == red]
        cx = (min(span) + max(span) + 1) / 2
        s.put(pts, round(cx - bw / 2), y, white); y += bh + 1


JOBS = {'P045': (0x18E3A8, p045), 'P014': (0x163764, p014), 'P034': (0x180654, p034),
        'P035': (0x18186C, p035), 'P040': (0x189724, p040), 'P054': (0x1C0678, p054),
        'P051': (0x1BE2D0, p051), 'P052': (0x1BEEC8, p052), 'P053': (0x1BF450, p053)}

if __name__ == '__main__':
    patches = json.load(open(JS))
    for pid in sys.argv[1:]:
        a, fn = JOBS[pid]
        s = Spr(pid, a, patches); fn(s)
        patches[pid] = dict(addr=f'0x{a:06X}', pixels=s.pixels())
        print(pid, 'redrawn')
    json.dump(patches, open(JS, 'w'), indent=0, sort_keys=True)
