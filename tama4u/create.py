"""Build a new download from nothing but a model and a category.

A retail item turns out to be almost entirely fields we already read: strip
the ones `editor.describe` reports and the header is zero all the way to the
sprite bank -- exactly zero unexplained bytes on a P's meal or a 4U
accessory, one on an iD L dress.  So a blank item can be written out rather
than copied from a retail file, which is the only way to ship this at all:
none of the download packs may go in the repository.

`reproduce()` is the proof.  Given a real packet it rebuilds one from that
packet's own field values and compares byte for byte -- if synthesis can
reproduce the retail files it can be trusted to make new ones.
`tests/test_create.py` runs it over whole packs.

Sizes follow the category rather than a fixed template.  The frame count is
what that category always has (three for a meal, twenty-eight for clothes,
one for a room), and each frame's slot is only as big as its own pixels and
palette need, so a 4-colour sprite costs less than a 16-colour one and the
file comes out as small as the rules allow.
"""
import collections
import struct

from . import charset, container, destinations, items, models, sprites

# Frames a category carries, measured across the four packs: (w, h) per
# frame.  Where a model differs it gets its own entry; '*' is every other.
#
# Toys are the exception and get TOY_SHAPES instead: how many frames one
# has is what its animation does, so there is no single right answer.
#
# Every category is offered the same sixteen colours, which is the most a
# 4-bit pixel can index.  What the packs actually contain is narrower, and
# worth knowing before blaming the tool for a file the device refuses:
#
#   옷            iD L 16 · P's 16 · 4U 8      (4U never goes past eight)
#   악세사리       iD 16 · iD L 16 · P's 16 · 4U 9
#   장난감         iD 17 · P's 17 · iD L 16 · 4U 16
#   방 · 식사 · 간식  전 기종 16
#
# So a sixteen-colour 4U dress has no retail precedent -- it stays inside
# the codec, but nothing in the packs vouches for it.  Toys are the other
# way round: seventeen colours do occur, and those frames switch to 8 bits
# per pixel and cost twice as much, which is why the ceiling stops at 16.
BLUEPRINTS = {
    ('*', '레스토랑 · 식사'):             [(24, 24)] * 3,
    ('*', '레스토랑 · 간식'):             [(24, 24)] * 3,
    ('*', '레스토랑 · 식사 (비매품)'):      [(24, 24)] * 3,
    ('*', '레스토랑 · 간식 (비매품)'):      [(24, 24)] * 3,
    ('*', '냉장고 직행 · 식사 (비매품)'):    [(24, 24)] * 3,
    ('*', '냉장고 직행 · 간식 (비매품)'):    [(24, 24)] * 3,
    ('*', '타마베이커리 · 간식'):          [(24, 24)] * 3,
    ('*', '고치 인테리어 · 방'):           [(128, 72)],
    ('*', '타마모리 · 옷'):               [(30, 12)] * 28,
    ('*', '타마모리 · 액세서리'):          [(30, 20)] * 3 + [(44, 30)],
    ('*', "타마모리 · 액세서리 (P's용)"):   [(30, 20)] * 3 + [(44, 30)],
    ('*', '타마모리 · 액세서리 2'):        [(30, 20)] * 3 + [(44, 30)],
    ('*', '타마데파 · 생활용품'):          [(24, 24)],
    ('iD', '타마모리 · 액세서리'):         [(24, 24), (30, 30), (36, 36), (60, 60),
                                        (24, 24), (30, 30), (36, 36)],
    ('iD', '사진관 · 의상'):              [(48, 48)] * 6,
    ('iD', '사진관 · 배경'):              [(120, 64)],
    ('iD', '우편함 · 편지'):              [(32, 32)],
}

# A toy's frame count is its animation.  Across all four packs the shape
# follows the count rather than the model -- every three-frame toy is
# 32x30, 48x32, 40x20 whoever made it -- and the animation bytes follow it
# too, so the two travel together here.  Counts are 1, 2, 3, 4, 6, 7 and 8;
# five never occurs.
TOY_LABEL = '타마데파 · 장난감'
TOY_SHAPES = {
    1: ([(32, 30)], (44, 44)),
    2: ([(32, 30), (32, 48)], (28, 28)),
    3: ([(32, 30), (48, 32), (40, 20)], (25, 25)),
    4: ([(32, 30), (24, 24), (24, 24), (24, 24)], (22, 22)),
    6: ([(32, 30), (40, 28), (40, 20), (40, 20), (56, 32), (48, 32)], (48, 54)),
    7: ([(32, 30), (40, 28), (40, 20), (40, 20), (56, 32), (48, 32),
         (16, 16)], (5, 5)),
    8: ([(32, 30), (24, 30), (24, 64), (24, 30), (24, 64), (24, 30),
         (24, 64), (16, 16)], (11, 8)),
}
TOY_DEFAULT = 4          # the commonest, 281 of 566


