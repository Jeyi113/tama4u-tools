"""Korean picture-text sprites: same-size, in-place pixel replacement.

sprites-ps-ko.json: {"P###": {"addr": "0xADDR", "pixels": "hex"}} where addr is
the record header [w,h,ncolors,0,nframes,0xFF] and pixels covers every frame
(4bpp low-nibble-left, or 8bpp above 16 colours).  Palette and header stay.
"""
import json

from .hangul import SAFE


# Profile window (function 0x2527520, r7 = 1 own profile / 2 a friend's,
# kept at [sp+2]).  Both used the 17-colour window 0x215A1D8.  A friend's
# keeps it (Korean labels, no icon); the own profile gets a copy of it with
# the user's person icon (entry with "copy": true, placed in SAFE -- the
# similar-looking 0x215EA28 is the birthday-entry window, with input boxes):
#   0x2527556  xld.w %r4,0x215a1d8  -> jump to a stub that picks the window.
# Gender line of the page routine (0x2527B88: ext + jp.d 0x2528108, delay
# slot ld.w %r7,0xa = the text's x): x 24 like the zodiac and hobby lines for
# the own profile and for a friend whose gender text is Korean (first byte a
# Hangul lead); 10 for a Japanese/English friend (its longer text would run
# into the candles at 24).  The text pointer is the page routine's [sp+0].  From the page
# routine's frame the window function's [sp+2] is [sp+0x34].
WIN_LD, WIN_NEXT, WIN_FRIEND = 0x527556, 0x252755C, 0x215A1D8
WIN_OLD = '42c087d6846d'
GENDER_JP, GENDER_TAIL = 0x527B88, 0x2528108
GENDER_OLD = '02c0bf1fa76c'


def _free(rom, n, below=None):
    """n bytes of 0xFF at the top of a SAFE region's free tail, under `below`
    if given (this runs last; text fills SAFE from the bottom)."""
    for lo, hi in reversed(SAFE):
        top = min(hi, below) if below and lo < below else hi
        at = (top - n) & ~1
        if at > lo and all(b == 0xFF for b in rom[at - 1:top]):
            return at
    raise ValueError(f'no room for {n} B in SAFE')


def gender_x(rom, src, own_window, alloc):
    """Own vs friend profile: window picture and gender-text x (see above).
    own_window: the own profile's full sprite record (bytes)."""
    from . import hangul as H
    if bytes(src[GENDER_JP:GENDER_JP + 6]).hex() != GENDER_OLD:
        raise ValueError('gender line: unexpected bytes')
    if bytes(src[WIN_LD:WIN_LD + 6]).hex() != WIN_OLD:
        raise ValueError('profile window: unexpected bytes')
    at = alloc(96)
    win = alloc(len(own_window))
    rom[win:win + len(own_window)] = own_window
    a = H._Asm(0x2000000 + at)
    a.L('WIN')                                   # r4 = window picture
    a.w(0x5000 | 2 << 4 | 4); a.w(H.cmp_i(4, 1)); a.br(H.JRNE, 'WF')
    a.li(4, 0x2000000 + win); a.br(H.JP, WIN_NEXT, x=True)
    a.L('WF'); a.li(4, WIN_FRIEND); a.br(H.JP, WIN_NEXT, x=True)
    a.L('GX')                                    # r7 = gender text x
    a.w(0x5000 | 13 << 4 | 4); a.w(H.cmp_i(4, 1)); a.br(H.JREQ, 'G24')
    a.w(0x5000 | 0 << 4 | 4); a.w(H.ldub_rb(4, 4))   # friend: first byte of the text
    H._lead_test(a, 4, 'G24', 'G10')             # Korean friend -> 24 too
    a.L('G10'); a.w(H.ld_i(7, 0x0A)); a.br(H.JP, GENDER_TAIL, x=True)
    a.L('G24'); a.w(H.ld_i(7, 0x18)); a.br(H.JP, GENDER_TAIL, x=True)
    code = a.build()
    rom[at:at + len(code)] = code
    for site, lab, n in ((WIN_LD, 'WIN', 6), (GENDER_JP, 'GX', 4)):
        j = H._Asm(0x2000000 + site); j.br(H.JP, a.labels[lab], x=True)
        rom[site:site + 4] = j.build()          # leftover words stay, unreached


def load(path):
    return json.load(open(path))


def apply(rom, patches, orig=None):
    """Write each sprite's changed pixels (vs `orig`) into rom; sizes must match."""
    rom = bytearray(rom)
    src = orig if orig is not None else rom
    top = [None]                                 # SAFE handed out downward from the top

    def alloc(n):
        top[0] = _free(rom, n, below=top[0])
        return top[0]
    from . import hangul_name
    hangul_name.friend_card(rom, src, alloc(256))
    own = patches.get('P015-OWN')
    if own:
        a = int(own['addr'], 16); nc = src[a + 2]
        gender_x(rom, src, bytes(src[a:a + 6 + 2 * nc]) + bytes.fromhex(own['pixels']), alloc)
    for pid, p in sorted(patches.items()):
        if p.get('copy'):
            continue
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
