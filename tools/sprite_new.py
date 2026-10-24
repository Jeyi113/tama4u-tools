"""Drafts for the picture-text sprites added from the full sprite list
(P060..), written into tama4u/sprites-ps-ko.json.

    python3 tools/sprite_new.py            # all
    python3 tools/sprite_new.py P066 P067

Generic block: erase the text colours inside a box (each erased pixel takes
the colour of the nearest kept pixel, so gradients/bursts behind the text
survive), then draw Galmuri lines in a fill colour with optional outline
rings, each line on the vertical centre of the original text band it
replaces (when the band count matches).  4bpp only.
"""
import json, os, sys
from collections import deque
sys.path.insert(0, os.path.dirname(__file__))
from sprite_fix import ROM, G, JS, Spr, glyph, ring
from tama4u.hangul import BdfFont

FONTS = {}


def font(name):
    if name not in FONTS:
        FONTS[name] = BdfFont(f'{G}/{ {"B11": "Galmuri11-Bold", "G11": "Galmuri11", "G9": "Galmuri9", "G7": "Galmuri7"}[name] }.bdf')
    return FONTS[name]


def run(spec, s_):
    """(w, h, pts) of a line; spec = (font, gap, emb, scale, space)."""
    fn, gap, emb, sc, sp = spec
    gl = [(sp, 0, 0, set()) if ch == ' ' else glyph(font(fn), ch, emb) for ch in s_]
    asc = max(bh + by for bw, bh, by, p in gl)
    pts, x = set(), 0
    for bw, bh, by, p in gl:
        top = asc - by - bh
        pts |= {(x + px, top + py) for px, py in p}; x += bw + gap
    if sc > 1:
        pts = {(px * sc + i, py * sc + j) for px, py in pts for i in range(sc) for j in range(sc)}
    w = max(px for px, _ in pts) + 1; h = max(py for _, py in pts) + 1
    top = min(py for _, py in pts)
    return w, h - top, {(px, py - top) for px, py in pts}


def thicken(pts, n=1):
    for _ in range(n):
        pts = pts | {(x + dx, y + dy) for x, y in pts for dx in (-1, 0, 1) for dy in (-1, 0, 1)}
    return pts


def erase(s, box, colours, k=0, mask=None):
    """Erased pixels take the nearest kept colour inside the box (BFS);
    `mask`: only these pixels may be erased."""
    x0, y0, x1, y1 = box; f = s.f[k]
    gone = lambda x, y: f[y][x] in colours and (mask is None or (x, y) in mask)
    hit = [(x, y) for y in range(y0, y1) for x in range(x0, x1) if gone(x, y)]
    gset = set(hit); q = deque(); seen = set()
    for y in range(y0, y1):
        for x in range(x0, x1):
            if (x, y) not in gset:
                q.append((x, y)); seen.add((x, y))
    if not q:
        return hit
    while q:
        x, y = q.popleft()
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if x0 <= nx < x1 and y0 <= ny < y1 and (nx, ny) not in seen:
                seen.add((nx, ny)); f[ny][nx] = f[y][x]; q.append((nx, ny))
    return hit


def bands_of(hit):
    ys = sorted({y for _, y in hit}); out = []
    for y in ys:
        if out and y <= out[-1][1] + 1: out[-1][1] = y
        else: out.append([y, y])
    return out


def fit(lines, box, fonts, rings):
    """First font spec whose every line fits the box width (and stacked height)."""
    x0, y0, x1, y1 = box; r = len(rings)
    for spec in fonts:
        runs = [run(spec, ''.join(t for t, _ in ln)) for ln in lines]
        if max(w for w, _, _ in runs) + 2 * r <= x1 - x0 and \
           sum(h for _, h, _ in runs) + 2 * r * len(lines) <= y1 - y0:
            return spec
    raise ValueError(f'{lines}: does not fit {box}')


