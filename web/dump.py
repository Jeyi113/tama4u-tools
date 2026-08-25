"""Reference dump for web/verify-bundle.mjs.

    python3 web/dump.py <pack-dir>... > /tmp/py.json

Emits {path: describe(file)} with the JPEG preview blanked, so the JS
bundle can be diffed against the Python implementation file by file.
"""
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tama4u import editor           # noqa: E402


def main(dirs):
    files = []
    for d in dirs:
        files += [f for f in glob.glob(os.path.join(d, '**', '*.*'), recursive=True)
                  if f.lower().endswith(('.jpg', '.jpeg'))]
    rows = {}
    for f in sorted(files):
        try:
            info = editor.describe(open(f, 'rb').read())
            info['jpeg_b64'] = None
            rows[f] = info
        except Exception as e:                       # noqa: BLE001
            rows[f] = {'error': str(e)}
    # ensure_ascii escapes the lone surrogates the VDP's false nested
    # packet names contain, which stdout cannot encode otherwise
    json.dump(rows, sys.stdout)


if __name__ == '__main__':
    main(sys.argv[1:])
