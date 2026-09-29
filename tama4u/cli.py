"""tama4u CLI: inspect, verify, export sprites, rebuild charset table.

    python -m tama4u info <file.jpg>
    python -m tama4u verify <file-or-dir>
    python -m tama4u export <file.jpg> -o <outdir>
    python -m tama4u charset <corpus-dir>
"""
import argparse
import json
import struct
import glob
import os
import sys

from . import charset, container, items, sprites


def _walk(pkt, depth=0):
    yield pkt, depth
    for c in pkt.children:
        yield from _walk(c, depth + 1)


def cmd_info(args):
    jpeg, packets, trailing = container.parse_file(args.file)
    print(f'{args.file}: jpeg {len(jpeg)}B, {len(packets)} top-level packet(s),'
          f' trailing {len(trailing)}B')
    table = charset.load_table()
    for top in packets:
        for pkt, depth in _walk(top):
            pad = '  ' * (depth + 1)
            name = charset.decode(pkt.item_name_codes, table)
            print(f'{pad}{pkt.ansi_id} [{pkt.kind}] serial={pkt.serial}'
                  f' "{name}" size={pkt.size}'
                  f' sig={pkt.type_sig.hex(" ")}'
                  f' checksum={"ok" if pkt.checksum_ok() else "BAD"}')
            if pkt.kind in ('gh', 'oy', 'ac', 'as', 'fk', 'bg', 'lv'):
                likes, dislikes = items.get_likes(pkt)
                print(f'{pad}  dest={items.get_destination(pkt)}'
                      f' price={items.get_price(pkt)}'
                      f' stats={items.get_stats(pkt)}'
                      f' likes={likes} dislikes={dislikes}')
            try:
                off = items.BANK_OFFSETS.get(pkt.kind, sprites.BANK_OFFSET)
                frames, _ = sprites.parse_bank(pkt.raw, off)
                dims = ' '.join(f'{f.width}x{f.height}' for f in frames)
                print(f'{pad}  sprites: {len(frames)} [{dims}]')
            except (ValueError, IndexError, KeyError, struct.error):
                pass


def cmd_verify(args):
    paths = [args.path] if os.path.isfile(args.path) else \
        glob.glob(os.path.join(args.path, '**', '*.jpg'), recursive=True)
    ok = bad = 0
    for f in paths:
        try:
            _, packets, _ = container.parse_file(f)
            fine = all(p.checksum_ok() for top in packets for p, _ in _walk(top))
        except (ValueError, IndexError):
            fine = False
        if fine:
            ok += 1
        else:
            bad += 1
            print('BAD', f)
    print(f'{ok} ok, {bad} bad')


def cmd_export(args):
    os.makedirs(args.out, exist_ok=True)
    _, packets, _ = container.parse_file(args.file)
    for top in packets:
        for pkt, _ in _walk(top):
            try:
                frames, _ = sprites.parse_bank(pkt.raw)
            except (ValueError, IndexError):
                continue
            for i, fr in enumerate(frames, 1):
                out = os.path.join(args.out, f'{pkt.ansi_id}_{i:02d}.bmp')
                open(out, 'wb').write(sprites.frame_to_bmp(fr))
                print(out, f'{fr.width}x{fr.height}')


def cmd_charset(args):
    table = charset.build_table(args.corpus)
    charset.save_table(table)
    print(f'{len(table)} mappings saved')


