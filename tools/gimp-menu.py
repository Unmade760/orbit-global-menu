#!/usr/bin/env python3
# builds the gimp mapping from a live menu tree and the source of the same release
# usage gimp-menu.py TREE_JSON GIMP_SOURCE PLUGINRC SCRIPTS_DIR LIVE_ACTIONS OUT_MAPPING OUT_SOURCES
# TREE_JSON comes from computer-use-linux state gimp
# SCRIPTS_DIR is share/gimp/3.0/scripts of the installed gimp
# LIVE_ACTIONS comes from gdbus call on org.gtk.Actions.DescribeAll

import json
import pathlib
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

ENTRY = re.compile(
    r'\{\s*"(?P<name>[a-z0-9-]+)",\s*[^,]*,\s*'
    r'(?:NC?_\((?:"[^"]*",\s*)?"(?P<label>(?:[^"\\]|\\.)*)"\)|(?P<nolabel>NULL)),\s*'
    r'(?:NC?_\((?:"[^"]*",\s*)?"(?P<short>[^"]*)"\)|NULL),\s*'
    r'\{\s*(?P<accel>"[^"]*"|NULL)')
TOOL = re.compile(
    r'"gimp-(?P<name>[a-z0-9-]+)-tool",\s*'
    r'(?:C?_\((?:"[^"]*",\s*)?"[^"]*"\)|NULL),\s*'
    r'(?:_\((?:"[^"]*"\s*)+\)|NULL),\s*'
    r'N_\("(?P<label>[^"]*)"\),\s*(?P<accel>"[^"]*"|NULL)')
PROC = re.compile(r'\(proc-def "([^"]+)" \d+\s+(?:"(?:[^"\\]|\\.)*"\s+){5}"((?:[^"\\]|\\.)*)"\s+\d+\s*'
                  r'((?:\(menu-path "[^"]*"\)\s*)*)')
KEYS = {'comma': ',', 'period': '.', 'semicolon': ';', 'minus': '-', 'plus': '+', 'slash': '/',
        'grave': '`', 'exclam': '!', 'Prior': 'Page_Up', 'Next': 'Page_Down'}
MODS = {'primary': 'Ctrl', 'control': 'Ctrl', 'shift': 'Shift', 'alt': 'Alt'}
# labels gimp changes at run time and help items its web-browser plug-in registers
ALIASES = {
    ('File', 'Save…'): 'file-save',
    ('Filters', 'Light and Shadow', 'Bevel…'): 'filters-gegl-bevel',
    ('Filters', 'Light and Shadow', 'Inner Glow…'): 'filters-gegl-inner-glow',
    ('Filters', 'Generic', 'Text Styling…'): 'filters-gegl-styles',
    ('Filters', 'Map', 'Paper Tile…'): 'filters-tile-paper',
    ('File', 'Send by Email…'): 'plug-in-mail-image',
    ('Colors', 'Local Threshold…'): 'filters-gegl-local-threshold',
    ('Tools', 'New Toolbox'): 'dialogs-toolbox',
    ('Windows', 'New Toolbox'): 'dialogs-toolbox',
    ('Help', 'About'): 'dialogs-about',
    ('Help', 'User Manual', 'Table of Contents'): 'gimp-help-main',
    ('Help', 'User Manual', 'Basic Concepts'): 'gimp-help-concepts-usage',
    ('Help', 'User Manual', 'Create and Use Selections'): 'gimp-help-using-selections',
    ('Help', 'User Manual', 'Create, Open and Save Files'): 'gimp-help-using-fileformats',
    ('Help', 'User Manual', 'Drawing Simple Objects'): 'gimp-help-using-simpleobjects',
    ('Help', 'User Manual', 'How to Use Dialogs'): 'gimp-help-using-docks',
    ('Help', 'User Manual', 'Preparing your Images for the Web'): 'gimp-help-using-web',
    ('Help', 'User Manual', 'Using Paths'): 'gimp-help-concepts-paths',
    ('Help', 'User Manual', 'Working with Digital Camera Photos'): 'gimp-help-using-photography',
    ('Help', 'GIMP Online', 'Bug Reports and Feature Requests'): 'gimp-online-bugs-features',
    ('Help', 'GIMP Online', 'Developer Web Site'): 'gimp-online-developer-web-site',
    ('Help', 'GIMP Online', 'Main Web Site'): 'gimp-online-main-web-site',
    ('Help', 'GIMP Online', 'Roadmaps'): 'gimp-online-roadmap',
    ('Help', 'GIMP Online', 'User Manual Web Site'): 'gimp-online-docs-web-site',
}


