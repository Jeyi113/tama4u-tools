// Item stats, character stats, text codec and cross-model conversion --
// a port of tama4u/{items,character,charset,convert}.py.
import {
  u16, putU16, u16le, putU16le, layoutFor, destOptions, destMatch, destApply, destExtra,
  pixelBytes, scanLoose, readLoose,
  parseBank, LAYOUTS, COMPAT_BIT, OFF_COMPAT_MASK, SIGNATURES,
  OFF_ANSI_ID, OFF_PACKET_SIZE, OFF_FILE_SIZE, OFF_UNICODE_NAME,
  OFF_TYPE_SIG, OFF_TOKEN, OFF_SERIAL, MAGIC, sum16, Packet, parseFile,
} from './core.js';
import { CHARSET } from './charset-data.js';

// ---- charset --------------------------------------------------------
const REV = {};
for (const [model, table] of Object.entries(CHARSET)) {
  REV[model] = {};
  for (const [code, ch] of Object.entries(table)) if (!(ch in REV[model])) REV[model][ch] = +code;
}
export const tableFor = m => CHARSET[m] || CHARSET['4U'];
export const decode = (codes, table) =>
  codes.filter(c => c).map(c => table[c] ?? `[${c.toString(16).toUpperCase().padStart(4, '0')}]`).join('');

const fullwidth = ch => {
  if (ch === ' ') return '　';
  const o = ch.charCodeAt(0);
  return o >= 0x21 && o <= 0x7e ? String.fromCharCode(0xff01 + o - 0x21) : null;
};
// The device font carries A-Z but no lowercase, so lowercase input is
// folded up rather than rejected -- the device renders it that way anyway.
export function encode(text, model) {
  const rev = REV[model] || REV['4U'];
  const out = [];
  for (const ch of text) {
    const up = ch.toUpperCase();
    const cands = [ch, fullwidth(ch), up, fullwidth(up)];
    const hit = cands.find(c => c != null && rev[c] !== undefined);
    if (hit === undefined) throw new Error(
      `'${ch}' 은(는) 기기 문자표에 없습니다 (쓸 수 있는 것: A-Z, 0-9, 가나, `
      + `한자 일부, 일부 기호. 소문자는 대문자로 저장됩니다)`);
    out.push(rev[hit]);
  }
  return out;
}
const spaceCode = model => (REV[model] || REV['4U'])['　'] ?? (REV[model] || REV['4U'])[' '] ?? 0;

// 0xFF is a line break, and also the commonest filler byte in a program
// blob, so letting the scanner treat it as text would turn code into
// paragraphs.  It still decodes; it just cannot start or extend a run.
const NOT_TEXT = new Set([0xff]);
export function scanTexts(raw, model, lo = 0x200, hi = null, minLen = 4, width = 2) {
  const table = tableFor(model);
  hi = hi ?? raw.length;
  const read = width === 1 ? o => raw[o] : o => u16(raw, o);
  const ok = c => c && table[c] !== undefined && !NOT_TEXT.has(c & 0xff);
  const runs = [];
  let o = lo;
  while (o < hi - width) {
    const c0 = read(o);
    if (ok(c0)) {
      const start = o; const chars = [];
      while (o < hi - width) {
        const code = read(o);
        if (ok(code)) { chars.push(table[code]); o += width; }
        else break;
      }
      if (chars.length >= minLen) runs.push([start, chars.length, chars.join('')]);
    } else o += 1;
  }
  return runs;
}

// A letter body is stored as several runs split by line separators; the
// user should see one paragraph, not five boxes.
export function groupRuns(runs, width = 2, maxGap = 8) {
  const groups = [];
  for (const [off, n, txt] of runs) {
    if (groups.length) {
      const g = groups[groups.length - 1];
      const last = g.parts[g.parts.length - 1];
      if (off - (last[0] + last[1] * width) <= maxGap) {
        g.parts.push([off, n]); g.text += txt; g.chars += n; continue;
      }
    }
    groups.push({ parts: [[off, n]], text: txt, chars: n });
  }
  return groups;
}

export function writeText(raw, offset, charCount, text, model, width = 2) {
  const codes = encode(text, model);
  if (codes.length > charCount) throw new Error(`text too long: ${codes.length} > ${charCount} chars`);
  while (codes.length < charCount) codes.push(spaceCode(model));
  for (let i = 0; i < codes.length; i++) {
    if (width === 1) raw[offset + i] = codes[i] & 0xff;
    else putU16(raw, offset + 2 * i, codes[i]);
  }
}
export function writeGrouped(raw, parts, text, model, width = 2) {
  const total = parts.reduce((a, [, n]) => a + n, 0);
  if (text.length > total) throw new Error(`text too long: ${text.length} > ${total} chars`);
  let pos = 0;
  for (const [off, n] of parts) { writeText(raw, off, n, text.slice(pos, pos + n), model, width); pos += n; }
}

// ---- item stats -----------------------------------------------------
export const OFF_DEST = 0x4e;
export const OFF_VERSION = 0x4c;
export const OFF_COMPAT = 0xf8;
export const SECTION_MAIL = 6;
export const SECTION_KIND = { 1: 'gh', 2: 'ac', 3: 'fk', 4: 'as', 6: 'mail', 7: 'bg' };
export const OPAQUE_KINDS = ['bg', 'lv'];
export const BANK_OFFSETS = { gh: 0x200, oy: 0x200, as: 0x200, fk: 0x200, bg: 0x200, lv: 0x200, ac: 0x5c2 };
export const ACC_POS_REL = 0x02, ACC_FRAMES = 14, ACC_BODY_TYPES = 4;
export const ACC_ROW_TO_POSE = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 14, 15];
const ACC_BLOCK_LENS = [784, 960];

export const VERSION_NAMES = {
  0xcd80: '오리지널 iD', 0x0dc0: 'Lovely Melody', 0x1dc0: 'iD 리비전 (1dc0)', 0x0000: '없음',
};
export const VERSION_PRESETS = {
  cd80: { label: '오리지널 iD', version: 0xcd80, compat: [0, 0], index_range: [0x01, 0x27] },
  '0dc0': { label: 'Lovely Melody', version: 0x0dc0, compat: [0x0dc0, 0x1dc0], index_range: [0xde, 0xfe] },
  '1dc0': { label: 'iD 리비전 (1dc0)', version: 0xcd80, compat: [0x1dc0, 0x1dc0], index_range: [0x01, 0x27] },
};

