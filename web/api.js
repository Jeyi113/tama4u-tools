// describe() / applyEdits() -- the two calls the UI makes.  Same shapes as
// the Python editor's /api/parse and /api/build so the view layer is
// unchanged; web/selftest.js diffs the two implementations file by file.
import {
  parseFile, buildFile, Packet, u16, putU16, OFF_PACKET_SIZE,
  parseBank, writeBank, scanBanks, scanLoose, readLoose, writeLoose,
  destOptions,
} from './core.js';
import * as F from './format.js';

const findPacket = (packets, path) => path.slice(1).reduce((p, i) => p.children[i], packets[path[0]]);

function* iterPackets(packets) {
  function* walk(pkt, path) {
    yield [path, pkt];
    for (let i = 0; i < pkt.children.length; i++) yield* walk(pkt.children[i], [...path, i]);
  }
  for (let i = 0; i < packets.length; i++) yield* walk(packets[i], [i]);
}

const b64 = u8 => {
  let s = '';
  const CH = 0x8000;
  for (let i = 0; i < u8.length; i += CH) s += String.fromCharCode.apply(null, u8.subarray(i, i + CH));
  return btoa(s);
};

const frameOut = f => ({ slot: f.slot_size, w: f.w, h: f.h, palette: f.palette, pixels: f.pixels });

