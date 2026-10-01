# The built-in GIMP mapping follows GIMP 3.2's own menu bar (File, Edit, Select, View, Image,
# Layer, Tools, Filters, Windows, Help) and the accelerators in app/actions/*-actions.c and
# app/tools/*.c at GIMP_3_2_6. verify-mapping proves each chord against those files; this checks
# that the mapping and its records agree and that the audited mistakes stay fixed.

import json
import os

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MAPPING = os.path.join(ROOT, 'global-menu@unmade.space', 'shortcuts', 'apps', 'gimp.json')
SOURCES = os.path.join(ROOT, 'tools', 'mapping-sources', 'gimp.sources.json')


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


def test_menu_bar_is_gimps_own(mapping):
    labels = [m['label'] for m in mapping['menus']]
    assert labels == ['File', 'Edit', 'Select', 'View', 'Image', 'Layer', 'Tools', 'Filters',
                      'Windows', 'Help']


def test_merge_down_has_no_chord(by_path):
    # layers-actions.c gives layers-merge-down no accelerator; Ctrl+M is Merge Visible Layers.
    assert ('Layer', 'Merge Down') not in by_path
    assert by_path[('Image', 'Merge Visible Layers…')] == '<Ctrl>M'


def test_navigation_window_has_no_chord(by_path):
    # dialogs-actions.c gives it none; Ctrl+Shift+N is Layer > New Layer.
    assert not [p for p in by_path if p[-1] == 'Navigation Window']
    assert by_path[('Layer', 'New Layer…')] == '<Ctrl><Shift>N'
    assert list(by_path.values()).count('<Ctrl><Shift>N') == 1


def test_chords_sit_under_the_menu_gimp_files_them_in(by_path):
    assert by_path[('Edit', 'Paste In Place')] == '<Ctrl><Alt>V'
    assert ('Edit', 'Invert Selection') not in by_path
    assert by_path[('Select', 'Invert')] == '<Ctrl>I'
    assert ('Edit', 'Search Actions') not in by_path
    assert by_path[('Help', 'Search and Run a Command')] == '/'
    assert by_path[('View', 'Zoom', 'Fit Image in Window')] == '<Ctrl><Shift>J'
    assert by_path[('File', 'Quit')] == '<Ctrl>Q'
    assert not [p for p in by_path if p[-1] == 'Quit GIMP']


def test_tool_keys_sit_under_the_tool_groups(by_path):
    assert by_path[('Tools', 'Selection Tools', 'Rectangle Select')] == 'R'
    assert by_path[('Tools', 'Selection Tools', 'By Color Select')] == '<Shift>O'
    assert by_path[('Tools', 'Paint Tools', 'Paintbrush')] == 'P'
    assert by_path[('Tools', 'Transform Tools', 'Move')] == 'M'
    assert by_path[('Tools', 'Transform Tools', 'Crop')] == '<Shift>C'
    assert by_path[('Tools', 'Paths')] == 'B'
    assert by_path[('Tools', 'Color Picker')] == 'O'
    assert not {p[0] for p in by_path} & {'Colors'}


def test_menu_chords_that_were_missing(by_path):
    assert by_path[('File', 'Open as Link Layer…')] == '<Ctrl><Shift><Alt>O'
    assert by_path[('File', 'Show in File Manager')] == '<Ctrl><Alt>F'
    assert by_path[('Select', 'Selection From Paths')] == '<Shift>V'
    assert by_path[('View', 'Zoom', 'Revert Zoom')] == '`'
    assert by_path[('View', 'Flip & Rotate', 'Reset Flip & Rotate')] == '!'
    assert by_path[('View', 'Center Image in Window')] == '<Shift>J'
    assert by_path[('View', 'Shrink Wrap')] == '<Ctrl>J'
    assert by_path[('View', 'Show Selection')] == '<Ctrl>T'
    assert by_path[('Image', 'Duplicate')] == '<Ctrl>D'
    assert by_path[('Layer', 'Stack', 'Select Previous Layers')] == 'Page_Up'
    assert by_path[('Layer', 'Stack', 'Select Next Layers')] == 'Page_Down'
    assert by_path[('Layer', 'Stack', 'Select Top Layer')] == 'Home'
    assert by_path[('Layer', 'Stack', 'Select Bottom Layer')] == 'End'
    assert by_path[('Layer', 'Transform', 'Offset…')] == '<Ctrl><Shift>O'
    assert by_path[('Tools', 'Toolbox')] == '<Ctrl>B'
    assert by_path[('Tools', 'Default Colors')] == 'D'
    assert by_path[('Tools', 'Swap Colors')] == 'X'
    assert by_path[('Windows', 'Dockable Dialogs', 'Layers')] == '<Ctrl>L'
    assert by_path[('Windows', 'Dockable Dialogs', 'Brushes')] == '<Ctrl><Shift>B'
    assert by_path[('Windows', 'Dockable Dialogs', 'Patterns')] == '<Ctrl><Shift>P'
    assert by_path[('Windows', 'Dockable Dialogs', 'Gradients')] == '<Ctrl>G'


def test_zoom_keys(by_path):
    zoom = {p[-1]: s for p, s in by_path.items() if p[:2] == ('View', 'Zoom') and ':' in p[-1]}
    assert zoom == {
        '16:1 (1600%)': '5', '8:1 (800%)': '4', '4:1 (400%)': '3', '2:1 (200%)': '2',
        '1:1 (100%)': '1', '1:2 (50%)': '<Shift>2', '1:4 (25%)': '<Shift>3',
        '1:8 (12.5%)': '<Shift>4', '1:16 (6.25%)': '<Shift>5'}


def test_shortcuts_gimp_does_not_define_are_gone(by_path):
    assert ('View', 'Toggle Grid') not in by_path
    assert '<Ctrl><Shift>\'' not in by_path.values()


def test_every_shortcut_has_a_source_record(by_path):
    records = {(tuple(r['path']), r['shortcut']) for r in load(SOURCES)['items']}
    wanted = {(p, s) for p, s in by_path.items() if s}
    assert wanted - records == set()
    assert records - wanted == set()


def test_labels_use_a_real_ellipsis(by_path):
    assert not [p for p in by_path if '...' in p[-1]]


def test_no_em_dash():
    for path in (MAPPING, SOURCES):
        with open(path, encoding='utf-8') as f:
            assert chr(0x2014) not in f.read()
