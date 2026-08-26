"""The disassembler against Mr.Blinky's hand-annotated patch assembly.

His P's translation scripts spell out the bytes they patch in and name the
instruction beside them, which is the only ground truth we have for the
core.  `ext` prefixes sit on their own lines there, so they are carried
forward onto the instruction they extend.
"""
import glob
import os
import re
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from tama4u import s1c33  # noqa: E402

LINE = re.compile(r'^\s*((?:[0-9a-fA-F]{4}\s+)*[0-9a-fA-F]{4})\s*;\s*'
                  r'([a-z][a-z0-9._]*)?\s*(\S.*?)?\s*(?:;.*)?$')


def pairs(script_dir):
    """(encoding words, expected text) for every annotated instruction."""
    out, pending = set(), []
    for path in sorted(glob.glob(os.path.join(script_dir, '*-text.txt'))):
        for line in open(path, encoding='utf-8-sig'):
            m = LINE.match(line)
            if not m:
                pending = []
                continue
            words = [int(x, 16) for x in m.group(1).split()]
            if not m.group(2):                      # bare ext line
                pending += words
                continue
            text = f'{m.group(2)} {m.group(3) or ""}'.strip()
            if '(' in text:                         # per-firmware variants
                pending = []
                continue
            out.add((tuple(pending + words), text))
            pending = []
    return sorted(out)


def norm(s):
    s = s.replace(' ', '').replace('%', '').lower()
    return re.sub(r'0x0*([0-9a-f])', r'0x\1', s)


def main(script_dir):
    ok, fails = 0, []
    cases = pairs(script_dir)
    for words, want in cases:
        raw = b''.join(struct.pack('<H', w) for w in words)
        got = s1c33.disasm(raw)
        text = got[0].text if got else '(none)'
        if norm(text) == norm(want):
            ok += 1
        else:
            fails.append((' '.join(f'{w:04x}' for w in words), want, text))
    print(f'정답 세트 {len(cases)}개 · 일치 {ok} · 불일치 {len(fails)}')
    for enc, want, got in fails:
        print(f'   {enc:14s} 기대 {want:26s} 결과 {got}')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1]))