def write(s, box, lines, fill, rings=(), fonts=None, align='c', lefts=None, k=0, centres=None, xc=None):
    """lines: str | [str] | [[(text, colour), ...]]; rings: outline colours, inner first."""
    if isinstance(lines, str): lines = [lines]
    lines = [[(ln, fill)] if isinstance(ln, str) else ln for ln in lines]
    fonts = fonts or [('B11', 1, False, 1, 6), ('B11', 0, False, 1, 4), ('G11', 1, False, 1, 5),
                      ('G9', 1, False, 1, 4), ('G9', 0, False, 1, 3), ('G7', 1, False, 1, 3)]
    spec = fit(lines, box, fonts, rings)
    x0, y0, x1, y1 = box
    runs = [run(spec, ''.join(t for t, _ in ln)) for ln in lines]
    tot = sum(h for _, h, _ in runs) + (len(runs) - 1) * 2
    ys = centres or [None] * len(runs)
    y = (y0 + y1) / 2 - tot / 2
    for i, ((w, h, pts), ln) in enumerate(zip(runs, lines)):
        cy = ys[i] if ys[i] is not None else y + h / 2
        top = round(cy - h / 2)
        if align == 'l':
            left = min(lefts[i] if lefts else x0 + 1 + len(rings), x1 - len(rings) - w)
        else:
            left = round((xc if xc is not None else (x0 + x1) / 2) - w / 2)
        bounds, pre = [], ''
        for t, c in ln:                                # per-segment colours
            bounds.append((run(spec, pre)[0] + spec[1] if pre.strip() else 0, c)); pre += t
        col = lambda px: [c for sx, c in bounds if px >= sx][-1]
        outer = [pts]
        for _ in rings:
            outer.append(thicken(outer[-1]))
        for j in range(len(rings), 0, -1):
            s.put(outer[j] - outer[j - 1], left, top, rings[j - 1], k)
        for px, py in pts:
            s.put({(px, py)}, left, top, col(px), k)
        y += h + 2


def block(s, box, clear, lines, fill, rings=(), fonts=None, align='c', k=0, keep_bands=True,
          xc_from_text=True, dx=0, mask=None):
    hit = erase(s, box, set(clear), k, mask)
    bands = bands_of(hit)
    n = len(lines) if isinstance(lines, list) else 1
    centres = [(a + b + 1) / 2 for a, b in bands] if keep_bands and len(bands) == n else None
    xc = None
    if xc_from_text and hit:
        xs = [x for x, _ in hit]; xc = (min(xs) + max(xs) + 1) / 2 + dx
    lefts = None
    if align == 'l' and centres:
        lefts = [min(x for x, y in hit)] * len(bands)      # one left edge for all lines
    write(s, box, lines, fill, rings, fonts, align, lefts, k, centres, xc)


# ---- special pieces ------------------------------------------------------------

