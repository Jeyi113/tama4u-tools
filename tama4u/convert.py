"""Convert an item packet between iD / iD L / P's / 4U.

Everything below is derived from the four download packs rather than
guessed, mostly by diffing the 333 items that ship for more than one
model (e.g. かんざし exists as iD, iD L, P's and 4U files):

* The **sprite codec and frame geometry are identical** across models for
  food, snacks, toys and rooms — a meal is 3x 24x24 everywhere.  So the
  whole body (wear-coordinate block + sprite bank) can be copied verbatim
  and only the header needs rebuilding.
* **Wearables are the exception.**  iD drives a different character rig:
  its accessories carry 7 frames (24x24, 30x30, 36x36, 60x60, 3x 24x24)
  and its costumes 5-6x 48x48, where iD L / P's / 4U all use 4 frames
  (3x 30x20 + 44x30) and 28x 30x12.  Those cannot be remapped
  automatically, so iD <-> anything is blocked for sections 2 and 3.
* The **internal charset is one table**; 4U just stores each code as
  0x04xx instead of a single byte (verified: every code in the iD/iD L/P's
  tables matches 4U's 0x0400 + code).  Name conversion is a width change.
* The **serial u16 at 0x5A is the number in the ASCII id** —
  `id2_ac11123_1` stores 0x2B73 = 11123.  iD has no serial (its name
  starts at 0x5A) so it only gets one on the way out.
* **Byte 0xFF is a compatibility bitmask** (models.COMPAT_BIT).
"""
import struct

from . import container, destinations, items, models

# 'DL_' + key + packet class + '_' + display name.  iD is the exception:
# its files carry no class letter (DL_MDP_トマトリゾット.did).
DL_KEY = {'iD': 'MDP', 'iDL': 'iDL', "P's": 'iDN', '4U': 'T4U'}


def dl_prefix(model, packet_class):
    return f'DL_{DL_KEY[model]}_' if model == 'iD' \
        else f'DL_{DL_KEY[model]}{packet_class}_'
ANSI_PREFIX = {'iD': '', 'iDL': 'id2_', "P's": 'idn_', '4U': 't4u_'}
ANSI_DIGITS = {'iD': 3, 'iDL': 5, "P's": 5, '4U': 5}
NAME_PAGE = 0x0400              # 4U's page byte for the shared charset

# section -> the sprite rig it is drawn on.  Only wearables differ.
WEARABLE_SECTIONS = (2, 3)
CONVERTIBLE_SECTIONS = (1, 2, 3, 4, 7)

# per-model bytes with no cross-model meaning, keyed by model
_ID_KIND_BYTE = 0x63            # iD: 2 for meals, 1 for snacks
_PS_FOOD_TAG = 0xA8             # P's food attribute...
_4U_FOOD_TAG = 0xB2             # ...same field on 4U (matches on 49 pairs)


def _has_bank(pkt):
    from . import sprites
    if pkt.packet_class != 'S' or pkt.section not in CONVERTIBLE_SECTIONS:
        return False
    try:
        sprites.parse_bank(pkt.raw, items.bank_offset(pkt))
        return True
    except Exception:
        return False


