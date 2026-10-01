# The built-in Thunderbird mapping: the main-window menus, the chords that
# were wrong before, and that every shortcut has a source record. The records
# are proven against Thunderbird's source and its support page by
# tools/mappings/bin/verify-mapping, which needs the network, so this only
# checks that the two files agree.

import json
import os

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MAPPING = os.path.join(ROOT, 'global-menu@unmade.space', 'shortcuts', 'apps', 'thunderbird.json')
SOURCES = os.path.join(ROOT, 'tools', 'mapping-sources', 'thunderbird.sources.json')


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


def test_menu_set(mapping):
    assert [m['label'] for m in mapping['menus']] == [
        'File', 'Edit', 'View', 'Go', 'Message', 'Tools', 'Help']


def test_identifiers_are_kept(mapping):
    assert mapping['identifiers'] == [
        'thunderbird.desktop', 'org.mozilla.Thunderbird.desktop',
        'net.thunderbird.Thunderbird.desktop', 'thunderbird', 'Thunderbird']


def test_get_new_messages_uses_the_f5_keys(by_path):
    base = ('File', 'Get New Messages for')
    assert by_path[base + ('All Accounts',)] == '<Shift>F5'
    assert by_path[base + ('Current Account',)] == 'F5'


def test_unbound_actions_are_placeholders(by_path):
    # F9 is cmd_getNewMessages, Ctrl+Shift+F is Search Messages, and Calendar,
    # Tasks and Chat have no key in mainKeySet or calendar-keys.
    for path in [('View', 'Layout', 'Folder Pane'),
                 ('Message', 'Forward As', 'Inline'),
                 ('Message', 'Forward As', 'Attachment'),
                 ('Go', 'Chat'), ('Go', 'Calendar'), ('Go', 'Tasks'),
                 # Bound in messenger.dtd to ] [ * \\ and in messenger.ftl to j, but
                 # verify-mapping cannot read those forms, so they stay unproven.
                 ('Go', 'Forward'), ('Go', 'Back'), ('Message', 'Mark', 'As Spam'),
                 ('View', 'Threads', 'Expand All Threads'),
                 ('View', 'Threads', 'Collapse All Threads')]:
        assert path in by_path, path
        assert by_path[path] is None, path


def test_no_chord_is_claimed_for_the_wrong_action(by_path):
    assert by_path[('Edit', 'Find', 'Search Messages\u2026')] == '<Ctrl><Shift>F'
    assert by_path[('Go', 'Undo Close Tab')] == '<Ctrl><Shift>T'
    assert by_path[('Tools', 'Developer Tools', 'Developer Toolbox')] == '<Ctrl><Shift>I'
    assert not [p for p, s in by_path.items() if s == 'F9']
    assert not [p for p, s in by_path.items() if s == '<Ctrl><Shift>C' and p[-1] != 'Calendar']


def test_compose_window_items_are_left_out(by_path):
    labels = {p[-1] for p in by_path}
    assert not {'Send Message', 'Send Message Later'} & labels
    assert not [p for p, s in by_path.items() if s in ('<Ctrl>Return', '<Ctrl><Shift>Return')]


def test_chords_that_were_missing_are_present(by_path):
    chords = {s for s in by_path.values() if s}
    assert {'<Ctrl>E', '<Ctrl><Shift>O', '<Ctrl><Shift>A', '<Ctrl><Shift>M', '<Ctrl>J',
            'F2', 'F7', 'F', 'B', 'C', '0', '1', '9', '<Alt>Home', '<Ctrl><Shift>Delete'} <= chords


def test_tag_keys_one_to_nine_and_zero(by_path):
    assert by_path[('Message', 'Tag', 'Remove All Tags')] == '0'
    for n in range(1, 10):
        assert by_path[('Message', 'Tag', 'Toggle Tag %d' % n)] == str(n)


def all_labels(items):
    for item in items:
        if item.get('separator'):
            continue
        yield item['label']
        yield from all_labels(item.get('items', []))


def test_labels_follow_messenger_dtd(mapping):
    labels = {label for m in mapping['menus'] for label in all_labels(m['items'])}
    assert {'Rename Folder\u2026', 'Print\u2026', 'Quit', 'Find in This Message\u2026',
            'Search Messages\u2026', 'Global Search\u2026', 'Message Pane', 'Message Source',
            'Reply to All', 'Edit As New Message', 'Open in Conversation', 'Move Again',
            'Mail Start Page', 'Unread Thread', 'Expand All Threads'} <= labels
    assert not {'Write New Message', 'Quit Thunderbird', 'Toggle Message Pane',
                'Forward Inline', 'Mark as Junk'} & labels


def test_every_shortcut_has_a_source_record(mapping):
    records = {(tuple(r['path']), r['shortcut']) for r in load(SOURCES)['items']}
    wanted = {(path, s) for m in mapping['menus'] for path, s in walk(m['items'], (m['label'],)) if s}
    assert wanted - records == set()
    assert records - wanted == set()


def test_no_em_dash():
    for path in (MAPPING, SOURCES):
        with open(path, encoding='utf-8') as f:
            assert chr(0x2014) not in f.read()
