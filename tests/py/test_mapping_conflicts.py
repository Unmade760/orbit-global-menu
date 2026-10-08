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
    return tuple(normalise(chord) for chord in shortcut.split())


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


SAME_COMMAND = 'both labels are one command that sits in two menus'
SCOPED = 'the labels name different views, modes, panels or pages of the app'
SUITE_MODULES = 'the mapping covers several programs of a suite and each binds the chord itself'
UNREVIEWED = 'existing duplicate, not yet checked against the app source'

# Chords that two labels with different names share inside one mapping, as
# {mapping file: {chord as written: why it is allowed}}. A new duplicate has to
# be fixed or added here with a reason.
SHARED_CHORDS = {
    'papers.json': {
        'W': SCOPED,
    },
    'loupe.json': {
        'Escape': SCOPED,
    },
    'nicotine.json': {
        '<Ctrl>C': SCOPED,
        '<Ctrl>F': SCOPED,
    },
    'komikku.json': {
        '<Ctrl>A': SCOPED,
    },
    'clocks.json': {
        '<Ctrl>N': SCOPED,
        'Escape': UNREVIEWED,
    },
    'scrcpy.json': {
        '<Alt>Up': SCOPED,
        '<Alt>Down': SCOPED,
    },
    'zen-browser.json': {
        '<Ctrl><Shift>Tab': UNREVIEWED,
    },
    'firefox.json': {
        '<Ctrl><Shift>Z': SCOPED,
        '<Ctrl><Shift>Tab': UNREVIEWED,
    },
    'thunar.json': {
        'Escape': SCOPED,
    },
    'gparted.json': {
        '<Ctrl>R': UNREVIEWED,
        '<Alt>V': UNREVIEWED,
        '<Alt>P': UNREVIEWED,
    },
    'timeshift.json': {
        'Return': SCOPED,
    },
    'bleachbit.json': {
        '<Alt>F': UNREVIEWED,
        '<Alt>H': UNREVIEWED,
    },
    'pinta.json': {
        '<Ctrl><Alt>V': UNREVIEWED,
        '<Ctrl>R': UNREVIEWED,
        '<Ctrl>G': UNREVIEWED,
    },
    'freecad.json': {
        '<Ctrl><Shift>P': UNREVIEWED,
        'V': UNREVIEWED,
    },
    'element.json': {
        '<Ctrl>E': SCOPED,
        'Escape': SCOPED,
        '<Alt>Down': SCOPED,
        '<Alt>Up': SCOPED,
    },
    'transmission.json': {
        '<Ctrl>P': UNREVIEWED,
    },
    'foliate.json': {
        '<Ctrl>I': SCOPED,
        '<Ctrl>C': SCOPED,
    },
    'calibre.json': {
        '<Ctrl>P': SCOPED,
    },
    'insomnia.json': {
        '<Ctrl><Shift>F': UNREVIEWED,
    },
    'alacritty.json': {
        'Return': SCOPED,
        '<Ctrl>U': SCOPED,
    },
    'gimp.json': {
        '<Ctrl><Shift>V': SAME_COMMAND,
    },
    'obs.json': {
        '<Ctrl><Shift>V': UNREVIEWED,
    },
    'shotwell.json': {
        '<Ctrl>A': UNREVIEWED,
    },
    'celluloid.json': {
        'Escape': SCOPED,
    },
    'boxes.json': {
        '<Alt>Left': SCOPED,
    },
    'geary.json': {
        '<Ctrl>W': SCOPED,
        '<Ctrl>B': SCOPED,
        '<Ctrl>I': SCOPED,
        '<Ctrl>U': SCOPED,
        '<Ctrl>K': SCOPED,
        '<Ctrl>L': SCOPED,
        '<Ctrl>D': SCOPED,
    },
    'thunderbird.json': {
        '<Ctrl>N': SAME_COMMAND,
        'M': SAME_COMMAND,
    },
    'evolution.json': {
        '<Ctrl><Shift>M': UNREVIEWED,
        '<Ctrl><Shift>K': UNREVIEWED,
    },
    'anki.json': {
        '<Ctrl>I': SCOPED,
        '<Shift>V': UNREVIEWED,
    },
    'evernote.json': {
        '<Ctrl>Q': UNREVIEWED,
    },
    'scrivener.json': {
        '<Ctrl><Shift>N': UNREVIEWED,
    },
    'vscode.json': {
        '<Ctrl><Shift>I': SCOPED,
        '<Ctrl><Shift>P': SCOPED,
        'F11': SCOPED,
        'F5': SCOPED,
    },
    'iotas.json': {
        '<Ctrl>F': SCOPED,
        '<Ctrl>G': SCOPED,
    },
    'librewolf.json': {
        '<Ctrl>W': SCOPED,
        '<Ctrl>S': SCOPED,
        '<Ctrl>P': SCOPED,
        '<Ctrl><Shift>Z': SCOPED,
        '<Ctrl>F': SCOPED,
        '<Ctrl>G': SCOPED,
        '<Ctrl>0': SCOPED,
        'Escape': SCOPED,
        'F11': SCOPED,
        'F10': SCOPED,
        '<Ctrl><Shift>D': SCOPED,
        '<Ctrl>B': SCOPED,
        '<Ctrl><Shift>B': SCOPED,
        '<Ctrl><Shift>F': SCOPED,
    },
    'mission-center.json': {
        '<Ctrl>E': SCOPED,
    },
    'wireshark.json': {
        '<Ctrl>R': SCOPED,
        '<Ctrl>E': SAME_COMMAND,
    },
    'wps-office.json': {
        '<Ctrl>Y': SUITE_MODULES,
        '<Ctrl>G': SUITE_MODULES,
        '<Ctrl>Return': SUITE_MODULES,
        '<Ctrl><Shift>G': SUITE_MODULES,
        '<Ctrl>Tab': SUITE_MODULES,
        '<Ctrl><Shift>Tab': SUITE_MODULES,
        '<Ctrl>D': SUITE_MODULES,
        '<Ctrl>R': SUITE_MODULES,
        '<Ctrl><Shift>equal': SUITE_MODULES,
        '<Ctrl><Shift>period': SUITE_MODULES,
        '<Ctrl><Shift>comma': SUITE_MODULES,
        '<Ctrl>bracketright': SUITE_MODULES,
        '<Ctrl>bracketleft': SUITE_MODULES,
        'F9': SUITE_MODULES,
    },
    'zaptide.json': {
        'Return': SCOPED,
    },
}


def shared_chords(mapping):
    labels = {}
    written = {}
    for menu in mapping['menus']:
        for path, shortcut in shortcut_items(menu['items'], (menu['label'],)):
            labels.setdefault(chords(shortcut), set()).add(path[-1].lower())
            written.setdefault(chords(shortcut), shortcut)
    return {written[chord] for chord, names in labels.items() if len(names) > 1}


def test_chord_is_not_shared_by_different_labels():
    found = []
    for filename, mapping in MAPPINGS:
        allowed = SHARED_CHORDS.get(filename, {})
        for shortcut in shared_chords(mapping) - set(allowed):
            found.append('%s: %s' % (filename, shortcut))
    assert not found, found


def test_shared_chord_allowlist_has_no_stale_entries():
    stale = []
    for filename, mapping in MAPPINGS:
        shared = shared_chords(mapping)
        for shortcut in SHARED_CHORDS.get(filename, {}):
            if shortcut not in shared:
                stale.append('%s: %s' % (filename, shortcut))
    assert not stale, stale
