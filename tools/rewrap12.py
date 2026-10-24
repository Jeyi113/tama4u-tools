"""Re-break multi-line Korean texts to each window's line limit (the longest
Japanese line of that screen's block, at most 12, less half a cell; longer
lines get re-wrapped by the firmware and a 2-line bubble then loses its end).

    python3 tools/rewrap12.py            # dry run: print changes
    python3 tools/rewrap12.py --apply    # write tama4u/text-ps-ko.json (+ sheet J column)

The old '/' breaks followed the Japanese line lengths, often mid-word.  Each
old break is joined back, without a space when it split a word.
(A break before a particle joins without a space; the others that split a
word are listed in JOIN.)  Then the text is broken at spaces only into as few
lines of <= 12 characters (a space counts half) as possible, every line after
a break at least 3 wide, as few awkward breaks (그/녀석, 할/수) as that allows,
earlier lines as full as possible.
Skipped: diary entries, texts with name cells (①②③), text that follows an item name (starts with a space or a comma),
full-width-space layouts, and the friend letter.
"""
import json, os, re, sys
import openpyxl

LIMIT = 12                  # every talk window holds ~12 Hangul a line (~10 px each, ~115 px wide)
JS = os.path.join(os.path.dirname(__file__), '..', 'tama4u', 'text-ps-ko.json')
SHEET = os.path.expanduser('~/Downloads/TMGC_PS_번역시트.xlsx')
SKIP = [(0x558370, 0x558370 + 75 * 40)]          # diary sentences


def skip(addr, v):
    a = int(addr, 16)
    return (any(lo <= a < hi for lo, hi in SKIP) or any(c in v for c in '①②③　')
            or v[:1] in ' ,、/' or '/' not in v)  # ' ', ',' after an item name; '/' after a name        # ' '/',' = after an item name


PUNCT = '!?.,…～~★♥♪☼◎↑↓、。「」（）()✧:'
PART = {'를', '을', '은', '는', '가', '에', '의', '도', '만', '로', '과', '랑', '에서', '에게', '으로', '서',
        '이랑', '처럼', '까지', '부터', '보다', '이야', '이란', '이라', '이다', '이지', '이고', '께', '한테'}
# old breaks that split a word, read one by one (the rest of the breaks between
# two words get a space; particles and punctuation are handled by rule)
JOIN = {
    '결혼|할래나츄?',
    '결혼|해',
    '결혼|해요…우후훗♥',
    '오물오물|하다가',
    '떨어뜨렸|모구………',
    '탔|으니까',
    'ROKET|이',
    '「노|래를',
    '「안전・편리・|튼튼」',
    '「전|망대」가',
    '가|려고',
    '가|면',
    '가|면,',
    '가져|와!',
    '각|각',
    '갈래|요?',
    '감동하|면',
    '같으|니까,',
    '거|야!',
    '거예|요…사랑받는다는',
    '걷|고',
    '결혼|하자모구',
    '결혼|해보는',
    '결혼|해주시겠어요?',
    '결혼|해줄래~?',
    '결혼|해줬으면',
    '계|산은',
    '고파|지는',
    '곳일까|요?',
    '괴로워|지게',
    '괴롭|히기',
    '그|쪽이',
    '기다|려져요★',
    '늦었|으니까',
    '다마고|치한테',
    '다마고치|별',
    '다정|하게',
    '달고・맵고・시고|・쓰고…음식뿐만',
    '닮았는|데,',
    '대단|한',
    '더러워|지니까,',
    '데이트|하자',
    '데이트|해보자구요!',
    '데이트|해주시겠습니까?',
    '데이트|해주실',
    '데이트|해줄래?',
    '데이트|해줘도',
    '도넛|이',
    '돌아|오면,',
    '뒀|답니다♪…어라??',
    '들|었닷치!',
    '들|켜',
    '등록|되어',
    '똑같다|고?',
    '레스|토랑에서',
    '로켓|이',
    '마들렌・키리에・|돗치누예요!',
    '만나|면,',
    '만들|고',
    '말이|야★',
    '맛있|었다페코!',
    '매력|적으로',
    '모르|겠닷치…↓↓↓',
    '모르겠|네요…',
    '모집하|니까,',
    '몫|이닷치!',
    '믿|어!',
    '바|라보면',
    '반복하|면…나,',
    '버렸|답니다★',
    '버리|거든～★',
    '보|고',
    '보|기만',
    '부끄|러움…공부하다',
    '불쌍하|니까,',
    '빙글빙글|이',
    '산타|쿠롯치랑',
    '상상했는|데…',
    '선|물을',
    '쇼핑|하면,',
    '수|다',
    '스|위츠,',
    '슬프|거나,',
    '시|험을',
    '시작|하면',
    '싶|답니다★',
    '싶어지|지…하지만,',
    '싶은|데,',
    '쌍안|경',
    '쌍안|경이래♪',
    '쓰레|기',
    '쓴다|고?',
    '아|트를',
    '아르|바이트를',
    '아이|템을',
    '액세|서리★',
    '어디|였더라…',
    '없|어…하지만',
    '연|습을',
    '연습|해',
    '옅어|졌닷치↓',
    '완성|됐으면',
    '우주|에서는',
    '위험|하니까,',
    '유|명한',
    '이뤄|진다는',
    '있|대!',
    '있|어☼',
    '있|지만,',
    '있도|록,',
    '있었|어요…다음엔',
    '있으니|까…다마고치별의',
    '잊|지',
    '작|으니까…거리를',
    '잔|뜩',
    '잔|뜩이라',
    '잘못|이었을까…꽃님',
    '점|심밥도',
    '정리|하는',
    '정신력|이라고!',
    '조를|지도',
    '졸려|졌다페코…',
    '좋아|해★',
    '주|거든★',
    '줬|어♥',
    '질|문하면',
    '참|지',
    '참가|해',
    '체|력,',
    '출발|하니까',
    '출발|할',
    '친|구',
    '커다|란',
    '컨트롤|하기',
    '코디네이트|해',
    '타마모리샵|에는,',
    '타마펫|이',
    '트레이닝|뿐이야!',
    '팥소|였으면',
    '퍼지|게',
    '학|교에서',
    '합치|면,',
    '협력|하면,',
    '힐링|돼♪',
    '힘|들지만,',
}