def toy_counts():
    return sorted(TOY_SHAPES)


def toy_anim(nframes):
    """The animation bytes retail toys pair with that many frames."""
    got = TOY_SHAPES.get(nframes)
    return got[1] if got else None


# Categories that are program blobs or need a stat block this cannot write.
# Categories whose body is S1C33 machine code.  Nothing here can write a
# game, but a new game file can still be made *from* one: the code comes
# from a download you already have and only the identity is rewritten.
FROM_BASE = {
    '게임센터 · 게임': '게임',
    '외출지': '외출지',
    'VDP · 아이템 묶음': 'VDP 묶음',
}

UNSUPPORTED = {
    '카드 · 캐릭터 프로그램': '캐릭터는 스탯 블록과 대사가 필요합니다 — '
                              '기존 캐릭터 파일을 불러와 편집하세요',
    '우편함 · 편지': '편지는 본문이 스탯 자리에 들어갑니다 — '
                     '기존 편지를 불러와 편집하세요',
    '보물상자 · 편지': '편지는 본문이 스탯 자리에 들어갑니다 — '
                       '기존 편지를 불러와 편집하세요',
    '우편함 · 해피메일': '해피메일은 보상 아이템을 품는 구조라 '
                         '기존 파일을 편집하는 편이 안전합니다',
    '보물상자 · 스탬프카드': '스탬프카드는 보상 아이템을 품는 구조라 '
                             '기존 파일을 편집하는 편이 안전합니다',
    '통신놀이 · 레시피': '레시피는 보상 아이템을 품는 구조라 '
                         '기존 파일을 편집하는 편이 안전합니다',
    '빙고 정의': '빙고 정의는 아이템을 품는 구조라 '
                 '기존 파일을 편집하는 편이 안전합니다',
    '타마데파 · 씨앗': '씨앗은 보상 아이템을 품는 구조라 '
                       '기존 파일을 편집하는 편이 안전합니다',
    '메뉴 아이콘 세트': 'VDP 전용 패킷입니다',
    '로딩 아이콘': 'VDP 전용 패킷입니다',
}
# iD costumes shift 0x63; every other model leaves it zero.  It is the only
# byte outside the known fields that a fresh item of these categories needs.
EXTRA_BYTES = {
    ('iD', '타마데파 · 장난감'): {0x63: 0x02},
    ('iD', '사진관 · 배경'): {0x63: 0x02},
    ('iD', '레스토랑 · 식사'): {0x63: 0x02},
    ('iD', '레스토랑 · 간식'): {0x63: 0x02},
    ('4U', '레스토랑 · 식사'): {0x73: 0x02},
    ('iDL', '레스토랑 · 식사'): {0x69: 0x02},
    ('iDL', '레스토랑 · 간식'): {0x69: 0x02},
    ("P's", '레스토랑 · 식사'): {0x69: 0x02},
    ("P's", '레스토랑 · 간식'): {0x69: 0x02},
    ('4U', '레스토랑 · 간식'): {0x73: 0x02},
    ('4U', '고치 인테리어 · 방'): {0x70: 0x04},
}

# Bytes that vary item by item and that nothing here can derive.  Accessories
# and clothes keep one at 0xA8 (values 3 to 30 with no favourite), 4U snacks
# one at 0xB2 (1 to 4).  Reproduction copies them; a new item leaves them at
# whatever EXTRA_BYTES says, which for these is nothing.
# iD keeps a per-file block at 0xF0-0xF7, right in front of the two
# firmware words.  0xF3 is always 03 and the three bytes after it vary the
# way a date would (02 09 0d, 04 07 0c, 03 08 1b); only about a fifth of iD
# items carry it at all.  Undecoded, so it travels as-is.
MODEL_CARRY = {'iD': tuple(range(0xF0, 0xF8))}