// Outings, minigames and character definitions are programs, not shop
// items: their body is code with sprite records and dialogue scattered
// through it, and the stat block offsets mean nothing.  The destination's
// first byte separates them: 0x94 on iD L / P's / 4U, 0x14 for iD outings.
export const PROGRAM_DESTS = [0x94, 0x14];
// 94 02 5b 02 is a program blob we have not decoded (VDPs, LCD tweaks).
// Its body is compressed, so any "text" a 1-byte charset finds there is an
// artifact -- scanning it produced 50-240 nonsense blocks per file.
export const OPAQUE_PROGRAM_DEST = '94025b02';
// Dialogue lives in the slivers between sprite records.  When those gaps add
// up to more than this share of the packet the body is code we cannot read,
// not a sprites+dialogue layout: real outings sit at 1-5%, undecoded blobs
// at 22-99%.
export const MAX_TEXT_GAP_RATIO = 0.20;
// Runs one byte apart are line breaks inside one speech; a wider gap means a
// new speaker.  Merging across those (the letter body's max_gap of 8) glued a
// whole outing's cast into a single paragraph.
export const DIALOGUE_MAX_GAP = 2;
// Real Japanese does not repeat the same kana four times running; a program
// blob does it constantly.
const REPEAT = /([^\u3000 ])\1{3,}/;

export const isProgram = p => PROGRAM_DESTS.includes(p.raw[OFF_DEST]);
export const scansText = p =>
  Array.from(p.raw.slice(OFF_DEST, OFF_DEST + 4))
    .map(x => x.toString(16).padStart(2, '0')).join('') !== OPAQUE_PROGRAM_DEST;
export const plausibleRun = (text, width) => width === 2 || !REPEAT.test(text);

// Byte ranges that can hold dialogue: outside every sprite record and nested
// packet, and after the first one.  The leading blob is program code, and on
// the 1-byte models every code byte decodes to *some* kana, so scanning it
// returns hundreds of nonsense runs.
export function textGaps(spans, size, start = 0x60) {
  if (!spans.length) return [[start, size]];
  const s = [...spans].sort((a, b) => a[0] - b[0]);
  const out = [];
  let cur = s[0][0];
  for (const [a, b] of s) {
    if (a > cur) out.push([cur, a]);
    cur = Math.max(cur, b);
  }
  if (cur < size - 2) out.push([cur, size - 2]);
  return out;
}

// Not for a program packet: 0x4F is part of its destination there, not a
// shop section, so reading it turns a game into an accessory -- which put a
// body-composite strip and a wear-coordinate grid on screen for VDP
// minigames (94 02 5b 01 has 0x02 at 0x4F, and 0x02 is the accessory
// section).
export const effectiveKind = p =>
  isProgram(p) ? 'gm' : (p.kind !== '?' ? p.kind : (SECTION_KIND[p.section] ?? '?'));

export function accBlockLen(p) {
  const o = p.layout.bank;
  if (o + 2 > p.size) return 0;     // nested reward packets can be tiny
  const n = u16(p.raw, o);
  return ACC_BLOCK_LENS.includes(n) ? n : 0;
}
export function bankOffset(p) {
  const n = accBlockLen(p);
  return n ? p.layout.bank + ACC_POS_REL + n : p.layout.bank;
}
export const priceOffset = p =>
  (p.model === 'iD' && effectiveKind(p) === 'as') ? 0x6c : p.layout.price;
export const getPrice = p => u16(p.raw, priceOffset(p));
export const setPrice = (p, v) => putU16(p.raw, priceOffset(p), v);
export const getHunger = p => p.raw[p.layout.hunger];
export const setHunger = (p, v) => { p.raw[p.layout.hunger] = v & 0xff; };
export const getFriendship = p => p.raw[p.layout.friendship];
export const setFriendship = (p, v) => { p.raw[p.layout.friendship] = v & 0xff; };
export const getAnim = p => (p.layout.anim ? [p.raw[p.layout.anim], p.raw[p.layout.anim + 1]] : [0, 0]);
export function setAnim(p, a, b) {
  const o = p.layout.anim;
  if (o) { p.raw[o] = a & 0xff; p.raw[o + 1] = b & 0xff; }
}
// Fallback names for codes outside the per-model catalogue (program and
// definition packets that never appear in a shop).
export const DESTINATIONS = {
  '81010201': 'Restaurant (meal)', '81010d02': 'Restaurant (snack)',
  '81010101': 'Fridge (meal, bundle reward)', '81010102': 'Fridge (snack, bundle reward)',
  '81042a01': 'TamaDepa (toys)', '81033300': 'TamaMori (clothes)',
  '81023400': 'TamaMori (accessory)', '81071f00': 'Gotchi Interior (wallpaper)',
  '81082900': 'Bingo definition', '94025b01': 'Minigame',
  '94024702': 'Outing definition', '94024803': 'Download character',
};
export function getDestination(p) {
  const four = Array.from(p.raw.slice(OFF_DEST, OFF_DEST + 4));
  const hex = four.map(x => x.toString(16).padStart(2, '0')).join('');
  return destMatch(p.model, four, p.raw) || DESTINATIONS[hex]
    || `unknown(${four.map(x => x.toString(16).padStart(2, '0')).join(' ')})`;
}
export function setDestination(p, code, label = null) {
  const cur = Array.from(p.raw.slice(OFF_DEST, OFF_DEST + 4));
  const merged = destApply(p.model, code, cur);
  p.raw.set(merged, OFF_DEST);
  p.raw[0x73] = parseInt(code.slice(2, 4), 16) === 0x01 ? 0x02 : 0x00;   // food flag
  // iD splits games from outings at 0x64, so picking the category has to
  // write that byte too
  const extra = destExtra(p.model, code, label);
  if (extra && p.raw.length > extra[0]) p.raw[extra[0]] = extra[1];
}

