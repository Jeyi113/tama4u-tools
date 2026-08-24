"""Tamagotchi 4U download packet container.

File layout: JPEG preview + one or more TAMAGO packets appended.
A packet may nest child packets (download characters embed their
clothes packet), or be followed by sibling packets (bundles).
Last 2 bytes of every packet = big-endian sum16 of all preceding bytes.
"""
import struct

from . import models

MAGIC = b'TAMAGO'

# header offsets (relative to packet start)
OFF_UNICODE_NAME = 0x06   # UTF-16BE "DL_T4Ux_<name>.jpg", null padded
OFF_FILE_SIZE    = 0x32   # u16 BE, declared size of full download file
OFF_ANSI_ID      = 0x34   # ASCII "t4u_gh01855_1", null padded
OFF_PACKET_SIZE  = 0x4A   # u16 BE, size of this packet incl. checksum
OFF_TYPE_SIG     = 0x4C   # 6 bytes, per record-type signature
OFF_TOKEN        = 0x52   # 8 bytes, per-file token (purpose unknown)
OFF_SERIAL       = 0x5A   # u16 BE
OFF_ITEM_NAME    = 0x5E   # u16 BE x 9, internal charset
OFF_BODY         = 0x200  # stat blocks end / sprite bank or char stats start


def sum16(data):
    return sum(data) & 0xFFFF


