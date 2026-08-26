"""Walk the reachable code in a program packet and point at its loops.

A VDP is mostly data with islands of S1C33 code, and nothing in it names
the sprite buffer -- the loader computes those addresses at run time, so a
plain search for the sprite offset finds nothing.  Following the control
flow does work: start at the entry, take every branch and call target, and
what comes back is the code, with the data left alone.

    python3 tools/trace_code.py <file.jpg> [entry-offset]

Prints where the code is, then the loops it found, ranked by how much they
look like an unpacker -- a byte read through a post-increment pointer, a
byte written through another, and a conditional branch between them.

The first thing it says is usually the useful one.  Measuring how much of
a packet disassembles cleanly separates code from data, and a VDP turns
out to be almost all data:

    EP001-F1 패치   48% 코드      P's 게임   63%      iD L 게임   69%
    VDP-009          3% 코드

So the sprite unpacker is not in the VDP.  Its loader is a stub that hands
data to the firmware, and the firmware does the unpacking -- which is why
following the VDP's own control flow will never reach the routine.
"""
import argparse
import collections
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from tama4u import container, s1c33  # noqa: E402

# Branch displacements count halfwords from the instruction's own address.
DISP = re.compile(r'^(\w+?)(\.d)? 0x([0-9a-f]+)$')
STOPS = ('jp', 'jp.d', 'ret', 'ret.d', 'reti', 'retd', 'brk')
CONDITIONAL = ('jrgt', 'jrge', 'jrlt', 'jrle', 'jrugt', 'jruge', 'jrult',
               'jrule', 'jreq', 'jrne')


def target(ins):
    m = DISP.match(ins.text)
    if not m:
        return None
    name, _d, val = m.groups()
    if name not in CONDITIONAL + ('jp', 'call'):
        return None
    v = int(val, 16)
    if v > 0x7FFFFFFF:
        v -= 0x100000000
    return ins.offset + 2 * v


def trace(raw, entry, limit=None):
    """Reachable instructions, keyed by offset."""
    limit = limit or len(raw)
    code, work, calls = {}, [entry], set()
    while work:
        pc = work.pop()
        while 0 <= pc < limit - 2 and pc not in code:
            ins = s1c33.disasm(raw, pc, min(pc + 8, limit))
            if not ins:
                break
            ins = ins[0]
            code[pc] = ins
            if ins.text.startswith('.word'):
                break                      # ran into data
            tgt = target(ins)
            name = ins.text.split()[0]
            if tgt is not None and 0 <= tgt < limit:
                if name.startswith('call'):
                    calls.add(tgt)
                work.append(tgt)
            if name in STOPS or name.startswith('jp'):
                break
            pc += ins.size
    return code, calls


def loops(code):
    """Back edges: a branch that jumps to an earlier reachable address."""
    out = []
    for off, ins in code.items():
        tgt = target(ins)
        if tgt is not None and tgt in code and tgt <= off:
            out.append((tgt, off))
    return sorted(out)


def score(body):
    """How much a loop looks like it unpacks bytes into a buffer."""
    text = ' | '.join(i.text for i in body)
    pts = 0
    pts += 3 * len(re.findall(r'ld\.ub? %r\d+,\[%r\d+\]\+', text))   # read++
    pts += 3 * len(re.findall(r'ld\.b \[%r\d+\]\+', text))           # write++
    pts += 2 * len(re.findall(r'\b(srl|sll) %r\d+,0x4\b', text))     # nibbles
    pts += 2 * len(re.findall(r'and %r\d+,0xf\b', text))
    pts += len(re.findall(r'\bcmp ', text))
    pts += len(re.findall(r'\bsub %r\d+,0x1\b', text))
    return pts


def islands(raw, window=128, floor=0.85):
    """Byte ranges that disassemble cleanly enough to be code, not data."""
    out, cur = [], None
    for o in range(0x40, len(raw) - window, window):
        d = s1c33.disasm(raw, o, o + window)
        good = d and 1 - sum(1 for i in d
                             if i.text.startswith('.word')) / len(d) >= floor
        if good:
            cur = [o, o + window] if cur is None else [cur[0], o + window]
        elif cur:
            out.append(tuple(cur))
            cur = None
    if cur:
        out.append(tuple(cur))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('path')
    ap.add_argument('entry', nargs='?', default='0xE8')
    ap.add_argument('--top', type=int, default=6)
    args = ap.parse_args()

    _, packets, _ = container.parse_file(args.path)
    raw = bytes(packets[0].raw)
    entry = int(args.entry, 0)

    got = islands(raw)
    total = sum(b - a for a, b in got)
    print(f'코드로 보이는 구간 {len(got)}개 · {total}B / {len(raw)}B '
          f'({total / len(raw):.0%})')
    for a, b in got[:8]:
        print(f'   0x{a:05X}-0x{b:05X}  {b - a}B')
    print()
    code, calls = trace(raw, entry)
    print(f'패킷 {len(raw)}B · 도달 명령 {len(code)}개 '
          f'({sum(i.size for i in code.values()) / len(raw):.0%} of file) '
          f'· 호출 대상 {len(calls)}개')

    found = loops(code)
    print(f'역방향 분기(루프) {len(found)}개\n')
    ranked = []
    for head, tail in found:
        body = [code[o] for o in sorted(code) if head <= o <= tail]
        ranked.append((score(body), head, tail, body))
    ranked.sort(reverse=True)
    for sc, head, tail, body in ranked[:args.top]:
        print(f'── 0x{head:05X}-0x{tail:05X}  명령 {len(body):3d}  점수 {sc}')
        for i in body[:26]:
            print(f'     {i.offset:05X}  {i.text}')
        if len(body) > 26:
            print(f'     … {len(body) - 26}개 더')
        print()


if __name__ == '__main__':
    main()
