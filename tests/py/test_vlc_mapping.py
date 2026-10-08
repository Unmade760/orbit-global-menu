# The built-in VLC mapping follows VLC 3.0's own menu bar (Media, Playback, Audio,
# Video, Subtitle, Tools, View, Help) and its default hotkeys. verify-mapping proves
# each chord against modules/gui/qt/menus.cpp and src/libvlc-module.c; this checks
# that the mapping and its records agree and that the audited mistakes stay fixed.

import json
import os

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MAPPING = os.path.join(ROOT, 'global-menu@unmade.space', 'shortcuts', 'apps', 'vlc.json')
SOURCES = os.path.join(ROOT, 'tools', 'mapping-sources', 'vlc.sources.json')


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


def test_menu_bar_is_vlcs_own(mapping):
    assert [m['label'] for m in mapping['menus']] == [
        'Media', 'Playback', 'Audio', 'Video', 'Subtitle', 'Tools', 'View', 'Help']


def test_track_synchronization_has_no_chord(by_path):
    # menus.cpp gives it an empty accelerator; Ctrl+Shift+S is "Open skin" in the popup menu.
    assert by_path[('Tools', 'Track Synchronization')] is None
    assert '<Ctrl><Shift>S' not in by_path.values()


def test_preferences_is_under_tools(by_path):
    assert by_path[('Tools', 'Preferences')] == '<Ctrl>P'
    assert not [p for p in by_path if p[0] == 'Edit']


def test_help_menu(by_path):
    assert by_path[('Help', 'Help')] == 'F1'
    assert by_path[('Help', 'About')] == '<Shift>F1'


def test_menu_chords_from_menus_cpp(by_path):
    assert by_path[('Playback', 'Jump to Specific Time')] == '<Ctrl>T'
    assert by_path[('Playback', 'Custom Bookmarks', 'Manage')] == '<Ctrl>B'
    assert by_path[('View', 'Fullscreen Interface')] == 'F11'
    assert by_path[('Tools', 'VLM Configuration')] == '<Ctrl><Shift>W'
    assert by_path[('Media', 'Quit')] == '<Ctrl>Q'


def test_default_hotkeys_are_present(by_path):
    chords = {s for s in by_path.values() if s}
    wanted = {'R', 'L', 'Z', '<Shift>Z', 'A', 'C', 'D', '<Shift>D', 'W', '<Shift>V', '<Shift>A',
              '<Alt>V', '<Shift>R', 'T', '<Shift>O', '<Shift>B', '<Shift>P', '<Shift>N',
              '<Shift>M', '<Alt>1', '<Alt>2', '<Alt>3', '<Alt>4', '<Alt>R', '<Alt>D', '<Alt>C',
              '<Alt>F', '[', ']', '<Ctrl>0', '<Shift>H', '<Shift>J', '<Shift>K',
              '<Ctrl><Shift>K', 'I', 'Page_Up', 'Page_Down'}
    assert wanted - chords == set()


def test_hotkeys_sit_under_the_menu_vlc_files_them_in(by_path):
    assert by_path[('Audio', 'Mute')] == 'M'
    assert by_path[('Playback', 'Next')] == 'N'
    assert by_path[('Playback', 'Previous')] == 'P'
    assert by_path[('Audio', 'Cycle Audio Track')] == 'B'
    assert by_path[('Subtitle', 'Cycle Subtitle Track')] == 'V'
    assert by_path[('Video', 'Take Snapshot')] == '<Shift>S'
    assert by_path[('Video', 'Zoom', '1:4 Quarter')] == '<Alt>1'


def test_vlc_wording(by_path):
    labels = {p[-1] for p in by_path}
    assert not {'Mute Volume', 'Next Track', 'Previous Track', 'Messages Log'} & labels
    assert not {p[0] for p in by_path} & {'File', 'Edit', 'Subtitles'}


def test_every_shortcut_has_a_source_record(by_path):
    records = {(tuple(r['path']), r['shortcut']) for r in load(SOURCES)['items']}
    wanted = {(p, s) for p, s in by_path.items() if s}
    assert wanted - records == set()
    # A recorded chord the mapping does not send belongs to a placeholder,
    # an item whose chord the shell grabs
    placeholders = {p for p, s in by_path.items() if not s}
    assert {p for p, _ in records - wanted} <= placeholders


def test_no_em_dash():
    for path in (MAPPING, SOURCES):
        with open(path, encoding='utf-8') as f:
            assert chr(0x2014) not in f.read()
