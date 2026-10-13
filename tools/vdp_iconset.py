"""A VDP that installs one menu icon set and nothing else (P's).

    python3 tools/vdp_iconset.py VDP069_DIR OUT_DIR

The leftover iD L icon sets in the P's ROM (sprite list rows 313-352) are
two 128x28 bars and ten 24x28 icons each; three of them are complete:

    yellow   bars 343/348, icons 313 + 3k
    heart    bars 344/349, icons 314 + 3k
    silver   bars 347/352, icons 315 + 3k

Template: vdp-069 (Neliatchi), a one-file VDP whose loader hangs the
pierce's own loading icon in the link animation.  (vdp-001's older loader
hangs the firmware's Halloween pumpkins -- a seasonal room item -- whatever
the pierce carries, so it must not be used.)
Its unpacked payload is a 4 KB pierce header, then whole packets:

    0x0A  8 codes   destination name shown under the door icon
    0x12  u32       bytes of an extra block after the characters (0 here)
    0x16  u32       bytes of the character packets incl. padding -- the
                    firmware skips this much to reach the other contents
    0x1B  u8        raisable characters (one 0x180 block each from 0x20)
    0xF24 u16 x 10  contents per kind: meal, snack, toy, menu icons,
                    accessory, clothes, minigame, ?, outing, living
                    (vdp-001: 1 1 0 1 0 0 1 0 0 2 -- exactly its packets)

The new payload keeps the header with no character and only the icon
count set, followed by the template's own icon packet (dest 81 04 29
02) with its 12-frame bank swapped for the ROM set.  Only one icon set can
be held at a time, so each VDP carries exactly one.
"""
import glob, os, struct, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from tama4u import charset, container, vdp

ROM = open(os.path.expanduser('~/Downloads/TMGC_PS.BIN'), 'rb').read()

# sprite list rows 313..352 -> ROM addresses
ROWS = dict(zip(range(313, 353), [
    0x139710, 0x139880, 0x1399EC, 0x139B5C, 0x139CC8, 0x139E30, 0x139F9C, 0x13A108,
    0x13A270, 0x13A3DC, 0x13A548, 0x13A6B4, 0x13A824, 0x13A990, 0x13AAF8, 0x13AC68,
    0x13ADD4, 0x13AF40, 0x13B0B0, 0x13B220, 0x13B38C, 0x13B500, 0x13B66C, 0x13B7D8,
    0x13B948, 0x13BAB4, 0x13BC1C, 0x13BD88, 0x13BEF4, 0x13C05C, 0x13C1C8, 0x13C8E0,
    0x13CFF4, 0x13D708, 0x13DE20, 0x13E538, 0x13EC50, 0x13F364, 0x13FA78, 0x140190]))
SETS = {  # name: (bar row offset, icon variant, dest name, item name, serial)
    'yellow': (0, 0, 'ICONYELW', 'YELLOW', 0x5A01),
    'heart':  (1, 1, 'ICONHART', 'HEART', 0x5A02),
    'silver': (4, 2, 'ICONSLVR', 'SILVER', 0x5A03),
}
# loading icon (24x24) per set: sprite list rows 988 star, 923 heart, 989 sun
LOADING = {'yellow': 0x2011B4, 'heart': 0x1F910C, 'silver': 0x2012E4}
# The loading icon rides in the pierce's extra block (header 0x12 bytes,
# right after the character slots): 0xEE reserved zero bytes, then
# [u16 L][placeholder living 81 07 1f 00, 2x2 dummy] [u16 L][loading icon
# 81 01 01 01: two 2x2 dummies + the 24x24 icon], where each u16 is the
# distance from its own end to the next u16.  Taken from vdp-069
# (Neliatchi), the single-file VDP that has one.

TABLE = 0xF24
ICON_KIND = 3                 # 4th count: menu icons
BANK = 0x100                  # icon packet: u16 frame count, then records


