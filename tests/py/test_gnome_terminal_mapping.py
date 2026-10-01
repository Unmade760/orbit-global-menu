# The gnome-terminal mapping follows the app's own menubar (menubar-with-mnemonics.ui) and the
# defaults in org.gnome.Terminal.gschema.xml. Actions the schema leaves 'disabled' stay placeholders.

import json
import os

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MAPPING = os.path.join(ROOT, 'global-menu@unmade.space', 'shortcuts', 'apps', 'gnome-terminal.json')
SOURCES = os.path.join(ROOT, 'tools', 'mapping-sources', 'gnome-terminal.sources.json')


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
    with open(MAPPING, encoding='utf-8') as f:
        return json.load(f)


@pytest.fixture(scope='module')
def by_path(mapping):
    return {p: s for m in mapping['menus'] for p, s in walk(m['items'], (m['label'],))}


def test_menus_are_the_apps_own(mapping):
    assert [m['label'] for m in mapping['menus']] == [
        'File', 'Edit', 'View', 'Search', 'Terminal', 'Tabs', 'Help']


@pytest.mark.parametrize('path', [
    ('Edit', 'Select All'), ('Edit', 'Preferences'), ('Help', 'Contents'),
    ('File', 'Save Contents…'), ('File', 'Export…'), ('File', 'Print…'),
    ('Edit', 'Copy as HTML'), ('Terminal', 'Reset'), ('Terminal', 'Reset and Clear'),
    ('Terminal', 'Read-Only'), ('Tabs', 'Detach Terminal'),
])
def test_disabled_by_default_is_a_placeholder(by_path, path):
    assert path in by_path
    assert by_path[path] is None


def test_search_menu_holds_find(by_path):
    assert by_path[('Search', 'Find…')] == '<Ctrl><Shift>F'
    assert ('Edit', 'Find') not in by_path


def test_every_chord_has_a_source_record(mapping, by_path):
    with open(SOURCES, encoding='utf-8') as f:
        records = {tuple(r['path']): r['shortcut'] for r in json.load(f)['items']}
    assert records == {p: s for p, s in by_path.items() if s}