def clean(label):
    return ' '.join(re.sub(r'_(.)', r'\1', label).replace('...', '…').replace('\\"', '"').split())


def chord(raw):
    mods = {MODS[m.lower()] for m in re.findall(r'<(\w+)>', raw)}
    key = re.sub(r'<\w+>', '', raw)
    key = key.upper() if len(key) == 1 else KEYS.get(key, key)
    return ''.join(f'<{m}>' for m in ('Ctrl', 'Shift', 'Alt') if m in mods) + key


def source_text(path):
    # blank comments and preprocessor lines but keep line numbers
    text = re.sub(r'/\*.*?\*/', lambda m: '\n' * m[0].count('\n'), path.read_text(), flags=re.S)
    return re.sub(r'^#.*$', '', text, flags=re.M)


def action_table(src):
    table = {}
    files = sorted((src / 'app/actions').glob('*-actions.c'))
    for path in files:
        text = source_text(path)
        for m in ENTRY.finditer(text):
            if m['nolabel'] and m['name'] in table:
                continue
            accel = None if m['accel'] == 'NULL' else m['accel'].strip('"')
            line = text.count('\n', 0, m.start('accel')) + 1
            table.setdefault(m['name'], {
                'label': m['label'], 'short': m['short'], 'accel': accel,
                'file': str(path.relative_to(src)), 'line': line})
    for path in sorted((src / 'app/tools').glob('*.c')):
        text = source_text(path)
        for m in TOOL.finditer(text):
            accel = None if m['accel'] == 'NULL' else m['accel'].strip('"')
            line = text.count('\n', 0, m.start('accel')) + 1
            table[f'tools-{m["name"]}'] = {
                'label': m['label'], 'accel': accel, 'file': str(path.relative_to(src)), 'line': line}
    return table


def ui_paths(src):
    text = (src / 'menus/image-menu.ui.in.in').read_text()
    dialogs = (src / 'menus/dialogs-menuitems.ui.in').read_text().split('?>', 1)[1]
    text = re.sub(r'<xi:include href="@GROUP@-dialogs-menuitems.ui" />', dialogs, text)
    text = text.replace('@GROUP@', 'app')
    text = re.sub(r'@[A-Z_]+@', '', text)
    root = ET.fromstring(text)
    out = {}

    def attr(node, name):
        for a in node.findall('attribute'):
            if a.get('name') == name:
                return a.text
        return None

    def walk(node, path):
        for child in node:
            if child.tag == 'submenu':
                walk(child, path + (clean(attr(child, 'label') or ''),))
            elif child.tag == 'section':
                walk(child, path)
            elif child.tag == 'item':
                action = attr(child, 'action')
                if action and action.startswith('app.'):
                    out.setdefault(path, []).append(action[4:])

    walk(root.find('menu'), ())
    return out


def plugin_paths(pluginrc, scripts):
    out = {}
    for path in pathlib.Path(scripts).rglob('*.scm'):
        text = path.read_text(errors='replace')
        labels = dict(re.findall(r'\(script-fu-register(?:-\w+)?\s+"([^"]+)"\s+_?"([^"]*)"', text))
        for name, menu in re.findall(r'\(script-fu-menu-register\s+"([^"]+)"\s+"<Image>/([^"]*)"', text):
            if name in labels:
                where = tuple(clean(part) for part in menu.split('/') if part and not part.startswith('['))
                out.setdefault(where, []).append((name, labels[name]))
    for name, label, paths in PROC.findall(pathlib.Path(pluginrc).read_text(errors='replace')):
        action = name.replace('_', '-')
        for p in re.findall(r'"<Image>/([^"]*)"', paths):
            path = tuple(clean(part) for part in p.split('/') if part and not part.startswith('['))
            out.setdefault(path, []).append((action, label))
    return out


def parse_live(path):
    rows = re.findall(r"'([a-z0-9_.-]+)': \((?:true|false), (?:signature )?'([^']*)', ", pathlib.Path(path).read_text())
    return dict(rows)