export const likesSlots = p => p.layout.likes_slots;
export function getLikesRaw(p) {
  const o = p.layout.likes, out = [];
  for (let c = 0; c < likesSlots(p); c++) out.push((p.raw[o + (c >> 2)] >> ((c % 4) * 2)) & 3);
  return out;
}
// Read-modify-write: iD only owns 22 of the 32 bits at 0x68, so blindly
// rewriting all four bytes would wipe the unrelated byte at 0x6B.
export function setLikesRaw(p, values) {
  const o = p.layout.likes;
  values.slice(0, likesSlots(p)).forEach((v, c) => {
    const shift = (c % 4) * 2, i = o + (c >> 2);
    p.raw[i] = (p.raw[i] & ~(3 << shift)) | ((v & 3) << shift);
  });
}

export const STAT_KEYS = ['intelligence', 'style', 'charisma', 'gourmet', 'strength'];
export function getStats(p) {
  const o = p.layout.stats, out = {};
  STAT_KEYS.forEach((k, i) => { out[k] = o === null ? 0 : p.raw[o + i]; });
  return out;
}
export function setStats(p, stats) {
  const o = p.layout.stats;
  if (o === null) return;
  STAT_KEYS.forEach((k, i) => { if (k in stats) p.raw[o + i] = stats[k] & 0xff; });
}

// Nested reward packets can be shorter than 0x100 bytes, so the field is
// not always present.
export function getCompat(p) {
  const mask = p.size > OFF_COMPAT_MASK ? p.raw[OFF_COMPAT_MASK] : 0;
  return { mask, models: Object.entries(COMPAT_BIT).filter(([, b]) => mask & b).map(([m]) => m) };
}
export function setCompat(p, list) {
  let mask = 0;
  for (const m of list) mask |= COMPAT_BIT[m] || 0;
  p.raw[OFF_COMPAT_MASK] = mask;
}

export function getVersion(p) {
  const ver = u16(p.raw, OFF_VERSION);
  return { version: ver, compat: [u16(p.raw, OFF_COMPAT), u16(p.raw, OFF_COMPAT + 2)],
           label: VERSION_NAMES[ver] ?? `0x${ver.toString(16).padStart(4, '0')}`,
           index: p.raw[OFF_DEST + 2] };
}
export function setVersion(p, version, compat, index) {
  if (version != null) putU16(p.raw, OFF_VERSION, version & 0xffff);
  if (compat != null) { putU16(p.raw, OFF_COMPAT, compat[0] & 0xffff); putU16(p.raw, OFF_COMPAT + 2, compat[1] & 0xffff); }
  if (index != null) p.raw[OFF_DEST + 2] = index & 0xff;
}

export function editableFields(p) {
  const kind = effectiveKind(p), model = p.model, lay = p.layout;
  // a program has no shop fields, but it does have a destination -- that is
  // what puts a game in the Game Center
  if (isProgram(p)) return ['dest'];
  if (p.section === SECTION_MAIL) return ['text'];
  const f = new Set(['price', 'dest']);
  if (kind === 'gh' || kind === 'oy') { f.add('hunger'); f.add('friendship'); }
  else if (kind === 'as' && model !== 'iD') f.add('friendship');
  if (!['bg', 'lv'].includes(kind) && !(model === 'iD' && kind === 'as')) f.add('likes');
  if (lay.stats !== null) f.add('stats');
  if (kind === 'as' && lay.anim !== null) f.add('anim');
  return [...f].sort();
}

// null when the table would not fit -- a nested reward accessory can be
// shorter than the block the section byte implies.
export function getAccPositions(p) {
  const base = p.layout.bank + ACC_POS_REL;
  if (base + 2 * ACC_BODY_TYPES * ACC_FRAMES > p.size) return null;
  return Array.from({ length: ACC_BODY_TYPES }, (_, b) =>
    Array.from({ length: ACC_FRAMES }, (_, i) =>
      [p.raw[base + 2 * (b * ACC_FRAMES + i)], p.raw[base + 2 * (b * ACC_FRAMES + i) + 1]]));
}
export function setAccPositions(p, table) {
  const base = p.layout.bank + ACC_POS_REL;
  table.slice(0, ACC_BODY_TYPES).forEach((rows, b) =>
    rows.slice(0, ACC_FRAMES).forEach(([x, y], i) => {
      const o = base + 2 * (b * ACC_FRAMES + i);
      p.raw[o] = x & 0xff; p.raw[o + 1] = y & 0xff;
    }));
}
export const letterTextRange = (p, bank) => {
  const body = p.layout.bank;
  return bank > body ? [body, bank] : [0x60, body];
};

// iD ships 11 characters in the like mask, and the two firmwares do not use
// the same 11 (Lovely Melody drops Uwasatchi, adds Melodytchi).
export const CHARACTERS = [
  'Mametchi', 'Rightchi', 'Knightchi', 'Takutotchi', 'Nandetchi',
  'Kuchipatchi', 'Doyatchi', 'Gotchimotchi',
  'Shirimotchi', 'Charatchi', 'Monakatchi', 'Mogumogutchi', 'Spacytchi',
  'Karakutchi', 'Atchitchi', 'Yumemitchi',
  'Kiraritchi', 'Himespetchi', 'Warutsutchi', 'Amiamitchi', 'Memetchi',
  'Chokomakatchi', 'Yukinkotchi', 'Hoshigalutchi',
  'Chouchoutchi', 'Harputchi', 'Patitchi', 'Kiramotchi', 'Furifuritchi',
  'Amakutchi', 'Julietchi', 'Pekopekotchi',
];
// Rosters pinned by the 44 single-difference files (6_*_호불호, 2026-08-26);
// all 44 re-encode byte-identically.  null = a slot the pack uses but no
// labelled file names.  P's is the 4U roster in the same order.
export const ID_ROSTER = [
  'Mametchi', 'Kuromametchi', 'Gozarutchi', 'Kuchipatchi',
  'Kikitchi', 'Lovelitchi', 'Chamametchi', 'Makiko',
  'Memetchi', 'Furawatchi', 'Uwasatchi', null,
  'Melodytchi', null, null, null,
];
export const IDL_ROSTER = [
  'Mametchi', 'Kuromametchi', 'Shinshitchi', 'Peintotchi',
  'Kuishinbotchi', 'Kuchipatchi', 'Shoototchi', 'Gozarutchi',
  'Sunopotchi', 'Kikitchi', 'Bokutchi', 'Guriguritchi',
  'Spacytchi', 'Herotchi', 'Meistertchi', 'Lovelitchi',
  'Melodytchi', 'Moriritchi', 'Chamametchi', 'Memetchi',
  'Perotchi', 'Shigurehimetchi', 'Makiko', 'Pitchipitchi',
  'Furawatchi', 'Ponpontchi', 'Agetchi', 'Watawatatchi',
  'Naturatchi', 'Uwasatchi', 'Madonnatchi', 'Giragiratchi',
  ...new Array(15).fill(null),
  'Oyajitchi', 'Otogitchi', 'Prince Tamahiko', 'Akahanatchi',
  'Nonopotchi', 'Racequeentchi', 'Mimitchi', 'Himetchi',
  'Momotchi', 'Princess Tamahiko', 'Antoinetchi',
  ...new Array(13).fill(null),
  'Pipospetchi', 'Akaspetchi', 'Himespetchi',
];
export const ROSTERS = { iD: ID_ROSTER, iDL: IDL_ROSTER, "P's": CHARACTERS, '4U': CHARACTERS };
export function likeLabels(p) {
  const r = ROSTERS[p.model] || [];
  return Array.from({ length: likesSlots(p) }, (_, c) => r[c] ?? null);
}
export const likeRoster = p => (ROSTERS[p.model] || []).filter(Boolean).length
  ? (ROSTERS[p.model] || []).filter(Boolean) : null;

