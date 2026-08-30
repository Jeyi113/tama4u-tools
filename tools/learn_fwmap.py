"""Learn the firmware call map from games that were ported between models.

A game is S1C33 code and it calls the device's own routines, which sit at
different addresses on each model.  That is why `convert` refuses program
packets: moving the sprite bank is not the problem, the calls are.

Mr.Blinky's packs ship 31 iD games alongside the P's ports of the same
games, byte for byte the same size.  Lining those up instruction by
instruction gives the correspondence directly -- where the iD file calls
0xFE0101D0 the P's file calls 0x02000CB0, and so on.

    python3 tools/learn_fwmap.py <iD-pack> <P's-pack>

Prints a table ready to paste into tama4u/port.py, plus how consistent it
came out.  Only addresses outside the packet count: a call that stays
inside is the game's own code and needs no mapping.

The ROM answers at two aliases -- 0x004xxxxx and 0x020xxxxx are the same
bytes -- so those are folded together before counting disagreements.
"""
import argparse
import collections
import glob
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.dirname(__file__))
from tama4u import container, s1c33          # noqa: E402
from trace_code import target as branch_target  # noqa: E402

ID_PREFIX = re.compile(r'^GAME_', re.I)
PS_PREFIX = re.compile(r'^ITEMPS_GAME_', re.I)
ROM_ALIAS_FROM = 0x00400000
ROM_ALIAS_TO = 0x02000000
ALIAS_MASK = 0xFFF00000


def canon(addr):
    """Fold the mirrored ROM window onto one address."""
    if (addr & ALIAS_MASK) == ROM_ALIAS_FROM:
        return (addr & ~ALIAS_MASK) | ROM_ALIAS_TO
    return addr


def index(root, strip):
    out = {}
    for path in glob.glob(os.path.join(root, '**', '*.[jJ][pP][gG]'),
                          recursive=True):
        name = os.path.basename(path)
        if not strip.match(name):
            continue
        out[strip.sub('', name).rsplit('.', 1)[0].upper()] = path
    return out


def calls(pkt):
    """{offset: target} for every branch, targets masked to 32 bits."""
    out = {}
    for ins in s1c33.disasm(bytes(pkt.raw), 0x100, pkt.size - 2):
        tgt = branch_target(ins)
        if tgt is not None:
            out[ins.offset] = tgt & 0xFFFFFFFF
    return out


def main(id_root, ps_root):
    ids, pss = index(id_root, ID_PREFIX), index(ps_root, PS_PREFIX)
    both = sorted(set(ids) & set(pss))
    table = collections.defaultdict(collections.Counter)
    used = skipped = 0
    for key in both:
        a = container.parse_file(ids[key])[1][0]
        b = container.parse_file(pss[key])[1][0]
        if a.size != b.size:
            skipped += 1
            continue
        used += 1
        ca, cb = calls(a), calls(b)
        for off in set(ca) & set(cb):
            ta, tb = ca[off], cb[off]
            # a branch that lands inside the packet is the game's own code
            if ta < a.size and tb < b.size:
                continue
            table[canon(ta)][canon(tb)] += 1

    argued = {k: v for k, v in table.items() if len(v) > 1}
    print(f'# 짝 {len(both)}쌍 중 크기가 같은 {used}쌍에서 배웠다'
          f' (크기가 달라 건너뛴 것 {skipped}쌍)')
    print(f'# 대상 {len(table)}종 · 대응이 갈리는 것 {len(argued)}종')
    print('FIRMWARE_MAP = {')
    print("    ('iD', \"P's\"): {")
    for src in sorted(table):
        dst, _n = table[src].most_common(1)[0]
        note = ''
        if src in argued:
            note = '  # ' + ' '.join(f'{a:#010x}×{n}'
                                     for a, n in table[src].most_common())
        print(f'        {src:#010x}: {dst:#010x},{note}')
    print('    },')
    print('}')
    return 0


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('id_pack')
    ap.add_argument('ps_pack')
    args = ap.parse_args()
    sys.exit(main(args.id_pack, args.ps_pack))