def cmd_hangul(args):
    from . import hangul, hangul_text
    bold_addrs = set(json.load(open(args.bold))) if args.bold else set()
    chars = hangul_text.bold_chars(args.text or (), bold_addrs)
    bmap = hangul.bold_map(chars) if chars else None
    strings = {}
    for path in args.text or ():
        strings.update(hangul_text.load(path, bold_addrs, bmap))
    if args.demo:       # boot: centred wait text (drawstr) + menu (putstr, mixed)
        enc = hangul_text.encode
        strings.update({0x557610: enc('잠깐만'), 0x557618: enc('기다려'),
                        0x557620: enc('이어12'), 0x557628: enc('지우けす')})
    some = open(args.some, 'rb').read() if args.some else None
    rom = hangul.build_ps(open(args.ps, 'rb').read(), some, font=args.font,
                          bold=not args.thin, strings=strings, name_ui=args.name_ui,
                          galmuri=args.galmuri, bold_chars=chars,
                          long_diary=not args.short_diary)
    if args.debug_menu:     # test builds: show the download menu's debug set
        rom = hangul.debug_menu(rom)
    if args.all_jobs:       # test builds: every part-time job recruiting
        rom = hangul.all_jobs(rom)
    if args.all_outings:    # test builds: every outing destination open
        rom = hangul.all_outings(rom)
    open(args.out, 'wb').write(rom)
    print(args.out, args.font, f'{len(strings)} texts')
    if args.carry_save:     # tamaemu: saves/tamagotchi_ps/<rom name>/save.sav
        sav = lambda p: os.path.join(os.path.dirname(os.path.abspath(p)), 'saves',
                                     'tamagotchi_ps', os.path.basename(p), 'save.sav')
        old, dst = args.carry_save, sav(args.out)
        img = hangul.carry_save(open(old, 'rb').read(), open(sav(old), 'rb').read(), rom)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        open(dst, 'wb').write(img)
        if os.path.exists(dst + '.tamasave'):
            os.remove(dst + '.tamasave')    # RAM snapshot of another build
        print(dst, 'save data carried from', old)


def main(argv=None):
    ap = argparse.ArgumentParser(prog='tama4u')
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('info'); p.add_argument('file'); p.set_defaults(fn=cmd_info)
    p = sub.add_parser('verify'); p.add_argument('path'); p.set_defaults(fn=cmd_verify)
    p = sub.add_parser('export'); p.add_argument('file')
    p.add_argument('-o', '--out', default='sprites'); p.set_defaults(fn=cmd_export)
    p = sub.add_parser('charset'); p.add_argument('corpus'); p.set_defaults(fn=cmd_charset)
    p = sub.add_parser('hangul'); p.add_argument('ps'); p.add_argument('some', nargs='?')
    p.add_argument('-o', '--out', required=True)
    p.add_argument('--font', default='galmuri11', choices=['galmuri11', 'galmuri11-bold', 'some'])
    p.add_argument('--galmuri', default='~/Downloads/galmuri', help='folder with Galmuri*.bdf')
    p.add_argument('--thin', action='store_true', help='font=some: keep 1px strokes')
    p.add_argument('--name-ui', action='store_true', help='Hangul user-name entry (unverified)')
    p.add_argument('--text', action='append', help='translations JSON {"0xADDR": "텍스트"}')
    p.add_argument('--short-diary', action='store_true',
                   help='test builds: no long-diary hooks (diary texts must fit 36 bytes)')
    p.add_argument('--bold', metavar='JSON',
                   help='["0xADDR", ...]: texts drawn with Galmuri11-Bold syllables')
    p.add_argument('--carry-save', metavar='OLD_ROM',
                   help="tamaemu: start OUT with OLD_ROM's save data (not its flash image)")
    p.add_argument('--debug-menu', action='store_true',
                   help='test builds: show the hidden debug set in the download menu')
    p.add_argument('--all-jobs', action='store_true',
                   help='test builds: open every part-time job')
    p.add_argument('--all-outings', action='store_true',
                   help='test builds: open every outing destination')
    p.add_argument('--demo', action='store_true'); p.set_defaults(fn=cmd_hangul)
    p = sub.add_parser('edit'); p.add_argument('-p', '--port', type=int, default=8477)
    p.set_defaults(fn=lambda a: __import__('tama4u.editor', fromlist=['serve']).serve(a.port))
    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == '__main__':
    main()
