"""Can a download be written from scratch rather than copied?

The packs cannot go in the repository, so a "new item" button has to build
the packet itself.  The way to know that works is to point it at real files:
take a retail item, rebuild one from that item's own field values, and see
whether the bytes come back the same.

    python3 tests/test_create.py <pack-dir> [<pack-dir> ...]

At the time of writing 4,097 of 4,507 items reproduce byte for byte (90.9%).
The rest miss by one to three bytes at fixed offsets -- fields nothing here
has decoded yet, listed at the end of the run.  A new item leaves those at
zero, or at whatever `create.EXTRA_BYTES` gives the category, so a generated
file is structurally sound but has not been tried on hardware.

The run fails if the rate drops below THRESHOLD, or if any item comes out a
different length -- a length change means the layout itself is wrong, which
is a different class of mistake from an undecoded byte.
"""
import collections
import glob
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from tama4u import container, create, destinations, items  # noqa: E402

THRESHOLD = 0.90


def walk(dirs):
    for root in dirs:
        for path in glob.glob(os.path.join(root, '**', '*.[jJ][pP][gG]'),
                              recursive=True):
            try:
                _, packets, _ = container.parse_file(path)
            except Exception:
                continue
            for pkt in packets:
                if pkt.children or items.is_program(pkt):
                    continue
                label = destinations.match(
                    pkt.model,
                    bytes(pkt.raw[items.OFF_DEST:items.OFF_DEST + 4]), pkt.raw)
                if not label or label in create.UNSUPPORTED:
                    continue
                yield path, pkt, label


def main(dirs):
    exact = tried = 0
    wrong_length, errors = [], collections.Counter()
    stray = collections.Counter()          # (model, label, offset) -> n
    for path, pkt, label in walk(dirs):
        tried += 1
        try:
            out = create.reproduce(pkt)
        except Exception as exc:
            errors[f'{type(exc).__name__}: {str(exc)[:60]}'] += 1
            continue
        if out == bytes(pkt.raw):
            exact += 1
            continue
        if len(out) != len(pkt.raw):
            wrong_length.append((os.path.basename(path), pkt.model, label,
                                 len(out) - len(pkt.raw)))
            continue
        for i in range(len(out) - 2):      # the checksum follows the rest
            if out[i] != pkt.raw[i]:
                stray[(pkt.model, label, i)] += 1

    if not tried:
        print('재현할 아이템을 찾지 못했습니다 — 팩 경로를 확인하세요')
        return 1
    rate = exact / tried
    print(f'재현 시도 {tried:,} · 완전 일치 {exact:,} ({rate:.1%})')

    for key, n in errors.most_common():
        print(f'  오류 {key} ×{n}')
    for name, model, label, delta in wrong_length[:10]:
        print(f'  ✗ 길이가 다름 {delta:+} [{model}] {label} · {name}')
    if wrong_length:
        print(f'  길이 불일치 {len(wrong_length)}건 — 레이아웃이 틀렸다는 뜻')

    if stray:
        print('\n아직 재현하지 못하는 바이트 (해독 안 된 필드)')
        for (model, label, off), n in stray.most_common(12):
            print(f'  [{model}] {label[:20]:22s} 0x{off:03X} ×{n}')

    ok = rate >= THRESHOLD and not wrong_length and not errors
    print(f'\n{"통과" if ok else "실패"} — 기준 {THRESHOLD:.0%}')
    return 0 if ok else 1


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1:]))