class Packet:
    def __init__(self, data, offset=0):
        """data: full file bytes; offset: packet start (at MAGIC)."""
        self.offset = offset
        size = struct.unpack_from('>H', data, offset + OFF_PACKET_SIZE)[0]
        self.raw = bytearray(data[offset:offset + size])
        self._orig = bytes(self.raw)
        self.children = []
        # nested packets live inside this packet's extent
        pos = self.raw.find(MAGIC, len(MAGIC))
        while pos != -1:
            declared = struct.unpack_from('>H', self.raw, pos + OFF_PACKET_SIZE)[0] \
                if pos + OFF_PACKET_SIZE + 2 <= len(self.raw) else 0
            if declared < 0x60 or pos + declared > len(self.raw):
                # false MAGIC inside pixel data — skip past it
                pos = self.raw.find(MAGIC, pos + len(MAGIC))
                continue
            child = Packet(bytes(self.raw), pos)
            self.children.append(child)
            pos = self.raw.find(MAGIC, pos + child.size)

    # --- fields -----------------------------------------------------
    @property
    def size(self):
        return len(self.raw)

    @property
    def unicode_name(self):
        u = self.raw[OFF_UNICODE_NAME:OFF_FILE_SIZE]
        chars = [int.from_bytes(u[i:i + 2], 'big') for i in range(0, len(u), 2)]
        out = []
        for c in chars:
            if c == 0:
                break
            out.append(chr(c))
        return ''.join(out)

    @property
    def ansi_id(self):
        raw = self.raw[OFF_ANSI_ID:OFF_PACKET_SIZE]
        return raw.split(b'\x00')[0].decode('ascii', 'replace')

    @property
    def type_sig(self):
        return bytes(self.raw[OFF_TYPE_SIG:OFF_TYPE_SIG + 6])

    @property
    def token(self):
        return bytes(self.raw[OFF_TOKEN:OFF_TOKEN + 8])

    @property
    def serial(self):
        return struct.unpack_from('>H', self.raw, OFF_SERIAL)[0]

    @property
    def declared_size(self):
        """u16 at 0x32 — total download size (jpeg preview + packets)."""
        return struct.unpack_from('>H', self.raw, OFF_FILE_SIZE)[0]

    def shift_declared_size(self, delta):
        v = max(0, min(0xFFFF, self.declared_size + delta))
        struct.pack_into('>H', self.raw, OFF_FILE_SIZE, v)

    @property
    def section(self):
        """Shop section id at 0x4F — 1 food, 2 accessory, 3 clothes,
        4 toy, 7 interior.  Present on every model, which is the only way
        to categorise iD packets (they carry no ASCII id)."""
        return self.raw[0x4F]

    @property
    def model(self):
        """'iD' | 'iDL' | "P's" | '4U'.

        The u16 signature at 0x4C wins; the download-name prefix is only a
        fallback, because a third of the corpus ships one model's packet
        under another model's download name (see models.SIGNATURES)."""
        sig = struct.unpack_from('>H', self.raw, OFF_TYPE_SIG)[0] \
            if len(self.raw) >= OFF_TYPE_SIG + 2 else 0
        return models.from_signature(sig) or models.detect(self.unicode_name)[0]

    @property
    def packet_class(self):
        """'S' item | 'A' character | 'C' clothes."""
        return models.detect(self.unicode_name)[1]

    @property
    def layout(self):
        return models.layout(self.model)

    @property
    def item_name_codes(self):
        lay = self.layout
        off, width, slots = lay['name'], lay['width'], lay['slots']
        if width == 1:
            codes = list(self.raw[off:off + slots])
        else:
            codes = [struct.unpack_from('>H', self.raw, off + 2 * i)[0]
                     for i in range(slots)]
        out = []
        for c in codes:
            if c == 0:
                break
            out.append(c)
        return out

    @property
    def kind(self):
        """'gh', 'oy', 'fk', 'ac', 'as', 'bg', 'gm', 'rec', 'dlode', ...
        derived from the ansi id (t4u_<kind><number>...)."""
        s = self.ansi_id
        for pre in ('t4u_', 'id2_', 'idn_'):
            if s.startswith(pre):
                s = s[len(pre):]
                break
        out = []
        for ch in s:
            if not ch.isalpha():
                break
            out.append(ch)
        return ''.join(out) or '?'

    # --- setters ----------------------------------------------------
    def set_serial(self, value):
        struct.pack_into('>H', self.raw, OFF_SERIAL, value)
        # keep the ASCII id's digits in sync: t4u_gh01855_1
        old = self.ansi_id
        if old.startswith('t4u_') and self.kind != '?':
            head = 't4u_' + self.kind
            tail = old[len(head):]                     # "01855_1"
            digits = ''
            for ch in tail:
                if not ch.isdigit():
                    break
                digits += ch
            new = f'{head}{value:0{len(digits) or 5}d}{tail[len(digits):]}'
            field = new.encode('ascii')[:OFF_PACKET_SIZE - OFF_ANSI_ID]
            field += b'\x00' * (OFF_PACKET_SIZE - OFF_ANSI_ID - len(field))
            self.raw[OFF_ANSI_ID:OFF_PACKET_SIZE] = field

    def set_item_name_codes(self, codes):
        lay = self.layout
        off, width, slots = lay['name'], lay['width'], lay['slots']
        if len(codes) > slots:
            raise ValueError(f'item name is limited to {slots} characters')
        codes = list(codes) + [0] * (slots - len(codes))
        if width == 1:
            self.raw[off:off + slots] = bytes(codes)
        else:
            for i, c in enumerate(codes):
                struct.pack_into('>H', self.raw, off + 2 * i, c)

    def set_unicode_name(self, name):
        """Set <name> in "DL_T4Ux_<name>.jpg" (variant letter kept)."""
        cur = self.unicode_name
        head = cur[:cur.index('_', 3) + 1] if '_' in cur[3:] else 'DL_T4US_'
        full = f'{head}{name}.jpg'
        if len(full) * 2 > OFF_FILE_SIZE - OFF_UNICODE_NAME:
            raise ValueError('unicode name too long')
        buf = bytearray(OFF_FILE_SIZE - OFF_UNICODE_NAME)
        for i, ch in enumerate(full):
            struct.pack_into('>H', buf, 2 * i, ord(ch))
        self.raw[OFF_UNICODE_NAME:OFF_FILE_SIZE] = buf

    # --- integrity --------------------------------------------------
    def checksum_ok(self):
        return sum16(self.raw[:-2]) == struct.unpack('>H', self.raw[-2:])[0]

    def fix_checksums(self):
        """Recompute nested checksums first, then own.

        Untouched packets keep their original trailing bytes verbatim:
        a few retail files ship a stale nested checksum that the device
        accepts, and silently "fixing" it would alter bytes we never
        edited.  Only packets whose body actually changed get a new sum.
        """
        for child in self.children:
            child.fix_checksums()
            self.raw[child.offset:child.offset + child.size] = child.raw
        if bytes(self.raw[:-2]) == self._orig[:-2]:
            self.raw[-2:] = self._orig[-2:]
        else:
            struct.pack_into('>H', self.raw, self.size - 2, sum16(self.raw[:-2]))


def parse_file(path_or_bytes):
    """Return (jpeg_bytes, [top-level Packets], trailing_bytes)."""
    data = path_or_bytes if isinstance(path_or_bytes, (bytes, bytearray)) \
        else open(path_or_bytes, 'rb').read()
    first = data.find(MAGIC)
    if first == -1:
        raise ValueError('no TAMAGO packet found')
    jpeg, packets, pos = data[:first], [], first
    while True:
        pkt = Packet(data, pos)
        packets.append(pkt)
        pos += pkt.size
        nxt = data.find(MAGIC, pos)
        if nxt == -1:
            break
        pos = nxt
    return jpeg, packets, data[pos:]


def build_file(jpeg, packets, trailing=b''):
    for p in packets:
        p.fix_checksums()
    return jpeg + b''.join(bytes(p.raw) for p in packets) + trailing
