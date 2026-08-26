"""Internal text encoding used by item/character names and dialogue.

Codes are u16; empirically A-Z = 0x04E0.., kana あ.. = 0x0401,
U+3000 space = 0x046C.  The definitive table is built by correlating
each packet's UTF-16 download name ("DL_T4Ux_<name>.jpg") with its
internal item name at 0x5E across a corpus (zero conflicts over the
917-file download pack).
"""
import glob
import json
import unicodedata
from collections import Counter
import os

from .container import MAGIC, OFF_ITEM_NAME

def _path(model):
    tag = {'4U': '', 'iD': '-id', 'iDL': '-idl', "P's": '-ps'}.get(model, '')
    return os.path.join(os.path.dirname(__file__), f'charset{tag}.json')


_TABLE_PATH = _path('4U')


def build_tables(*corpus_dirs):
    """Correlate each packet's UTF-16 download name with its internal
    item name, per model.  Returns {model: {code: char}}."""
    from . import container, models
    tables = {}
    for corpus_dir in corpus_dirs:
        for f in glob.glob(os.path.join(corpus_dir, '**', '*.[jJ][pP][gG]'),
                           recursive=True):
            d = open(f, 'rb').read()
            i = d.find(MAGIC)
            if i < 0:
                continue
            try:
                pkt = container.Packet(d, i)
            except Exception:
                continue
            u = pkt.unicode_name
            if '_' not in u[3:] or '.' not in u:
                continue
            disp = u[u.index('_', 3) + 1:u.rindex('.')]
            internal = pkt.item_name_codes
            if not disp or len(disp) != len(internal):
                continue
            tables.setdefault(pkt.model, {})
            for a, b in zip(disp, internal):
                tables[pkt.model].setdefault(b, a)
    for k in range(26):                      # systematic fill for 4U latin
        tables.setdefault('4U', {}).setdefault(0x04E0 + k, chr(ord('A') + k))
    return tables


def build_table(corpus_dir):
    return build_tables(corpus_dir).get('4U', {})


def save_tables(tables):
    for model, table in tables.items():
        save_table(table, _path(model))


def save_table(table, path=_TABLE_PATH):
    json.dump({f'{k:04X}': v for k, v in table.items()},
              open(path, 'w'), ensure_ascii=False, indent=0)


MODELS = ('4U', 'iD', 'iDL', "P's")
_CANON = None

# Codes the four packs never spelled out, recovered from Mr.Blinky's P's
# translation patches (github.com/MrBlinky/TamaPsTranslation).  Each patch
# ships a script listing the strings it writes *and* the compiled download
# that writes them, so aligning the two reads the codes straight off:
# 1101 of 1354 strings line up, pinning 0x62 ☼, 0x68 ↓, 0x69 →, 0x6B $ and
# 0xFF (line break) directly.
#
# Those land in a symbol run at 0x51-0x6B that follows the order of the
# character list in the script header exactly -- 16 of its 27 codes are
# confirmed one by one, and 0x67 ↑ was already in our table from corpus
# work, which is what makes the four gaps safe to interpolate.  The two
# roman extras sit right after Z (0xF9) the same way.
PATCH_CHARS = {
    # pinned directly by aligning script text against the compiled patch
    0x68: '↓', 0x69: '→', 0x6B: '$',
    0xFF: '<',          # line break inside one speech, not a glyph
    # gaps in the same run, filled from its order (see above)
    0x5F: '◯', 0x60: '☓', 0x66: '╬', 0x6A: '←',
    0xFA: 'i', 0xFB: '_',
}
# 0xFF is also the commonest filler byte in a program blob, so letting the
# dialogue scanner treat it as text would turn code into paragraphs.  It
# still decodes; it just cannot start or extend a run.
NOT_TEXT = frozenset({0xFF})


def _fold(ch):
    """Key that treats Ｓ and S as one character, and nothing else.

    Folding must stay narrow: NFKC also expands … into three dots and
    turns （ into (, which would break the 1:1 code<->character mapping
    the encoder depends on.  So only accept the result when it is a
    single ASCII letter or digit.
    """
    n = unicodedata.normalize('NFKC', ch)
    if len(n) == 1 and n.isascii() and n.isalnum():
        return n.upper()
    return ch


def canonical_bytes():
    """One byte->char table for all four models.

    The four per-model tables were each derived from the strings that
    happen to appear in that pack, so each one has holes and a few wrong
    guesses -- iD L reads 0xF2 as マ and P's reads 0xE8/0xF8 as n/e, which
    is why encoding an English name used to fail with "no internal code
    known for 'S'".  The device charset is one shared table (README), so
    merge the four by majority vote and pin the two blocks that are
    provably contiguous: A-Z at 0xE0-0xF9 and 0-9 at 0x6D-0x76.  Each
    outlier's character already lives at its own real code (ー 0x51,
    マ 0x95), which is what gives the vote away.
    """
    global _CANON
    if _CANON is not None:
        return _CANON
    votes = {}
    for m in MODELS:
        path = _path(m)
        if not os.path.exists(path):
            continue
        for k, v in json.load(open(path)).items():
            votes.setdefault(int(k, 16) & 0xFF, []).append(v)
    table = {}
    for code, vals in votes.items():
        key = Counter(_fold(v) for v in vals).most_common(1)[0][0]
        # letters/digits settle on the plain ASCII form; everything else
        # keeps whichever exact string the models agree on
        table[code] = key if (key.isascii() and key.isalnum()) else \
            Counter(v for v in vals if _fold(v) == key).most_common(1)[0][0]
    for k in range(26):
        table[0xE0 + k] = chr(ord('A') + k)
    for k in range(10):
        table[0x6D + k] = str(k)
    table.update(PATCH_CHARS)
    _CANON = table or {0xE0 + k: chr(ord('A') + k) for k in range(26)}
    return _CANON