export function describe(data, opts = {}) {
  const { jpeg, packets } = parseFile(data);
  const out = { jpeg_b64: opts.jpeg === false ? null : b64(jpeg), packets: [] };
  for (const [path, pkt] of iterPackets(packets)) {
    const model = pkt.model;
    const table = F.tableFor(model);
    const sig = pkt.typeSig;
    const isChar = F.isCharacter(pkt);
    const info = {
      model,
      name_slots: pkt.layout.slots,
      packet_class: pkt.packetClass,
      is_wardrobe: pkt.packetClass === 'C',
      stats_verified: pkt.packetClass === 'S',
      path,
      ansi_id: pkt.ansiId,
      kind: F.effectiveKind(pkt),
      section: pkt.section,
      serial: pkt.serial,
      unicode_name: pkt.unicodeName,
      name: F.decode(pkt.itemNameCodes, table),
      size: pkt.size,
      dest: Array.from(pkt.raw.slice(F.OFF_DEST, F.OFF_DEST + 4))
        .map(x => x.toString(16).padStart(2, '0')).join(''),
      dest_label: F.getDestination(pkt),
      dest_options: destOptions(model).map(([label, code]) => ({ label, code })),
      is_item: !isChar && !F.isProgram(pkt)
        && (F.BANK_OFFSETS[F.effectiveKind(pkt)] !== undefined || model !== '4U'),
    };
    if (model === 'iD') { info.version = F.getVersion(pkt); info.version_presets = F.VERSION_PRESETS; }
    info.compat = F.getCompat(pkt);
    info.convert = {};
    for (const m of ['iD', 'iDL', "P's", '4U']) if (m !== model) info.convert[m] = F.convertPlan(pkt, m);
    if (info.is_item && !info.is_wardrobe) info.price = F.getPrice(pkt);
    if (info.is_item && info.stats_verified) {
      const anim = F.getAnim(pkt);
      info.fields = F.editableFields(pkt);
      info.likes_slots = F.likesSlots(pkt);
      info.likes_labels = F.likeLabels(pkt);
      info.likes_roster = F.likeRoster(pkt);
      info.hunger = F.getHunger(pkt);
      info.friendship = F.getFriendship(pkt);
      info.likes = F.getLikesRaw(pkt);
      info.stats = F.getStats(pkt);
      info.anim_a = anim[0]; info.anim_b = anim[1];
    }
    info.opaque = F.OPAQUE_KINDS.includes(pkt.kind);
    if (info.is_item && pkt.section === F.SECTION_MAIL) {
      const width = pkt.layout.width;
      const banks = scanBanks(pkt.raw, 0x60);
      if (banks.length) {
        const [lo, hi] = F.letterTextRange(pkt, banks[0].offset);
        const body = F.scanTexts(pkt.raw, model, lo, hi, 3, width);
        F.groupRuns(body, width).forEach((g, i) => {
          (info.texts ??= []).push({ parts: g.parts, chars: g.chars, text: g.text, width,
            label: i === 0 ? '편지 본문' : `편지 본문 ${i + 1}` });
        });
      }
    }
    if (F.effectiveKind(pkt) === 'ac' && pkt.packetClass === 'S') {
      const rows = F.getAccPositions(pkt);
      if (rows) { info.acc_pos = rows; info.acc_rows = F.ACC_ROW_TO_POSE; }
    }

    // sprite banks: fixed offset for plain items; program/definition packets
    // keep theirs at code-determined offsets, so fall back to a scan
    let banks = [];
    if (info.is_item) {
      const off = F.bankOffset(pkt);
      try { const { frames } = parseBank(pkt.raw, off); if (frames.length) banks.push({ offset: off, frames }); }
      catch (e) { /* not a bank at the usual place */ }
    }
    if (info.is_item && !banks.length) {
      for (const b of scanBanks(pkt.raw, 0x40)) banks.push({ offset: b.offset, frames: b.frames });
      if (!banks.length)
        for (const rec of scanLoose(pkt.raw))
          banks.push({ offset: rec[0], loose: rec, frames: readLoose(pkt.raw, rec) });
    }
    if (!info.is_item) {
      const covered = pkt.children.map(c => [c.offset, c.offset + c.size]);
      const spans = covered.map(x => [...x]);
      const own = (a, b) => !covered.some(([s, e]) => (s <= a && a < e) || (s < b && b <= e));
      // collect count-banks *and* loose records: program packets often carry
      // both, and taking only the first kind hid up to 50 of a file's sprites
      for (const b of scanBanks(pkt.raw, 0x60)) {
        if (own(b.offset, b.end)) {
          banks.push({ offset: b.offset, frames: b.frames });
          covered.push([b.offset, b.end]); spans.push([b.offset, b.end]);
        }
      }
      for (const rec of scanLoose(pkt.raw)) {
        const [start, , , ncol, , avail] = rec;
        const end = start + 6 + 2 * ncol + avail;
        if (own(start, end)) {
          banks.push({ offset: start, loose: rec, frames: readLoose(pkt.raw, rec) });
          covered.push([start, end]); spans.push([start, end]);
        }
      }
      if (isChar) {
        info.texts = F.DIALOGUE_LABELS.map((label, i) => {
          const off = F.CH.DIALOGUE + i * 150;
          const codes = [];
          for (let k = 0; k < 75; k++) codes.push(u16(pkt.raw, off + 2 * k));
          return { offset: off, chars: 75, label, width: 2,
                   text: F.decode(codes, table).replace(/^　+|　+$/g, '') };
        });
        info.body_type = pkt.raw[F.CH.BODY_TYPE];
        info.char_stats = F.getCharStats(pkt);
        const cs = info.char_stats;
        const accpos = F.getCharAccPositions(pkt);
        const nm = n => { const c = []; for (let i = 0; i < n[1]; i++) c.push(u16(pkt.raw, n[0] + 2 * i)); return c; };
        info.char_extra = {
          acc_pos: accpos,
          acc_rows: F.ACC_ROW_TO_FRAME,
          tama_roster: F.roster(cs.tama_id),
          revert_roster: F.roster(cs.revert_id),
          transform_name: F.decode(nm([F.CH.TRANSFORM_NAME, 10]), table).replace(/^[　\s]+|[　\s]+$/g, ''),
          name2: F.decode(nm([F.CH.NAME2, pkt.layout.slots]), table),
        };
        info.char_enums = { gender: F.GENDER, stage: F.STAGE, body_type: F.bodyTypes(model),
                            transform_type: F.TRANSFORM_TYPE, like_index: F.LIKE_INDEX };
      } else {
        // dialogue is 1 byte/char on iD/iD L/P's and 2 on 4U, and it only
        // lives in the gaps between sprite records
        const width = pkt.layout.width;
        const gaps = F.textGaps(spans, pkt.size);
        const ratio = gaps.reduce((a, [x, y]) => a + (y - x), 0) / Math.max(1, pkt.size);
        let texts = [];
        if (F.scansText(pkt) && ratio <= F.MAX_TEXT_GAP_RATIO) {
          for (const [lo, hi] of gaps) {
            if (hi - lo < 8) continue;
            texts = texts.concat(
              F.scanTexts(pkt.raw, model, lo, hi, width === 2 ? 4 : 6, width)
                .filter(r => F.plausibleRun(r[2], width)));
          }
        }
        if (texts.length) {
          const groups = F.groupRuns(texts, width, F.DIALOGUE_MAX_GAP);
          // Some files store a line twice (the P's travel packets keep a
          // second copy right after the first) or reuse one phrase in
          // several entries.  That is the file's own content, not a scan
          // artefact -- but editing one copy and not the others leaves stale
          // text on the device, so each block says how many copies it has.
          const seen = {}, nth = {};
          for (const g of groups) seen[g.text] = (seen[g.text] || 0) + 1;
          info.texts = groups.map((g, i) => {
            const n = seen[g.text];
            nth[g.text] = (nth[g.text] || 0) + 1;
            const label = `대사 ${i + 1}` + (n > 1 ? ` · 중복 ${nth[g.text]}/${n}` : '');
            return { parts: g.parts, chars: g.chars, text: g.text, width, dup_count: n, label };
          });
        }
      }
    }
    if (banks.length)
      info.banks = banks.map(b => ({ offset: b.offset, loose: b.loose ?? null,
                                     frames: b.frames.map(frameOut) }));
    out.packets.push(info);
  }
  return out;
}

