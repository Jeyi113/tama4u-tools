"""Firmware text replacement for the Hangul P's.

Texts live in the bank 0x530000-0x55C980, NUL-terminated and 4-aligned, and
are reached either by pointer words (menu tables right after the texts) or
by `xld.w` immediates in code.  A translation that fits its slot (text +
NUL, rounded up to 4) is written in place; a longer one goes to SAFE and
every reference to the old address is rewritten.  A slot another reference
points into (tail-shared texts) is never written in place.

Translations: {"0x538FBC": "거실", ...}; '/' = line break, ' ' = half-pitch
space (hangul.HALF; '\u3000' keeps the firmware's full-cell 0x6C), ASCII
!?()~&., map to the firmware's full-width forms.
"""
import json
import os
import re
import struct

from . import hangul

BANK = (0x530000, 0x55C980)
CODE = (0x400000, 0x530000)
# Texts the firmware copies into fixed profile fields (stored in the save and
# sent with the profile), not just drawn: max text bytes before the NUL.
FIELDS = {0x5580D4: 4, 0x5580DC: 4}                     # gender: 5-byte field
FIELDS.update({0x5580EC + 12 * k: 7 for k in range(12)})  # zodiac: 8-byte field
# Built-in item records ("idn_gh15001_1\0" ...): the name is a fixed 10-byte
# field at record+0x2A, then a u16 kind (0x0002 ...) whose high byte is 0 and
# ends a full 10-byte name; written in place.
ITEM_ID = re.compile(rb'idn_[a-z]+\d+_\d\x00')
ITEM_NAME, ITEM_NAME_LEN = 0x2A, 10


def item_names(rom, lo=0, hi=0x400000):
    """{name field offset: item id} for the item records in rom[lo:hi]."""
    out = {}
    for m in ITEM_ID.finditer(rom, lo, hi):
        if rom[m.start() + 0x26] == 0x3A:
            out[m.start() + ITEM_NAME] = m.group()[:-1].decode()
    return out


ASCII = {'!': '！', '?': '？', '(': '（', ')': '）', '~': '～', '&': '＆',
         '.': '．', ',': '、', '"': '」'}


def charmap():
    fw = json.load(open(os.path.join(os.path.dirname(__file__), 'fwchars-ps.json')))
    return {v: int(k, 16) for k, v in fw.items() if not v.startswith('[')}


def encode(text, rev=None):
    rev = rev or charmap()
    out = bytearray()
    for ch in text:
        if ch == '/':
            out.append(0xFF)
        elif ch == ' ':                                 # half-pitch Hangul space
            out += hangul.code(hangul.HALF)
        elif ch == '\u3000':                            # full kana cell (0x6C)
            out.append(0x6C)
        elif '가' <= ch <= '힣':
            out += hangul.code(hangul.KS.index(int.from_bytes(ch.encode('euc-kr'), 'big')))
        elif ch in hangul.JAMO:
            out += hangul.code(len(hangul.KS) + hangul.JAMO.index(ch))
        else:
            out.append(rev[ASCII.get(ch, ch)])
    return bytes(out)


def _xld(rom, off):
    """(value, rd) of `ext; ext; ld.w %rd,imm6` at off, else None."""
    e1, e2, op = struct.unpack_from('<3H', rom, off)
    if e1 & 0xE000 != 0xC000 or e2 & 0xE000 != 0xC000 or op & 0xFC00 != 0x6C00:
        return None
    return (e1 & 0x1FFF) << 19 | (e2 & 0x1FFF) << 6 | (op >> 4 & 0x3F), op & 0xF


def scan_refs(rom):
    """{bank offset: [('p', word offset) | ('x', xld.w offset)]}."""
    lo, hi = hangul.BASE + BANK[0], hangul.BASE + BANK[1]
    refs = {}
    for off in range(0, len(rom) - 3, 4):
        v = struct.unpack_from('<I', rom, off)[0]
        if lo <= v < hi:
            refs.setdefault(v - hangul.BASE, []).append(('p', off))
    for off in range(CODE[0], CODE[1] - 5, 2):
        x = _xld(rom, off)
        if x and lo <= x[0] < hi:
            refs.setdefault(x[0] - hangul.BASE, []).append(('x', off))
    return refs


def _retarget(rom, kind, off, addr):
    v = hangul.BASE + addr
    if kind == 'p':
        struct.pack_into('<I', rom, off, v)
    else:
        e1, e2, op = struct.unpack_from('<3H', rom, off)
        struct.pack_into('<3H', rom, off, 0xC000 | v >> 19 & 0x1FFF,
                         0xC000 | v >> 6 & 0x1FFF, op & 0xFC0F | (v & 0x3F) << 4)


def apply(rom, texts, alloc, refs=None):
    """Write {offset: bytes} into rom; alloc(n) -> SAFE offset for n bytes.
    `refs`: scan_refs of the unpatched image.  Returns (in place, relocated)."""
    refs = refs if refs is not None else scan_refs(rom)
    targets = sorted(refs)
    items = item_names(rom)
    done = [0, 0]
    for addr, data in sorted(texts.items()):
        if addr in items:                              # fixed item name field
            if len(data) > ITEM_NAME_LEN or rom[addr + ITEM_NAME_LEN]:
                raise ValueError(f'{addr:#x} {items[addr]}: {len(data)} B > item name {ITEM_NAME_LEN} B')
            rom[addr:addr + ITEM_NAME_LEN] = data.ljust(ITEM_NAME_LEN, b'\0')
            done[0] += 1
            continue
        if len(data) > FIELDS.get(addr, len(data)):
            raise ValueError(f'{addr:#x}: {len(data)} B > profile field {FIELDS[addr]} B')
        n = rom.index(0, addr) - addr
        slot = (n + 4) & ~3
        shared = any(addr < t < addr + slot for t in targets)
        if len(data) < slot and not shared:
            rom[addr:addr + slot] = data.ljust(slot, b'\0')
            done[0] += 1
            continue
        if addr not in refs:
            raise ValueError(f'{addr:#x}: {len(data)} B > slot {slot} and no reference to move')
        new = alloc(len(data) + 1)
        rom[new:new + len(data) + 1] = data + b'\0'
        for kind, off in refs[addr]:
            _retarget(rom, kind, off, new)
        done[1] += 1
    return tuple(done)


def load(path):
    rev = charmap()
    return {int(k, 16): encode(v, rev) for k, v in json.load(open(path)).items()}
