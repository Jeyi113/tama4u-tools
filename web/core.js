// Container, sprite codec and per-model layout -- a direct port of
// tama4u/{container,sprites,models,destinations}.py.  The Python package
// stays the reference implementation; web/selftest.js diffs the two over
// the whole download pack so this file cannot drift silently.

export const MAGIC = [0x54, 0x41, 0x4d, 0x41, 0x47, 0x4f];   // "TAMAGO"

export const OFF_UNICODE_NAME = 0x06;
export const OFF_FILE_SIZE    = 0x32;
export const OFF_ANSI_ID      = 0x34;
export const OFF_PACKET_SIZE  = 0x4a;
export const OFF_TYPE_SIG     = 0x4c;
export const OFF_TOKEN        = 0x52;
export const OFF_SERIAL       = 0x5a;

export const sum16 = b => { let s = 0; for (const x of b) s += x; return s & 0xffff; };
export const u16 = (b, o) => (b[o] << 8) | b[o + 1];
export const putU16 = (b, o, v) => { b[o] = (v >> 8) & 0xff; b[o + 1] = v & 0xff; };
export const u16le = (b, o) => b[o] | (b[o + 1] << 8);
export const putU16le = (b, o, v) => { b[o] = v & 0xff; b[o + 1] = (v >> 8) & 0xff; };

function find(hay, needle, from = 0) {
  outer: for (let i = from; i <= hay.length - needle.length; i++) {
    for (let j = 0; j < needle.length; j++) if (hay[i + j] !== needle[j]) continue outer;
    return i;
  }
  return -1;
}

// ---- models ---------------------------------------------------------
export const LAYOUTS = {
  'iD':  { name: 0x5a, width: 1, slots: 9,  price: 0x66, bank: 0x100,
           hunger: 0x6c, friendship: 0x6d, anim: null,
           likes: 0x68, likes_slots: 16, stats: null },
  'iDL': { name: 0x5e, width: 1, slots: 14, price: 0x6c, bank: 0x100,
           hunger: 0x70, friendship: 0x71, anim: 0x6e,
           likes: 0x72, likes_slots: 74, stats: null },
  "P's": { name: 0x5e, width: 1, slots: 14, price: 0x6c, bank: 0x100,
           hunger: 0x70, friendship: 0x71, anim: 0x6e,
           likes: 0x8a, likes_slots: 32, stats: 0xae },
  '4U':  { name: 0x5e, width: 2, slots: 9,  price: 0x76, bank: 0x200,
           hunger: 0x7a, friendship: 0x7b, anim: 0x78,
           likes: 0x94, likes_slots: 32, stats: 0xb8 },
};
export const DEFAULT_MODEL = '4U';

// u16 at 0x4C.  Authoritative: a third of the corpus ships one model's
// packet under another model's download name.
export const SIGNATURES = {
  0xcd80: 'iD', 0x0dc0: 'iD', 0x1dc0: 'iD', 0xcdc0: 'iD',
  0x2dc0: 'iDL', 0x8dc0: "P's", 0x0101: '4U',
};
export const COMPAT_BIT = { 'iDL': 0x01, "P's": 0x02, '4U': 0x10 };
export const OFF_COMPAT_MASK = 0xff;

const PREFIX = { MDP: 'iD', iDL: 'iDL', iDN: "P's", T4U: '4U', APL: 'iD' };

export function detect(unicodeName) {
  if (!unicodeName.startsWith('DL_')) return [DEFAULT_MODEL, 'S'];
  const head = unicodeName.slice(3).split('_')[0];
  if (!head) return [DEFAULT_MODEL, 'S'];
  const last = head[head.length - 1];
  const cls = 'SAC'.includes(last) ? last : 'S';
  const key = 'SAC'.includes(last) ? head.slice(0, -1) : head;
  return [PREFIX[key] || PREFIX[head] || DEFAULT_MODEL, cls];
}
export const layoutFor = m => LAYOUTS[m] || LAYOUTS[DEFAULT_MODEL];