CARRY_OVER = {
    ("P's", '타마모리 · 액세서리'): (0xA8,),
    ("P's", '타마모리 · 액세서리 2'): (0xA8,),
    ("P's", '타마모리 · 옷'): (0xA8,),
    ('iDL', '타마모리 · 액세서리'): (0xA8,),
    ('iDL', "타마모리 · 액세서리 (P's용)"): (0xA8,),
    ('iDL', '타마모리 · 옷'): (0xA8,),
    ('4U', '레스토랑 · 간식'): (0xB2,),
    ('4U', '레스토랑 · 식사'): (0xB2,),
    ('4U', '고치 인테리어 · 방'): (0x70,),
    ('iD', '타마데파 · 장난감'): (0x65, 0x66, 0x67),
    ('iD', '타마모리 · 액세서리'): (0x65, 0x66, 0x67),
    # 0x68-0x6B is where food keeps its like mask, but a costume keeps a run
    # of pose indices there instead -- see items.LIKES_LABELS
    ('iD', '사진관 · 의상'): (0x65, 0x66, 0x67, 0x68, 0x69, 0x6A, 0x6B,
                              0x6C, 0x6D),
}


# The lowest serial no retail file of that shelf uses.  Serials are
# numbered per shelf, not per model -- 4U 1001 belongs to a living room,
# an outing, an accessory and a dress at once -- so a new item only has
# to miss the ones its own category already took.  See SERIALS.md.
NEXT_SERIAL = {
    ('4U', '게임센터 · 게임'): 1026,
    ('4U', '고치 인테리어 · 방'): 33214,
    ('4U', '냉장고 직행 · 간식 (비매품)'): 1167,
    ('4U', '냉장고 직행 · 식사 (비매품)'): 1106,
    ('4U', '레스토랑 · 간식'): 15024,
    ('4U', '레스토랑 · 식사'): 1867,
    ('4U', '빙고 정의'): 1621,
    ('4U', '외출지'): 1015,
    ('4U', '카드 · 캐릭터 프로그램'): 1184,
    ('4U', '타마데파 · 장난감'): 1807,
    ('4U', '타마모리 · 액세서리'): 16176,
    ('4U', '타마모리 · 옷'): 16005,
    ("P's", 'VDP · 아이템 묶음'): 2523,
    ("P's", '게임센터 · 게임'): 16553,
    ("P's", '고치 인테리어 · 방'): 39170,
    ("P's", '레스토랑 · 간식'): 16586,
    ("P's", '레스토랑 · 간식 (비매품)'): 16612,
    ("P's", '레스토랑 · 식사'): 16606,
    ("P's", '레스토랑 · 식사 (비매품)'): 16628,
    ("P's", '보물상자 · 스탬프카드'): 11025,
    ("P's", '보물상자 · 편지'): 11122,
    ("P's", '외출지'): 16559,
    ("P's", '타마데파 · 장난감'): 16731,
    ("P's", '타마모리 · 액세서리'): 39170,
    ("P's", '타마모리 · 액세서리 2'): 16141,
    ("P's", '타마모리 · 옷'): 39169,
    ("P's", '통신놀이 · 레시피'): 16024,
    ('iD', '게임센터 · 게임'): 296,
    ('iD', '고치 인테리어 · 방'): 60921,
    ('iD', '레스토랑 · 간식'): 50826,
    ('iD', '레스토랑 · 간식 (변종)'): 4128,
    ('iD', '레스토랑 · 식사'): 50826,
    ('iD', '사진관 · 배경'): 37026,
    ('iD', '사진관 · 의상'): 50078,
    ('iD', '외출지'): 517,
    ('iD', '우편함 · 편지'): 49859,
    ('iD', '타마데파 · 장난감'): 50347,
    ('iD', '타마모리 · 액세서리'): 50085,
    ('iDL', '게임센터 · 게임'): 11103,
    ('iDL', '고치 인테리어 · 방'): 39170,
    ('iDL', '레스토랑 · 간식'): 11343,
    ('iDL', '레스토랑 · 간식 (비매품)'): 11266,
    ('iDL', '레스토랑 · 식사'): 11254,
    ('iDL', '레스토랑 · 식사 (비매품)'): 11197,
    ('iDL', '외출지'): 11058,
    ('iDL', '우편함 · 편지'): 11336,
    ('iDL', '우편함 · 해피메일'): 11083,
    ('iDL', '타마데파 · 생활용품'): 12056,
    ('iDL', '타마데파 · 씨앗'): 13124,
    ('iDL', '타마데파 · 장난감'): 11239,
    ('iDL', '타마모리 · 액세서리'): 39170,
    ('iDL', "타마모리 · 액세서리 (P's용)"): 11200,
    ('iDL', '타마모리 · 옷'): 39169,
    ('iDL', '타마베이커리 · 간식'): 11276,
}