def build(tree, table, ui, plugins, live):
    kids = {}
    for node in tree:
        kids.setdefault(node['parent_index'], []).append(node)
    bar = next(n for n in tree if n['role'] == 'menu bar')
    dropped, records = [], []

    def candidates(path):
        found = {}
        for action in ui.get(path, []):
            entry = table.get(action, {})
            for label in (entry.get('label'), entry.get('short')):
                if label:
                    found.setdefault(clean(label), action)
        for action, label in plugins.get(path, []):
            found.setdefault(clean(label), action)
        return found

    def leaf(label, action, path):
        item = {'label': label, 'action': action}
        if live[action]:
            item['target'] = 0
        entry = table.get(action)
        if entry and entry['accel']:
            item['shortcut'] = chord(entry['accel'])
            records.append({'path': list(path + (label,)), 'shortcut': item['shortcut'],
                            'file': entry['file'], 'line': entry['line']})
        return item

    def items(parent, path):
        found = candidates(path)
        out = []
        for node in kids.get(parent['index'], []):
            if 'visible' not in node['states']:
                continue
            if node['role'] == 'separator':
                if out and 'separator' not in out[-1]:
                    out.append({'separator': True})
                continue
            label = node['name'] or ''
            shown = ' '.join(label.split()).replace('...', '…')
            sub = kids.get(node['index'], [])
            if node['role'] == 'menu' and sub:
                inner = items(node, path + (shown,))
                if inner:
                    out.append({'label': shown, 'items': inner})
                continue
            alias = ALIASES.get(path + (shown,))
            action = alias or found.get(shown)
            if alias and alias in table:
                shown = clean(table[alias]['label'])
            if not action or action not in live:
                dropped.append(' » '.join(path + (shown,)))
                continue
            out.append(leaf(shown, action, path))
        # state hidden items are absent from the tree so restore them after their source neighbour
        order = ui.get(path, [])
        for pos, action in enumerate(order):
            if action in live and not any(i.get('action') == action for i in out):
                before = {i.get('action'): n for n, i in enumerate(out)}
                at = max((before[a] + 1 for a in order[:pos] if a in before), default=0)
                out.insert(at, leaf(clean(table[action]['label']), action, path))
        while out and 'separator' in out[-1]:
            out.pop()
        return out

    menus = [{'label': t['name'], 'items': items(t, (t['name'],))} for t in kids[bar['index']]]
    return menus, records, dropped


def render(items, depth):
    pad = ' ' * depth
    rows = []
    for item in items:
        if 'items' in item:
            rows.append(f'{pad}{{"label": {json.dumps(item["label"], ensure_ascii=False)}, "items": [\n'
                        f'{render(item["items"], depth + 2)}\n{pad}]}}')
        else:
            rows.append(pad + json.dumps(item, ensure_ascii=False))
    return ',\n'.join(rows)


def main():
    tree_file, src_dir, pluginrc, scripts, live_file, out_map, out_src = sys.argv[1:8]
    src = pathlib.Path(src_dir)
    table = action_table(src)
    plugins = plugin_paths(pluginrc, scripts)
    menus, records, dropped = build(json.load(open(tree_file)), table, ui_paths(src), plugins, parse_live(live_file))
    old = json.load(open(out_map))
    body = ',\n'.join(f'    {{\n      "label": {json.dumps(m["label"])},\n      "items": [\n'
                      f'{render(m["items"], 8)}\n      ]\n    }}' for m in menus)
    head = json.dumps({k: old[k] for k in ('format', 'app', 'name', 'identifiers')}, indent=2)[:-2]
    pathlib.Path(out_map).write_text(f'{head},\n  "menus": [\n{body}\n  ]\n}}\n')
    commit = subprocess.check_output(['git', '-C', src_dir, 'rev-parse', 'HEAD'], text=True).strip()
    sources = {'format': 1, 'app': old['app'],
               'repos': {'gimp': {'url': 'https://gitlab.gnome.org/GNOME/gimp.git', 'commit': commit}},
               'items': [{**r, 'repo': 'gimp', 'commit': commit} for r in records]}
    pathlib.Path(out_src).write_text(json.dumps(sources, indent=2, ensure_ascii=False) + '\n')
    print(f'{len(records)} chords, dropped {len(dropped)}:')
    print('\n'.join(dropped))


if __name__ == '__main__':
    main()