// ---- destinations ---------------------------------------------------
const COMMON = [
  ['레스토랑 · 식사', '81010201', 'ffffffff'],
  ['레스토랑 · 간식', '81010d02', 'ffffffff'],
  ['타마데파 · 장난감', '81042a01', 'ffffffff'],
  ['타마모리 · 옷', '81033300', 'ffffffff'],
  ['타마모리 · 액세서리', '81023400', 'ffffffff'],
  ['고치 인테리어 · 방', '81071f00', 'ffffffff'],
];
export const DEST_CATALOG = {
  'iD': [
    ['레스토랑 · 식사', '01010001', 'ffff00ff'],
    ['레스토랑 · 간식', '01010003', 'ffff00ff'],
    ['타마데파 · 장난감', '01040001', 'ffff00ff'],
    ['타마모리 · 액세서리', '01020000', 'ffff00ff'],
    ['고치 인테리어 · 방', '01070000', 'ffff00ff'],
    ['사진관 · 의상', '02030001', 'ffff00ff'],
    ['우편함 · 편지', '01060000', 'ffffffff'],
    // iD parks games and outings on one destination and keeps the
    // category in a byte at 0x64 -- that is the 4th element
    ['게임센터 · 게임', '14020000', 'ffffffff', [0x64, 0x37]],
    ['외출지', '14020000', 'ffffffff', [0x64, 0x0f]],
  ],
  'iDL': [...COMMON,
    ['우편함 · 편지', '81065101', 'ffffffff'],
    ['우편함 · 해피메일', '81065202', 'ffffffff'],
    ["타마모리 · 액세서리 (P's용)", '81023500', 'ffffffff'],
    ['타마데파 · 씨앗', '81082900', 'ffffffff'],
    ['타마데파 · 생활용품', '81042902', 'ffffffff'],
    ['타마베이커리 · 간식', '81010c02', 'ffffffff'],
    ['게임센터 · 게임', '94025b01', 'ffffffff'],
    ['외출지', '94024702', 'ffffffff'],
  ],
  "P's": [...COMMON,
    ['보물상자 · 편지', '81065101', 'ffffffff'],
    ['보물상자 · 스탬프카드', '81065203', 'ffffffff'],
    ['통신놀이 · 레시피', '81092900', 'ffffffff'],
    ['타마모리 · 액세서리 2', '81023500', 'ffffffff'],
    ['게임센터 · 게임', '94025b01', 'ffffffff'],
    ['외출지', '94024702', 'ffffffff'],
    ['VDP · 아이템 묶음', '94025b02', 'ffffffff'],
    // only ever seen inside VDPs, never as a standalone P's download, but
    // it is the iD L code for the same shop shelf
    ['타마데파 · 생활용품', '81042902', 'ffffffff'],
  ],
  '4U': [...COMMON,
    ['냉장고 직행 · 식사 (비매품)', '81010101', 'ffffffff'],
    ['냉장고 직행 · 간식 (비매품)', '81010102', 'ffffffff'],
    ['빙고 정의', '81082900', 'ffffffff'],
    ['게임센터 · 게임', '94025b01', 'ffffffff'],
    ['외출지', '94024702', 'ffffffff'],
    ['카드 · 캐릭터 프로그램', '94024803', 'ffffffff'],
  ],
};
export const destOptions = m => DEST_CATALOG[m] || DEST_CATALOG['4U'];
const hex2bytes = h => h.match(/../g).map(x => parseInt(x, 16));

// `raw` is the whole packet; without it, entries that also depend on a byte
// outside the destination are only reported when nothing else claims the code.
export function destMatch(model, code, raw = null) {
  let pending = null;
  for (const [label, tmpl, mask, extra] of destOptions(model)) {
    const t = hex2bytes(tmpl), m = hex2bytes(mask);
    let ok = true;
    for (let i = 0; i < 4; i++) if (m[i] && t[i] !== code[i]) { ok = false; break; }
    if (!ok) continue;
    if (!extra) return label;
    const [off, val] = extra;
    if (raw) { if (raw.length > off && raw[off] === val) return label; }
    else if (pending === null) pending = label;
  }
  return pending;
}
export function destApply(model, code, current) {
  for (const [, tmpl, mask] of destOptions(model)) {
    if (tmpl === code) {
      const t = hex2bytes(tmpl), m = hex2bytes(mask);
      return t.map((v, i) => (m[i] ? v : current[i]));
    }
  }
  return hex2bytes(code);
}
// The (offset, value) a chosen category also needs written, if any.  Several
// categories can share one code, so the label picks between them.
export function destExtra(model, code, label = null) {
  for (const e of destOptions(model)) {
    if (e[1] !== code) continue;
    if (label != null && e[0] !== label) continue;
    return e[3] || null;
  }
  return null;
}