def record(a):
    """ROM sprite record [w,h,nc,0,n,FF][palette][pixels] as bytes."""
    w, h, nc, _, n, _ = ROM[a:a + 6]
    return ROM[a:a + 6 + 2 * nc + n * w * h // 2]


def frames(bar, var):
    rows = [343 + bar, 348 + bar] + [313 + 3 * k + var for k in range(10)]
    return [record(ROWS[r]) for r in rows]


def icon_packet(tmpl, recs, name, serial):
    raw = bytearray(tmpl.raw[:BANK])
    raw += struct.pack('>H', len(recs))
    for r in recs:
        raw += struct.pack('>H', len(r)) + r
    raw += b'\x00\x00'                                   # checksum
    struct.pack_into('>H', raw, container.OFF_PACKET_SIZE, len(raw))
    struct.pack_into('>H', raw, container.OFF_SERIAL, serial)
    p = container.Packet(bytes(raw), 0)
    lay = p.layout
    p.raw[lay['name']:lay['name'] + lay['slots']] = bytes(lay['slots'])
    charset.write_text(p.raw, lay['name'], lay['slots'], name,
                       charset.load_table(model=p.model), lay['width'])
    struct.pack_into('>H', p.raw, len(p.raw) - 2, container.sum16(p.raw[:-2]))
    return bytes(p.raw)


def preview(recs):
    """JPEG preview: top bar, the ten icons, bottom bar (Pillow, optional)."""
    try:
        from PIL import Image
    except ImportError:
        return None
    import io
    def img(r):
        w, h, nc = r[0], r[1], r[2]; pal = []
        for j in range(nc):
            v = r[6 + 2 * j] << 8 | r[7 + 2 * j]
            pal.append(((v & 31) << 3, ((v >> 5) & 63) << 2, (v >> 11) << 3))
        px = r[6 + 2 * nc:]
        im = Image.new('RGB', (w, h), (255, 255, 255))
        im.putdata([pal[c] if c else (255, 255, 255)
                    for c in ((px[i // 2] >> 4) if i & 1 else px[i // 2] & 15 for i in range(w * h))])
        return im
    page = Image.new('RGB', (128, 128), (255, 255, 255))
    page.paste(img(recs[0]), (0, 0)); page.paste(img(recs[1]), (0, 100))
    for k, r in enumerate(recs[2:]):
        page.paste(img(r), (4 + (k % 5) * 24, 30 + (k // 5) * 36))
    buf = io.BytesIO(); page.save(buf, 'JPEG', quality=85)
    return buf.getvalue()


def extra_block(nelia_dir, key, serial):
    """(block bytes up to the first content's u16) for one loading icon."""
    f = sorted(glob.glob(os.path.join(nelia_dir, '*.jpg')))[0]
    main = container.parse_file(open(f, 'rb').read())[1][0]
    data, base, subs = vdp.sub_packets(main)
    data = bytes(data)
    x12, x16 = struct.unpack_from('>II', data, 0x12)
    start = 0x1002 + x16
    load = [p for p in subs if bytes(p.raw[0x4E:0x52]).hex() == '81010101'][0]
    lo = base + load.offset
    part1 = data[start:lo - 2]                          # zeros + living + pad
    raw = bytes(load.raw)
    n = struct.unpack_from('>H', raw, BANK)[0]; o = BANK + 2
    frames_ = []
    for i in range(n):
        ss = struct.unpack_from('>H', raw, o)[0]; frames_.append(raw[o + 2:o + 2 + ss]); o += 2 + ss
    frames_[-1] = record(LOADING[key])
    pk = bytearray(raw[:BANK]) + struct.pack('>H', n)
    for r in frames_:
        pk += struct.pack('>H', len(r)) + r
    pk += b'\x00\x00'
    struct.pack_into('>H', pk, container.OFF_PACKET_SIZE, len(pk))
    struct.pack_into('>H', pk, container.OFF_SERIAL, serial + 0x100)
    struct.pack_into('>H', pk, len(pk) - 2, container.sum16(pk[:-2]))
    rel = len(part1) + 2 + len(pk)                     # end of the packet
    nxt = rel + 2
    while nxt % 4: nxt += 1                             # next packet 4-aligned
    block = part1 + struct.pack('>H', nxt - 2 - len(part1) - 2) + bytes(pk)
    block += bytes(nxt - 2 - len(block))
    return block                                         # icon u16 goes next


def build(vdp_dir, key, nelia_dir=None):
    bar, var, dname, iname, serial = SETS[key]
    f = sorted(glob.glob(os.path.join(vdp_dir, '*.jpg')))[0]
    jpeg, pkts, trailing = container.parse_file(open(f, 'rb').read())
    main = pkts[0]
    data, base, subs = vdp.sub_packets(main)
    icon = [s for s in subs if bytes(s.raw[0x4E:0x52]).hex() == vdp.ICON_DEST][0]
    head = bytearray(data[:base + subs[0].offset])
    head[vdp.CHAR_COUNT_AT] = 0
    # the firmware finds the contents by skipping these sections: u32 at 0x12
    # (vdp+ extra block) and u32 at 0x16 (character packets incl. padding,
    # vdp-001: 0x39BA = 14664 + 0x72).  Left at the template's value it read
    # the icon set 14,778 bytes past the real one (blank bars).
    struct.pack_into('>II', head, 0x12, 0, 0)
    extra = extra_block(nelia_dir, key, serial) if nelia_dir else b''
    for k in range(10):
        struct.pack_into('>H', head, TABLE + 2 * k, 1 if k == ICON_KIND else 0)
    table = charset.load_table(model="P's")
    charset.write_text(head, vdp.DEST_NAME, vdp.DEST_NAME_LEN, dname, table, 1)
    last = subs[-1]
    tail = bytes(data[base + last.offset + last.size:])
    recs = frames(bar, var)
    ipk = icon_packet(icon, recs, iname, serial)
    if extra:
        extra += struct.pack('>H', len(ipk) + 2)
        struct.pack_into('>I', head, 0x12, len(extra))   # icon starts at 0x1002 + this
    payload = bytes(head) + extra + ipk + tail
    jpeg = preview(recs) or jpeg
    blob = bytearray(vdp.repack(main, payload))
    struct.pack_into('>H', blob, container.OFF_PACKET_SIZE, len(blob))
    struct.pack_into('>H', blob, container.OFF_SERIAL, serial)
    pk = container.Packet(bytes(blob), 0)
    lay = pk.layout
    charset.write_text(pk.raw, lay['name'], lay['slots'], 'ICON★' + iname[:4],
                       charset.load_table(model=pk.model), lay['width'])
    uname = f'DL_iDNA_ICON-{key[0].upper()}.jpg'.encode('utf-16-be')
    assert len(uname) <= container.OFF_FILE_SIZE - container.OFF_UNICODE_NAME
    pk.raw[container.OFF_UNICODE_NAME:container.OFF_FILE_SIZE] = uname.ljust(
        container.OFF_FILE_SIZE - container.OFF_UNICODE_NAME, b'\0')
    aid = f'idn_od{serial:05d}_01'.encode()
    assert len(aid) <= container.OFF_PACKET_SIZE - container.OFF_ANSI_ID
    pk.raw[container.OFF_ANSI_ID:container.OFF_PACKET_SIZE] = aid.ljust(
        container.OFF_PACKET_SIZE - container.OFF_ANSI_ID, b'\0')
    struct.pack_into('>H', pk.raw, container.OFF_FILE_SIZE, pk.size)      # vdp-001: = packet size
    struct.pack_into('>H', pk.raw, len(pk.raw) - 2, container.sum16(pk.raw[:-2]))
    return jpeg + bytes(pk.raw) + trailing, payload


if __name__ == '__main__':
    src, dst = sys.argv[1], sys.argv[2]
    os.makedirs(dst, exist_ok=True)
    for key in SETS:
        blob, _ = build(src, key, src)          # loader, header and extra block from vdp-069
        path = os.path.join(dst, f'ICON-{key.upper()}.jpg')
        open(path, 'wb').write(blob)
        print(path, len(blob))
