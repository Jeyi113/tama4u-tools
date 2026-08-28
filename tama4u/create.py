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
import struct

from . import charset, container, destinations, items, models, sprites

# Frames a category carries, measured across the four packs: (w, h) per
# frame and the palette ceiling.  Where a model differs it gets its own
# entry; '*' is every other model.
#
# The ceiling is the largest palette that category is ever seen with, not
# the commonest -- most clothes use eight colours but P's and iD L ship
# sixteen-colour ones, and capping at the usual value would refuse artwork
# the device accepts.  Two of them are genuinely lower: 4U clothes never go
# past eight and 4U accessories past nine.  Toys reach seventeen on P's and
# iD, which crosses the codec's boundary -- sixteen or fewer is 4 bits per
# pixel, more is 8, so those frames cost twice as much per pixel.
#
# Toys are the one category with no settled shape -- 101 different frame
# layouts across 156 4U toys -- so the entry is a starting point, not a rule.
BLUEPRINTS = {
    ('*', '레스토랑 · 식사'):      ([(24, 24)] * 3, 16),
    ('*', '레스토랑 · 간식'):      ([(24, 24)] * 3, 16),
    ('*', '레스토랑 · 식사 (비매품)'): ([(24, 24)] * 3, 16),
    ('*', '레스토랑 · 간식 (비매품)'): ([(24, 24)] * 3, 16),
    ('*', '냉장고 직행 · 식사 (비매품)'): ([(24, 24)] * 3, 16),
    ('*', '냉장고 직행 · 간식 (비매품)'): ([(24, 24)] * 3, 16),
    ('*', '타마베이커리 · 간식'):    ([(24, 24)] * 3, 16),
    ('*', '고치 인테리어 · 방'):    ([(128, 72)], 16),
    ('*', '타마모리 · 옷'):        ([(30, 12)] * 28, 16),
    ('*', '타마모리 · 액세서리'):    ([(30, 20)] * 3 + [(44, 30)], 16),
    ('*', "타마모리 · 액세서리 (P's용)"): ([(30, 20)] * 3 + [(44, 30)], 16),
    ('*', '타마모리 · 액세서리 2'):  ([(30, 20)] * 3 + [(44, 30)], 16),
    ('*', '타마데파 · 장난감'):     ([(24, 24), (30, 30)], 17),
    ('*', '타마데파 · 생활용품'):    ([(24, 24)], 16),
    ('iD', '타마모리 · 액세서리'):   ([(24, 24), (30, 30), (36, 36), (60, 60),
                                   (24, 24), (30, 30), (36, 36)], 16),
    ('iD', '타마데파 · 장난감'):    ([(32, 30), (40, 28), (40, 20), (40, 20),
                                   (56, 32), (32, 30)], 17),
    ('iD', '사진관 · 의상'):       ([(48, 48)] * 6, 16),
    ('iD', '사진관 · 배경'):       ([(120, 64)], 16),
    ('iD', '우편함 · 편지'):       ([(32, 32)], 15),
    ('iDL', '타마데파 · 장난감'):   ([(32, 30)] + [(24, 24)] * 3, 16),
    ('4U', '타마데파 · 장난감'):    ([(128, 72)], 16),
    ('4U', '타마모리 · 옷'):       ([(30, 12)] * 28, 8),
    ('4U', '타마모리 · 액세서리'):   ([(30, 20)] * 3 + [(44, 30)], 9),
    ('iDL', '타마데파 · 장난감'):   ([(32, 30)] + [(24, 24)] * 3, 16),
}

# Categories that are program blobs or need a stat block this cannot write.
UNSUPPORTED = {
    '게임센터 · 게임': '게임은 S1C33 프로그램이라 만들어 낼 수 없습니다',
    '외출지': '외출지는 S1C33 프로그램이라 만들어 낼 수 없습니다',
    'VDP · 아이템 묶음': 'VDP는 프로그램 + 압축 스트림이라 만들어 낼 수 없습니다',
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
    ('iD', '사진관 · 의상'): (0x65, 0x66, 0x67),
}


PAL4_MAX = 16       # up to here a pixel is 4 bits; past it, 8


def blueprint(model, label):
    """([(w, h), ...], palette ceiling) for a category, or None."""
    return BLUEPRINTS.get((model, label)) or BLUEPRINTS.get(('*', label))


def categories(model):
    """Every category this can build for one model."""
    out = []
    for entry in destinations.options(model):
        label = entry[0]
        if label in UNSUPPORTED or blueprint(model, label) is None:
            continue
        out.append(label)
    return out


def slot_for(w, h, ncol):
    """Bytes one frame needs: record header, palette, pixels."""
    return 6 + 2 * ncol + sprites.pixel_bytes(w, h, 1, ncol)


def blank_frames(model, label, colors=None):
    spec = blueprint(model, label)
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
               for o in CARRY_OVER.get((pkt.model, label), ())
               if o < pkt.size},
        acc_block=bytes(pkt.raw[at:at + acc_len]) if acc_len else None,
        pad_to=pkt.size)
    return bytes(out.raw)
