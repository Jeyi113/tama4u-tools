// describe() / applyEdits() -- the two calls the UI makes.  Same shapes as
// the Python editor's /api/parse and /api/build so the view layer is
// unchanged; web/selftest.js diffs the two implementations file by file.
import {
  parseFile, buildFile, Packet, u16, putU16, OFF_PACKET_SIZE,
  parseBank, writeBank, encodeBank, encodeLoose, sum16, scanBanks, scanLoose, readLoose, writeLoose,
  destOptions,
  OFF_TYPE_SIG,
} from './core.js';
import * as F from './format.js';

const hexDest = p => Array.from(p.raw.slice(78, 82))
  .map(x => x.toString(16).padStart(2, '0')).join('');
const findPacket = (packets, path) => path.slice(1).reduce((p, i) => p.children[i], packets[path[0]]);

// A VDP's contents are whole packets inside its packed stream, so they are
// walked too, under a 'vdp' step -- [0, 'vdp', 2].  Each then gets the
// ordinary item treatment: price, stats, likes, all of it.
let extraStream = null;
function* iterPackets(packets) {
  function* walk(pkt, path) {
    yield [path, pkt];
    for (let i = 0; i < pkt.children.length; i++) yield* walk(pkt.children[i], [...path, i]);
    const subs = F.vdpSubPackets(pkt, extraStream);
    if (subs) {
      for (let i = 0; i < subs[2].length; i++)
        yield* walk(subs[2][i], [...path, 'vdp', i]);
      // older change pierces keep their bodies as bare banks with no header
      if (!subs[2].some(s => F.vdpIsCharContent(s))) {
        const bodies = F.vdpBareBodies(subs[0], subs[1], pkt.model);
        for (let i = 0; i < bodies.length; i++)
          yield* walk(bodies[i].packet, [...path, 'vdpbody', i]);
      }
    }
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
  // opts.partner is the rest of a VDP+ -- one continuation or a list; their
  // streams are appended so the bundle unpacks whole
  let extra = null;
  const others = partnerPackets(opts.partner);
  if (others.length) {
    const chunks = others.map(o => F.vdpPartStream(o.packets[0]));
    const n = chunks.reduce((a, c) => a + c.length, 0);
    extra = new Uint8Array(n);
    let at = 0;
    for (const c of chunks) { extra.set(c, at); at += c.length; }
  }
  const { jpeg, packets } = parseFile(data);
  const out = { jpeg_b64: opts.jpeg === false ? null : b64(jpeg), packets: [] };
  extraStream = extra;
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
      ansi_num: pkt.ansiNum,
      kind: F.effectiveKind(pkt),
      section: pkt.section,
      serial: pkt.serial,
      unicode_name: pkt.unicodeName,
      name: F.decode(pkt.itemNameCodes, table),
      size: pkt.size,
      dest: Array.from(pkt.raw.slice(F.OFF_DEST, F.OFF_DEST + 4))
        .map(x => x.toString(16).padStart(2, '0')).join(''),
      // the model/firmware signature sits right in front of the
      // destination and is what makes the field differ between models that
      // share a category code -- see tama4u/editor.py
      dest_sig: Array.from(pkt.raw.slice(OFF_TYPE_SIG, OFF_TYPE_SIG + 2))
        .map(x => x.toString(16).padStart(2, '0')).join(''),
      dest_label: path.includes('vdp')
        ? F.vdpContentLabel(pkt, F.getDestination(pkt))
        : (F.isVdpPart(pkt) ? 'VDP+ 뒷부분 (압축 스트림)' : F.getDestination(pkt)),
      // the mask travels with the code so the UI can show iD's free
      // per-item index byte as ** instead of a misleading 00
      dest_options: destOptions(model).map(e => ({ label: e[0], code: e[1], mask: e[2] })),
      is_item: !isChar && !F.isProgram(pkt)
        && (F.BANK_OFFSETS[F.effectiveKind(pkt)] !== undefined || model !== '4U'),
    };
    // a VDP character body reads as kind 'fk' but its 28 frames are poses,
    // not wearable pieces -- the body-type composite must not slice them
    const inVdp = path.includes('vdp') || path.includes('vdpbody');
    info.pose_bank = inVdp ? F.vdpIsCharContent(pkt) : false;
    // everything on that shelf inside a bundle belongs to one specific
    // character, body or change dress alike, so composing it onto the
    // generic reference tamagotchi says nothing
    info.char_shelf = inVdp
      && Array.from(pkt.raw.slice(F.OFF_DEST, F.OFF_DEST + 4))
           .map(x => x.toString(16).padStart(2, '0')).join('') === F.VDP_CHAR_DEST;
    if (model === 'iD') { info.version = F.getVersion(pkt); info.version_presets = F.VERSION_PRESETS; }
    info.compat = F.getCompat(pkt);
    const period = F.getPeriod(pkt);
    if (period !== null) info.period = period;
    if (model === 'iD') {
      const label = F.getDestination(pkt);
      if (label === '사진관 · 의상' || label === '타마모리 · 액세서리') {
        info.id_line = { label,
          firmware: F.VERSION_NAMES[F.getVersion(pkt).version] ?? '?' };
        if (label === '사진관 · 의상') {
          try {
            const { frames } = parseBank(pkt.raw, F.bankOffset(pkt));
            const g = F.studioGender(frames.length);
            if (g !== null) info.id_line.gender = g;
          } catch (e) { /* not a bank we can read */ }
        }
      }
    }
    info.convert = {};
    for (const m of ['iD', 'iDL', "P's", '4U']) if (m !== model) info.convert[m] = F.convertPlan(pkt, m);
    if (info.is_item && !info.is_wardrobe) info.price = F.getPrice(pkt);
    // programs have no shop fields, but their destination is what files a
    // game under the Game Center
    if (!info.is_item) {
      info.fields = F.editableFields(pkt);
      if (F.isProgram(pkt)) {
        const shape = F.gameShape(pkt);
        if (shape.length) info.game_shape = shape;
        if (F.getDestination(pkt) === '외출지') {
          const cast = F.outingCast(pkt);
          if (cast) { cast.gifts = pkt.children.length; info.outing = cast; }
        }
      }
    }
    if (info.is_item && info.stats_verified) {
      const anim = F.getAnim(pkt);
      info.fields = F.editableFields(pkt);
      info.likes_slots = F.likesSlots(pkt);
      info.likes_offset = pkt.layout.likes;
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
        // A character is two packets: this card, and the body nested at
        // 0xB00.  Their ASCII ids share one number and the body repeats it
        // as *its* serial (68/68 in the 4U pack), so the screen edits the
        // number once and writes both.
        if (pkt.children.length) {
          const body = pkt.children[0];
          info.char_body = {
            path: [...path, 0], ansi_id: body.ansiId, ansi_num: body.ansiNum,
            serial: body.serial, name: F.decode(body.itemNameCodes, table),
          };
        }
        info.char_enums = { stage: F.STAGE, personality: F.PERSONALITY, body_type: F.bodyTypes(model),
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
    if (F.isVdpPart(pkt)) info.vdp_part = { stream: F.vdpPartStream(pkt).length };
    if (F.isVdp(pkt) && path.length === 1) {
      const got = F.vdpSubPackets(pkt, extra);
      info.vdp_truncated = !!(got && got[2].length && !got[2][got[2].length - 1].checksumOk());
      info.vdp_merged = !!(extra && extra.length);
      info.vdp_part_gap = partGap(others);
      // a VDP+ part 1 is a bundle whose item name ends in a digit -- true
      // of all 20 VDP+ releases and none of the 50 plain pierces
      info.vdp_multipart = F.vdpPartIndex(pkt) !== null;
      info.vdp = !got ? [] : got[2].map((sub, k) => ({
        index: k,
        name: F.decode(Array.from(sub.itemNameCodes), F.tableFor(sub.model))
               .replace(/[　 ]+$/, ''),
        label: F.vdpContentLabel(sub, F.getDestination(sub)),
        model: sub.model, size: sub.size, serial: sub.serial,
        dest: hexDest(sub),
        dest_sig: Array.from(sub.raw.slice(76, 78)).map(x => x.toString(16).padStart(2, '0')).join(''),
        price: F.getPrice(sub),
        sprites: scanLoose(sub.raw, 0x40).length,
      }));
      if (got) {
        // the raising conditions, from the payload's 4 KB prefix
        const where = new Map(got[2].map((sub, k) => [sub.serial, k]));
        info.vdp_dest_name = F.vdpDestName(got[0], pkt.model);
        info.vdp_chars = F.vdpCharBlocks(got[0], pkt.model).map(c => ({
          ...c, item_index: where.has(c.item_serial) ? where.get(c.item_serial) : null,
        }));
        // tie each raisable character to its block so that selecting the
        // character itself shows its conditions, not only the bundle
        let n = 0;
        got[2].forEach((sub, k) => {
          const isChar = F.vdpIsCharContent(sub);
          info.vdp[k].char_index = isChar ? n : null;
          if (isChar) n++;
        });
        // bare change bodies (anniversary) join the list on their own
        // 'vdpbody' path
        if (!got[2].some(s => F.vdpIsCharContent(s)))
          F.vdpBareBodies(got[0], got[1], pkt.model).forEach((body, k) =>
            info.vdp.push({
              bare: true, bindex: k, char_index: k, name: body.name,
              label: '캐릭터 (육성)', model: pkt.model, size: F.VDP_BODY_STRIDE,
              serial: 0, dest: F.VDP_CHAR_DEST, dest_sig: '', price: 0, sprites: 0,
            }));
      }
    }
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

// Rewrite banks whose frames no longer fit their slots.  A bigger frame
// makes the packet longer, invalidating its 0x4A, every enclosing 0x4A and
// every top-level 0x32; splicing through replacePacket fixes the first two
// and the returned delta is what the caller shifts the 0x32s by.  Only
// banks marked `grow` are considered, so an ordinary edit still fails
// loudly rather than quietly moving everything after the bank.
function resizeBanks(packets, edits) {
  let delta = 0;
  for (const edit of edits) {
    if (edit.path.includes('vdp') || edit.path.includes('vdpchar')) continue;
    for (const bank of edit.banks || []) {
      if (!bank.grow) continue;
      const pkt = findPacket(packets, edit.path);
      const off = bank.offset;
      let raw, oldSpan;
      if (bank.loose) {
        // a loose record sits in a program's sprite tail; rebuild at any
        // size and splice, moving every record after it (see api warning)
        const rec = bank.loose;
        oldSpan = 6 + 2 * rec[3] + rec[5];
        const fr = bank.frames;
        const blob = encodeLoose(fr[0].w, fr[0].h, fr[0].palette, fr.map(f => f.pixels));
        if (blob.length === oldSpan) continue;        // same size; in-place has it
        raw = new Uint8Array(pkt.size - oldSpan + blob.length);
        raw.set(pkt.raw.subarray(0, off), 0);
        raw.set(blob, off);
        raw.set(pkt.raw.subarray(off + oldSpan), off + blob.length);
      } else {
        const oldEnd = parseBank(pkt.raw, off).end;
        const frames = bank.frames.map(f => ({ slot_size: f.slot, w: f.w, h: f.h,
                                               palette: f.palette, pixels: f.pixels }));
        const blob = encodeBank(frames, true);
        bank.frames.forEach((f, i) => { f.slot = frames[i].slot_size; });
        if (off + blob.length === parseBank(pkt.raw, off).end) continue; // fits
        raw = new Uint8Array(pkt.size - (oldEnd - off) + blob.length);
        raw.set(pkt.raw.subarray(0, off), 0);
        raw.set(blob, off);
        raw.set(pkt.raw.subarray(oldEnd), off + blob.length);
      }
      putU16(raw, OFF_PACKET_SIZE, raw.length);
      // replacePacket re-parses from these bytes, so the new Packet would
      // consider itself untouched and keep the checksum that belonged to
      // the shorter body.  Seal it here; parents then reseal themselves.
      putU16(raw, raw.length - 2, sum16(raw.subarray(0, raw.length - 2)));
      const grew = raw.length - pkt.size;
      delta += grew;
      replacePacket(packets, edit.path, raw);
      bank.done = true;
      // shift the offsets of later banks (the outing's other loose records,
      // still sent for their unchanged in-place rewrite) by the same amount
      for (const other of edit.banks || []) {
        if (other === bank || (other.offset ?? 0) <= off) continue;
        other.offset += grew;
        if (other.loose) other.loose = [other.loose[0] + grew, ...other.loose.slice(1)];
      }
    }
  }
  for (const edit of edits)
    if (edit.banks) edit.banks = edit.banks.filter(b => !b.done);
  return delta;
}

// A VDP+ ships in two or three files and the stream is one run split across
// them, so it only unpacks when they are concatenated in part order.  Files
// handed over in any order are sorted here.
// True when the continuations skip a number.  Part 1 is the file being
// edited, so the rest should be 2, 3, ...  A hole is worth naming because
// the truncation check can miss it: Ciao read as 1+3 stops at 12 contents
// but the last one's checksum happens to be good.
function partGap(others) {
  const idx = others.map(o => o.idx).sort((a, b) => a - b);
  return idx.some((v, i) => v !== i + 2);
}

function partnerPackets(partner) {
  if (!partner) return [];
  const list = Array.isArray(partner) ? partner : [partner];
  const out = [];
  for (const raw of list) {
    const parsed = parseFile(raw);
    if (F.isVdpPart(parsed.packets[0]))
      out.push({ ...parsed, idx: F.vdpPartIndex(parsed.packets[0]) ?? 99 });
  }
  out.sort((a, b) => a.idx - b.idx);
  return out;
}

// `partner` is a VDP+'s continuations -- one file or a list; with them,
// edits reach the whole bundle
// and the result comes back as [part 1, part 2].
export function applyEdits(data, edits, newJpeg = null, partner = null) {
  const others = partnerPackets(partner);
  let { jpeg, packets, trailing } = parseFile(data);
  let extra = null;
  if (others.length) {
    const chunks = others.map(o => F.vdpPartStream(o.packets[0]));
    const n = chunks.reduce((a, c) => a + c.length, 0);
    extra = new Uint8Array(n);
    let at = 0;
    for (const c of chunks) { extra.set(c, at); at += c.length; }
  }
  const swaps = edits.filter(e => (e.replace_bytes || e.convert)
                                 && !e.path.includes('vdp'));
  if (swaps.length) {
    const before = packets.reduce((a, p) => a + p.size, 0);
    for (const e of swaps) {
      if (e.convert) {
        const pkt = findPacket(packets, e.path);
        replacePacket(packets, e.path, F.convert(pkt, e.convert, e.serial ?? null).raw);
        continue;
      }
      const { packets: srcpkts } = parseFile(e.replace_bytes);
      let donor = srcpkts[0];
      // a donor from another model keeps its bank, name encoding and
      // destination elsewhere, so convert it rather than splice raw bytes
      if (e.convert_to && donor.model !== e.convert_to)
        donor = F.convert(donor, e.convert_to);
      replacePacket(packets, e.path, donor.raw);
    }
    const delta = packets.reduce((a, p) => a + p.size, 0) - before;
    for (const p of packets) p.shiftDeclaredSize(delta);
    edits = edits.filter(e => !swaps.includes(e));
  }
  if (newJpeg) {
    const delta = newJpeg.length - jpeg.length;
    for (const p of packets) p.shiftDeclaredSize(delta);
    jpeg = newJpeg;
  }
  const applyOne = (pkt, edit) => {
    const model = pkt.model;
    if ('serial' in edit) pkt.setSerial(+edit.serial);
    if (edit.ansi_num != null) pkt.setAnsiNum(+edit.ansi_num);
    if ('name' in edit) pkt.setItemNameCodes(F.encode(edit.name, model));
    if ('unicode_name' in edit) pkt.setUnicodeName(edit.unicode_name);
    if ('price' in edit) F.setPrice(pkt, +edit.price);
    if ('hunger' in edit) F.setHunger(pkt, edit.hunger);
    if ('friendship' in edit) F.setFriendship(pkt, edit.friendship);
    if ('dest' in edit) F.setDestination(pkt, edit.dest, edit.dest_label);
    if ('likes' in edit) F.setLikesRaw(pkt, edit.likes);
    if (edit.period) F.setPeriod(pkt, edit.period);
    if ('stats' in edit) F.setStats(pkt, edit.stats);
    if ('acc_pos' in edit) F.setAccPositions(pkt, edit.acc_pos);
    if ('char_stats' in edit) F.setCharStats(pkt, edit.char_stats);
    if ('transform_name' in edit) F.writeText(pkt.raw, F.CH.TRANSFORM_NAME, 10, edit.transform_name, model, 2, 0);
    if ('char_acc_pos' in edit) F.setCharAccPositions(pkt, edit.char_acc_pos);
    if ('name2' in edit) F.writeText(pkt.raw, F.CH.NAME2, pkt.layout.slots, edit.name2, model, 2, 0);
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
  };
  // a frame that outgrew its slot lengthens the packet, so this runs before
  // the field edits (which need the re-parsed Packet objects)
  const grew = resizeBanks(packets, edits);
  if (grew) for (const p of packets) p.shiftDeclaredSize(grew);
  for (const edit of edits) {
    if (!edit.path.includes('vdp') && !edit.path.includes('vdpchar')
        && !edit.path.includes('vdpbody'))
      applyOne(findPacket(packets, edit.path), edit);
  }
  // VDP contents live inside the packed stream: unpack once per bundle,
  // apply everything, then rebuild the stream once.  The raising conditions
  // sit in the same payload, so they ride along rather than costing a
  // second unpack-repack.
  const groups = new Map();
  const bucketOf = { vdp: 0, vdpchar: 1, vdpbody: 3 };
  for (const edit of edits) {
    let placed = false;
    for (const step of ['vdp', 'vdpchar', 'vdpbody']) {
      const k = edit.path.indexOf(step);
      if (k < 0) continue;
      const key = edit.path.slice(0, k).join(',');
      if (!groups.has(key)) groups.set(key, [[], [], [], []]);
      groups.get(key)[bucketOf[step]].push([edit.path[k + 1], edit]);
      placed = true;
      break;
    }
    // the destination name lives in the payload, not in the packet, so it
    // has to ride the same unpack even when nothing else changed
    if (!placed && edit.vdp_dest_name != null) {
      const key = edit.path.join(',');
      if (!groups.has(key)) groups.set(key, [[], [], [], []]);
      groups.get(key)[2].push(edit);
    }
  }
  for (const [key, [jobs, charjobs, namejobs, bodyjobs]] of groups) {
    let pkt = findPacket(packets, key.split(',').map(Number));
    const got = F.vdpSubPackets(pkt, extra);
    if (!got) throw new Error('이 VDP는 아직 압축을 풀 수 없습니다');
    // repacking a truncated bundle would drop everything in the other part
    if (got[2].length && !got[2][got[2].length - 1].checksumOk())
      throw new Error('VDP+의 뒷부분이 없습니다 — 짝 파일을 함께 불러오지 '
                      + '않으면 나머지 내용물이 사라집니다');
    const [data, base, subs] = got;
    for (const [idx, edit] of jobs) {
      if (edit.replace_bytes) {
        // swap one content for a whole downloaded item; the payload is
        // reassembled around it, so the sizes need not match
        const { packets: srcpkts } = parseFile(edit.replace_bytes);
        let donor = srcpkts[0];
        if (edit.convert_to && donor.model !== edit.convert_to)
          donor = F.convert(donor, edit.convert_to);
        subs[idx] = F.vdpFitContent(subs[idx], donor);
        continue;
      }
      applyOne(subs[idx], edit);
    }
    for (const [idx, edit] of charjobs)
      F.vdpWriteCharBlock(data, idx, edit, pkt.model);
    for (const edit of namejobs)
      F.vdpWriteDestName(data, edit.vdp_dest_name, pkt.model);
    // bare change bodies live in the payload prefix; patch the bank in place
    // and the assemble below carries it across, leaving the blank header
    if (bodyjobs.length) {
      const bodies = F.vdpBareBodies(data, base, pkt.model);
      for (const [bidx, edit] of bodyjobs) {
        if (bidx >= bodies.length) continue;
        const body = bodies[bidx];
        applyOne(body.packet, edit);
        const bank = body.packet.raw.subarray(F.VDP_BODY_HEADER);
        data.set(bank, body.off + F.VDP_BODY_HEADER);
      }
    }
    const before = pkt.size;
    const path = key.split(',').map(Number);
    // Rebuild the Packet objects from the new bytes rather than swapping
    // pkt.raw in place: a compressed stream can spell TAMAGO by accident,
    // so pkt may carry a spurious nested child parsed from the old layout,
    // and buildFile's checksum pass would splice that stale child back at
    // its old offset -- what broke a two-part edit (easter).
    if (extra) {
      // split back across the parts: each fills to 32,768 bytes
      const blob = F.vdpAssemble(data, base, subs);
      const cuts = F.vdpRepackSplit(pkt, others.map(o => o.packets[0]), blob);
      replacePacket(packets, path, cuts[0]);
      others.forEach((o, i) => {
        o.packets[0] = new Packet(cuts[i + 1], 0);
        o.packets[0].children = [];
      });
    } else {
      replacePacket(packets, path, F.vdpWriteSubs(pkt, data, base, subs));
    }
    pkt = findPacket(packets, path);
    // the compressed stream can spell TAMAGO by chance, so the re-parsed
    // part may carry a spurious child; drop it so the checksum pass does
    // not splice stale bytes over the new stream (easter's part 1)
    pkt.children = [];
    for (const q of packets) q.shiftDeclaredSize(pkt.size - before);
  }
  const out = buildFile(jpeg, packets, trailing);
  return others.length
    ? [out, ...others.map(o => buildFile(o.jpeg, o.packets, o.trailing))]
    : out;
}
