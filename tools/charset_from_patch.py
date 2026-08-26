"""Recover character codes from Mr.Blinky's P's translation patches.

Each EP patch ships as a script (`EP00x-Fy-text.txt`, plain text listing
`<rom address>: <len>,"TEXT"`) *and* as the compiled download that writes
those strings (`ep00x-fy.jpg`).  The compiled file therefore contains every
string in the device's own encoding, which turns the pair into a Rosetta
stone: anchor on the characters we already know, and the bytes that line up
with the rest name the codes we do not.

    python3 tools/charset_from_patch.py <script-dir> <pack-dir>

Prints one line per code it can pin, plus any disagreement with the table
we ship.  Nothing is written -- the mapping is reviewed by hand before it
goes into charset.json.
"""
import argparse
import collections
import glob
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from tama4u import charset, container  # noqa: E402

# <hex address>: <count>,"TEXT"   -- the count is a character count, and the
# script zero-fills that many bytes before writing, so it is an upper bound
# on the string, not its length.
LINE = re.compile(r'^\s*([0-9A-Fa-f]{6,8})\s*:\s*(\d+)\s*,\s*"([^"]*)"')
MIN_ANCHOR = 4          # shorter runs match too many places to be safe
MODEL = "P's"


def scripts(dirname):
    for path in sorted(glob.glob(os.path.join(dirname, '*-text.txt'))):
        stem = os.path.basename(path).replace('-text.txt', '').lower()
        out = []
        with open(path, encoding='utf-8-sig') as fh:
            for line in fh:
                m = LINE.match(line)
                if m:
                    out.append((int(m.group(1), 16), m.group(3)))
        yield stem, out


def packet_of(pack, stem):
    for path in glob.glob(os.path.join(pack, '**', '*.jpg'), recursive=True):
        if os.path.basename(path).lower() == stem + '.jpg':
            _, packets, _ = container.parse_file(path)
            return path, bytes(packets[0].raw)
    return None, None


def runs(text, known):
    """Maximal runs of characters we can already encode, longest first."""
    out, i = [], 0
    while i < len(text):
        if text[i] in known:
            j = i
            while j < len(text) and text[j] in known:
                j += 1
            out.append((i, text[i:j]))
            i = j
        else:
            i += 1
    return sorted(out, key=lambda r: -len(r[1]))


def locate(raw, text, rev):
    """Byte offset where `text` starts, or None if it is not pinned.

    Every known character in the string has to agree, and the anchor has to
    land in exactly one place -- 'YES' alone occurs 17 times."""
    for at, run in runs(text, rev):
        if len(run) < MIN_ANCHOR:
            break
        needle = bytes(rev[c] for c in run)
        hits = []
        for i in range(len(raw) - len(needle) + 1):
            if raw[i:i + len(needle)] != needle:
                continue
            start = i - at
            if start < 0 or start + len(text) > len(raw):
                continue
            if all(raw[start + k] == rev[c]
                   for k, c in enumerate(text) if c in rev):
                hits.append(start)
        if len(hits) == 1:
            return hits[0]
    return None


def deltas(hits):
    """address - file offset, for the strings we did pin.

    The patch writes each block to a fixed ROM address, so one constant
    covers a whole region; a script touches a handful of regions."""
    c = collections.Counter(a - o for a, o in hits)
    return [d for d, n in c.most_common() if n >= 2]


def place(raw, text, rev, addr, ds):
    """Offset for a string the anchor search could not pin, from the
    address constants its neighbours established."""
    for d in ds:
        at = addr - d
        if at < 0 or at + len(text) > len(raw):
            continue
        if all(raw[at + k] == rev[c] for k, c in enumerate(text) if c in rev):
            return at
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('scripts')
    ap.add_argument('pack')
    args = ap.parse_args()

    table = charset.load_table(model=MODEL)
    rev = {v: k for k, v in table.items()}
    votes = collections.defaultdict(collections.Counter)
    files = []
    for stem, lines in scripts(args.scripts):
        path, raw = packet_of(args.pack, stem)
        if raw is None:
            print(f'-- {stem}: 대응하는 .jpg 없음, 건너뜀')
            continue
        files.append((stem, path, raw, lines))
    strings = sum(len(l) for _, _, _, l in files)

    # Learning one character unlocks strings that were unpinnable while it
    # was unknown, so keep going round until nothing new turns up.
    pinned = 0
    for round_no in range(1, 8):
        found = {}
        got = 0
        for stem, path, raw, lines in files:
            hits = []
            for addr, text in lines:
                at = locate(raw, text, rev)
                if at is not None:
                    hits.append((addr, at))
            ds = deltas(hits)
            placed = dict(hits)
            for addr, text in lines:
                if addr in placed:
                    continue
                at = place(raw, text, rev, addr, ds)
                if at is not None:
                    placed[addr] = at
            got += len(placed)
            for addr, text in lines:
                at = placed.get(addr)
                if at is None:
                    continue
                for k, ch in enumerate(text):
                    votes[ch][raw[at + k]] += 1
        for ch, cnt in votes.items():
            if ch not in rev:
                code, n = cnt.most_common(1)[0]
                if n >= 2 and n / sum(cnt.values()) >= 0.8:
                    found[ch] = code
        print(f'-- {round_no}회차: 정렬 {got}/{strings}'
              + (f' · 새로 확정 {len(found)}자: ' + ' '.join(found) if found else ''))
        pinned = got
        if not found:
            break
        for ch, code in found.items():
            rev.setdefault(ch, code)

    print(f'\n문자열 {strings}개 · 정렬 성공 {pinned}개\n')
    print('코드      글자   표    근거   비고')
    for ch in sorted(votes, key=lambda c: -sum(votes[c].values())):
        code, n = votes[ch].most_common(1)[0]
        total = sum(votes[ch].values())
        cur = table.get(code)
        if cur == ch:
            note = '일치'
        elif cur is None:
            note = '★ 새 코드'
        else:
            note = f'⚠ 우리는 {cur!r}'
        spread = '' if len(votes[ch]) == 1 else f' (다른 후보 {len(votes[ch]) - 1})'
        print(f'  0x{code:02X}    {ch!r:6s} {cur!r:6s} {n}/{total}   {note}{spread}')


if __name__ == '__main__':
    main()