// ---- Virtual Deco Pierce bundles (destination 94 02 5b 02) ---------
// Each embedded item keeps the tail of an ordinary P's packet header, so
// the destination itself is the anchor: sig at -2, dest at 0, token +4,
// serial +12, name +16 (= 0x4C / 0x4E / 0x52 / 0x5A / 0x5E).  Pixels are
// packed and are not drawn -- see tama4u/vdp.py.
export const VDP_DEST = '94025b02';
const VDP_LOAD_BASE = 0x02000000, VDP_STUB_END = 0x600;
const VDP_ROUTINES = [
  ['lz', [0x8a, 0x8c, 0x4a, 0x36]],
  ['rle', [0x02, 0x54, 0x12, 0x54, 0x12, 0x27, 0x92, 0x23]],
];
const VDP_UNPACK_LIMIT = 1 << 20;
const VDP_CHAR_DEST = '81033300', VDP_ICON_DEST = '81042902', VDP_STUB_MAX = 0x200;
const hex4 = b => Array.from(b).map(x => x.toString(16).padStart(2, '0')).join('');
export const isVdp = p =>
  hex4(p.raw.slice(OFF_DEST, OFF_DEST + 4)) === VDP_DEST;

export function vdpUnpackRle(raw, start, limit = VDP_UNPACK_LIMIT) {
  const out = [];
  let ip = start;
  while (out.length < limit && ip + 1 < raw.length) {
    let ctrl = raw[ip] | (raw[ip + 1] << 8);
    ip += 2;
    if (ctrl === 0) break;
    if (ctrl < 0x8000) {
      const n = 2 * ctrl;
      if (ip + n > raw.length) break;
      for (let k = 0; k < n; k++) out.push(raw[ip + k]);
      ip += n;
    } else {
      const v = ctrl & 0xff;
      for (let k = 0, n = ((ctrl >> 8) & 0x7f) + 1; k < n; k++) out.push(v, v);
    }
  }
  return Uint8Array.from(out);
}

// vdp-009: byte control word with back-references
export function vdpUnpack(raw, start, limit = VDP_UNPACK_LIMIT) {
  const out = [];
  let ip = start;
  while (out.length < limit && ip < raw.length) {
    let ctrl = raw[ip++];
    if (ctrl > 127) ctrl -= 256;
    if (ctrl > 0) {
      if (ip >= raw.length) break;
      const v = raw[ip++];
      for (let k = 0; k <= ctrl; k++) out.push(v, v);
    } else if (ctrl < 0) {
      const n = 2 * -ctrl;
      if (ip + n > raw.length) break;
      for (let k = 0; k < n; k++) out.push(raw[ip + k]);
      ip += n;
    } else {
      if (ip + 1 >= raw.length) break;
      const a = raw[ip], b = raw[ip + 1];
      ip += 2;
      if (a === 0) break;
      const dist = ((((0xfffffff0 | a) << 8) | b) >>> 0) - 0x100000000;
      let src = out.length + dist;
      if (src < 0) break;
      for (let k = 0; k <= (a >> 4); k++) { out.push(out[src], out[src + 1]); src += 2; }
    }
  }
  return Uint8Array.from(out);
}

// The stub sets the input pointer with `ext imm13, ext imm13, ld.w %rN,imm6`
// -- three halfwords, the first two 0b110xxxxxxxxxxxxx and the last with
// opcode 0b011011.  Decoding just that shape saves porting the whole
// disassembler for one immediate.
export function vdpStreamStart(raw) {
  let at = -1, kind = null;
  for (const [name, sig] of VDP_ROUTINES) {
    for (let i = 0; i + sig.length <= raw.length && at < 0; i++)
      if (sig.every((v, k) => raw[i + k] === v)) { at = i; kind = name; }
    if (at >= 0) break;
  }
  if (at < 0) return null;
  let best = null;
  const hw = o => raw[o] | (raw[o + 1] << 8);
  for (let o = Math.max(0x40, at - 0x80); o + 6 <= at; o += 2) {
    const a = hw(o), b = hw(o + 2), c = hw(o + 4);
    if ((a >> 13) !== 0b110 || (b >> 13) !== 0b110) continue;
    if ((c >> 10) !== 0x1b) continue;                   // ld.w %rd,imm6
    const v = (((a & 0x1fff) << 19) | ((b & 0x1fff) << 6) | ((c >> 4) & 0x3f)) >>> 0;
    if (v >= VDP_LOAD_BASE + 0x40 && v < VDP_LOAD_BASE + raw.length)
      best = v - VDP_LOAD_BASE;
  }
  return best === null ? null : [kind, best];
}

export function vdpPayload(p) {
  const found = vdpStreamStart(p.raw);
  if (found === null) return null;
  const [kind, start] = found;
  return (kind === 'lz' ? vdpUnpack : vdpUnpackRle)(p.raw, start);
}


