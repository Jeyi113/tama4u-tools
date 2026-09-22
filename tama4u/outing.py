"""Free-form sprite resize for Tamagotchi P's outing (VDP destination) items.

Bandai's outing runtime copies the item to a fixed exec buffer at CPU
0x02000000 and runs it there.  The item's S1C33 code addresses its own
sprites and dialogue by *absolute* address (0x02000000 + file offset), so
growing or shrinking one sprite record shifts everything after it and every
baked reference past the edit point must be adjusted by the same delta.

Six things move together (all confirmed on hardware):
  1. the sprite record itself (re-encoded, 4-byte aligned)
  2. every ``xld.w rX, 0x02000000+off`` immediate in the code (scanned from the
     real entry at 0x104 -- the entry stub before 0x200 references the walk
     frames and the loading icon, so a scan that starts at 0x200 misses them)
  3. the dialogue string pointer table (LE32 pointers stored as *data*, indexed
     by ``[base + state*4]`` in the entry stub)
  4. the copy-size field at 0x102-0x103 (big-endian = item_len - 0x106)
  5. the packet-size field at 0x4A (big-endian = item_len)
  6. the trailing sum16 checksum
"""

import struct
from . import sprites, container

EXEC_BASE = 0x02000000
CODE_START = 0x104          # real entry point (0x02000000 + BE32 at 0xA4..0xA7)


def _sext(v, bits):
    m = 1 << (bits - 1)
    return (v ^ m) - m


def _code_refs(item, lo=CODE_START, hi=None):
    """Yield (pc, imm) for every ext-extended ``xld.w`` in the code region.

    A pure S1C33 walk from the entry point; verified to match the emulator's
    disassembler exactly.  Only immediates that resolve to an exec-buffer
    address are of interest to the caller.  ``hi`` defaults to the first loose
    sprite record (where code ends and data begins).
    """
    if hi is None:
        recs = sprites.scan_loose(item)
        hi = recs[0][0] if recs else len(item)
    pc = lo
    while pc < hi - 1:
        start = pc                                  # first ext (instruction start)
        hw = struct.unpack_from('<H', item, pc)[0]
        ext_n = 0
        ext0 = ext1 = 0
        while (hw >> 13) == 6:
            if ext_n == 0:
                ext0 = hw & 0x1FFF
            elif ext_n == 1:
                ext1 = hw & 0x1FFF
            else:
                break
            ext_n += 1
            pc += 2
            if pc >= hi - 1:
                return
            hw = struct.unpack_from('<H', item, pc)[0]
        cls = hw >> 13
        if cls == 3 and ext_n == 2:                 # two-ext class-3 ALU immediate
            op1 = (hw >> 10) & 7
            imm6 = (hw >> 4) & 0x3F
            imm = (ext0 << 19) | (ext1 << 6) | imm6
            if op1 == 3:                            # ld.w rd, imm
                yield start, imm                    # start = first ext prefix
        pc += 2


def _reencode_ldw(item, pc, new_imm):
    """Rewrite a two-ext ``xld.w`` in place to carry new_imm (length unchanged)."""
    struct.pack_into('<H', item, pc, 0xC000 | ((new_imm >> 19) & 0x1FFF))
    struct.pack_into('<H', item, pc + 2, 0xC000 | ((new_imm >> 6) & 0x1FFF))
    base = struct.unpack_from('<H', item, pc + 4)[0]
    base = (base & ~(0x3F << 4)) | ((new_imm & 0x3F) << 4)
    struct.pack_into('<H', item, pc + 4, base)


def _is_exec_ptr(v, item_len, base):
    return base <= v <= base + item_len


def _detect_base(item):
    """Find the exec-buffer base the item's code addresses itself with.

    The buffer address is device-specific -- P's/4U/iD L map the running outing
    at 0x02000000, the iD at 0x00FF0000 -- but every sprite reference in the
    code is base + record_offset, so the base is the offset that the most
    ``ld.w`` immediates share with a loose record start.  Falls back to the P's
    value when nothing lines up (e.g. no sprites).
    """
    recs = sprites.scan_loose(item)
    starts = [r[0] for r in recs]
    if not starts:
        return EXEC_BASE
    votes = {}
    for _pc, imm in _code_refs(item):
        for o in starts:
            b = imm - o
            if b > 0:
                votes[b] = votes.get(b, 0) + 1
    if not votes:
        return EXEC_BASE
    return max(votes, key=votes.get)


def resize_sprite(item, index, width, height, palette, pixel_lists):
    """Replace loose sprite ``index`` and fix every baked reference.

    ``item`` is a full TAMAGO outing record (bytes).  The sprite is rebuilt
    from ``width``/``height``/``palette``/``pixel_lists`` at whatever size that
    implies; the rest of the item shifts and all references are patched.
    Returns the new item bytes.
    """
    item = bytearray(item)
    orig = bytes(item)
    orig_len = len(orig)
    base = _detect_base(orig)             # exec-buffer address (device-specific)

    recs = sprites.scan_loose(orig)
    rec = recs[index]
    start = rec[0]
    old_len = sprites.loose_span(tuple(rec))
    blob = sprites.encode_loose(width, height,
                                [tuple(c) for c in palette], pixel_lists)
    delta = len(blob) - old_len
    grow_point = start + old_len          # offsets >= here shift by delta

    # Locate references and dialogue tables on the ORIGINAL layout.
    refs = [(pc, imm) for pc, imm in _code_refs(orig)
            if _is_exec_ptr(imm, orig_len, base)]

    # A code ref whose target holds back-to-back exec pointers is a pointer
    # table (the dialogue strings); a ref into a sprite/record is not.
    tables = []
    for _pc, imm in refs:
        fo = imm - base
        if fo + 8 <= orig_len:
            a = struct.unpack_from('<I', orig, fo)[0]
            b = struct.unpack_from('<I', orig, fo + 4)[0]
            if _is_exec_ptr(a, orig_len, base) and _is_exec_ptr(b, orig_len, base):
                tables.append(fo)

    # 1. splice the new record in (code region precedes grow_point, unaffected)
    item[start:start + old_len] = blob

    # 2. patch code immediates that point past the edit
    for pc, imm in refs:
        if imm - base >= grow_point:
            _reencode_ldw(item, pc, imm + delta)

    # 3. patch each dialogue pointer table's entries (table itself has shifted)
    for fo in tables:
        a = fo + (delta if fo >= grow_point else 0)
        while a + 4 <= len(item):
            v = struct.unpack_from('<I', item, a)[0]
            if _is_exec_ptr(v, orig_len, base) and (v - base) >= grow_point:
                struct.pack_into('<I', item, a, v + delta)
                a += 4
            elif _is_exec_ptr(v, orig_len, base):    # pointer before edit: keep
                a += 4
            else:
                break

    # 4/5. size fields.  The P's runtime keeps a copy-size at 0x102-0x103
    # (big-endian, = item_len - 0x106); the 4U leaves it zero and sizes the
    # copy another way, so only refresh it when the source used it.
    if struct.unpack_from('>H', orig, 0x102)[0] != 0:
        struct.pack_into('>H', item, 0x102, len(item) - 0x106)
    struct.pack_into('>H', item, 0x4A, len(item))            # packet size
    # 6. checksum
    struct.pack_into('>H', item, len(item) - 2,
                     container.sum16(item[:-2]))
    return bytes(item)
