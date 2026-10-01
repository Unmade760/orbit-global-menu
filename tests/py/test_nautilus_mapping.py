# The built-in Nautilus mapping: dialog titles, the app-level items and the
# chords that were missing. verify-mapping proves each chord against the
# Nautilus 50.3 source; this checks that the mapping and its records agree.

import json
import os

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MAPPING = os.path.join(ROOT, 'global-menu@unmade.space', 'shortcuts', 'apps', 'nautilus.json')
SOURCES = os.path.join(ROOT, 'tools', 'mapping-sources', 'nautilus.sources.json')


def load(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def walk(items, path=()):
    for item in items:
        if item.get('separator'):
            continue
        here = path + (item['label'],)
        if 'items' in item:
            yield from walk(item['items'], here)
        else:
            yield here, item.get('shortcut')


@pytest.fixture(scope='module')
def mapping():
    return load(MAPPING)


@pytest.fixture(scope='module')
def by_path(mapping):
    return {path: s for m in mapping['menus'] for path, s in walk(m['items'], (m['label'],))}


def test_app_level_items(by_path):
    assert by_path[('File', 'Quit')] == '<Ctrl>Q'
    assert by_path[('Edit', 'Show Preferences')] == '<Ctrl>comma'


def test_missing_chords_are_present(by_path):
    chords = {s for s in by_path.values() if s}
    assert {'<Ctrl>period', '<Alt>Down', '<Shift>F10', 'F10', '<Ctrl>M', '<Ctrl><Shift>M',
            '<Ctrl>I', 'F5', '<Ctrl><Shift>F', 'slash', 'asciitilde'} <= chords


def test_tabs_alt_1_to_8(by_path):
    for n in range(1, 9):
        assert by_path[('Tabs', 'Open Tab', 'Tab %d' % n)] == '<Alt>%d' % n


def test_labels_are_the_dialog_titles(by_path):
    labels = {p[-1] for p in by_path}
    assert {'Show/Hide Hidden Files', 'Move to Trash', 'Bookmark Current Location',
            'Enter Location', 'Open Item Location (Search and Recent Only)',
            'Show Item Properties', 'Refresh View', 'Create Folder', 'Go Up'} <= labels
    assert not {'Show Hidden Files', 'Bookmark This Location', 'Properties', 'Reload',
                'New Folder', 'Parent Folder'} & labels


def test_unbound_actions_are_placeholders(by_path):
    # app.shortcuts has no accelerator in nautilus-application.c.
    assert by_path[('Help', 'Shortcuts')] is None
    assert not [p for p, s in by_path.items() if s == '<Ctrl>question']


def test_every_shortcut_has_a_source_record(by_path):
    records = {(tuple(r['path']), r['shortcut']) for r in load(SOURCES)['items']}
    wanted = {(p, s) for p, s in by_path.items() if s}
    assert wanted - records == set()
    assert records - wanted == set()


def test_no_em_dash():
    for path in (MAPPING, SOURCES):
        with open(path, encoding='utf-8') as f:
            assert chr(0x2014) not in f.read()