def flag(s, x_pole, top, side, white, red, navy, grey, w=37, h=11):
    """Waving たまでん flag -> a plain wider flag holding 타마열차 (G7)."""
    f = s.f[0]
    xa = x_pole if side > 0 else x_pole - w + 1
    xb = xa + w - 1
    for y in range(top, top + h):
        for x in range(xa, xb + 1):
            edge = y in (top, top + h - 1) or x in (xa, xb)
            f[y][x] = navy if edge else white
    shade = xa + 1 if side > 0 else xb - 1
    for y in range(top + 1, top + h - 1):
        f[y][shade] = grey
    wd, ht, pts = run(('G7', 1, False, 1, 3), '타마열차')
    lo, hi = (xa + 2, xb) if side > 0 else (xa + 1, xb - 1)
    s.put(pts, round((lo + hi) / 2 - wd / 2), top + (h - ht) // 2, red)


def rankup(s):
    """なかよしランク/アップ (cyan, white + navy rims) -> 친밀도 랭크/업!; the
    shine streak (colours 4, 5) between the lines stays."""
    f = s.f[0]
    for y in range(s.h):
        for x in range(s.w):
            if f[y][x] in (1, 2, 3, 4, 5): f[y][x] = 0
    # the shine between the lines was a big heart behind the text (4 fill, 5 rim)
    body = heart(48, 21, 15, 13)
    s.put(body, 0, 0, 4); s.put(ring(body), 0, 0, 5)
    write(s, (0, 3, 96, 20), '친밀도 랭크', 3, (2, 1), fonts=[('B11', 1, False, 1, 5)], centres=[11.5])
    write(s, (0, 20, 96, 38), '업!', 3, (2, 1), fonts=[('B11', 1, False, 1, 5)], centres=[29])


def heart(cx, cy, rx, ry):
    """Pixels of a heart centred at (cx, cy), half-sizes rx, ry."""
    pts = set()
    for y in range(int(cy - ry) - 1, int(cy + ry) + 2):
        for x in range(int(cx - rx) - 1, int(cx + rx) + 2):
            u = (x + .5 - cx) / rx * 1.2; v = -(y + .5 - cy) / ry * 1.25 + .15
            if (u * u + v * v - 1) ** 3 - u * u * v ** 3 <= 0:
                pts.add((x, y))
    return pts


def burst(cx, cy, rin, rout, n, sy=1.0):
    """Star burst polygon pixels (n spikes), vertical scale sy."""
    import math
    poly = []
    for i in range(2 * n):
        r = rout if i % 2 == 0 else rin
        t = math.pi * i / n + .2
        poly.append((cx + r * math.cos(t), cy + r * math.sin(t) * sy))
    pts = set()
    for y in range(int(cy - rout * sy) - 1, int(cy + rout * sy) + 2):
        xs = []
        for (ax, ay), (bx, by) in zip(poly, poly[1:] + poly[:1]):
            if (ay <= y + .5 < by) or (by <= y + .5 < ay):
                xs.append(ax + (y + .5 - ay) * (bx - ax) / (by - ay))
        xs.sort()
        for a, b in zip(xs[::2], xs[1::2]):
            pts |= {(x, y) for x in range(round(a), round(b))}
    return pts


def puzzle(s, ch):
    """A fat outlined glyph whose inside copies the puzzle colouring nearby."""
    f = s.f[0]
    pal = []
    for j in range(s.nc):
        v = ROM[s.a + 6 + 2 * j] << 8 | ROM[s.a + 7 + 2 * j]
        pal.append(((v & 31) << 3, ((v >> 5) & 63) << 2, (v >> 11) << 3))
    # puzzle pieces only: no white highlight, no grey shade
    piece = {c for c, (r, g, b) in enumerate(pal) if max(r, g, b) - min(r, g, b) >= 40 and min(r, g, b) < 230}
    src = {(x, y): f[y][x] for y in range(s.h) for x in range(s.w) if f[y][x] in piece - {0, 1}}
    w, h, pts = run(('G9', 1, False, 3, 4), ch)
    ox, oy = (s.w - w) // 2 + 1, (s.h - h) // 2 + 1
    body = {(x + ox, y + oy) for x, y in pts}
    for y in range(s.h):
        for x in range(s.w):
            f[y][x] = 0
    keys = list(src)
    for x, y in body:
        if not (0 <= x < s.w and 0 <= y < s.h): continue
        c = src.get((x, y))
        if c is None:
            c = src[min(keys, key=lambda p: (p[0] - x) ** 2 + (p[1] - y) ** 2)]
        f[y][x] = c
    # piece borders in the original's grey (the low-saturation dark one)
    grey = min((c for c in range(2, s.nc) if c not in piece), key=lambda c: sum(pal[c]))
    old = {(x, y): f[y][x] for x, y in body if 0 <= x < s.w and 0 <= y < s.h}
    for (x, y), c in old.items():
        if any(old.get(q, c) != c for q in ((x + 1, y), (x, y + 1))):
            f[y][x] = grey
    # rounded corners: convex corner pixels of the body become outline, and
    # the outline only touches the body side-on (no diagonal corner pixels)
    corner = {(x, y) for x, y in body
              if ((x - 1, y) not in body or (x + 1, y) not in body) and ((x, y - 1) not in body or (x, y + 1) not in body)
              and sum(q in body for q in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1))) == 2}
    body -= corner
    rim = {(x + a, y + b) for x, y in body for a, b in ((1, 0), (-1, 0), (0, 1), (0, -1))} - body
    for x, y in corner - rim:
        if 0 <= x < s.w and 0 <= y < s.h: f[y][x] = 0
    for x, y in rim:
        if 0 <= x < s.w and 0 <= y < s.h: f[y][x] = 1