PAL4_MAX = 16       # up to here a pixel is 4 bits; past it, 8


def blueprint(model, label, nframes=None):
    """([(w, h), ...], palette ceiling) for a category, or None.

    Toys take `nframes` because the count is a real choice there; every
    other category has one shape.
    """
    if label == TOY_LABEL:
        got = TOY_SHAPES.get(nframes or TOY_DEFAULT)
        return None if got is None else (got[0], PAL4_MAX)
    geometry = BLUEPRINTS.get((model, label)) or BLUEPRINTS.get(('*', label))
    return None if geometry is None else (geometry, PAL4_MAX)


def next_serial(model, label):
    """A serial that collides with nothing retail ships for that shelf."""
    return NEXT_SERIAL.get((model, label), 1)


def categories(model):
    """Every category this can build for one model."""
    out = []
    for entry in destinations.options(model):
        label = entry[0]
        if label in FROM_BASE:
            out.append(label)                 # needs a base file, not a blueprint
            continue
        if label in UNSUPPORTED or blueprint(model, label) is None:
            continue
        out.append(label)
    return out


def game_shape(pkt):
    """The sprite layout a program packet carries, sorted.

    Games come in engines: what a game *is* shows up as its sprite set, and
    two different games built on one engine carry the same one.  Across the
    four packs 99 of the 139 distinct games share a layout with at least one
    other -- seven of them are the twelve-frame matching game (10x10, ten
    16x20 cards and the 128x72 backdrop), and かいがらあわせ and
    ジュエルハンター are different games, different sizes, same engine.
    So this is what to match on when picking a base to build from.
    """
    return sorted((r[1], r[2]) for r in sprites.scan_loose(bytes(pkt.raw),
                                                           lo=0x40))


OUTING_BACKDROP = (128, 72)
OUTING_FRAMES_PER_CHAR = 2


