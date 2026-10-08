# Checks across every built-in mapping: identifiers that would let one app's
# mapping take over another app's windows.

import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SHORTCUTS = os.path.join(ROOT, 'global-menu@unmade.space', 'shortcuts')


def load_mappings():
    with open(os.path.join(SHORTCUTS, 'index.json'), encoding='utf-8') as f:
        index = json.load(f)['apps']
    mappings = []
    for filename in index:
        with open(os.path.join(SHORTCUTS, 'apps', filename), encoding='utf-8') as f:
            mappings.append((filename, json.load(f)))
    return mappings


MAPPINGS = load_mappings()

# Display names that more than one app uses as its desktop name.
GENERIC_NAMES = {
    'archive manager',
    'calculator',
    'document viewer',
    'files',
    'image viewer',
    'terminal',
}


def test_identifier_is_not_another_mappings_name():
    names = {}
    for filename, mapping in MAPPINGS:
        names.setdefault(mapping['name'].lower(), filename)
    clashes = []
    for filename, mapping in MAPPINGS:
        for identifier in mapping['identifiers']:
            owner = names.get(identifier.lower())
            if owner is not None and owner != filename:
                clashes.append('%s: %r is the name of %s' % (filename, identifier, owner))
    assert not clashes, clashes


def test_identifier_is_claimed_by_one_mapping():
    claimed = {}
    clashes = []
    for filename, mapping in MAPPINGS:
        for identifier in mapping['identifiers']:
            owner = claimed.setdefault(identifier.lower(), filename)
            if owner != filename:
                clashes.append('%s: %r is already claimed by %s' % (filename, identifier, owner))
    assert not clashes, clashes


def test_identifiers_avoid_generic_names():
    found = []
    for filename, mapping in MAPPINGS:
        for identifier in mapping['identifiers']:
            if identifier.lower() in GENERIC_NAMES:
                found.append('%s: %r' % (filename, identifier))
    assert not found, found


MODIFIERS = {
    'ctrl': 'ctrl',
    'control': 'ctrl',
    'primary': 'ctrl',
    'shift': 'shift',
    'alt': 'alt',
    'super': 'super',
}
MODIFIER = re.compile(r'<(ctrl|control|primary|shift|alt|super)>', re.IGNORECASE)


def normalise(chord):
    modifiers = set()
    match = MODIFIER.match(chord)
    while match:
        modifiers.add(MODIFIERS[match.group(1).lower()])
        chord = chord[match.end():]
        match = MODIFIER.match(chord)
    return frozenset(modifiers), chord.lower()


def chords(shortcut):
    return [normalise(chord) for chord in shortcut.split()]


def shortcut_items(items, path=()):
    for item in items:
        if item.get('separator'):
            continue
        here = path + (item['label'],)
        if 'items' in item:
            yield from shortcut_items(item['items'], here)
        elif 'shortcut' in item:
            yield here, item['shortcut']


# Chords that GNOME Shell or mutter bind by default. A synthesized keystroke
# goes through these bindings first, so the app never sees them.
GLOBAL_CHORDS = set()
for key in ('left', 'right', 'up', 'down'):
    GLOBAL_CHORDS.add((frozenset({'ctrl', 'alt'}), key))
    GLOBAL_CHORDS.add((frozenset({'ctrl', 'shift', 'alt'}), key))


def test_no_item_sends_a_chord_the_shell_grabs():
    found = []
    for filename, mapping in MAPPINGS:
        for menu in mapping['menus']:
            for path, shortcut in shortcut_items(menu['items'], (menu['label'],)):
                if any(chord in GLOBAL_CHORDS for chord in chords(shortcut)):
                    found.append('%s: %s: %s' % (filename, ' > '.join(path), shortcut))
    assert not found, found