def glue(prev, nxt):
    """'' when the old break split a word, else ' '."""
    if prev.endswith(' ') or nxt.startswith(' '):
        return ''
    if prev[-1] in PUNCT:                        # after a mark: a new sentence/word
        return ' '
    if nxt[0] in PUNCT:                          # a mark closing the word before
        return ''
    a, b = prev.split(' ')[-1], nxt.split(' ')[0]
    if b.strip(PUNCT) in PART or f'{a}|{b}' in JOIN:
        return ''
    return ' '


def join(v, limit=None):
    parts = v.split('/'); out = parts[0]
    for prev, nxt in zip(parts, parts[1:]):
        if nxt and out: out += glue(out, nxt) + nxt
        elif nxt: out = nxt
    return out


def width(s):
    """Screen width in characters: a space is half a cell."""
    return len(s.replace(' ', '')) + s.count(' ') / 2


def hangul(s):
    return sum('가' <= c <= '힣' for c in s)


MIN_NEXT = 3                  # a line after a break holds at least this much
# breaks to avoid when the line count allows: after a one-syllable modifier,
# before a dependent noun (할 수, 먹을 거야, 갈 때 ...)
BAD_END = set('그이저한두세더안못잘꼭좀반내네제각새큰온첫몇갓딴헌옛') | {'이런', '그런', '저런', '어떤', '무슨', '이번', '다른'}
BAD_START = {'수', '것', '줄', '데', '적', '뿐', '듯', '채', '때', '만큼', '것뿐', '수밖에'}


