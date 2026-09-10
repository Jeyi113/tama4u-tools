"""Sprite bank codec, shared by every packet type.

Bank (at packet offset 0x200 for item packets, and at +0x200 inside a
character's nested clothes packet):
    u16 BE frame_count, then frame records back to back.
Record:
    u16 BE slot_size   (bytes following this field; fixed per pose slot,
                        unused space zero-padded)
    u8 width, u8 height, u8 n_colors, u8 zero
    u16 BE 0x01FF
    n_colors x u16 BE palette, BGR565 (palette[0] = transparent)
    width*height/2 bytes of 4bpp pixels, LOW nibble = left pixel

Records with more than 16 colours store one byte per pixel instead.  The
games use them for their backgrounds and item strips -- Choco Catch keeps
its 16 falling hearts and chocolates as one 16x16 x16 record of 42
colours -- and reading those as 4bpp both halves the pixel data and
rejects the record outright on the palette-size check.
"""
import struct

BANK_OFFSET = 0x200
PAL4_MAX = 16           # <=16 colours -> 4bpp, more -> 8bpp


def bpp_for(ncol):
    return 4 if ncol <= PAL4_MAX else 8


def pixel_bytes(w, h, nf, ncol):
    return nf * (w * h if ncol > PAL4_MAX else (w * h + 1) // 2)


def unpack_pixels(buf, ncol):
    if ncol > PAL4_MAX:
        return list(buf)
    px = []
    for byte in buf:
        px += [byte & 0xF, byte >> 4]
    return px


def pack_pixels(px, ncol):
    if ncol > PAL4_MAX:
        return bytes(px)
    return bytes((px[i + 1] << 4 | px[i]) for i in range(0, len(px) - 1, 2))


def bgr565_to_rgb(v):
    b, g, r = v >> 11 & 0x1F, v >> 5 & 0x3F, v & 0x1F
    return (r << 3 | r >> 2, g << 2 | g >> 4, b << 3 | b >> 2)


def rgb_to_bgr565(rgb):
    r, g, b = rgb
    return (b >> 3) << 11 | (g >> 2) << 5 | (r >> 3)


class Frame:
    def __init__(self, slot_size, width, height, palette, pixels):
        self.slot_size = slot_size          # keep on repack
        self.width, self.height = width, height
        self.palette = palette              # list[(r,g,b)]
        self.pixels = pixels                # flat list of palette indices

    def encode(self, grow=False):
        """`grow` lets the slot stretch to fit rather than refusing.

        Slots are normally fixed so the bank stays the same length and
        nothing downstream of it moves.  A 4U character's built-in
        accessory (frames 23-26) ships as 2x2, though, and a real
        accessory drawn there needs more room -- so the caller may allow
        the slot to grow and take on the job of fixing every size field
        the longer packet invalidates.
        """
        body = struct.pack('>BBBBH', self.width, self.height,
                           len(self.palette), 0, 0x01FF)
        body += b''.join(struct.pack('>H', rgb_to_bgr565(c)) for c in self.palette)
        px = list(self.pixels)
        if len(px) % 2:
            px.append(0)
        body += pack_pixels(px, len(self.palette))
        if len(body) > self.slot_size:
            if not grow:
                raise ValueError(f'frame data {len(body)} exceeds slot '
                                 f'{self.slot_size} (reduce palette size)')
            self.slot_size = len(body)
        body += b'\x00' * (self.slot_size - len(body))
        return struct.pack('>H', self.slot_size) + body


def parse_bank(raw, offset=BANK_OFFSET):
    count = struct.unpack_from('>H', raw, offset)[0]
    frames, o = [], offset + 2
    for _ in range(count):
        slot = struct.unpack_from('>H', raw, o)[0]
        w, h, ncol, zero, sig = struct.unpack_from('>BBBBH', raw, o + 2)
        if zero != 0 or sig != 0x01FF:
            raise ValueError(f'bad frame record at {o:#x}')
        pal_off = o + 8
        palette = [bgr565_to_rgb(struct.unpack_from('>H', raw, pal_off + 2 * i)[0])
                   for i in range(ncol)]
        px_off = pal_off + 2 * ncol
        pixels = unpack_pixels(
            raw[px_off:px_off + pixel_bytes(w, h, 1, ncol)], ncol)
        frames.append(Frame(slot, w, h, palette, pixels[:w * h]))
        o += 2 + slot
    return frames, o  # o = end of bank


def scan_banks(raw, start=0x60):
    """Find every frame-record chain preceded by a u16 count.

    Needed for gm/dlode/rec packets, whose banks sit at code-determined
    offsets inside a program blob.  Returns [(offset, end, frames)].
    """
    found, o = [], start
    while o < len(raw) - 8:
        n = struct.unpack_from('>H', raw, o)[0]
        if 1 <= n <= 200:
            try:
                frames, end = parse_bank(raw, o)
                if frames and end <= len(raw):
                    found.append((o, end, frames))
                    o = end
                    continue
            except (ValueError, IndexError, struct.error):
                pass
        o += 1
    return found


def scan_loose(raw, lo=0x200, hi=None):
    """Standalone frame records inside gm/dlode program blobs.

    Layout is a bank record without the u16 slot-size prefix:
    [w][h][ncol][00][nframes][0xFF][palette][pixels x nframes].
    Records are anchored on the 00+NN+FF signature and sit back to back,
    so consecutive starts differ by exactly 6 + 2*ncol + nf*w*h/2.  A record may hold several
    animation frames sharing one palette (item banks always use 1).
    Pixel data may be truncated by the next record.
    Returns [(offset, w, h, ncol, nframes, pixel_bytes_available)].
    """
    hi = hi or len(raw)
    sigs = []
    for o in range(lo + 6, hi - 2):
        if raw[o + 1] != 0xFF or not 1 <= raw[o] <= 32:
            continue
        start = o - 4
        w, h, ncol, z = raw[start], raw[start + 1], raw[start + 2], raw[start + 3]
        if z != 0 or not (2 <= w <= 128 and 2 <= h <= 128) \
                or not 1 <= ncol <= 255 or start + 6 + 2 * ncol >= hi:
            continue
        if ncol > PAL4_MAX:
            # 8bpp widens the signature a lot, so only take the record when
            # every pixel actually indexes into the palette
            px = start + 6 + 2 * ncol
            end = px + pixel_bytes(w, h, raw[o], ncol)
            if end > hi or max(raw[px:end], default=255) >= ncol:
                continue
        sigs.append((start, w, h, ncol, raw[o]))
    out = []
    for i, (start, w, h, ncol, nf) in enumerate(sigs):
        if out and start < out[-1][0] + 6 + 2 * out[-1][3]:
            continue  # inside previous record's header/palette: false hit
        px_start = start + 6 + 2 * ncol
        px_need = pixel_bytes(w, h, nf, ncol)
        px_end = min(px_start + px_need,
                     sigs[i + 1][0] if i + 1 < len(sigs) else hi)
        out.append((start, w, h, ncol, nf, max(0, px_end - px_start)))
    return out


def read_loose(raw, rec):
    """Return the record's frames (they share one palette)."""
    start, w, h, ncol, nf, avail = rec
    pal_off = start + 6
    palette = [bgr565_to_rgb(struct.unpack_from('>H', raw, pal_off + 2 * i)[0])
               for i in range(ncol)]
    px = unpack_pixels(raw[pal_off + 2 * ncol: pal_off + 2 * ncol + avail], ncol)
    px += [0] * (nf * w * h - len(px))
    per = w * h
    return [Frame(0, w, h, palette, px[k * per:(k + 1) * per])
            for k in range(nf)]


def write_loose(packet_raw, rec, palette, pixel_lists):
    """Recolor palette + repaint frames in place; structure untouched."""
    start, w, h, ncol, nf, avail = rec
    if len(palette) != ncol:
        raise ValueError('loose record: palette size must stay %d' % ncol)
    pal_off = start + 6
    for i, c in enumerate(palette):
        struct.pack_into('>H', packet_raw, pal_off + 2 * i, rgb_to_bgr565(c))
    px = [v for pixels in pixel_lists for v in pixels]
    packed = pack_pixels(px, ncol)[:avail]
    packet_raw[pal_off + 2 * ncol: pal_off + 2 * ncol + len(packed)] = packed


LOOSE_ALIGN = 4         # records sit on 4-byte boundaries (see loose_span)


def encode_loose(w, h, palette, pixel_lists):
    """A whole loose record from scratch: [w][h][ncol][00][nf][FF][pal][px].

    Unlike write_loose this is not in place -- it returns the bytes for a
    record of whatever size, so a differently-sized import can replace the
    old one.  nframes is len(pixel_lists), one shared palette.

    The record is zero-padded up to a 4-byte boundary.  The device finds the
    next record by walking from this one -- it reads this header, computes
    6 + 2*ncol + pixel_bytes, rounds *up to a multiple of 4*, and lands on the
    next record.  Retail files obey this on every record (verified across the
    whole outing set); a record left an odd length desyncs that walk and every
    later sprite draws from the wrong bytes (flicker / missing sprites)."""
    nf, ncol = len(pixel_lists), len(palette)
    out = bytes((w, h, ncol, 0, nf, 0xFF))
    out += b''.join(struct.pack('>H', rgb_to_bgr565(c)) for c in palette)
    px = [v for pixels in pixel_lists for v in pixels]
    body = out + pack_pixels(px, ncol)
    pad = (-len(body)) % LOOSE_ALIGN
    return body + b'\x00' * pad


def loose_span(rec):
    """Stride to the next record: header+palette+pixels, rounded up to 4.

    This is the walk step the device takes, so a resize must replace exactly
    this many bytes and shift the rest by a multiple of 4 to keep every later
    record on its boundary."""
    _start, w, h, ncol, nf, _avail = rec
    body = 6 + 2 * ncol + pixel_bytes(w, h, nf, ncol)
    return (body + LOOSE_ALIGN - 1) // LOOSE_ALIGN * LOOSE_ALIGN


def encode_bank(frames, grow=False):
    return struct.pack('>H', len(frames)) + b''.join(f.encode(grow) for f in frames)


def write_bank(packet_raw, frames, offset=BANK_OFFSET):
    """Encode frames back into packet_raw (bytearray) in place."""
    blob = encode_bank(frames)
    packet_raw[offset:offset + len(blob)] = blob


# --- BMP import/export (indexed; 4bpp like Tama Image Editor, 8bpp for
# the >16-colour records the games use) ------------------------------
def frame_to_bmp(frame):
    w, h = frame.width, frame.height
    ncol = max(len(frame.palette), 1)
    bpp = bpp_for(ncol)
    slots = 16 if bpp == 4 else 256
    rowsz = ((w * bpp + 31) // 32) * 4
    pal = frame.palette + [(0, 0, 0)] * (slots - len(frame.palette))
    paloff = 54 + 4 * slots
    header = struct.pack('<2sIHHI', b'BM', paloff + rowsz * h, 0, 0, paloff)
    info = struct.pack('<IiiHHIIiiII', 40, w, h, 1, bpp, 0, rowsz * h,
                       2835, 2835, slots, 0)
    paldata = b''.join(bytes((b, g, r, 0)) for r, g, b in pal)
    rows = []
    for y in range(h - 1, -1, -1):
        row = bytearray(rowsz)
        line = frame.pixels[y * w:(y + 1) * w]
        for x, v in enumerate(line):
            if bpp == 8:
                row[x] = v
            elif x % 2 == 0:
                row[x // 2] |= v << 4
            else:
                row[x // 2] |= v
        rows.append(bytes(row))
    return header + info + paldata + b''.join(rows)


def bmp_to_frame(data, slot_size):
    off = struct.unpack_from('<I', data, 10)[0]
    w = struct.unpack_from('<i', data, 18)[0]
    h = struct.unpack_from('<i', data, 22)[0]
    bpp = struct.unpack_from('<H', data, 28)[0]
    if bpp not in (4, 8):
        raise ValueError('expected a 4bpp or 8bpp indexed BMP')
    ncol = struct.unpack_from('<I', data, 46)[0] or (1 << bpp)
    palette = [tuple(data[54 + 4 * i:54 + 4 * i + 3][::-1]) for i in range(ncol)]
    rowsz = ((w * bpp + 31) // 32) * 4
    pixels = []
    for y in range(h - 1, -1, -1):
        row = data[off + y * rowsz: off + (y + 1) * rowsz]
        if bpp == 8:
            pixels += list(row[:w])
        else:
            pixels += [(row[x // 2] >> 4) if x % 2 == 0 else (row[x // 2] & 0xF)
                       for x in range(w)]
    # drop trailing duplicate colors that are all black padding
    used = max(pixels) + 1
    return Frame(slot_size, w, h, palette[:max(used, 1)], pixels)