def load_table(path=None, model='4U'):
    if path is not None:
        return {int(k, 16): v for k, v in json.load(open(path)).items()}
    page = 0x0400 if model == '4U' else 0
    return {page + c: v for c, v in canonical_bytes().items()}


def decode(codes, table=None):
    table = table or load_table()
    return ''.join(table.get(c, f'[{c:04X}]') for c in codes if c)


def scan_texts(raw, table=None, lo=0x200, hi=None, min_len=4, width=2):
    """Runs of consecutive charset-decodable codes (NPC dialogue inside
    outing/minigame blobs, letter bodies).  `width` is bytes per char —
    2 on 4U, 1 on iD / iD L / P's.
    Returns [(offset, char_count, text)]."""
    import struct
    table = table or load_table()
    hi = hi or len(raw)
    read = ((lambda o: raw[o]) if width == 1
            else (lambda o: struct.unpack_from('>H', raw, o)[0]))
    scannable = lambda c: c and c in table and (c & 0xFF) not in NOT_TEXT
    runs, o = [], lo
    while o < hi - width:
        if scannable(read(o)):
            start, chars = o, []
            while o < hi - width:
                code = read(o)
                if scannable(code):
                    chars.append(table[code])
                    o += width
                else:
                    break
            if len(chars) >= min_len:
                runs.append((start, len(chars), ''.join(chars)))
        else:
            o += 1
    return runs


def group_runs(runs, width=2, max_gap=8):
    """Merge runs that are only separated by a few control bytes into one
    editable message.  A letter body is stored as several runs broken by
    line separators; the user should see one paragraph, not five boxes.
    Returns [{'parts': [(offset, chars)], 'text': str, 'chars': int}]."""
    groups = []
    for off, n, txt in runs:
        if groups:
            last = groups[-1]['parts'][-1]
            end = last[0] + last[1] * width
            if off - end <= max_gap:
                groups[-1]['parts'].append((off, n))
                groups[-1]['text'] += txt
                groups[-1]['chars'] += n
                continue
        groups.append({'parts': [(off, n)], 'text': txt, 'chars': n})
    return groups


def write_grouped(packet_raw, parts, text, table=None, width=2):
    """Write `text` across a group's runs, filling each in order."""
    total = sum(n for _, n in parts)
    if len(text) > total:
        raise ValueError(f'text too long: {len(text)} > {total} chars')
    pos = 0
    for off, n in parts:
        write_text(packet_raw, off, n, text[pos:pos + n], table, width)
        pos += n


def space_code(table):
    rev = {v: k for k, v in table.items()}
    return rev.get('\u3000', rev.get(' ', 0))


def write_text(packet_raw, offset, char_count, text, table=None, width=2):
    """Replace a text run in place; shorter text is padded with the
    full-width space."""
    import struct
    table = table or load_table()
    codes = encode(text, table)
    if len(codes) > char_count:
        raise ValueError(f'text too long: {len(codes)} > {char_count} chars')
    codes += [space_code(table)] * (char_count - len(codes))
    for i, c in enumerate(codes):
        if width == 1:
            packet_raw[offset + i] = c & 0xFF
        else:
            struct.pack_into('>H', packet_raw, offset + 2 * i, c)


def _fullwidth(ch):
    """ASCII -> its full-width twin; the device font stores those."""
    if ch == ' ':
        return '\u3000'
    o = ord(ch)
    if 0x21 <= o <= 0x7E:
        return chr(0xFF01 + o - 0x21)
    return None


def encode(text, table=None):
    """Text -> internal codes.

    The device font carries A-Z but no lowercase, so lowercase input is
    folded up rather than rejected -- the device would render it that way
    regardless.  Half/full-width twins map to the same code.
    """
    table = table or load_table()
    rev = {v: k for k, v in table.items()}
    out = []
    for ch in text:
        for cand in (ch, _fullwidth(ch), ch.upper(),
                     _fullwidth(ch.upper()) if ch.isalpha() else None):
            if cand is not None and cand in rev:
                out.append(rev[cand])
                break
        else:
            raise ValueError(
                f'{ch!r} 은(는) 기기 문자표에 없습니다 '
                '(쓸 수 있는 것: A-Z, 0-9, 가나, 한자 일부, 일부 기호. '
                '소문자는 대문자로 저장됩니다)')
    return out