// ---- packet ---------------------------------------------------------
export class Packet {
  constructor(data, offset = 0) {
    this.offset = offset;
    const size = u16(data, offset + OFF_PACKET_SIZE);
    this.raw = data.slice(offset, offset + size);
    this._orig = this.raw.slice();
    this.children = [];
    let pos = find(this.raw, MAGIC, MAGIC.length);
    while (pos !== -1) {
      const declared = pos + OFF_PACKET_SIZE + 2 <= this.raw.length
        ? u16(this.raw, pos + OFF_PACKET_SIZE) : 0;
      const sig = pos + OFF_TYPE_SIG + 2 <= this.raw.length
        ? u16(this.raw, pos + OFF_TYPE_SIG) : 0;
      // A size check alone is not enough: a VDP's program blob spells
      // TAMAGO often enough that false hits passed and then masked the
      // regions the sprite scan would have read.  A real nested packet
      // always carries a model signature at 0x4C.
      if (declared < 0x60 || pos + declared > this.raw.length
          || !SIGNATURES[sig]) {
        pos = find(this.raw, MAGIC, pos + MAGIC.length);   // false hit in pixels
        continue;
      }
      const child = new Packet(this.raw, pos);
      this.children.push(child);
      pos = find(this.raw, MAGIC, pos + child.size);
    }
  }
  get size() { return this.raw.length; }
  get unicodeName() {
    let out = '';
    for (let i = OFF_UNICODE_NAME; i < OFF_FILE_SIZE; i += 2) {
      const c = u16(this.raw, i);
      if (c === 0) break;
      out += String.fromCharCode(c);
    }
    return out;
  }
  get ansiId() {
    let out = '';
    for (let i = OFF_ANSI_ID; i < OFF_PACKET_SIZE; i++) {
      const b = this.raw[i];
      if (b === 0) break;
      out += b < 0x80 ? String.fromCharCode(b) : '\ufffd';   // ascii, errors='replace'
    }
    return out;
  }
  get typeSig() { return Array.from(this.raw.slice(OFF_TYPE_SIG, OFF_TYPE_SIG + 6)); }
  get token() { return this.raw.slice(OFF_TOKEN, OFF_TOKEN + 8); }
  get serial() { return u16(this.raw, OFF_SERIAL); }
  get declaredSize() { return u16(this.raw, OFF_FILE_SIZE); }
  shiftDeclaredSize(d) {
    putU16(this.raw, OFF_FILE_SIZE, Math.max(0, Math.min(0xffff, this.declaredSize + d)));
  }
  get section() { return this.raw[0x4f]; }
  get model() {
    const sig = this.raw.length >= OFF_TYPE_SIG + 2 ? u16(this.raw, OFF_TYPE_SIG) : 0;
    return SIGNATURES[sig] || detect(this.unicodeName)[0];
  }
  get packetClass() { return detect(this.unicodeName)[1]; }
  get layout() { return layoutFor(this.model); }
  get itemNameCodes() {
    const { name: off, width, slots } = this.layout;
    const out = [];
    for (let i = 0; i < slots; i++) {
      const c = width === 1 ? this.raw[off + i] : u16(this.raw, off + 2 * i);
      if (c === 0) break;
      out.push(c);
    }
    return out;
  }
  get kind() {
    let s = this.ansiId;
    for (const p of ['t4u_', 'id2_', 'idn_']) if (s.startsWith(p)) { s = s.slice(p.length); break; }
    let out = '';
    for (const ch of s) { if (!/[a-zA-Z]/.test(ch)) break; out += ch; }
    return out || '?';
  }
  setSerial(value) {
    putU16(this.raw, OFF_SERIAL, value);
    const old = this.ansiId;                     // keep t4u_gh01855_1 in sync
    if (old.startsWith('t4u_') && this.kind !== '?') {
      const head = 't4u_' + this.kind;
      const tail = old.slice(head.length);
      let digits = '';
      for (const ch of tail) { if (!/[0-9]/.test(ch)) break; digits += ch; }
      const pad = digits.length || 5;
      const next = head + String(value).padStart(pad, '0') + tail.slice(digits.length);
      const field = new Uint8Array(OFF_PACKET_SIZE - OFF_ANSI_ID);
      for (let i = 0; i < next.length && i < field.length; i++) field[i] = next.charCodeAt(i);
      this.raw.set(field, OFF_ANSI_ID);
    }
  }
  setItemNameCodes(codes) {
    const { name: off, width, slots } = this.layout;
    if (codes.length > slots) throw new Error(`item name is limited to ${slots} characters`);
    const full = [...codes, ...new Array(slots - codes.length).fill(0)];
    for (let i = 0; i < slots; i++) {
      if (width === 1) this.raw[off + i] = full[i] & 0xff;
      else putU16(this.raw, off + 2 * i, full[i]);
    }
  }
  setUnicodeName(name) {
    const cur = this.unicodeName;
    const us = cur.indexOf('_', 3);
    const head = us >= 0 ? cur.slice(0, us + 1) : 'DL_T4US_';
    const full = `${head}${name}.jpg`;
    if (full.length * 2 > OFF_FILE_SIZE - OFF_UNICODE_NAME) throw new Error('unicode name too long');
    const buf = new Uint8Array(OFF_FILE_SIZE - OFF_UNICODE_NAME);
    for (let i = 0; i < full.length; i++) putU16(buf, 2 * i, full.charCodeAt(i));
    this.raw.set(buf, OFF_UNICODE_NAME);
  }
  checksumOk() { return sum16(this.raw.subarray(0, -2)) === u16(this.raw, this.size - 2); }
  // Untouched packets keep their original trailing bytes: a few retail files
  // ship a stale nested checksum the device accepts, and "fixing" it would
  // alter bytes we never edited.
  fixChecksums() {
    for (const c of this.children) {
      c.fixChecksums();
      this.raw.set(c.raw, c.offset);
    }
    let same = this.raw.length === this._orig.length;
    if (same) for (let i = 0; i < this.raw.length - 2; i++)
      if (this.raw[i] !== this._orig[i]) { same = false; break; }
    if (same) { this.raw[this.size - 2] = this._orig[this.size - 2];
                this.raw[this.size - 1] = this._orig[this.size - 1]; }
    else putU16(this.raw, this.size - 2, sum16(this.raw.subarray(0, -2)));
  }
}

