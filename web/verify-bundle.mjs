// Verify the *shipped bundle*, not the source modules: pull the script out
// of docs/index.html, run it, and diff describe() against the Python
// reference dump over a whole download pack.
//
//   python3 web/dump.py <pack-dir> > /tmp/py.json
//   node web/verify-bundle.mjs /tmp/py.json <pack-dir>
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const here = dirname(fileURLToPath(import.meta.url));
const html = readFileSync(join(here, '..', 'docs', 'index.html'), 'utf8');
const start = html.indexOf('<script>');
const code = html.slice(start + 8, html.indexOf('</script>', start));

const sandbox = { window: {}, btoa: s => Buffer.from(s, 'binary').toString('base64'),
                  atob: s => Buffer.from(s, 'base64').toString('binary'), console };
vm.createContext(sandbox);
vm.runInContext(code, sandbox);
const TAMA = sandbox.window.TAMA;
if (!TAMA) { console.error('bundle did not expose window.TAMA'); process.exit(1); }

function walk(dir, out = []) {
  for (const e of readdirSync(dir)) {
    const p = join(dir, e), st = statSync(p);
    if (st.isDirectory()) walk(p, out);
    else if (/\.jpe?g$/i.test(e)) out.push(p);
  }
  return out;
}

const [refPath, ...dirs] = process.argv.slice(2);
const ref = JSON.parse(readFileSync(refPath, 'utf8'));
const files = dirs.flatMap(d => walk(d)).sort();

const canon = v => JSON.stringify(v, (k, x) =>
  (x && typeof x === 'object' && !Array.isArray(x))
    ? Object.fromEntries(Object.keys(x).sort().map(kk => [kk, x[kk]])) : x);

let same = 0; const diffs = [];
for (const f of files) {
  const data = new Uint8Array(readFileSync(f));
  let got;
  try { got = TAMA.describe(data, { jpeg: false }); }
  catch (e) { got = { error: String(e.message) }; }
  const want = ref[f];
  if (want === undefined) { diffs.push([f, 'python 쪽에 없음']); continue; }
  // key order can differ between the two dumps; compare canonically
  if (canon(want) === canon(got)) same++;
  else diffs.push([f, '내용 불일치']);
}
console.log(`번들 vs 파이썬: 일치 ${same}/${files.length} · 불일치 ${diffs.length}`);
diffs.slice(0, 5).forEach(([f, why]) => console.log('  ', why, f.split('/').pop()));
process.exit(diffs.length ? 1 : 0);
