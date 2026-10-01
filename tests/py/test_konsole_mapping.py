# The Konsole mapping takes its labels and default chords from ViewManager.cpp and MainWindow.cpp.
# Konsole::ACCEL is Ctrl+Shift on Linux.

import json
import os

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MAPPING = os.path.join(ROOT, 'global-menu@unmade.space', 'shortcuts', 'apps', 'konsole.json')
SOURCES = os.path.join(ROOT, 'tools', 'mapping-sources', 'konsole.sources.json')


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
def entries(mapping):
    return [(p, s) for m in mapping['menus'] for p, s in walk(m['items'], (m['label'],))]


def chord_labels(entries):
    return {s: p[-1] for p, s in entries if s}


@pytest.mark.parametrize('chord,label', [
    ('<Ctrl>(', 'Split View Left/Right'),
    ('<Ctrl>)', 'Split View Top/Bottom'),
    ('<Ctrl>*', 'Split View Automatically'),
    ('<Ctrl><Shift>]', 'Expand View'),
    ('<Ctrl><Shift>[', 'Shrink View'),
    ('<Ctrl><Shift>E', 'Toggle maximize current view'),
    ('<Ctrl><Shift>Z', 'Toggle zoom-maximize current view'),
    ('<Ctrl><Alt>]', 'Setup semantic integration (bash)'),
    ('<Ctrl><Alt>[', 'Toggle semantic hints display'),
    ('<Ctrl><Alt>\\', 'Toggle line numbers display'),
    ('<Ctrl><Shift>\\', 'Equal size to all views'),
    ('<Ctrl><Shift>H', 'Detach Current View'),
    ('<Ctrl>F11', 'Focus Next Terminal'),
    ('<Ctrl><Shift>F11', 'Focus Previous Terminal'),
    ('<Shift>F10', 'Open Menu'),
    ('<Ctrl><Shift>F10', 'Activate Menu'),
])
def test_chord_carries_the_source_label(entries, chord, label):
    assert chord_labels(entries).get(chord) == label


def test_second_tab_chords(entries):
    assert chord_labels(entries)['<Ctrl>Page_Down'] == 'Next Tab'
    assert chord_labels(entries)['<Ctrl>Page_Up'] == 'Previous Tab'


def test_old_split_names_are_gone(entries):
    labels = {p[-1] for p, _ in entries}
    assert 'Split View Vertically' not in labels
    assert 'Split View Horizontally' not in labels


def test_chords_the_source_does_not_define_are_dropped(entries):
    chords = {s for _, s in entries if s}
    assert '<Ctrl><Shift>X' not in chords
    assert '<Ctrl><Shift>U' not in chords


def test_every_chord_has_a_source_record(entries):
    with open(SOURCES, encoding='utf-8') as f:
        records = sorted((tuple(r["path"]), r["shortcut"]) for r in json.load(f)["items"])
    assert records == sorted((p, s) for p, s in entries if s)