export function parseFile(data) {
  const first = find(data, MAGIC);
  if (first === -1) throw new Error('no TAMAGO packet found');
  const jpeg = data.slice(0, first);
  const packets = [];
  let pos = first;
  for (;;) {
    const pkt = new Packet(data, pos);
    packets.push(pkt);
    pos += pkt.size;
    const nxt = find(data, MAGIC, pos);
    if (nxt === -1) break;
    pos = nxt;
  }
  return { jpeg, packets, trailing: data.slice(pos) };
}

export function buildFile(jpeg, packets, trailing = new Uint8Array(0)) {
  for (const p of packets) p.fixChecksums();
  const total = jpeg.length + packets.reduce((a, p) => a + p.size, 0) + trailing.length;
  const out = new Uint8Array(total);
  let o = 0;
  out.set(jpeg, o); o += jpeg.length;
  for (const p of packets) { out.set(p.raw, o); o += p.size; }
  out.set(trailing, o);
  return out;
}

// ---- sprite codec ---------------------------------------------------
// Frame record: u16 slot_size | w | h | ncol | 00 | 01 FF | BGR565 palette
//               | 4bpp pixels, LOW nibble = left pixel
export const bgr565ToRgb = v => {
  const b = (v >> 11) & 0x1f, g = (v >> 5) & 0x3f, r = v & 0x1f;
  return [(r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2)];
};
export const rgbToBgr565 = ([r, g, b]) =>
  ((b >> 3) << 11) | ((g >> 2) << 5) | (r >> 3);

// Records with more than 16 colours store one byte per pixel, not a nibble.
// The games keep their backgrounds and item strips that way.
export const PAL4_MAX = 16;
export const bppFor = ncol => (ncol <= PAL4_MAX ? 4 : 8);
export const pixelBytes = (w, h, nf, ncol) =>
  nf * (ncol > PAL4_MAX ? w * h : (w * h + 1) >> 1);
export function unpackPixels(buf, ncol) {
  if (ncol > PAL4_MAX) return Array.from(buf);
  const px = [];
  for (const b of buf) px.push(b & 0xf, b >> 4);
  return px;
}
export function packPixels(px, ncol) {
  if (ncol > PAL4_MAX) return px.slice();
  const out = [];
  for (let i = 0; i + 1 < px.length; i += 2) out.push((px[i + 1] << 4) | px[i]);
  return out;
}