// A nested packet lives inside its parent's bytes, so the parent has to be
// spliced and its u16 size field rewritten before it is re-parsed.
function replacePacket(packets, path, newRaw) {
  if (path.length === 1) { packets[path[0]] = new Packet(newRaw, 0); return; }
  const parent = findPacket(packets, path.slice(0, -1));
  const child = parent.children[path[path.length - 1]];
  const raw = new Uint8Array(parent.size - child.size + newRaw.length);
  raw.set(parent.raw.subarray(0, child.offset), 0);
  raw.set(newRaw, child.offset);
  raw.set(parent.raw.subarray(child.offset + child.size), child.offset + newRaw.length);
  putU16(raw, OFF_PACKET_SIZE, raw.length);
  replacePacket(packets, path.slice(0, -1), raw);
}

export function applyEdits(data, edits, newJpeg = null) {
  let { jpeg, packets, trailing } = parseFile(data);
  const swaps = edits.filter(e => e.replace_bytes || e.convert);
  if (swaps.length) {
    const before = packets.reduce((a, p) => a + p.size, 0);
    for (const e of swaps) {
      if (e.convert) {
        const pkt = findPacket(packets, e.path);
        replacePacket(packets, e.path, F.convert(pkt, e.convert, e.serial ?? null).raw);
        continue;
      }
      const { packets: srcpkts } = parseFile(e.replace_bytes);
      replacePacket(packets, e.path, srcpkts[0].raw);
    }
    const delta = packets.reduce((a, p) => a + p.size, 0) - before;
    for (const p of packets) p.shiftDeclaredSize(delta);
    edits = edits.filter(e => !(e.replace_bytes || e.convert));
  }
  if (newJpeg) {
    const delta = newJpeg.length - jpeg.length;
    for (const p of packets) p.shiftDeclaredSize(delta);
    jpeg = newJpeg;
  }
  for (const edit of edits) {
    const pkt = findPacket(packets, edit.path);
    const model = pkt.model;
    if ('serial' in edit) pkt.setSerial(+edit.serial);
    if ('name' in edit) pkt.setItemNameCodes(F.encode(edit.name, model));
    if ('unicode_name' in edit) pkt.setUnicodeName(edit.unicode_name);
    if ('price' in edit) F.setPrice(pkt, +edit.price);
    if ('hunger' in edit) F.setHunger(pkt, edit.hunger);
    if ('friendship' in edit) F.setFriendship(pkt, edit.friendship);
    if ('dest' in edit) F.setDestination(pkt, edit.dest);
    if ('likes' in edit) F.setLikesRaw(pkt, edit.likes);
    if ('stats' in edit) F.setStats(pkt, edit.stats);
    if ('acc_pos' in edit) F.setAccPositions(pkt, edit.acc_pos);
    if ('char_stats' in edit) F.setCharStats(pkt, edit.char_stats);
    if ('transform_name' in edit) F.writeText(pkt.raw, F.CH.TRANSFORM_NAME, 10, edit.transform_name, model, 2);
    if ('char_acc_pos' in edit) F.setCharAccPositions(pkt, edit.char_acc_pos);
    if ('name2' in edit) F.writeText(pkt.raw, F.CH.NAME2, pkt.layout.slots, edit.name2, model, 2);
    if ('version' in edit) F.setVersion(pkt, edit.version.version, edit.version.compat, edit.version.index);
    if ('compat' in edit) F.setCompat(pkt, edit.compat);
    if ('anim_a' in edit) F.setAnim(pkt, edit.anim_a, edit.anim_b ?? edit.anim_a);
    for (const t of edit.texts || []) {
      if (t.parts) F.writeGrouped(pkt.raw, t.parts, t.text, model, t.width ?? 2);
      else F.writeText(pkt.raw, t.offset, t.chars, t.text, model, t.width ?? 2);
    }
    for (const bank of edit.banks || []) {
      const off = bank.offset;
      if (bank.loose) {
        writeLoose(pkt.raw, bank.loose, bank.frames[0].palette, bank.frames.map(f => f.pixels));
        continue;
      }
      const frames = bank.frames.map(f => ({ slot_size: f.slot, w: f.w, h: f.h,
                                             palette: f.palette, pixels: f.pixels }));
      const oldEnd = parseBank(pkt.raw, off).end;      // must not change length
      const blobLen = 2 + frames.reduce((a, f) => a + 2 + f.slot_size, 0);
      if (off + blobLen !== oldEnd) throw new Error('bank size mismatch — frame slots must be kept');
      writeBank(pkt.raw, frames, off);
    }
  }
  return buildFile(jpeg, packets, trailing);
}