const VDP_MAX_LIT = 128, VDP_MAX_RUN = 128, VDP_MAX_MATCH = 16, VDP_WINDOW = 4096;
const hwAt = (d, k) => (d[2 * k] << 8) | d[2 * k + 1];   // compare key only

// vdp-001..008 packer -- byte-identical to Mr.Blinky's output
export function vdpPackRle(data) {
  const out = [], n = data.length >> 1;
  let i = 0;
  while (i < n) {
    const lo = data[2 * i], hi = data[2 * i + 1];
    if (lo === hi) {
      let j = i;
      while (j < n && data[2 * j] === lo && data[2 * j + 1] === hi
             && j - i < VDP_MAX_RUN) j++;
      if (j - i >= 2) {
        const c = 0x8000 | ((j - i - 1) << 8) | lo;
        out.push(c & 0xff, (c >> 8) & 0xff);
        i = j;
        continue;
      }
    }
    let j = i;
    while (j < n && j - i < 0x7fff) {
      const a = data[2 * j], b = data[2 * j + 1];
      if (a === b) {
        let k = j;
        while (k < n && data[2 * k] === a && data[2 * k + 1] === b
               && k - j < VDP_MAX_RUN) k++;
        if (k - j >= 2) break;
      }
      j++;
    }
    out.push((j - i) & 0xff, ((j - i) >> 8) & 0xff);
    for (let k = 2 * i; k < 2 * j; k++) out.push(data[k]);
    i = j;
  }
  out.push(0, 0);
  return Uint8Array.from(out);
}

// vdp-009 packer -- greedy, so not byte-identical, but smaller and exact
export function vdpPackLz(data) {
  const n = data.length >> 1, out = [], lit = [], index = new Map();
  const same = (a, b) => data[2 * a] === data[2 * b] && data[2 * a + 1] === data[2 * b + 1];
  const flush = () => {
    while (lit.length) {
      const take = lit.splice(0, VDP_MAX_LIT);
      out.push((256 - take.length) & 0xff);
      for (const k of take) out.push(data[2 * k], data[2 * k + 1]);
    }
  };
  let i = 0;
  while (i < n) {
    const lo = data[2 * i], hi = data[2 * i + 1];
    let run = 0;
    if (lo === hi) {
      let j = i;
      while (j < n && data[2 * j] === lo && data[2 * j + 1] === hi
             && j - i < VDP_MAX_RUN) j++;
      run = j - i;
    }
    let bestLen = 0, bestD = 0;
    if (i + 1 < n) {
      const key = hwAt(data, i) * 65536 + hwAt(data, i + 1);
      const cand = index.get(key);
      if (cand) for (let c = cand.length - 1, seen = 0; c >= 0 && seen < 64; c--, seen++) {
        const s = cand[c], d = i - s;
        if (d < 1 || d > VDP_WINDOW / 2) continue;
        let L = 0;
        while (L < VDP_MAX_MATCH && i + L < n && same(s + L, i + L)) L++;
        if (L > bestLen) { bestLen = L; bestD = d; }
        if (bestLen >= VDP_MAX_MATCH) break;
      }
    }
    let step;
    if (run >= 3 && run >= bestLen) { flush(); out.push(run - 1, lo); step = run; }
    else if (bestLen >= 3) {
      flush();
      const field = 0x1000 - 2 * bestD;
      out.push(0x00, ((bestLen - 1) << 4) | (field >> 8), field & 0xff);
      step = bestLen;
    } else {
      lit.push(i); step = 1;
      if (lit.length >= VDP_MAX_LIT) flush();
    }
    for (let k = i; k < i + step; k++) {
      if (k + 1 >= n) break;
      const key = hwAt(data, k) * 65536 + hwAt(data, k + 1);
      if (!index.has(key)) index.set(key, []);
      index.get(key).push(k);
    }
    i += step;
  }
  flush();
  out.push(0, 0);
  return Uint8Array.from(out);
}

export function vdpRepack(p, data) {
  const found = vdpStreamStart(p.raw);
  if (found === null) throw new Error('이 VDP의 압축 방식은 아직 해독되지 않았습니다');
  const [kind, start] = found;
  const stream = (kind === 'lz' ? vdpPackLz : vdpPackRle)(data);
  const out = new Uint8Array(start + stream.length + 2);
  out.set(p.raw.slice(0, start), 0);
  out.set(stream, start);
  return out;
}

// Fixed-width in place: the name pads to its 14 slots with the ideographic
// space, so the payload never changes length.



// What a content packet really is, where the destination misleads --
// see tama4u/vdp.py.
export function vdpContentLabel(sub, plain) {
  const dest = hex4(sub.raw.slice(OFF_DEST, OFF_DEST + 4));
  if (dest === VDP_CHAR_DEST) return '캐릭터 (육성)';
  if (dest === VDP_ICON_DEST) return '메뉴 아이콘 세트';
  if (sub.size <= VDP_STUB_MAX) return `빈 슬롯 (${plain})`;
  return plain;
}

// The payload is a run of complete packets, TAMAGO header and all, so the
// container parses it and every content gets the ordinary item treatment.
export function vdpSubPackets(p) {
  if (!isVdp(p)) return null;
  const data = vdpPayload(p);
  if (!data) return null;
  let base = -1;
  for (let i = 0; i + MAGIC.length <= data.length && base < 0; i++)
    if (MAGIC.every((v, k) => data[i + k] === v)) base = i;
  if (base < 0) return null;
  try {
    const { packets } = parseFile(data.slice(base));
    return [data, base, packets];
  } catch (e) { return null; }
}

// Recompressing changes the packet's length, so the size it declares at
// 0x4A has to move with it.
// A downloaded item, made fit to sit inside a bundle: the destination,
// price, stats, likes, name and sprites come across; the identity fields
// (download name, ANSI id, declared file size) keep the slot's, because a
// content is already installed and nothing routes it by name.
export function vdpFitContent(old, src) {
  const out = new Packet(src.raw, 0);
  out.raw.set(old.raw.slice(OFF_UNICODE_NAME, OFF_FILE_SIZE + 2), OFF_UNICODE_NAME);
  out.raw.set(old.raw.slice(OFF_ANSI_ID, OFF_PACKET_SIZE), OFF_ANSI_ID);
  out.offset = old.offset;
  out._orig = old._orig.slice();
  return out;
}