export function parseBank(raw, offset) {
  // Python's struct.unpack_from raises past the end; JS would quietly read
  // NaN, so every read is bounds-checked to keep the two in step.
  if (offset + 2 > raw.length) throw new Error('bank header past packet end');
  const count = u16(raw, offset);
  const frames = [];
  let o = offset + 2;
  for (let n = 0; n < count; n++) {
    if (o + 8 > raw.length) throw new Error('frame header past packet end');
    const slot = u16(raw, o);
    const w = raw[o + 2], h = raw[o + 3], ncol = raw[o + 4], zero = raw[o + 5];
    const sig = u16(raw, o + 6);
    if (zero !== 0 || sig !== 0x01ff) throw new Error(`bad frame record at 0x${o.toString(16)}`);
    const palOff = o + 8;
    if (palOff + 2 * ncol > raw.length) throw new Error('palette past packet end');
    const palette = [];
    for (let i = 0; i < ncol; i++) palette.push(bgr565ToRgb(u16(raw, palOff + 2 * i)));
    const pxOff = palOff + 2 * ncol;
    const need = pixelBytes(w, h, 1, ncol);
    if (pxOff + need > raw.length) throw new Error('frame runs past packet');
    const pixels = unpackPixels(raw.subarray(pxOff, pxOff + need), ncol)
      .slice(0, w * h);
    while (pixels.length < w * h) pixels.push(0);
    frames.push({ slot_size: slot, w, h, palette, pixels });
    o += 2 + slot;
  }
  return { frames, end: o };
}

export function writeBank(raw, frames, offset) {
  putU16(raw, offset, frames.length);
  let o = offset + 2;
  for (const f of frames) {
    const body = [f.w, f.h, f.palette.length, 0, 0x01, 0xff];
    for (const c of f.palette) { const v = rgbToBgr565(c); body.push(v >> 8, v & 0xff); }
    const px = f.pixels.slice();
    if (px.length % 2) px.push(0);
    body.push(...packPixels(px, f.palette.length));
    if (body.length > f.slot_size)
      throw new Error(`frame data ${body.length} exceeds slot ${f.slot_size} (reduce palette size)`);
    while (body.length < f.slot_size) body.push(0);
    putU16(raw, o, f.slot_size);
    raw.set(body, o + 2);
    o += 2 + f.slot_size;
  }
}

// Standalone records inside gm/dlode program blobs: a bank record without
// the u16 slot prefix, anchored on the 00 NN FF signature.
export function scanBanks(raw, start = 0x60) {
  const found = [];
  let o = start;
  while (o < raw.length - 8) {
    const n = u16(raw, o);
    if (n >= 1 && n <= 200) {
      try {
        const { frames, end } = parseBank(raw, o);
        if (frames.length && end <= raw.length) { found.push({ offset: o, end, frames }); o = end; continue; }
      } catch (e) { /* not a bank here */ }
    }
    o += 1;
  }
  return found;
}

export function scanLoose(raw, lo = 0x200, hi = null) {
  hi = hi ?? raw.length;
  const sigs = [];
  for (let o = lo + 6; o < hi - 2; o++) {
    if (raw[o + 1] !== 0xff || !(raw[o] >= 1 && raw[o] <= 32)) continue;
    const start = o - 4;
    const w = raw[start], h = raw[start + 1], ncol = raw[start + 2], z = raw[start + 3];
    if (z !== 0 || !(w >= 2 && w <= 128 && h >= 2 && h <= 128)
        || !(ncol >= 1 && ncol <= 255) || start + 6 + 2 * ncol >= hi) continue;
    if (ncol > PAL4_MAX) {
      // 8bpp widens the signature a lot, so only take the record when every
      // pixel actually indexes into the palette
      const px = start + 6 + 2 * ncol;
      const end = px + pixelBytes(w, h, raw[o], ncol);
      if (end > hi) continue;
      let bad = false;
      for (let k = px; k < end; k++) if (raw[k] >= ncol) { bad = true; break; }
      if (bad) continue;
    }
    sigs.push([start, w, h, ncol, raw[o]]);
  }
  const out = [];
  for (let i = 0; i < sigs.length; i++) {
    const [start, w, h, ncol, nf] = sigs[i];
    const last = out[out.length - 1];
    if (last && start < last[0] + 6 + 2 * last[3]) continue;   // inside previous header
    const pxStart = start + 6 + 2 * ncol;
    const need = pixelBytes(w, h, nf, ncol);
    const pxEnd = Math.min(pxStart + need, i + 1 < sigs.length ? sigs[i + 1][0] : hi);
    out.push([start, w, h, ncol, nf, Math.max(0, pxEnd - pxStart)]);
  }
  return out;
}

