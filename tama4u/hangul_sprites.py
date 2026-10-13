"""Korean picture-text sprites: same-size, in-place pixel replacement.

sprites-ps-ko.json: {"P###": {"addr": "0xADDR", "pixels": "hex"}} where addr is
the record header [w,h,ncolors,0,nframes,0xFF] and pixels covers every frame
(4bpp low-nibble-left, or 8bpp above 16 colours).  Palette and header stay.
"""
import json

from .hangul import SAFE


def load(path):
    return json.load(open(path))


def apply(rom, patches, orig=None):
    """Write each sprite's changed pixels (vs `orig`) into rom; sizes must match."""
    rom = bytearray(rom)
    src = orig if orig is not None else rom
    for pid, p in sorted(patches.items()):
        a = int(p['addr'], 16)
        w, h, nc, z, n, ff = src[a:a + 6]
        if z != 0 or ff != 0xFF:
            raise ValueError(f'{pid}: no sprite record at {p["addr"]}')
        per = w * h if nc > 16 else w * h // 2
        px = bytes.fromhex(p['pixels'])
        if len(px) != n * per:
            raise ValueError(f'{pid}: {len(px)} pixel bytes, record holds {n * per}')
        off = a + 6 + 2 * nc
        if any(off < hi and lo < off + len(px) for lo, hi in SAFE):
            raise ValueError(f'{pid}: sprite overlaps SAFE')
        # only the pixels the draft changed: earlier patches to the same
        # picture (the name window's three slots) survive
        mask = 0xFF if nc > 16 else None
        for i, v in enumerate(px):
            o = src[off + i]
            if v == o:
                continue
            if mask:
                rom[off + i] = v
            else:
                lo = v & 0x0F if v & 0x0F != o & 0x0F else rom[off + i] & 0x0F
                hi = v & 0xF0 if v & 0xF0 != o & 0xF0 else rom[off + i] & 0xF0
                rom[off + i] = hi | lo
    return bytes(rom)