def plan(pkt, target):
    """What a conversion to `target` would do.  Never mutates."""
    src = pkt.model
    out = {'from': src, 'to': target, 'ok': True,
           'blockers': [], 'warnings': [], 'changes': []}
    if target not in models.LAYOUTS:
        out['ok'] = False
        out['blockers'].append(f'알 수 없는 기종: {target}')
        return out
    if src == target:
        out['ok'] = False
        out['blockers'].append('이미 이 기종입니다.')
        return out
    if not _has_bank(pkt):
        out['ok'] = False
        out['blockers'].append(
            '스프라이트 뱅크를 읽을 수 없는 패킷입니다 '
            '(외출·캐릭터·편지 등은 변환 대상이 아닙니다).')
        return out
    if pkt.section in WEARABLE_SECTIONS and 'iD' in (src, target):
        out['ok'] = False
        out['blockers'].append(
            'iD는 액세서리·의상 스프라이트 구성이 완전히 다릅니다 '
            f'(iD 액세서리 7장/의상 48×48 vs 나머지 4장/28장). '
            '스프라이트를 새로 그려야 하므로 자동 변환하지 않습니다.')
        return out

    L, M = models.layout(src), models.layout(target)
    out['changes'].append(f'기종 시그니처 0x4C → {_sig_for(target):#06x}')
    out['changes'].append(f'다운로드 이름 접두사 → {dl_prefix(target, pkt.packet_class)}')
    out['changes'].append(f'스프라이트 뱅크 {L["bank"]:#x} → {M["bank"]:#x}')

    codes = pkt.item_name_codes
    if len(codes) > M['slots']:
        out['warnings'].append(
            f'이름이 {len(codes)}자인데 {target}는 {M["slots"]}자까지라 잘립니다.')
    if L['width'] != M['width']:
        out['changes'].append(
            f'이름 인코딩 {L["width"]}바이트 → {M["width"]}바이트'
            + (' (0x04 페이지 부착)' if M['width'] == 2 else ' (0x04 페이지 제거)'))

    label = destinations.match(src, bytes(pkt.raw[items.OFF_DEST:items.OFF_DEST + 4]))
    tgt_code = _dest_for(target, label)
    if tgt_code:
        out['changes'].append(f'행선지 → {label} ({tgt_code})')
    else:
        out['warnings'].append(
            f'행선지 "{label or "미확인"}"에 해당하는 {target} 코드가 없어 '
            '섹션 기본값으로 둡니다. 저장 후 확인하세요.')

    if any(pkt.raw[L['likes'] + i] for i in range((items.likes_slots(pkt) + 3) // 4)):
        out['warnings'].append(
            f'호불호는 기종마다 캐릭터 명단이 달라(iD 11명 / 나머지 32명) '
            '옮길 수 없습니다. 전부 해제됩니다.')
    if L.get('stats') and not M.get('stats'):
        out['warnings'].append(f'{target}에는 5스탯 칸이 없어 버려집니다.')
    if L.get('anim') and not M.get('anim'):
        out['warnings'].append(f'{target}에는 애니메이션 ID 칸이 없어 버려집니다.')
    if target == 'iD':
        out['warnings'].append(
            'iD는 카탈로그 인덱스(행선지 3번째 바이트)를 기기가 검사합니다. '
            '변환 후 "기기 버전" 카드에서 인덱스를 지정하세요.')
    out['warnings'].append(
        '0x52 토큰 8바이트는 계산식을 몰라 원본 값을 그대로 둡니다.')
    return out


def _sig_for(model):
    for sig, m in models.SIGNATURES.items():
        if m == model:
            return sig
    return 0


_SIG_PREFERRED = {'iD': 0xCD80, 'iDL': 0x2DC0, "P's": 0x8DC0, '4U': 0x0101}


def _dest_for(target, label):
    if not label:
        return None
    for lbl, code, _mask in destinations.options(target):
        if lbl == label:
            return code
    return None


def _recode_name(codes, src_width, dst_width, slots):
    out = []
    for c in codes[:slots]:
        if src_width == dst_width:
            out.append(c)
        elif dst_width == 2:
            out.append(NAME_PAGE | (c & 0xFF))
        else:
            out.append(c & 0xFF)
    return out


def convert(pkt, target, serial=None):
    """Return a new packet (container.Packet) rebuilt for `target`."""
    info = plan(pkt, target)
    if not info['ok']:
        raise ValueError('; '.join(info['blockers']))
    src = pkt.model
    L, M = models.layout(src), models.layout(target)

    body = bytes(pkt.raw[L['bank']:-2])          # wear block + bank (+ any tail)
    size = M['bank'] + len(body) + 2
    new = bytearray(size)
    new[0:len(container.MAGIC)] = container.MAGIC

    # --- names -------------------------------------------------------
    disp = pkt.unicode_name
    tail = disp[disp.index('_', 3) + 1:] if disp.startswith('DL_') and '_' in disp[3:] \
        else disp
    if '.' in tail:                       # iD ships some names as .did
        tail = tail[:tail.rindex('.')] + '.jpg'
    dl = dl_prefix(target, pkt.packet_class) + tail
    enc = dl.encode('utf-16-be')[:container.OFF_FILE_SIZE - container.OFF_UNICODE_NAME - 2]
    new[container.OFF_UNICODE_NAME:container.OFF_UNICODE_NAME + len(enc)] = enc

    ser = pkt.serial if (serial is None and src != 'iD') else (serial or 0)
    kind = items.SECTION_KIND.get(pkt.section, 'gh')
    # iD numbers only go to three digits, and plenty of its files ship
    # with no ASCII id at all — leave it blank rather than invent one.
    if ANSI_PREFIX[target] or ser < 10 ** ANSI_DIGITS[target]:
        aid = f'{ANSI_PREFIX[target]}{kind}{ser:0{ANSI_DIGITS[target]}d}_1'
        new[container.OFF_ANSI_ID:container.OFF_ANSI_ID + len(aid)] = aid.encode()

    # --- fixed header fields ----------------------------------------
    struct.pack_into('>H', new, container.OFF_FILE_SIZE,
                     max(0, pkt.declared_size + size - pkt.size))
    struct.pack_into('>H', new, container.OFF_PACKET_SIZE, size)
    struct.pack_into('>H', new, container.OFF_TYPE_SIG, _SIG_PREFERRED[target])

    cur = bytes(pkt.raw[items.OFF_DEST:items.OFF_DEST + 4])
    label = destinations.match(src, cur)
    code = _dest_for(target, label)
    dest = bytes.fromhex(code) if code else cur
    if target == 'iD':                    # keep byte 2 free for the index
        dest = destinations.apply('iD', dest.hex(), b'\x00' * 4)
    new[items.OFF_DEST:items.OFF_DEST + 4] = dest

    new[container.OFF_TOKEN:container.OFF_TOKEN + 8] = pkt.token
    if target != 'iD':
        struct.pack_into('>H', new, container.OFF_SERIAL, ser & 0xFFFF)

    codes = _recode_name(pkt.item_name_codes, L['width'], M['width'], M['slots'])
    # 4U pads unused slots with either 0x0000 (547 files) or the bare page
    # byte 0x0400 (86) — the device clearly ignores it, so use zero.
    o = M['name']
    for i in range(M['slots']):
        c = codes[i] if i < len(codes) else 0
        if M['width'] == 1:
            new[o] = c & 0xFF
        else:
            struct.pack_into('>H', new, o, c)
        o += M['width']

    # --- stat block --------------------------------------------------
    struct.pack_into('>H', new, M['price'], items.get_price(pkt))
    new[M['hunger']] = pkt.raw[L['hunger']]
    new[M['friendship']] = pkt.raw[L['friendship']]
    if L.get('anim') and M.get('anim'):
        new[M['anim']] = pkt.raw[L['anim']]
        new[M['anim'] + 1] = pkt.raw[L['anim'] + 1]
    if L.get('stats') and M.get('stats'):
        new[M['stats']:M['stats'] + 5] = pkt.raw[L['stats']:L['stats'] + 5]
    # likes stay zero: the character rosters differ between models

    # --- per-model odds and ends ------------------------------------
    new[models.OFF_COMPAT_MASK] = models.COMPAT_BIT.get(target, 0)
    if target == 'iD':
        new[_ID_KIND_BYTE] = 1 if items.effective_kind(pkt) == 'oy' else 2
    if pkt.section == 1:
        tag = {'P\'s': _PS_FOOD_TAG, '4U': _4U_FOOD_TAG}
        v = pkt.raw[tag[src]] if src in tag else 0
        if target in tag:
            new[tag[target]] = v
        if target == '4U':
            new[0x73] = 0x02

    new[M['bank']:M['bank'] + len(body)] = body
    struct.pack_into('>H', new, size - 2, container.sum16(new[:-2]))
    return container.Packet(bytes(new), 0)
