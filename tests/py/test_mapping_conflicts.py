# Checks across every built-in mapping: identifiers that would let one app's
# mapping take over another app's windows.

import json
import os

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