// The payload is reassembled rather than patched in place, because swapping
// a content for a different download changes its length.  The 4 KB prefix
// and the alignment padding between packets carry across untouched.
export function vdpWriteSubs(p, data, base, packets) {
  const parts = [data.slice(0, base + packets[0].offset)];
  packets.forEach((sub, k) => {
    sub.fixChecksums();
    parts.push(sub.raw);
    const was = base + sub.offset + sub._orig.length;
    const nxt = k + 1 < packets.length ? base + packets[k + 1].offset : data.length;
    parts.push(data.slice(was, nxt));
  });
  let n = 0; for (const q of parts) n += q.length;
  const buf = new Uint8Array(n);
  let at = 0; for (const q of parts) { buf.set(q, at); at += q.length; }
  const out = vdpRepack(p, buf);
  putU16(out, OFF_PACKET_SIZE, out.length);
  return out;
}
// ---- character stats ------------------------------------------------
export const CH = {
  TAMA_ID: 0x204, REVERT_ID: 0x206, GRAPHICS: 0x208, PERSONALITY: 0x20c,
  SKILLS: 0x20d, STAGE: 0x212, WEIGHT_STD: 0x213, WEIGHT_MIN: 0x214,
  HUNGER_DEP: 0x215, HAPPY_DEP: 0x216, SICKNESS: 0x217, WAKE: 0x218,
  SLEEP: 0x219, GENDER: 0x21a, BODY_TYPE: 0x21b, SEP_CLOTHES: 0x21c,
  SEP_ACCESSORY: 0x21e, BIRTH_MONTH: 0x220, BIRTH_DAY: 0x221,
  LIKE_INDEX: 0x222, TRANSFORM_TYPE: 0x22e, TRANSFORM_SERIAL: 0x230,
  TRANSFORM_NAME: 0x232, NAME2: 0x246, DIALOGUE: 0x272,
};
const CH_U8 = ['personality', 'stage', 'weight_std', 'weight_min', 'hunger_dep',
  'happy_dep', 'sickness', 'wake', 'gender', 'body_type', 'sep_clothes',
  'sep_accessory', 'birth_month', 'birth_day'];
const CH_U8_OFF = {
  personality: CH.PERSONALITY, stage: CH.STAGE, weight_std: CH.WEIGHT_STD,
  weight_min: CH.WEIGHT_MIN, hunger_dep: CH.HUNGER_DEP, happy_dep: CH.HAPPY_DEP,
  sickness: CH.SICKNESS, wake: CH.WAKE, gender: CH.GENDER, body_type: CH.BODY_TYPE,
  sep_clothes: CH.SEP_CLOTHES, sep_accessory: CH.SEP_ACCESSORY,
  birth_month: CH.BIRTH_MONTH, birth_day: CH.BIRTH_DAY,
};
const CH_U16_OFF = {
  tama_id: CH.TAMA_ID, revert_id: CH.REVERT_ID, graphics: CH.GRAPHICS,
  like_index: CH.LIKE_INDEX, transform_type: CH.TRANSFORM_TYPE,
  transform_serial: CH.TRANSFORM_SERIAL,
};
// The high byte of tama/revert id is a roster page encoding gender.
export const ROSTER_PAGE = { 0x13: 'Boy', 0x1b: 'Girl' };
export const roster = v => ({ page: (v >> 8) & 0xff, slot: v & 0xff,
  gender: ROSTER_PAGE[(v >> 8) & 0xff] ?? null, value: v });

export const GENDER = { 0: 'Boy', 1: 'Girl' };
export const STAGE = { 1: 'Baby', 2: 'Toddler', 3: 'Adult', 4: 'Transform character', 5: 'Download character' };
export const BODY_TYPE = {
  '4U': { 0: 'Ignore', 1: 'Normal', 2: 'Kuchipatchi', 3: 'Neenetchi', 4: 'Toddlers' },
  "P's": { 1: 'Normal', 2: 'Kuchipatchi', 3: 'Monakatchi', 4: 'Doyatchi' },
};
export const TRANSFORM_TYPE = { 0: 'Meal', 1: 'Snack', 2: 'Toy', 4: 'Clothes/accessory', 6: 'Minigame', 8: 'Outing' };
const LIKE_CHARS = ['Mametchi', 'MameLabtchi', 'Naughty Mametchi', 'Kuchipatchi',
  'Kuchipatchin', 'JeanisKuchipa', 'Spacytchi', 'Kirari Spacy', 'King Spacy',
  'Kuromametchi', 'Kuromamesenpai', 'Otakuromame', 'Orenetchi', 'Oreotonatchi',
  'Memetchi', 'Gourmemequeen', 'Memeobatchi', 'Himespetchi', 'Mamelove Himespetchi',
  'Lovelitchi', 'Lovelitchi Lovely Fire', 'PochaLovelitchi', 'Melodytchi',
  'Oyamelojitchi', 'Neenetchi', 'Slim Neene'];
const LIKE_TRAITS = ['Likes elegance', 'Likes coolness', 'Likes ??? (4143)',
  'Likes ??? (4144)', 'Likes sports', 'Likes ??? (4146)'];
export const LIKE_INDEX = { 0: 'No likes and dislikes' };
LIKE_CHARS.forEach((n, i) => { LIKE_INDEX[((0x41 + i) << 8) | 0xff] = n; });
LIKE_TRAITS.forEach((n, i) => { LIKE_INDEX[0x4141 + i] = n; });
export const bodyTypes = m => BODY_TYPE[m] || BODY_TYPE['4U'];
export const DIALOGUE_LABELS = [
  'Birthday', 'Marry proposal', 'Hungry', 'Play', 'Dress-up',
  'Upset (park camping)', 'Goodbye (good end)', 'Goodbye (bad end)',
  'Hobby skill rnd NFC4', 'Dream job rnd NFC3', 'Fav.food rnd NFC2',
  'Best friend rnd NFC1', 'Random talk 1', 'Random talk 2',
];

