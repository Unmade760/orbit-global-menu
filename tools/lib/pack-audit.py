#!/usr/bin/env python3
"""Compare an extension zip with the files the extension loads.

Usage: pack-audit.py <zip>

"Loaded" means one of:
  - metadata.json, and stylesheet.css (plus stylesheet-dark.css and
    stylesheet-light.css when present), which gnome-shell reads itself
  - extension.js, prefs.js and every module they reach through a relative
    static import or a relative dynamic import('...') with a literal string
  - schemas/<settings-schema>.gschema.xml named in metadata.json
  - shortcuts/index.json and every shortcuts/apps/<name> it lists, which
    shortcutStore.js reads at run time

Prints one line per problem and a "summary: " line. Exit 0 when the zip
holds exactly the loaded set, 1 otherwise.
"""

import json
import posixpath
import re
import sys
import zipfile

IMPORT_RE = re.compile(
    r"""(?:\bfrom\s*|\bimport\s*\(\s*|^\s*import\s+)(['"])(\.{1,2}/[^'"]+)\1""",
    re.MULTILINE,
)


def js_graph(names, entries):
    seen = set()
    todo = [e for e in entries if e in names]
    while todo:
        path = todo.pop()
        if path in seen:
            continue
        seen.add(path)
        text = names[path].decode('utf-8', errors='replace')
        for _, spec in IMPORT_RE.findall(text):
            target = posixpath.normpath(posixpath.join(posixpath.dirname(path), spec))
            if target in names:
                todo.append(target)
            else:
                print(f'missing import: {path} imports {spec}, not in the zip')
                seen.add(f'!missing:{target}')
    return seen


def main():
    zip_path = sys.argv[1]
    with zipfile.ZipFile(zip_path) as z:
        names = {i.filename: z.read(i) for i in z.infolist() if not i.is_dir()}

    problems = 0
    loaded = {'metadata.json'}
    for css in ('stylesheet.css', 'stylesheet-dark.css', 'stylesheet-light.css'):
        if css in names:
            loaded.add(css)
    if 'metadata.json' not in names:
        print('missing: metadata.json')
        problems += 1
        meta = {}
    else:
        meta = json.loads(names['metadata.json'])

    graph = js_graph(names, ['extension.js', 'prefs.js'])
    for item in sorted(graph):
        if item.startswith('!missing:'):
            problems += 1
        else:
            loaded.add(item)
    if 'extension.js' not in names:
        print('missing: extension.js')
        problems += 1

    schema = meta.get('settings-schema')
    if schema:
        path = f'schemas/{schema}.gschema.xml'
        if path in names:
            loaded.add(path)
        else:
            print(f'missing: {path} (metadata.json settings-schema)')
            problems += 1

    if 'shortcuts/index.json' in names:
        loaded.add('shortcuts/index.json')
        index = json.loads(names['shortcuts/index.json'])
        for app in index.get('apps', []):
            path = f'shortcuts/apps/{app}'
            if path in names:
                loaded.add(path)
            else:
                print(f'missing: {path} (listed in shortcuts/index.json)')
                problems += 1

    extra = sorted(set(names) - loaded)
    for path in extra:
        print(f'not loaded: {path}')
    problems += len(extra)

    print(f'zip files: {len(names)}, loaded set: {len(loaded)}, '
          f'js modules: {sum(1 for p in loaded if p.endswith(".js"))}')
    if problems:
        first = extra[0] if extra else 'see log'
        print(f'summary: {problems} problem(s) in the zip, first: {first}')
        return 1
    print(f'summary: {len(names)} files, every one loaded by the extension')
    return 0


if __name__ == '__main__':
    sys.exit(main())