export function readLoose(raw, rec) {
  const [start, w, h, ncol, nf, avail] = rec;
  const palOff = start + 6;
  const palette = [];
  for (let i = 0; i < ncol; i++) palette.push(bgr565ToRgb(u16(raw, palOff + 2 * i)));
  const px = unpackPixels(
    raw.subarray(palOff + 2 * ncol, palOff + 2 * ncol + avail), ncol);
  while (px.length < nf * w * h) px.push(0);
  const per = w * h;
  const frames = [];
  for (let k = 0; k < nf; k++)
    frames.push({ slot_size: 0, w, h, palette, pixels: px.slice(k * per, (k + 1) * per) });
  return frames;
}

export function writeLoose(raw, rec, palette, pixelLists) {
  const [start, , , ncol, , avail] = rec;
  if (palette.length !== ncol) throw new Error(`loose record: palette size must stay ${ncol}`);
  const palOff = start + 6;
  for (let i = 0; i < palette.length; i++) putU16(raw, palOff + 2 * i, rgbToBgr565(palette[i]));
  const px = [].concat(...pixelLists);
  raw.set(packPixels(px, ncol).slice(0, avail), palOff + 2 * ncol);
}

// ---- indexed BMP: 4bpp like Tama Image Editor, 8bpp for >16 colours ---
export function frameToBmp(f) {
  const ncol = Math.max(f.palette.length, 1);
  const bpp = bppFor(ncol), slots = bpp === 4 ? 16 : 256;
  const rowsz = (((f.w * bpp + 31) / 32) | 0) * 4;
  const pal = [...f.palette];
  while (pal.length < slots) pal.push([0, 0, 0]);
  const paloff = 54 + 4 * slots;
  const size = paloff + rowsz * f.h;
  const out = new Uint8Array(size);
  const dv = new DataView(out.buffer);
  out[0] = 0x42; out[1] = 0x4d;
  dv.setUint32(2, size, true); dv.setUint32(10, paloff, true);
  dv.setUint32(14, 40, true); dv.setInt32(18, f.w, true); dv.setInt32(22, f.h, true);
  dv.setUint16(26, 1, true); dv.setUint16(28, bpp, true);
  dv.setUint32(34, rowsz * f.h, true);
  dv.setUint32(38, 2835, true); dv.setUint32(42, 2835, true); dv.setUint32(46, slots, true);
  for (let i = 0; i < slots; i++) {
    const [r, g, b] = pal[i];
    out[54 + 4 * i] = b; out[54 + 4 * i + 1] = g; out[54 + 4 * i + 2] = r;
  }
  let p = paloff;
  for (let y = f.h - 1; y >= 0; y--) {
    const row = new Uint8Array(rowsz);
    for (let x = 0; x < f.w; x++) {
      const v = f.pixels[y * f.w + x];
      if (bpp === 8) row[x] = v;
      else if (x % 2 === 0) row[x >> 1] |= v << 4;
      else row[x >> 1] |= v;
    }
    out.set(row, p); p += rowsz;
  }
  return out;
}

export function bmpToFrame(data, slotSize) {
  const dv = new DataView(data.buffer, data.byteOffset, data.byteLength);
  const off = dv.getUint32(10, true);
  const w = dv.getInt32(18, true), h = dv.getInt32(22, true);
  const bpp = dv.getUint16(28, true);
  if (bpp !== 4 && bpp !== 8) throw new Error('expected a 4bpp or 8bpp indexed BMP');
  const ncol = dv.getUint32(46, true) || (1 << bpp);
  const palette = [];
  for (let i = 0; i < ncol; i++)
    palette.push([data[54 + 4 * i + 2], data[54 + 4 * i + 1], data[54 + 4 * i]]);
  const rowsz = (((w * bpp + 31) / 32) | 0) * 4;
  const pixels = [];
  for (let y = h - 1; y >= 0; y--)
    for (let x = 0; x < w; x++) {
      if (bpp === 8) pixels.push(data[off + y * rowsz + x]);
      else {
        const b = data[off + y * rowsz + (x >> 1)];
        pixels.push(x % 2 === 0 ? b >> 4 : b & 0xf);
      }
    }
  const used = Math.max(...pixels) + 1;
  return { slot_size: slotSize, w, h, palette: palette.slice(0, Math.max(used, 1)), pixels };
}
