# The built-in Firefox mapping: its menu set, its wording, and that every
# shortcut in it has a source record. The records themselves are proven
# against Firefox's source by tools/mappings/bin/verify-mapping, which needs
# the network, so this only checks that the two files agree.

import json
import os

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MAPPING = os.path.join(ROOT, 'global-menu@unmade.space', 'shortcuts', 'apps', 'firefox.json')
SOURCES = os.path.join(ROOT, 'tools', 'mapping-sources', 'firefox.sources.json')


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


def menu(mapping, label):
    return next(m for m in mapping['menus'] if m['label'] == label)


def test_menu_set(mapping):
    labels = [m['label'] for m in mapping['menus']]
    assert labels == ['File', 'Edit', 'View', 'History', 'Bookmarks', 'Tabs', 'Profiles', 'Tools', 'Help']


def test_identifiers_are_kept(mapping):
    assert mapping['identifiers'] == [
        'org.mozilla.firefox.desktop', 'org.mozilla.firefox', 'firefox', 'Firefox']


def test_tabs_menu_chords(mapping):
    chords = {s for _, s in walk(menu(mapping, 'Tabs')['items']) if s}
    assert {'<Ctrl>Tab', '<Ctrl><Shift>Tab', '<Ctrl>Page_Down', '<Ctrl>Page_Up',
            '<Alt>1', '<Alt>9', '<Ctrl><Shift>Page_Up', '<Ctrl><Shift>Page_Down',
            '<Ctrl><Shift>Home', '<Ctrl><Shift>End', '<Ctrl>F4'} <= chords


def test_missing_menu_chords_are_present(mapping):
    chords = {s for m in mapping['menus'] for _, s in walk(m['items']) if s}
    assert {'F5', '<Ctrl>F5', 'F3', '<Shift>F3', '<Ctrl>bracketleft', '<Ctrl>bracketright',
            '<Alt>D', '<Ctrl>Y', 'F12', 'F6', '<Shift>F6'} <= chords


@pytest.mark.parametrize('name', ['Help', 'Profiles'])
def test_help_and_profiles_are_placeholders(mapping, name):
    items = list(walk(menu(mapping, name)['items']))
    assert items
    assert all(shortcut is None for _, shortcut in items)


def test_back_forward_reload_are_not_in_history(mapping):
    labels = {path[-1] for path, _ in walk(menu(mapping, 'History')['items'])}
    assert not {'Back', 'Forward', 'Reload', 'Home', 'Stop'} & labels


def all_labels(items):
    for item in items:
        if item.get('separator'):
            continue
        yield item['label']
        yield from all_labels(item.get('items', []))


def test_labels_follow_menubar_ftl(mapping):
    labels = {label for m in mapping['menus'] for label in all_labels(m['items'])}
    assert {'Save Page As…', 'Open File…', 'Print…', 'Find in Page…', 'Quit', 'Full Screen',
            'Bookmark Current Tab…', 'Extensions and Themes', 'Clear Recent History…',
            'Page Source', 'Page Info', 'Browser Tools'} <= labels
    assert not {'Save Page As', 'Open File', 'Print Page', 'Find in Page', 'Quit Firefox',
                'Toggle Full Screen', 'Bookmark Current Tab', 'Open Add-ons and Themes',
                'Clear Recent History', 'View Page Source', 'View Page Info'} & labels


def test_page_source_is_under_browser_tools(mapping):
    paths = {path for path, _ in walk(menu(mapping, 'Tools')['items'], ('Tools',))}
    assert ('Tools', 'Browser Tools', 'Page Source') in paths
    assert ('Tools', 'Page Info') in paths


def test_every_shortcut_has_a_source_record(mapping):
    records = {(tuple(r['path']), r['shortcut']) for r in load(SOURCES)['items']}
    wanted = {(path, s) for m in mapping['menus'] for path, s in walk(m['items'], (m['label'],)) if s}
    assert wanted - records == set()
    assert records - wanted == set()


def test_no_em_dash():
    for path in (MAPPING, SOURCES):
        with open(path, encoding='utf-8') as f:
            assert chr(0x2014) not in f.read()
