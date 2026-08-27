"""Swapping a packet for a differently-sized one must not break the file.

A download is packets inside packets, and three things have to move together
when one of them changes length -- the packet's own 0x4A, the 0x32 that every
top-level packet carries, and a checksum per packet, innermost first.  Miss
one and the device rejects the file, which is not something a round-trip
through the parser would notice on its own.

So this walks real files: for each category that nests (seeds, happy mail,
recipes, stamp cards, bingo, 4U cards, outings) and for each VDP bundle, it
swaps a child for donors that are much smaller and much larger, then checks
the result byte for byte.

    python3 tests/test_nesting.py <pack-dir> [<pack-dir> ...]

What is checked, and what is deliberately not:

  * every checksum that was good before is still good.  Ones that were
    already bad stay bad and are ignored -- a few retail files ship a stale
    nested checksum, and vdp-001 carries a whole spurious packet inside its
    compressed stream, header and all.
  * 0x4A equals the packet's real length everywhere.
  * each top-level 0x32 moves by exactly the file's change in length --
    but only where it started out as a real size.  A VDP program packet
    carries junk there (vdp-009 ships 704 against a 27,414-byte packet), and
    shifting junk by a large negative delta just clamps at zero.
  * a nested packet's 0x32 is left alone.  It is a leftover from the file
    that item was downloaded as -- child 0x32 2,310 against a child of
    1,202 bytes is that file's JPEG plus its packet -- and it means nothing
    where it now sits.  Retail files carry their donors' values unchanged.
"""
import base64
import glob
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from tama4u import container, destinations, editor, items  # noqa: E402

VDP_DIR_HINT = 'Virtual Deco Pierces'


def audit(data):
    """(length, top-level (0x32, size) pairs, offending checksums, 0x4A ok)"""
    _, packets, _ = container.parse_file(data)
    bad, tops, sizes_ok = set(), [], True

    def walk(nodes, path=()):
        nonlocal sizes_ok
        for i, pkt in enumerate(nodes):
            here = path + (i,)
            if not pkt.checksum_ok():
                bad.add(here)
            declared = struct.unpack_from('>H', pkt.raw,
                                          container.OFF_PACKET_SIZE)[0]
            if declared != pkt.size:
                sizes_ok = False
            if len(here) == 1:
                tops.append((struct.unpack_from('>H', pkt.raw,
                                                container.OFF_FILE_SIZE)[0],
                             pkt.size))
            walk(pkt.children or [], here)

    walk(packets)
    return len(data), tops, bad, sizes_ok


def swap(data, path, donor):
    return editor.apply_edits(
        data, [{'path': list(path),
                'replace_b64': base64.b64encode(donor).decode()}])


def check(data, path, donor):
    """None when the swap held, else what went wrong.

    A refusal counts as holding: editing a VDP+ without its other half is
    supposed to be turned away, not quietly written out short."""
    n0, tops0, bad0, _ = audit(data)
    try:
        out = swap(data, path, donor)
    except ValueError:
        return None
    n1, tops1, bad1, sizes_ok = audit(out)
    broke = sorted(bad1 - bad0)
    if broke:
        return f'체크섬이 새로 깨짐 {broke}'
    if not sizes_ok:
        return '0x4A가 실제 길이와 다름'
    if len(tops0) != len(tops1):
        return f'최상위 패킷 수가 {len(tops0)}에서 {len(tops1)}로 바뀜'
    for (d0, size0), (d1, _), in zip(tops0, tops1):
        if d0 != size0:
            continue        # not a real size to begin with -- see the docstring
        if d1 - d0 != n1 - n0:
            return (f'최상위 0x32가 {d1 - d0:+}만큼 움직임 '
                    f'(파일은 {n1 - n0:+})')
    return None


def collect(dirs):
    """Files that nest, one or two per category, plus every VDP."""
    nested, vdps, donors = {}, [], []
    for root in dirs:
        for path in glob.glob(os.path.join(root, '**', '*.[jJ][pP][gG]'),
                              recursive=True):
            try:
                _, packets, _ = container.parse_file(path)
            except Exception:
                continue
            if not packets:
                continue
            top = packets[0]
            if not top.children and not items.is_program(top):
                donors.append((top.size, path))
            if VDP_DIR_HINT in path or 'pierce' in os.path.basename(path):
                if editor.describe(open(path, 'rb').read()
                                   )['packets'][0].get('vdp'):
                    vdps.append(path)
                continue
            if not top.children:
                continue
            # a spurious child inside packed data is not a real nesting
            if not all(c.checksum_ok() for c in top.children):
                continue
            label = destinations.match(
                top.model, bytes(top.raw[items.OFF_DEST:items.OFF_DEST + 4]),
                top.raw)
            nested.setdefault((top.model, label), []).append(path)
    donors.sort()
    return nested, vdps, donors


def main(dirs):
    nested, vdps, donors = collect(dirs)
    if not donors:
        print('공여로 쓸 단독 아이템 파일을 찾지 못했습니다')
        return 1
    picks = [donors[0][1], donors[len(donors) // 2][1], donors[-1][1]]
    sizes = [container.parse_file(p)[1][0].size for p in picks]
    print(f'공여 아이템 {sizes} 바이트\n')

    ok = fails = 0
    for key in sorted(nested, key=str):
        model, label = key
        for path in nested[key][:2]:
            for donor_path in picks:
                donor = open(donor_path, 'rb').read()
                why = check(open(path, 'rb').read(), (0, 0), donor)
                if why:
                    fails += 1
                    print(f'  ✗ [{model}] {label} · {os.path.basename(path)}'
                          f' ← {os.path.basename(donor_path)}: {why}')
                else:
                    ok += 1
        print(f'  [{model}] {label}: {min(2, len(nested[key]))}개 파일')

    for path in sorted(vdps):
        data = open(path, 'rb').read()
        for donor_path in picks:
            donor = open(donor_path, 'rb').read()
            why = check(data, (0, 'vdp', 1), donor)
            if why:
                fails += 1
                print(f'  ✗ VDP {os.path.basename(path)}'
                      f' ← {os.path.basename(donor_path)}: {why}')
            else:
                ok += 1
    print(f'  VDP {len(vdps)}개')

    print(f'\n교체 {ok + fails}건 · 통과 {ok} · 실패 {fails}')
    return 1 if fails else 0


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1:]))