def outing_cast(pkt):
    """Who an outing carries: (sprite size, frame count, character count).

    An outing is a place with characters standing in it, each with a couple
    of animation frames and a line of dialogue.  The cast shows up as the
    sprite size that repeats once the 128x72 backdrop and the gifts' own
    icons are set aside, and the frames come in pairs, so half the count is
    the head count.  Four of the 37 have an odd number, so it is an
    estimate rather than a rule -- `paired` says which.

    The gifts are nested packets and are counted separately.  On the
    regional and sponsor outings the two agree exactly -- Kinki and Kanto
    carry eight 30x36 frames and four gifts, Calbee and the cafes six and
    three -- but 15 of the 37 hand out nothing at all, so one gift per
    character is a pattern of those sets, not of outings generally.
    """
    # the gifts are whole packets sitting inside this one and they carry
    # their own icons, so their bytes have to come out of the count first
    kids = [(c.offset, c.offset + c.size) for c in (pkt.children or [])]
    inside = lambda o: any(a <= o < b for a, b in kids)
    sizes = collections.Counter()
    for rec in sprites.scan_loose(bytes(pkt.raw), lo=0x40):
        wh = (rec[1], rec[2])
        if wh != OUTING_BACKDROP and not inside(rec[0]):
            sizes[wh] += 1
    if not sizes:
        return None
    (w, h), n = sizes.most_common(1)[0]
    return {'sprite': [w, h], 'frames': n,
            # round up, not to even: five frames reads as three characters
            # with one of them holding a single frame
            'characters': max(1, -(-n // OUTING_FRAMES_PER_CHAR)),
            'paired': n % OUTING_FRAMES_PER_CHAR == 0}


def from_base(data, model, label, name='', serial=None):
    """A new program download built on one you already have.

    A game or an outing is S1C33 code and there is no writing that from
    nothing, so the body comes across untouched and only the identity is
    rewritten -- the item name, the serial, the ASCII id and the download
    name.  The destination is set from the chosen category, which is what
    lets an outing be re-filed as a game.
    """
    _, packets, _ = container.parse_file(data)
    if not packets:
        raise ValueError('패킷이 없는 파일입니다')
    pkt = packets[0]
    if not items.is_program(pkt):
        raise ValueError('프로그램 패킷이 아닙니다 — 게임이나 외출지 파일을 '
                         '고르세요')
    if pkt.model != model:
        raise ValueError(f'{pkt.model} 파일입니다 — {model}용을 고르거나 '
                         f'기종을 {pkt.model}로 바꾸세요')
    entry = next((e for e in destinations.options(model) if e[0] == label), None)
    if entry is None:
        raise ValueError(f'{model}에 "{label}" 카테고리가 없습니다')

    out = container.Packet(bytes(pkt.raw), 0)
    if serial is None:
        serial = pkt.serial
    struct.pack_into('>H', out.raw, container.OFF_SERIAL, serial & 0xFFFF)
    # the destination keeps iD's per-item index byte, and a category that
    # also depends on a byte outside it gets that written too
    cur = bytes(out.raw[items.OFF_DEST:items.OFF_DEST + 4])
    out.raw[items.OFF_DEST:items.OFF_DEST + 4] = destinations.apply(
        model, entry[1], cur)
    extra = destinations.extra_for(model, entry[1], label)
    if extra:
        off, val = extra
        if off < len(out.raw):
            out.raw[off] = val
    if name:
        _write_names(out, name, None, None, label, serial)
    out.fix_checksums()
    return out


def slot_for(w, h, ncol):
    """Bytes one frame needs: record header, palette, pixels."""
    return 6 + 2 * ncol + sprites.pixel_bytes(w, h, 1, ncol)


def blank_frames(model, label, colors=None, nframes=None):
    spec = blueprint(model, label, nframes)
    if spec is None:
        raise ValueError(f'{model}의 "{label}"은(는) 아직 만들 수 없습니다')
    geometry, ceiling = spec
    # default to 16 even where the ceiling is higher: seventeen colours or
    # more switches the codec to 8 bits per pixel and doubles what the
    # sprites cost, which is not something to opt into by accident
    ncol = max(2, min(colors or min(ceiling, PAL4_MAX), ceiling))
    # a flat transparent-ish palette; index 0 is what the device treats as
    # see-through on the categories that honour it
    palette = [(0, 255, 0)] + [(0, 0, 0)] * (ncol - 1)
    return [sprites.Frame(slot_for(w, h, ncol), w, h, palette, [0] * (w * h))
            for w, h in geometry]


def _fit(frames):
    """Give every frame a slot exactly big enough for what it holds."""
    for f in frames:
        f.slot_size = slot_for(f.width, f.height, len(f.palette))
    return frames


ACC_SECTION = 2
ACC_BLOCK = {'iD': 784}          # every other model carries 960


def _bank_for(model, dest_hex):
    """(bank offset, wear-table length) for a fresh packet.

    On a real file the table's length is read from the u16 sitting at the
    layout's bank offset; on a new one there is nothing to read yet, so it
    comes from the category instead -- section 2 is where accessories live.
    """
    lay = models.layout(model)
    if bytes.fromhex(dest_hex)[1] != ACC_SECTION:
        return lay['bank'], 0
    n = ACC_BLOCK.get(model, 960)
    return lay['bank'] + items.ACC_POS_REL + n, n


def new_item(model, label, name='', serial=0, frames=None, fields=None,
             ansi_id=None, download_name=None, tight=True,
             token=None, declared_size=None, name_codes=None,
             dest=None, extra=None, signature=None,
             acc_block=None, pad_to=None):
    """A complete packet for one shop item, ready to write to a file.

    `fields` carries whatever the category supports -- price, hunger,
    friendship, stats, likes, anim.  Anything it leaves out stays zero.
    With `tight`, each frame's slot shrinks to fit its own data, which is
    where the size saving comes from.
    """
    if label in UNSUPPORTED:
        raise ValueError(UNSUPPORTED[label])
    entry = next((e for e in destinations.options(model) if e[0] == label), None)
    if entry is None:
        raise ValueError(f'{model}에 "{label}" 카테고리가 없습니다')
    frames = list(frames) if frames else blank_frames(model, label)
    if tight:
        _fit(frames)

    lay = models.layout(model)
    bank, acc_len = _bank_for(model, entry[1])

    body = 2 + sum(2 + f.slot_size for f in frames)
    size = bank + body + 2                    # + the trailing checksum
    # a few retail items keep a couple of spare bytes past the bank
    size = max(size, pad_to or 0)
    raw = bytearray(size)
    if acc_len:
        # accessories keep the wear-coordinate table where the bank would
        # otherwise start, behind a u16 saying how long it is.  Only the
        # first 112 bytes are wear positions; iD fills far more of it, so
        # reproduction hands the whole block over rather than rebuilding it.
        struct.pack_into('>H', raw, lay['bank'], acc_len)
        if acc_block:
            at = lay['bank'] + items.ACC_POS_REL
            raw[at:at + len(acc_block)] = bytes(acc_block[:acc_len])
    raw[0:6] = container.MAGIC
    raw[container.OFF_TYPE_SIG:container.OFF_TYPE_SIG + 2] = struct.pack(
        '>H', _signature(model) if signature is None else signature)
    # iD keeps a per-item index inside the destination, so the catalogue's
    # template is only a starting point there
    raw[items.OFF_DEST:items.OFF_DEST + 4] = dest or bytes.fromhex(entry[1])
    struct.pack_into('>H', raw, container.OFF_PACKET_SIZE, size)
    struct.pack_into('>H', raw, container.OFF_FILE_SIZE,
                     size if declared_size is None else declared_size)
    if token:
        raw[container.OFF_TOKEN:container.OFF_TOKEN + 8] = bytes(token[:8])
    struct.pack_into('>H', raw, container.OFF_SERIAL, serial & 0xFFFF)

    pkt = container.Packet(raw, 0)
    _write_names(pkt, name, ansi_id, download_name, label, serial, name_codes)
    # after the name: several of these sit inside its unused slots
    for off, val in EXTRA_BYTES.get((model, label), {}).items():
        if off < len(pkt.raw):
            pkt.raw[off] = val
    for off, val in (extra or {}).items():
        if off < len(pkt.raw):
            pkt.raw[off] = val
    sprites.write_bank(pkt.raw, frames, bank)
    _write_fields(pkt, fields or {})
    extra = destinations.extra_for(model, entry[1], label)
    if extra:
        off, val = extra
        if off < len(pkt.raw):
            pkt.raw[off] = val
    pkt.fix_checksums()
    return pkt


def _signature(model):
    for sig, name in models.SIGNATURES.items():
        if name == model:
            return sig
    raise ValueError(f'알 수 없는 기종 {model}')


def _kind_of(pkt):
    try:
        return items.effective_kind(pkt)
    except Exception:
        return '?'


def _kind_for(pkt):
    return items.SECTION_KIND.get(pkt.section, 'as')


def _write_names(pkt, name, ansi_id, download_name, label, serial,
                 name_codes=None):
    table = charset.load_table(model=pkt.model)
    lay = pkt.layout
    # retail pads the name field with 0x00, not with the ideographic space
    # that write_text uses -- and a couple of categories keep an unrelated
    # byte inside the unused slots, which is why name_codes exists
    codes = list(name_codes) if name_codes is not None else (
        charset.encode(name, table) if name else [])
    for i in range(lay['slots']):
        v = codes[i] if i < len(codes) else 0
        o = lay['name'] + i * lay['width']
        if lay['width'] == 1:
            pkt.raw[o] = v & 0xFF
        else:
            struct.pack_into('>H', pkt.raw, o, v)
    # the id's leading letters are read back as the packet's kind
    # (t4u_<kind><number>), and that kind is what decides which shop fields
    # apply -- so a generated meal has to say 'gh' the way a retail one does
    ident = f't4u_{_kind_for(pkt)}{serial:05d}' if ansi_id is None else ansi_id
    blob = ident.encode('ascii', 'ignore')[:container.OFF_PACKET_SIZE
                                           - container.OFF_ANSI_ID]
    pkt.raw[container.OFF_ANSI_ID:container.OFF_ANSI_ID + len(blob)] = blob
    title = f'DL_{ident}.jpg' if download_name is None else download_name
    room = container.OFF_FILE_SIZE - container.OFF_UNICODE_NAME
    enc = title.encode('utf-16-be')[:room]
    pkt.raw[container.OFF_UNICODE_NAME:
            container.OFF_UNICODE_NAME + len(enc)] = enc


def _write_fields(pkt, fields):
    allowed = items.editable_fields(pkt)
    if 'price' in fields:
        items.set_price(pkt, int(fields['price']))
    if 'hunger' in allowed and 'hunger' in fields:
        items.set_hunger(pkt, int(fields['hunger']))
    if 'friendship' in allowed and 'friendship' in fields:
        items.set_friendship(pkt, int(fields['friendship']))
    if 'anim' in allowed and 'anim' in fields:
        items.set_anim(pkt, *fields['anim'])
    if 'stats' in allowed and 'stats' in fields:
        items.set_stats(pkt, fields['stats'])
    if 'likes' in allowed and 'likes' in fields:
        items.set_likes_raw(pkt, fields['likes'])
    if 'id_compat' in fields and fields['id_compat']:
        # iD keeps two firmware version words at 0xF8; a Lovely Melody item
        # carries 0x0DC0 there and a later-revision one 0x1DC0
        items.set_version(pkt, compat=fields['id_compat'])
    if 'compat' in fields:
        # get_compat hands back {'mask', 'models'}; the mask is the field
        items.set_compat(pkt, fields['compat'].get('models', [])
                         if isinstance(fields['compat'], dict)
                         else fields['compat'])
        if isinstance(fields['compat'], dict):
            pkt.raw[models.OFF_COMPAT_MASK] = fields['compat']['mask']
    if 'acc_pos' in fields and fields['acc_pos']:
        items.set_acc_positions(pkt, fields['acc_pos'])


def build_file(pkt, jpeg=b''):
    """The packet wrapped as a .jpg download."""
    return container.build_file(jpeg, [pkt], b'')


def reproduce(pkt):
    """Rebuild `pkt` from its own field values; returns the new bytes.

    Every difference from the original is a field synthesis does not know
    about yet, which is what makes this worth running over a whole pack.
    """
    label = destinations.match(
        pkt.model, bytes(pkt.raw[items.OFF_DEST:items.OFF_DEST + 4]), pkt.raw)
    frames, _end = sprites.parse_bank(pkt.raw, items.bank_offset(pkt))
    table = charset.load_table(model=pkt.model)
    fields = {'price': items.get_price(pkt), 'compat': items.get_compat(pkt)}
    allowed = items.editable_fields(pkt)
    if 'hunger' in allowed:
        fields['hunger'] = items.get_hunger(pkt)
    if 'friendship' in allowed:
        fields['friendship'] = items.get_friendship(pkt)
    if 'anim' in allowed:
        fields['anim'] = items.get_anim(pkt)
    if 'stats' in allowed:
        fields['stats'] = items.get_stats(pkt)
    if 'likes' in allowed:
        fields['likes'] = items.get_likes_raw(pkt)
    if pkt.model == 'iD':
        fields['id_compat'] = items.get_version(pkt)['compat']
    acc_len = items.acc_block_len(pkt)
    at = pkt.layout['bank'] + items.ACC_POS_REL
    out = new_item(
        pkt.model, label, serial=pkt.serial, frames=frames, fields=fields,
        ansi_id=pkt.ansi_id, download_name=pkt.unicode_name, tight=False,
        # the token is eight per-file bytes of unknown purpose and 0x32 is
        # the size of the download this came in, JPEG included -- neither can
        # be derived, so reproduction is handed both
        token=bytes(pkt.raw[container.OFF_TOKEN:container.OFF_TOKEN + 8]),
        declared_size=pkt.declared_size,
        name_codes=list(pkt.item_name_codes),
        dest=bytes(pkt.raw[items.OFF_DEST:items.OFF_DEST + 4]),
        signature=struct.unpack_from('>H', pkt.raw, container.OFF_TYPE_SIG)[0],
        extra={o: pkt.raw[o]
               for o in (CARRY_OVER.get((pkt.model, label), ())
                         + MODEL_CARRY.get(pkt.model, ()))
               if o < pkt.size},
        acc_block=bytes(pkt.raw[at:at + acc_len]) if acc_len else None,
        pad_to=pkt.size)
    return bytes(out.raw)
