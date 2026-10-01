# The built-in Blender mapping follows Blender 5.1's own top bar (scripts/startup/bl_ui/space_topbar.py)
# joined with the default keymap (scripts/presets/keyconfig/keymap_data/blender_default.py) at v5.1.0.
# verify-mapping proves each chord against that file; this checks that the mapping and its records agree
# and that the audited mistakes stay fixed.

import json
import os

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MAPPING = os.path.join(ROOT, 'global-menu@unmade.space', 'shortcuts', 'apps', 'blender.json')
SOURCES = os.path.join(ROOT, 'tools', 'mapping-sources', 'blender.sources.json')


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


def test_top_bar_is_blenders_own(mapping):
    labels = [m['label'] for m in mapping['menus']]
    assert labels[:5] == ['File', 'Edit', 'Render', 'Window', 'Help']


def test_editor_keys_sit_in_one_named_menu(mapping):
    labels = [m['label'] for m in mapping['menus']]
    assert labels[5:] == ['3D Viewport']
    assert not set(labels) & {'View', 'Go', 'Tools'}


def test_render_keys_are_under_render_not_tools(by_path):
    assert by_path[('Render', 'Render Image')] == 'F12'
    assert by_path[('Render', 'Render Animation')] == '<Ctrl>F12'
    assert not [p for p in by_path if p[0] == 'Tools']


def test_top_bar_chords_that_were_missing(by_path):
    assert by_path[('File', 'Save Incremental')] == '<Ctrl><Alt>S'
    assert by_path[('Edit', 'Adjust Last Operation…')] == 'F9'
    assert by_path[('Edit', 'Rename Active Item…')] == 'F2'
    assert by_path[('Edit', 'Batch Rename…')] == '<Ctrl>F2'
    assert by_path[('Render', 'View Render')] == 'F11'
    assert by_path[('Render', 'View Animation')] == '<Ctrl>F11'
    assert by_path[('Render', 'Render Sequencer Image')] == '<Alt>F12'
    assert by_path[('Render', 'Render Sequencer Animation')] == '<Ctrl><Alt>F12'
    assert by_path[('Window', 'Next Workspace')] == '<Ctrl>Page_Down'
    assert by_path[('Window', 'Previous Workspace')] == '<Ctrl>Page_Up'
    assert by_path[('Help', 'Manual')] == 'F1'


def test_labels_are_blenders_own(by_path):
    for label, chord in [('New', '<Ctrl>N'), ('Open…', '<Ctrl>O'), ('Save', '<Ctrl>S'),
                         ('Save As…', '<Ctrl><Shift>S'), ('Quit', '<Ctrl>Q')]:
        assert by_path[('File', label)] == chord
    names = {p[-1] for p in by_path}
    assert not names & {'New File', 'Open File', 'Save File', 'Save File As', 'Quit Blender'}


def test_chords_that_only_the_legacy_keymap_binds_are_not_mapped(by_path):
    # Undo History is Ctrl+Alt+Z only in the legacy keymap; Space is the toolbar, not Play, by default.
    assert not [p for p in by_path if p[-1] in ('Undo History', 'Play / Pause Animation')]
    assert by_path[('3D Viewport', 'Animation', 'Play Animation')] == '<Shift>space'


def test_area_keys_are_labelled_as_blender_labels_them(by_path):
    assert by_path[('3D Viewport', 'View', 'Maximize Area')] == '<Ctrl>space'
    assert by_path[('3D Viewport', 'View', 'Focus Mode')] == '<Ctrl><Alt>space'


def test_viewport_keys_are_all_under_3d_viewport(by_path):
    assert by_path[('3D Viewport', 'Transform', 'Move')] == 'G'
    assert by_path[('3D Viewport', 'Transform', 'Rotate')] == 'R'
    assert by_path[('3D Viewport', 'Transform', 'Scale')] == 'S'
    assert by_path[('3D Viewport', 'Select', 'Box Select')] == 'B'
    assert by_path[('3D Viewport', 'Object', 'Hide Selected')] == 'H'
    assert by_path[('3D Viewport', 'View', 'Toggle Sidebar')] == 'N'
    top = {p for p in by_path if p[0] in ('File', 'Edit', 'Render', 'Window', 'Help')}
    assert not {p for p in top if by_path[p] in ('G', 'R', 'S', 'B', 'H', 'N')}


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
