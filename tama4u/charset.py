"""Internal text encoding used by item/character names and dialogue.

Codes are u16; empirically A-Z = 0x04E0.., kana あ.. = 0x0401,
U+3000 space = 0x046C.  The definitive table is built by correlating
each packet's UTF-16 download name ("DL_T4Ux_<name>.jpg") with its
internal item name at 0x5E across a corpus (zero conflicts over the
917-file download pack).
"""
import glob
import json
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


def load_table(path=None, model='4U'):
    path = path or _path(model)
    if not os.path.exists(path):
        return {0x04E0 + k: chr(ord('A') + k) for k in range(26)}
    return {int(k, 16): v for k, v in json.load(open(path)).items()}


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
    runs, o = [], lo
    while o < hi - width:
        if read(o) in table and read(o):
            start, chars = o, []
            while o < hi - width:
                code = read(o)
                if code in table and code:
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
    table = table or load_table()
    rev = {v: k for k, v in table.items()}
    out = []
    for ch in text:
        code = rev.get(ch)
        if code is None:
            alt = _fullwidth(ch)
            code = rev.get(alt) if alt else None
        if code is None:
            raise ValueError(f'no internal code known for {ch!r}')
        out.append(code)
    return out
