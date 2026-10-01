# The built-in Inkscape mapping follows Inkscape 1.4.3's own menu bar (share/ui/menus.ui) joined with
# the default key bindings (share/keys/inkscape.xml, installed as keys/default.xml) at INKSCAPE_1_4_3.
# verify-mapping proves each chord against that file; this checks that the mapping and its records
# agree and that the audited mistakes stay fixed.

import json
import os

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MAPPING = os.path.join(ROOT, 'global-menu@unmade.space', 'shortcuts', 'apps', 'inkscape.json')
SOURCES = os.path.join(ROOT, 'tools', 'mapping-sources', 'inkscape.sources.json')


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


def test_menu_bar_is_inkscapes_own(mapping):
    # Filters and Help have no default chord, so they are left out.
    labels = [m['label'] for m in mapping['menus']]
    assert labels == ['File', 'Edit', 'View', 'Layer', 'Object', 'Path', 'Text', 'Extensions']


def test_no_menu_inkscape_does_not_have(mapping):
    labels = {m['label'] for m in mapping['menus']}
    assert not labels & {'Select', 'Tools'}


def test_group_and_ungroup_are_under_object(by_path):
    assert by_path[('Object', 'Group')] == '<Ctrl>G'
    assert by_path[('Object', 'Ungroup')] == '<Ctrl><Shift>G'
    assert ('Layer', 'Group') not in by_path


def test_duplicate_clone_and_zoom_sit_where_inkscape_files_them(by_path):
    assert by_path[('Edit', 'Duplicate')] == '<Ctrl>D'
    assert by_path[('Edit', 'Clone', 'Create Clone')] == '<Alt>D'
    assert by_path[('Edit', 'Clone', 'Select Original')] == '<Shift>D'
    assert by_path[('View', 'Zoom', 'Zoom Selection')] == '3'
    assert not [p for p in by_path if p[0] == 'Tools']


def test_file_labels_are_inkscapes_own(by_path):
    for label, chord in [('New', '<Ctrl>N'), ('Open…', '<Ctrl>O'), ('Save As…', '<Ctrl><Shift>S'),
                         ('Export…', '<Ctrl><Shift>E'), ('Quit', '<Ctrl>Q')]:
        assert by_path[('File', label)] == chord
    names = {p[-1] for p in by_path}
    assert not names & {'New Document', 'Open Document', 'Save Document As', 'Quit Inkscape',
                        'Export PNG / Image'}


def test_menu_chords_that_were_missing(by_path):
    assert by_path[('Edit', 'Delete')] == 'Delete'
    assert by_path[('Edit', 'Make a Bitmap Copy')] == '<Alt>B'
    assert by_path[('Edit', 'Resize Page to Selection')] == '<Ctrl><Shift>R'
    assert by_path[('View', 'Zoom', 'Zoom Previous')] == '`'
    assert by_path[('View', 'Zoom', 'Zoom Next')] == '~'
    assert by_path[('View', 'Zoom', 'Center Page')] == '<Ctrl>4'
    assert by_path[('View', 'Display Mode', 'Cycle')] == '<Ctrl>5'
    assert by_path[('View', 'Gray Scale')] == '<Alt>5'
    assert by_path[('View', 'Page Grid')] == '#'
    assert by_path[('View', 'Guides')] == '|'
    assert by_path[('View', 'Show/Hide', 'Palette')] == '<Shift><Alt>P'
    assert by_path[('View', 'Show/Hide Dialogs')] == 'F12'
    assert by_path[('View', 'Command Palette')] == '?'
    assert by_path[('View', 'Next Window')] == '<Ctrl>Tab'
    assert by_path[('Layer', 'Layer to Top')] == '<Ctrl><Shift>Home'
    assert by_path[('Object', 'Clip', 'Set Clip')] == '<Ctrl>M'
    assert by_path[('Object', 'Clip', 'Release Clip')] == '<Alt>M'
    assert by_path[('Object', 'Pattern', 'Objects to Pattern')] == '<Alt>I'
    assert by_path[('Object', 'Raise to Top')] == 'Home'
    assert by_path[('Object', 'Lower to Bottom')] == 'End'
    assert by_path[('Object', 'Flip Horizontal')] == 'H'
    assert by_path[('Object', 'Flip Vertical')] == 'V'
    assert by_path[('Path', 'Object to Path')] == '<Ctrl><Shift>C'
    assert by_path[('Path', 'Stroke to Path')] == '<Ctrl><Alt>C'
    assert by_path[('Path', 'Union')] == '<Ctrl>+'
    assert by_path[('Path', 'Difference')] == '<Ctrl>-'
    assert by_path[('Path', 'Combine')] == '<Ctrl>K'
    assert by_path[('Path', 'Break Apart')] == '<Ctrl><Shift>K'
    assert by_path[('Path', 'Simplify')] == '<Ctrl>L'
    assert by_path[('Text', 'Flow into Frame')] == '<Alt>W'
    assert by_path[('Text', 'Unflow')] == '<Shift><Alt>W'
    assert by_path[('Extensions', 'Previous Extension')] == '<Alt>Q'


def test_a_chord_that_inkscape_cannot_parse_is_not_mapped(by_path):
    # default.xml writes the first key of Set Inverse Clip as "<primary>alt>m".
    assert not [p for p in by_path if 'Inverse' in p[-1]]


def test_every_shortcut_has_a_source_record(by_path):
    records = {(tuple(r['path']), r['shortcut']) for r in load(SOURCES)['items']}
    wanted = {(p, s) for p, s in by_path.items() if s}
    assert wanted - records == set()
    assert records - wanted == set()


def test_labels_use_a_real_ellipsis_and_no_mnemonic(by_path):
    assert not [p for p in by_path if '...' in p[-1] or '_' in p[-1]]


def test_no_em_dash():
    for path in (MAPPING, SOURCES):
        with open(path, encoding='utf-8') as f:
            assert chr(0x2014) not in f.read()