def p060(s):   # 祝 / オープン (vertical sign)
    block(s, (60, 30, 73, 43), [1], '축', 1, fonts=[('G9', 1, False, 1, 3)])
    f = s.f[0]
    erase(s, (62, 52, 70, 70), {1})
    for i, ch in enumerate('오픈'):
        w, h, pts = run(('G7', 1, False, 1, 3), ch)
        s.put(pts, 65 - w // 2, (53, 61)[i], 1)


def p065(s):   # HENSHIN -> 변신장소
    block(s, (41, 17, 88, 25), [6], '변신장소', 6, fonts=[('G7', 1, False, 1, 3)], keep_bands=False)


def p068(s):   # いまだけ! / ゲームセンター / しょうきん / 2ばい
    """The burst behind 2ばい is redrawn whole (yellow, orange rim), the 2
    put back, then 우승상금 and 배 drawn over it; sparkles kept."""
    f = s.f[0]; o = [r[:] for r in f]
    hit = erase(s, (7, 7, 52, 20), {4})
    spec = ('G9', 0, True, 1, 3)
    w, h, pts = run(spec, '한정기회!'); w4 = run(spec, '한정기회')[0]
    left = round((min(x for x, _ in hit) + max(x for x, _ in hit) + 1) / 2 + 1 - w / 2)
    top = round(13 - h / 2)
    s.put({(x, y) for x, y in pts if x < w4}, left - 2, top, 4)       # 한정기회: 2px left
    s.put({(x, y) for x, y in pts if x >= w4}, left, top, 4)          # ! where it was
    block(s, (56, 6, 124, 22), [1, 2, 3, 5], '게임센터', 5, (1, 2))
    # the burst behind the old text: keep every visible pixel of it, and fill
    # what しょうきん / ばい covered from its outline traced by angle around
    # the centre (hidden angles interpolated), yellow inside, orange rim
    import math
    T = {(x, y) for y in range(24, 40) for x in range(40, 103) if o[y][x] in (2, 6)}
    T |= {(x, y) for y in range(39, 59) for x in range(71, 98) if o[y][x] in (1, 4)}
    D = {(x, y) for y in range(39, 59) for x in range(53, 71) if o[y][x] in (1, 4)}   # the 2: not burst edge
    cx, cy = 60, 46
    rad = {}
    for t in range(360):
        a = math.radians(t); inb = False
        for r in range(0, 60):
            x, y = round(cx + r * math.cos(a)), round(cy + r * math.sin(a))
            if not (8 <= x < 104 and 23 <= y < 66): break
            if (x, y) in T: break
            if (x, y) in D: inb = True; continue           # through the 2 (it sits inside the burst)
            if o[y][x] in (3, 5): inb = True
            elif o[y][x] == 4 and inb:
                rad[t] = r; break
    known = sorted(rad)
    def R(t):
        if t in rad: return rad[t]
        lo = max([k for k in known if k < t], default=known[-1] - 360)
        hi = min([k for k in known if k > t], default=known[0] + 360)
        a, b = rad[lo % 360], rad[hi % 360]
        return a + (b - a) * (t - lo) / (hi - lo)
    for x, y in T:
        d = math.hypot(x - cx, y - cy); t = round(math.degrees(math.atan2(y - cy, x - cx))) % 360
        r = R(t)
        f[y][x] = 5 if d <= r - 3 else 3 if d <= r else 4
    write(s, (40, 23, 110, 39), '우승상금', 2, (6,), fonts=[('B11', 1, False, 1, 4)], centres=[31], xc=72)
    write(s, (71, 39, 98, 58), '배', 4, (1,), fonts=[('G7', 1, False, 2, 3)], centres=[48.5], xc=84)


def p069(s):   # たまもり/ショップ -> 타마모리/숍
    block(s, (3, 18, 35, 34), [5], ['타마모리', '숍♥'], 5, fonts=[('G7', 1, False, 1, 3)])


def p070(s):   # いまだけ! / こうち/リフォーム
    block(s, (71, 20, 121, 31), [2], '한정기회!', 2)
    block(s, (60, 34, 104, 48), [0xA], '고치리폼', 0xA, fonts=[('G7', 1, False, 1, 3)], keep_bands=False)


def p071(s):   # アルバイトだいぼしゅう!! / あさ7:00~ こうえんで まってるよ!!
    block(s, (4, 2, 124, 17), [4, 5, 6], '아르바이트 보너스!!', 6, (5, 1), keep_bands=False)
    block(s, (42, 34, 89, 67), [2, 6], [[('아침', 2), ('7:00~', 6)], '공원에서', [('기다려줘!!', 2)]], 6,
          fonts=[('G9', 1, False, 1, 3), ('G9', 0, False, 1, 3), ('G7', 1, False, 1, 3)])


def p072(s):   # きょうは/なんのひ?
    block(s, (2, 4, 46, 25), [2], ['오늘은', '어떤 날?'], 2, fonts=[('G7', 1, False, 1, 3)])


def p077(s):   # ゴメンネ (heart) -> 미안해요
    """The glyphs' own white insides go too (only around the old text); the
    middle of the heart (pink, transparent) shows behind the new letters."""
    f = s.f[0]; box = (2, 10, 49, 23)
    inside = {(x, y) for y in range(10, 23) for x in range(2, 49)}
    txt = {(x, y) for x, y in inside if f[y][x] in (1, 5)}
    hit = erase(s, box, {1, 3, 5}, mask=thicken(txt) & inside)
    middle = heart(25.5, 20, 10, 12)               # fitted to the original's pink middle
    for x, y in hit:
        if (x, y) in middle: f[y][x] = 0
    # the cloud's inner rim (blue) where the old letters covered it
    N4 = ((1, 0), (-1, 0), (0, 1), (0, -1))
    rim = [(x, y) for y in range(8, 26) for x in range(2, 50)
           if f[y][x] not in (0, 1) and any(f[y + b][x + a] == 0 and (x + a, y + b) in middle for a, b in N4)]
    for x, y in rim: f[y][x] = 1                   # blue edge, grey just inside (as the original)
    for x, y in rim:
        for a, b in N4:
            if f[y + b][x + a] in (2, 3): f[y + b][x + a] = 4
    bands = bands_of(txt)
    write(s, box, '미안해요', 5, (1,), [('G9', 1, True, 1, 3), ('G9', 1, False, 1, 3)],
          centres=[(bands[0][0] + bands[-1][1] + 1) / 2 + 1], xc=25.5)


def p059(s):
    """No-info birthday window = the own profile's window (0x15A1D8 copy with
    the person icon, P015-OWN) in this record's palette, with this one's grey
    placeholders (성별/별자리/취미, ? 살) from the P059 draft on top."""
    P = json.load(open(JS))
    def pal(a):
        out = []
        for j in range(ROM[a + 2]):
            v = ROM[a + 6 + 2 * j] << 8 | ROM[a + 7 + 2 * j]
            out.append(((v & 31) << 3, ((v >> 5) & 63) << 2, (v >> 11) << 3))
        return out
    pa, pc = pal(0x15A1D8), pal(0x15C600)
    m = [0] + [min(range(1, len(pc)), key=lambda j: sum((pc[j][t] - c[t]) ** 2 for t in range(3))) for c in pa[1:]]
    own = bytes.fromhex(P['P015-OWN']['pixels']); cur = bytes.fromhex(P['P059']['pixels'])
    grey = pc.index((136, 140, 136))
    out = bytearray(m[c] for c in own)
    for i, c in enumerate(cur):
        x, y = i % 128, i // 128
        if c == grey and not (x < 3 or x > 124 or y < 3 or y > 68) or (x >= 95 and 3 <= y < 20):
            out[i] = c
    return dict(addr='0x15C600', pixels=bytes(out).hex())
def bubble(lines):
    def fn(s):
        block(s, (5, 5, 113, 28), [2], lines, 2, align='l',
              fonts=[('G9', 1, False, 1, 4), ('G9', 1, False, 1, 3), ('G9', 0, False, 1, 3), ('G7', 1, False, 1, 3)])
    return fn


def p080(s):   # このアイテムは/ダウンロード/できないよ! (bold)
    block(s, (5, 5, 123, 67), [6], ['이 아이템은', '다운로드', '할 수 없어!'], 6,
          fonts=[('B11', 1, False, 1, 6)])


def p081(s):   # 才 (age) -> 살
    f = s.f[0]
    for y in range(s.h):
        for x in range(s.w): f[y][x] = 0
    w, h, pts = run(('B11', 0, True, 1, 3), '살')
    s.put(pts, (s.w - w) // 2, s.h - h - 1, 1)


def p018(s):   # つうしん/たいき… etc. (3 frames) -> one line at the top centre
    for k, txt in enumerate(('통신 대기 중...', '통신 중…', '통신 실패')):
        hit = erase(s, (6, 4, 122, 36), {5}, k)
        b = bands_of(hit)
        write(s, (6, 4, 122, 36), txt, 5, (), [('B11', 1, False, 1, 4)], k=k,
              centres=[(b[0][0] + b[-1][1] + 1) / 2], xc=64)


def p043(s):
    """Current drafts, each frame's text moved to the original's left edge."""
    o = Spr('-', s.a, {})
    for k in range(s.n):
        f = s.f[k]
        L0 = min(x for row in o.f[k] for x, c in enumerate(row) if c == 2)
        L = min(x for row in f for x, c in enumerate(row) if c == 2)
        for row in f:
            old = row[:]
            for x in range(s.w):
                if old[x] == 2: row[x] = 1
            for x in range(s.w):
                if old[x] == 2: row[x - (L - L0)] = 2


def p040(s):
    """つうしん/たいき…/あそびによぶほうが/Bボタンをおしてね！ -> centred lines over
    P034's picture (hearts and waves, its text gone) faded 50% toward white."""
    f = s.f[0]; navy, white = 5, 1
    o = [r[:] for r in f]
    pal = lambda a: [((v & 31) << 3, ((v >> 5) & 63) << 2, (v >> 11) << 3)
                     for v in (ROM[a + 6 + 2 * j] << 8 | ROM[a + 7 + 2 * j] for j in range(ROM[a + 2]))]
    mine, src = pal(s.a), pal(0x180654)
    b = bands_of([(x, y) for y in range(4, 68) for x in range(4, 124) if o[y][x] == navy])
    for y in range(4, 68):
        for x in range(4, 124): f[y][x] = white
    p34 = Spr('-', 0x180654, {}).f[0]
    for y in range(4, 68):
        for x in range(4, 124):
            c = p34[y][x]
            if c in (0, 1) or (c == 5 and y < 40): continue      # drop only リンクちゅう… (navy, top)
            r, g, bl = ((src[c][t] + 248) // 2 for t in range(3))
            f[y][x] = min(range(1, len(mine)), key=lambda j: (mine[j][0] - r) ** 2 + (mine[j][1] - g) ** 2 + (mine[j][2] - bl) ** 2)
    write(s, (4, 4, 124, 68), ['통신', '대기 중…', '초대하는 쪽이', 'B버튼을 눌러줘!'], navy,
          fonts=[('B11', 1, False, 1, 5)], centres=[(a + c + 1) / 2 for a, c in b], xc=64)


JOBS = {
    'P040': (0x189724, 'つうしん／たいき…／あそびによぶほうが／Bボタンをおしてね！', '통신/대기 중…/초대하는 쪽이/B버튼을 눌러줘!', p040),
    'P043': (0x18C770, 'たまごっちカゼ・えいようぶそく・じゅみょう・いえで', '다마고치병/영양부족/수명/가출', p043),
    'P018': (0x16C0A8, 'つうしん／たいき…・ちゅう…・しっぱい', '통신 대기 중... / 통신 중… / 통신 실패', p018),
    'P060': (0x0F8EEC, '祝／オープン', '축/오픈', p060),
    'P061': (0x132808, 'たまでん (깃발)', '타마열차', lambda s: flag(s, 19, 13, +1, 2, 8, 5, 7)),
    'P062': (0x133A30, 'たまでん (깃발)', '타마열차', lambda s: flag(s, 108, 13, -1, 3, 7, 5, 8)),
    'P063': (0x134C58, 'たまでん (깃발)', '타마열차', lambda s: flag(s, 23, 14, +1, 2, 8, 5, 7)),
    'P064': (0x135E80, 'たまでん (깃발)', '타마열차', lambda s: flag(s, 104, 14, -1, 3, 7, 5, 8)),
    'P065': (0x1372C0, 'HENSHIN', '변신장소', p065),
    'P066': (0x1E4F70, 'なかよしランク／アップ', '친밀도 랭크/업!', rankup),
    'P067': (0x1E5704, 'なかよしランク／アップ', '친밀도 랭크/업!', rankup),
    'P068': (0x1EF970, 'いまだけ!／ゲームセンター／しょうきん／2ばい', '한정기회!/게임센터/우승상금/2배', p068),
    'P069': (0x1F0B88, 'たまもり／ショップ', '타마모리/숍♥️', p069),
    'P070': (0x1F1DA8, 'いまだけ!／こうち／リフォーム', '한정기회!/고치리폼', p070),
    'P071': (0x1F2FCC, 'アルバイトだいぼしゅう!!／あさ7:00~／こうえんで／まってるよ!!',
             '아르바이트 보너스!!/아침7:00~/공원에서/기다려줘!!', p071),
    'P072': (0x1F79FC, 'きょうは／なんのひ?', '오늘은/어떤 날?', p072),
    'P073': (0x20DE50, 'ゴ (퍼즐)', '미', lambda s: puzzle(s, '미')),
    'P074': (0x20E068, 'メ (퍼즐)', '안', lambda s: puzzle(s, '안')),
    'P075': (0x20E284, 'ン (퍼즐)', '해', lambda s: puzzle(s, '해')),
    'P076': (0x20E49C, 'ネ (퍼즐)', '요', lambda s: puzzle(s, '요')),
    'P077': (0x20E6B4, 'ゴメンネ (하트)', '미안해요', p077),
    'P078': (0x20EB7C, 'このみのタイプのひとは／いたかしら。', '이 중에서 타입인 사람이/누가 있으려나?',
             bubble(['이 중에서 타입인 사람이', '누가 있으려나?'])),
    'P079': (0x20F474, 'どのひとにするのか／きめてちょうだい。', '누구를 선택할지/결정해주세요.',
             bubble(['누구를 선택할지', '결정해주세요.'])),
    'P080': (0x20FF44, 'このアイテムは／ダウンロード／できないよ!', '이 아이템은/다운로드/할 수 없어!', p080),
    'P081': (0x212368, '才 (나이)', '살', p081),
}

if __name__ == '__main__':
    patches = json.load(open(JS))
    for pid in sys.argv[1:] or JOBS:
        if pid == 'P059':
            patches[pid] = p059(None); print(pid, 'rebased'); continue
        a, _, _, fn = JOBS[pid]
        s = Spr(pid if pid == 'P043' else '-', a, patches); fn(s)
        patches[pid] = dict(addr=f'0x{a:06X}', pixels=s.pixels())
        print(pid, 'drawn')
    json.dump(patches, open(JS, 'w'), indent=0, sort_keys=True)
