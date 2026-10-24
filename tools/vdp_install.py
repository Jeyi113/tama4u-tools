"""tamaemu 세이브(플래시 이미지)에 VDP+ 파일을 넣는다 — 적외선 다운로드 대신.

  python3 tools/vdp_install.py ROM.bin NEW_ROM.bin FILE.jpg ...

ROM 옆 saves/tamagotchi_ps/<ROM이름>/save.sav를 복사해(키우던 캐릭터 유지)
NEW_ROM 이름의 새 세이브를 만들고, 원본 ROM 파일도 NEW_ROM으로 복사한다.
P's 저장 위치(tamaemu tools/dlc.c): VDP 목적지 0x720000 x2칸, VDP 레시피
0x750000 x4칸, 칸마다 0x8000. 두 곳을 비운 뒤 차례로 넣는다.
"""
import os, shutil, struct, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from tama4u import container, vdp

STORES = {'vdp': (0x720000, 2), 'part': (0x750000, 4)}
SLOT = 0x8000


def main(rom, new, files):
    saves = lambda r: os.path.join(os.path.dirname(os.path.abspath(r)),
                                   'saves', 'tamagotchi_ps', os.path.basename(r))
    src = os.path.join(saves(rom), 'save.sav')
    img = bytearray(open(src, 'rb').read())
    for base, n in STORES.values():
        img[base:base + n * SLOT] = b'\xff' * (n * SLOT)
    used = {k: 0 for k in STORES}
    for f in files:
        pkt = container.parse_file(open(f, 'rb').read())[1][0]
        kind = 'vdp' if vdp.is_vdp(pkt) else 'part' if vdp.is_part(pkt) else None
        if kind is None:
            sys.exit(f'{f}: VDP+ 파일이 아닙니다')
        base, n = STORES[kind]
        if used[kind] >= n:
            sys.exit(f'{kind} 칸이 모자랍니다')
        raw = bytes(pkt.raw)
        off = base + used[kind] * SLOT
        img[off:off + len(raw)] = raw
        used[kind] += 1
        print(f'{os.path.basename(f)} -> {hex(off)} ({len(raw)}B)')
    shutil.copy(rom, new)
    os.makedirs(saves(new), exist_ok=True)
    open(os.path.join(saves(new), 'save.sav'), 'wb').write(img)
    print('세이브:', os.path.join(saves(new), 'save.sav'))


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2], sys.argv[3:])