export function getCharStats(p) {
  const out = {};
  for (const k of CH_U8) out[k] = p.raw[CH_U8_OFF[k]];
  for (const [k, o] of Object.entries(CH_U16_OFF)) out[k] = u16le(p.raw, o);
  out.skills = Array.from(p.raw.slice(CH.SKILLS, CH.SKILLS + 5));
  out.sleep = p.raw[CH.SLEEP] + 1;             // displayed value
  return out;
}
export function setCharStats(p, s) {
  for (const k of CH_U8) if (k in s) p.raw[CH_U8_OFF[k]] = s[k] & 0xff;
  for (const [k, o] of Object.entries(CH_U16_OFF)) if (k in s) putU16le(p.raw, o, s[k] & 0xffff);
  if ('skills' in s) s.skills.slice(0, 5).forEach((v, i) => { p.raw[CH.SKILLS + i] = v & 0xff; });
  if ('sleep' in s) p.raw[CH.SLEEP] = (s.sleep - 1) & 0xff;
}
// The 0x50-0x51 signature alone is not enough: those two bytes are the tail
// of the destination code, so an iD item whose destination happens to end
// 48 03 matches it.  A character also has to hold the stat block and all 14
// dialogue slots.
export const CHAR_MIN_SIZE = CH.DIALOGUE + 14 * 150;
export const isCharacter = p =>
  p.typeSig[4] === 0x48 && p.typeSig[5] === 0x03 && p.size >= CHAR_MIN_SIZE;

// The character's own accessory (wardrobe frames 23-26) carries wear
// coordinates at the very end of the parent packet, *after* the nested
// wardrobe packet: 4 body types x 14 frames x (x, y).
export const ACC_TAIL_LEN = 4 * 14 * 2;
export const ACC_ROW_LEN = 14 * 2;        // one body type
export const ACC_FRAME_FOR_POSE = { 1: 23, 2: 23, 3: 23, 4: 23, 5: 23, 6: 23, 11: 23,
  7: 24, 8: 24, 9: 24, 10: 24, 13: 25, 14: 26, 15: 26 };
export const ACC_ROW_TO_FRAME = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 14, 15];

// 68 of 69 characters leave exactly 112 bytes, but fk00024_1-yumemitchi
// ships 108 -- its last body-type row is two pairs short.  Requiring an
// exact 112 dropped that file's table entirely.
export function accTailOffset(p) {
  if (!p.children.length) return null;
  const end = Math.max(...p.children.map(c => c.offset + c.size));
  const tail = p.size - 2 - end;
  return tail >= ACC_ROW_LEN && tail <= ACC_TAIL_LEN ? [end, tail] : null;
}
// A character has one body type, so the four rows are identical in every
// retail file; entries past a short tail fall back to row 0.
export function getCharAccPositions(p) {
  const got = accTailOffset(p);
  if (!got) return null;
  const [o, length] = got;
  const tail = p.raw.slice(o, o + length);
  if (!tail.some(x => x)) return null;
  const pair = k => (2 * k + 1 < length ? [tail[2 * k], tail[2 * k + 1]] : null);
  const base = Array.from({ length: 14 }, (_, i) => pair(i) || [64, 42]);
  return Array.from({ length: 4 }, (_, b) =>
    Array.from({ length: 14 }, (_, i) => pair(b * 14 + i) || base[i]));
}
export function setCharAccPositions(p, table) {
  const got = accTailOffset(p);
  if (!got) throw new Error('this packet has no wear-coordinate table');
  const [o, length] = got;
  table.slice(0, 4).forEach((rows, b) => rows.slice(0, 14).forEach(([x, y], i) => {
    const k = 2 * (b * 14 + i);
    if (k + 1 >= length) return;          // short tail: nothing to write into
    p.raw[o + k] = x & 0xff;
    p.raw[o + k + 1] = y & 0xff;
  }));
}

// ---- cross-model conversion -----------------------------------------
const DL_KEY = { 'iD': 'MDP', 'iDL': 'iDL', "P's": 'iDN', '4U': 'T4U' };
const ANSI_PREFIX = { 'iD': '', 'iDL': 'id2_', "P's": 'idn_', '4U': 't4u_' };
const ANSI_DIGITS = { 'iD': 3, 'iDL': 5, "P's": 5, '4U': 5 };
const NAME_PAGE = 0x0400;
const WEARABLE_SECTIONS = [2, 3];
const CONVERTIBLE_SECTIONS = [1, 2, 3, 4, 7];
const SIG_PREFERRED = { 'iD': 0xcd80, 'iDL': 0x2dc0, "P's": 0x8dc0, '4U': 0x0101 };
const dlPrefix = (m, cls) => (m === 'iD' ? `DL_${DL_KEY[m]}_` : `DL_${DL_KEY[m]}${cls}_`);

function hasBank(p) {
  if (p.packetClass !== 'S' || !CONVERTIBLE_SECTIONS.includes(p.section)) return false;
  try { parseBank(p.raw, bankOffset(p)); return true; } catch (e) { return false; }
}
const destFor = (target, label) => {
  if (!label) return null;
  for (const [l, code] of destOptions(target)) if (l === label) return code;
  return null;
};