def wrap(text, LIMIT=LIMIT, maxlines=None):
    """Break at spaces only: as few lines as possible, each <= LIMIT wide, every
    line after a break at least MIN_NEXT wide; among those, earlier lines as
    full as possible (a line that fits with the next one simply takes it).
    A single run wider than a line is cut after a mark (or before 「)."""
    words = []
    for wd in text.split(' '):
        while width(wd) > LIMIT:                 # cut after a mark (…・」!?) or before 「
            M = int(LIMIT)                       # a run has no spaces: width = characters
            cuts = [j + 1 for j, ch in enumerate(wd[:M]) if ch in '…・」!?♥♪★☼、,.'] + \
                   [j for j, ch in enumerate(wd[1:M + 1], 1) if ch in '「（(']
            k = max([c for c in cuts if 2 <= c <= M and width(wd[c:]) >= MIN_NEXT], default=M)
            words.append(wd[:k]); wd = wd[k:]
        words.append(wd)
    n = len(words)

    def line(a, b):
        return ' '.join(words[a:b])

    def bad(b):                                   # an awkward break before words[b]
        if b >= n: return 0
        prev, nxt = words[b - 1].strip(PUNCT), words[b].strip(PUNCT)
        return int(prev in BAD_END or nxt in BAD_START
                   or (nxt[:1] == '거' and len(nxt) <= 4 and not nxt.startswith('거기')))

    def key(c):
        # an awkward break weighs one line, but never at the cost of more
        # lines than the window had in Japanese (maxlines)
        over = max(0, c[0] - maxlines) if maxlines else 0
        return (100 * over + c[0] + (c[1] if maxlines else 0), c[1], c[0])

    def solve(minw):
        best = [None] * (n + 1); best[n] = (0, 0)  # (lines, awkward breaks) for words[i:]
        for a in range(n - 1, -1, -1):
            for b in range(a + 1, n + 1):
                w = width(line(a, b))
                if w > LIMIT: break
                if a and w < minw: continue
                if best[b] is not None:
                    c = (best[b][0] + 1, best[b][1] + bad(b))
                    if best[a] is None or key(c) < key(best[a]): best[a] = c
        if best[0] is None: return None
        out, a = [], 0
        while a < n:                              # longest first line keeping the score
            b = max(b for b in range(a + 1, n + 1)
                    if width(line(a, b)) <= LIMIT and (not a or width(line(a, b)) >= minw)
                    and best[b] is not None and key((best[b][0] + 1, best[b][1] + bad(b))) == key(best[a]))
            out.append(line(a, b)); a = b
        return out

    lines = solve(MIN_NEXT) or solve(0)
    for i in range(len(lines) - 1):              # an opening mark never ends a line
        while lines[i] and lines[i][-1] in '「（(':
            lines[i], lines[i + 1] = lines[i][:-1].rstrip(), lines[i][-1] + lines[i + 1]
    return '/'.join(lines)


def main(apply):
    T = json.load(open(JS))
    wb = openpyxl.load_workbook(SHEET); ws = wb['번역']
    rows = {}
    for r in range(2, ws.max_row + 1):
        a = ws.cell(r, 2).value
        if a: rows['0x%06X' % int(a, 16)] = r
    # window width per block of consecutive sheet IDs (one screen's texts):
    # the longest Japanese line there (줄별 글자수, column G), at most 12, less
    # half a cell -- a Hangul syllable is a bit wider than a kana (S1422: 12
    # cells wrapped where the Japanese had 12; the park held 11.5)
    todo = [(k, v, rows.get(k)) for k, v in sorted(T.items()) if not skip(k, v)]
    todo.sort(key=lambda t: str(ws.cell(t[2], 1).value) if t[2] else '')
    def g_of(r):
        g = [int(x) for x in str(ws.cell(r, 7).value).split(',') if x.strip().isdigit()] if r else []
        return g or [12]
    blocks = []
    for k, v, r in todo:
        sid = str(ws.cell(r, 1).value) if r else ''
        n = int(sid[1:]) if sid[1:].isdigit() else -99
        if blocks and n - blocks[-1][-1][0] <= 6: blocks[-1].append((n, k, v, r))
        else: blocks.append([(n, k, v, r)])
    changes, done = {}, []
    for b in blocks:
        lim = min(max(max(g_of(r)) for _, _, _, r in b), 12) - 0.5
        for _, k, v, r in b:
            done.append(k)
            g = g_of(r)
            # a very narrow pad whose Japanese fills every line (letters: 7 a
            # line) is its own window, whatever the block around it
            own = len(g) >= 3 and max(g) <= 8 and sum(x >= max(g) - 1 for x in g[:-1]) >= 0.6 * (len(g) - 1)
            new = wrap(join(v), LIMIT=(max(g) - 0.5) if own else lim, maxlines=len(g))
            if new != v: changes[k] = new
    for k, new in changes.items():
        print(k, T[k], '\n        ->', new)
    print(len(changes), 'changed')
    if apply:
        T.update(changes)
        json.dump(T, open(JS, 'w'), ensure_ascii=False, indent=0, sort_keys=True)
        for k in done:                           # sheet = what is applied
            if k in rows and ws.cell(rows[k], 10).value != T[k]: ws.cell(rows[k], 10).value = T[k]
        wb.save(SHEET)


if __name__ == '__main__':
    main('--apply' in sys.argv)
