"""org.gtk.Menus to the JSON tree the extension renders.

Covers globalmenu/menu_model/menu_model.py (DbusGtkMenu, MenuModel) and the
tree to JSON conversion in globalmenu/utils/menu.py (DbusMenu._children_list),
against a scripted GTK application: a menubar with sections, a submenu, a
disabled item, a checkbox and a radio group.
"""

import pytest

from fakes import (FakeSession, FakeWindow, GTK_BUS, GTK_PROPS, gtk_item, gtk_describe,
	install_gtk_app, no_registrar)

from globalmenu.menu_model.menu_model import MenuModel
from globalmenu.utils.menu import DbusMenu


MENUS = {
	(0, 0): [gtk_item(section=(0, 1))],
	(0, 1): [gtk_item(label='_File', submenu=(1, 0)), gtk_item(label='_View', submenu=(2, 0))],
	(1, 0): [gtk_item(section=(1, 1)), gtk_item(section=(1, 2))],
	(1, 1): [
		gtk_item(label='_New', action='app.new', accel='<Primary>n'),
		gtk_item(label='_Open', action='win.open'),
		gtk_item(label='Recent', submenu=(1, 3)),
	],
	(1, 2): [gtk_item(label='_Quit', action='app.quit')],
	(1, 3): [gtk_item(label='a.txt', action='win.open')],
	(2, 0): [gtk_item(section=(2, 1)), gtk_item(section=(2, 2))],
	(2, 1): [gtk_item(label='Show _Grid', action='win.grid')],
	(2, 2): [
		gtk_item(label='_Small', action='win.size', target='small'),
		gtk_item(label='_Large', action='win.size', target='large'),
	],
}

ACTIONS = {
	'app.new': gtk_describe(True),
	'win.open': gtk_describe(False),
	'app.quit': gtk_describe(True),
	'win.grid': gtk_describe(True, True),
	'win.size': gtk_describe(True, 'small'),
}


def json_tree(model):
	tree = model.tree
	if tree.root is None:
		return []
	return DbusMenu._children_list(DbusMenu.__new__(DbusMenu), tree, tree[tree.root])


def find(nodes, *labels):
	"""Walk the JSON tree by labels, e.g. find(tree, '_File', '_New')."""
	node = None
	for label in labels:
		node = next(n for n in nodes if n.get('label') == label)
		nodes = node.get('children', [])
	return node


@pytest.fixture
def app():
	session = FakeSession()
	no_registrar(session)
	install_gtk_app(session, MENUS, ACTIONS)
	model = MenuModel(session, FakeWindow(GTK_PROPS))
	model._update_menus()
	return session, model


def test_top_level_menus(app):
	_, model = app
	assert model.top_level_menus == ['_File', '_View']
	assert [n['label'] for n in json_tree(model)] == ['_File', '_View']


def test_sections_become_separators(app):
	_, model = app
	file_menu = find(json_tree(model), '_File')['children']
	shape = ['---' if n.get('separator') else n['label'] for n in file_menu]
	assert shape == ['_New', '_Open', 'Recent', '---', '_Quit']


def test_submenu_and_keys(app):
	_, model = app
	recent = find(json_tree(model), '_File', 'Recent')
	assert [c['label'] for c in recent['children']] == ['a.txt']
	assert recent['children'][0]['key'] == '_File  »  Recent  »  a.txt'


def test_enabled_state_from_describe(app):
	_, model = app
	tree = json_tree(model)
	assert find(tree, '_File', '_New')['enabled'] is True
	assert find(tree, '_File', '_Open')['enabled'] is False


def test_checkbox_state(app):
	_, model = app
	grid = find(json_tree(model), '_View', 'Show _Grid')
	assert (grid['toggleType'], grid['toggleState']) == ('checkmark', True)


def test_radio_marks_only_the_item_whose_target_is_the_state(app):
	# GTK radio items share one stateful action; an item is selected when
	# the action's state equals the item's own "target"
	_, model = app
	small = find(json_tree(model), '_View', '_Small')
	large = find(json_tree(model), '_View', '_Large')
	assert small['toggleType'] == large['toggleType'] == 'radio'
	assert (small['toggleState'], large['toggleState']) == (True, False)


@pytest.mark.parametrize('states, want', [
	(['large'], (False, True)),
	(['large', 'small'], (True, False)),
])
def test_radio_state_change_signal_moves_the_dot(app, states, want):
	_, model = app
	for state in states:
		model.gtkmenu.on_gtk_actions_changed([], {}, {'size': state}, [])
	small = find(json_tree(model), '_View', '_Small')
	large = find(json_tree(model), '_View', '_Large')
	assert (small['toggleState'], large['toggleState']) == want


def test_enabled_change_signal_updates_every_item_of_the_action(app):
	# win.open backs both File > Open and File > Recent > a.txt
	_, model = app
	model.gtkmenu.on_gtk_actions_changed([], {'open': True}, {}, [])
	tree = json_tree(model)
	assert find(tree, '_File', '_Open')['enabled'] is True
	assert find(tree, '_File', 'Recent', 'a.txt')['enabled'] is True


def test_checkbox_change_signal(app):
	_, model = app
	model.gtkmenu.on_gtk_actions_changed([], {}, {'grid': False}, [])
	assert find(json_tree(model), '_View', 'Show _Grid')['toggleState'] is False


def test_activate_sends_the_action_to_the_right_object(app):
	session, model = app
	model.activate('_File  »  _New')
	model.activate('_View  »  Show _Grid')
	sent = [(c[1], c[4][0]) for c in session.calls_to('Activate')]
	assert sent == [(GTK_PROPS['_GTK_APPLICATION_OBJECT_PATH'], 'new'), (GTK_PROPS['_GTK_WINDOW_OBJECT_PATH'], 'grid')]
	assert all(c[0] == GTK_BUS for c in session.calls_to('Activate'))


def test_activating_a_radio_item_passes_its_target(app):
	# GIO docs (GMenuModel, "String Parameter and State"): selecting a radio
	# item activates the action with the item's target as the parameter
	session, model = app
	model.activate('_View  »  _Large')
	sent = [(c[4][0], [str(v) for v in c[4][1]]) for c in session.calls_to('Activate')]
	assert sent == [('size', ['large'])]


@pytest.mark.skip(reason='feature F2: the JSON tree does not carry the item accel yet, '
	'so native menus cannot show shortcut labels. Expected key name is "accel"')
def test_json_carries_the_accel(app):
	_, model = app
	assert find(json_tree(model), '_File', '_New').get('accel') == '<Primary>n'


def test_remove_listener_disconnects_every_signal(app):
	session, model = app
	assert session.signals, 'the model subscribed to Changed signals'
	model.gtkmenu.remove_actions_listener()
	assert all(s[3].removed for s in session.signals)


def test_window_without_menus_gives_an_empty_tree():
	session = FakeSession()
	no_registrar(session)
	model = MenuModel(session, FakeWindow({}))
	model._update_menus()
	assert json_tree(model) == []
	assert model.top_level_menus == []