export function convertPlan(p, target) {
  const src = p.model;
  const out = { from: src, to: target, ok: true, blockers: [], warnings: [], changes: [] };
  if (!LAYOUTS[target]) { out.ok = false; out.blockers.push(`알 수 없는 기종: ${target}`); return out; }
  if (src === target) { out.ok = false; out.blockers.push('이미 이 기종입니다.'); return out; }
  if (!hasBank(p)) {
    out.ok = false;
    out.blockers.push('스프라이트 뱅크를 읽을 수 없는 패킷입니다 (외출·캐릭터·편지 등은 변환 대상이 아닙니다).');
    return out;
  }
  if (WEARABLE_SECTIONS.includes(p.section) && (src === 'iD' || target === 'iD')) {
    out.ok = false;
    out.blockers.push('iD는 액세서리·의상 스프라이트 구성이 완전히 다릅니다 '
      + '(iD 액세서리 7장/의상 48×48 vs 나머지 4장/28장). 스프라이트를 새로 그려야 하므로 자동 변환하지 않습니다.');
    return out;
  }
  const L = layoutFor(src), M = layoutFor(target);
  out.changes.push(`기종 시그니처 0x4C → 0x${SIG_PREFERRED[target].toString(16).padStart(4, '0')}`);
  out.changes.push(`다운로드 이름 접두사 → ${dlPrefix(target, p.packetClass)}`);
  out.changes.push(`스프라이트 뱅크 0x${L.bank.toString(16)} → 0x${M.bank.toString(16)}`);
  const codes = p.itemNameCodes;
  if (codes.length > M.slots) out.warnings.push(`이름이 ${codes.length}자인데 ${target}는 ${M.slots}자까지라 잘립니다.`);
  if (L.width !== M.width)
    out.changes.push(`이름 인코딩 ${L.width}바이트 → ${M.width}바이트`
      + (M.width === 2 ? ' (0x04 페이지 부착)' : ' (0x04 페이지 제거)'));
  const label = destMatch(src, Array.from(p.raw.slice(OFF_DEST, OFF_DEST + 4)), p.raw);
  const code = destFor(target, label);
  if (code) out.changes.push(`행선지 → ${label} (${code})`);
  else out.warnings.push(`행선지 "${label || '미확인'}"에 해당하는 ${target} 코드가 없어 섹션 기본값으로 둡니다. 저장 후 확인하세요.`);
  const nbytes = (likesSlots(p) + 3) >> 2;
  let anyLike = false;
  for (let i = 0; i < nbytes; i++) if (p.raw[L.likes + i]) anyLike = true;
  if (anyLike) out.warnings.push("호불호는 기종마다 캐릭터 명단이 달라(iD 16 / iD L 74 / P's·4U 32칸) 옮길 수 없습니다. 전부 해제됩니다.");
  if (L.stats !== null && M.stats === null) out.warnings.push(`${target}에는 5스탯 칸이 없어 버려집니다.`);
  if (L.anim !== null && M.anim === null) out.warnings.push(`${target}에는 애니메이션 ID 칸이 없어 버려집니다.`);
  if (target === 'iD') out.warnings.push('iD는 카탈로그 인덱스(행선지 3번째 바이트)를 기기가 검사합니다. 변환 후 "기기 버전" 카드에서 인덱스를 지정하세요.');
  out.warnings.push('0x52 토큰 8바이트는 계산식을 몰라 원본 값을 그대로 둡니다.');
  return out;
}

export function convert(p, target, serial = null) {
  const info = convertPlan(p, target);
  if (!info.ok) throw new Error(info.blockers.join('; '));
  const src = p.model, L = layoutFor(src), M = layoutFor(target);
  const body = p.raw.slice(L.bank, p.size - 2);
  const size = M.bank + body.length + 2;
  const nw = new Uint8Array(size);
  nw.set(MAGIC, 0);

  const disp = p.unicodeName;
  const us = disp.startsWith('DL_') ? disp.indexOf('_', 3) : -1;
  let tail = us >= 0 ? disp.slice(us + 1) : disp;
  if (tail.includes('.')) tail = tail.slice(0, tail.lastIndexOf('.')) + '.jpg';
  const dl = dlPrefix(target, p.packetClass) + tail;
  for (let i = 0; i < dl.length && OFF_UNICODE_NAME + 2 * i + 1 < OFF_FILE_SIZE; i++)
    putU16(nw, OFF_UNICODE_NAME + 2 * i, dl.charCodeAt(i));

  const ser = (serial === null && src !== 'iD') ? p.serial : (serial || 0);
  const kind = SECTION_KIND[p.section] || 'gh';
  if (ANSI_PREFIX[target] || ser < 10 ** ANSI_DIGITS[target]) {
    const aid = `${ANSI_PREFIX[target]}${kind}${String(ser).padStart(ANSI_DIGITS[target], '0')}_1`;
    for (let i = 0; i < aid.length; i++) nw[OFF_ANSI_ID + i] = aid.charCodeAt(i);
  }
  putU16(nw, OFF_FILE_SIZE, Math.max(0, p.declaredSize + size - p.size));
  putU16(nw, OFF_PACKET_SIZE, size);
  putU16(nw, OFF_TYPE_SIG, SIG_PREFERRED[target]);

  const cur = Array.from(p.raw.slice(OFF_DEST, OFF_DEST + 4));
  const label = destMatch(src, cur, p.raw);
  const code = destFor(target, label);
  let dest = code ? code.match(/../g).map(x => parseInt(x, 16)) : cur;
  if (target === 'iD') dest = destApply('iD', dest.map(b => b.toString(16).padStart(2, '0')).join(''), [0, 0, 0, 0]);
  nw.set(dest, OFF_DEST);
  // iD splits games from outings at 0x64
  const dhex = dest.map(b => b.toString(16).padStart(2, '0')).join('');
  const dx = destExtra(target, dhex, label);
  if (dx && nw.length > dx[0]) nw[dx[0]] = dx[1];
  nw.set(p.token, OFF_TOKEN);
  if (target !== 'iD') putU16(nw, OFF_SERIAL, ser & 0xffff);

  const codes = p.itemNameCodes.slice(0, M.slots).map(c =>
    L.width === M.width ? c : (M.width === 2 ? NAME_PAGE | (c & 0xff) : c & 0xff));
  for (let i = 0; i < M.slots; i++) {
    const c = i < codes.length ? codes[i] : 0;      // 4U pads with 0x0000
    if (M.width === 1) nw[M.name + i] = c & 0xff;
    else putU16(nw, M.name + 2 * i, c);
  }
  putU16(nw, M.price, getPrice(p));
  nw[M.hunger] = p.raw[L.hunger];
  nw[M.friendship] = p.raw[L.friendship];
  if (L.anim !== null && M.anim !== null) { nw[M.anim] = p.raw[L.anim]; nw[M.anim + 1] = p.raw[L.anim + 1]; }
  if (L.stats !== null && M.stats !== null) nw.set(p.raw.slice(L.stats, L.stats + 5), M.stats);
  // likes stay zero: the character rosters differ between models
  nw[OFF_COMPAT_MASK] = COMPAT_BIT[target] || 0;
  if (target === 'iD') nw[0x63] = effectiveKind(p) === 'oy' ? 1 : 2;
  if (p.section === 1) {
    const tag = { "P's": 0xa8, '4U': 0xb2 };
    const v = tag[src] !== undefined ? p.raw[tag[src]] : 0;
    if (tag[target] !== undefined) nw[tag[target]] = v;
    if (target === '4U') nw[0x73] = 0x02;
  }
  nw.set(body, M.bank);
  putU16(nw, size - 2, sum16(nw.subarray(0, -2)));
  return new Packet(nw, 0);
}
