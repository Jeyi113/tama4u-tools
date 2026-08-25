"""Bundle the editor into one self-contained docs/index.html.

    python3 web/build.py

The browser UI is unchanged; only the three calls that used to hit the local
Python server are rewired to the JS port, which runs in the page.  ES module
syntax is stripped because `file://` refuses `<script type=module>`, so the
result opens by double-click as well as over http.
"""
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, 'web')
OUT = os.path.join(ROOT, 'docs', 'index.html')
MODULES = ['charset-data.js', 'core.js', 'format.js', 'api.js']

# The UI talks to the port through these; same shapes the server returned.
SHIM = r"""
// ---- local backend -------------------------------------------------
// describe()/applyEdits() run in this page, so the editor works from a
// plain file:// open with no server and nothing leaving the browser.
const b64ToArray = s => { const b = atob(s); const u = new Uint8Array(b.length);
  for (let i = 0; i < b.length; i++) u[i] = b.charCodeAt(i); return u; };
const arrToB64 = u8 => { let s = ''; const C = 0x8000;
  for (let i = 0; i < u8.length; i += C) s += String.fromCharCode.apply(null, u8.subarray(i, i + C));
  return btoa(s); };
async function apiParse(buf) {
  try { return TAMA.describe(new Uint8Array(buf)); }
  catch (e) { return { error: String(e.message || e) }; }
}
async function apiBuild(payload) {
  const data = b64ToArray(payload.file_b64);
  const edits = (payload.edits || []).map(e =>
    e.replace_b64 ? { ...e, replace_bytes: b64ToArray(e.replace_b64) } : e);
  const jpeg = payload.jpeg_b64 ? b64ToArray(payload.jpeg_b64) : null;
  return TAMA.applyEdits(data, edits, jpeg);   // throws on bad input
}
"""


def strip_module(src):
    src = re.sub(r'^\s*import\s[^;]*;\s*$', '', src, flags=re.M)
    src = re.sub(r'^export\s+', '', src, flags=re.M)
    # `import * as F from './format.js'` -> everything shares one scope now
    src = re.sub(r'\bF\.(?=[A-Za-z_])', '', src)
    return src


def main():
    parts = [strip_module(open(os.path.join(WEB, m), encoding='utf-8').read())
             for m in MODULES]
    bundle = ('(function(){\n' + '\n'.join(parts)
              + '\nwindow.TAMA = { describe, applyEdits, parseFile, buildFile };\n})();\n')

    html = open(os.path.join(ROOT, 'tama4u', 'editor.html'), encoding='utf-8').read()

    # 1. parse: server returned JSON
    html = html.replace(
        "  const r=await fetch('/api/parse',{method:'POST',body:buf});\n  const j=await r.json();",
        "  const j=await apiParse(buf);")
    html = html.replace(
        "  const info=await (await fetch('/api/parse',{method:'POST',body:buf})).json();",
        "  const info=await apiParse(buf);")

    # 2. build: server returned the rebuilt file as a blob
    html = html.replace(
        """      const r=await fetch('/api/build',{method:'POST',body:JSON.stringify(
        {file_b64:fileB64,edits:[{path:pk.path,convert:m}]})});
      if(!r.ok){toast('변환 실패: '+await r.text());return}
      const blob=await r.blob();""",
        """      let blob;
      try { blob=new Blob([await apiBuild({file_b64:fileB64,edits:[{path:pk.path,convert:m}]})]); }
      catch(err){ toast('변환 실패: '+err.message); return }""")
    html = html.replace(
        """  const r=await fetch('/api/build',{method:'POST',body:JSON.stringify({
    file_b64:fileB64, edits:[{path:pk.path, replace_b64:arrayToB64(buf)}]})});
  if(!r.ok){toast('교체 실패: '+(await r.json()).error);return}
  const blob=await r.blob();""",
        """  let blob;
  try { blob=new Blob([await apiBuild({file_b64:fileB64,
    edits:[{path:pk.path, replace_b64:arrayToB64(buf)}]})]); }
  catch(err){ toast('교체 실패: '+err.message); return }""")
    html = html.replace(
        """  const r=await fetch('/api/build',{method:'POST',body:JSON.stringify(payload)});
  if(!r.ok){const j=await r.json();toast('저장 실패: '+j.error);return}
  const blob=await r.blob();""",
        """  let blob;
  try { blob=new Blob([await apiBuild(payload)]); }
  catch(err){ toast('저장 실패: '+err.message); return }""")

    # 3. reference body-type sprites are Bandai artwork and are not shipped,
    #    so the device simulation stays off in the web build
    html = html.replace(
        "fetch('/api/charasprites').then(r=>r.ok?r.json():null).then(j=>{chara=j;drawSim()}).catch(()=>{});",
        "chara=null;   // no reference sprites in the web build (see README)")

    for marker in ["const j=await apiParse(buf);", "window.TAMA"]:
        pass
    if 'apiParse' not in html:
        raise SystemExit('rewire failed: /api/parse call site not found')
    if "fetch('/api/build'" in html:
        raise SystemExit('rewire failed: an /api/build call site remains')

    tag = f'<script>\n{bundle}{SHIM}</script>\n'
    html = html.replace('<script>', tag + '<script>', 1)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, 'w', encoding='utf-8').write(html)
    print(f'{OUT}  {len(html) / 1024:.0f} KB')


if __name__ == '__main__':
    main()
