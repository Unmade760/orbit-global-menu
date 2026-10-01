"""org.gtk.Menus to the JSON tree the extension renders.

Covers globalmenu/menu_model/menu_model.py (DbusGtkMenu, MenuModel) and the
tree to JSON conversion in globalmenu/utils/menu.py (DbusMenu._children_list),
against a scripted GTK application: a menubar with sections, a submenu, a
disabled item, a checkbox and a radio group.
"""

import dbus
import pytest

from fakes import (FakeSession, FakeWindow, GTK_APP_MENU_PROPS, GTK_BUS, GTK_PROPS, gtk_item,
	gtk_describe, install_gtk_app, no_registrar)

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


APP_PATH = GTK_PROPS['_GTK_APPLICATION_OBJECT_PATH']
WIN_PATH = GTK_PROPS['_GTK_WINDOW_OBJECT_PATH']


def actions_changed(session, path, removed=(), enabled=None, state=None, added=None):
	"""org.gtk.Actions.Changed as GTK emits it at the app or window path."""
	session.emit(GTK_BUS, path, 'org.gtk.Actions', 'Changed',
		list(removed), enabled or {}, state or {}, added or {})


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


def load(menus, actions, props=GTK_PROPS, **kwargs):
	session = FakeSession()
	no_registrar(session)
	install_gtk_app(session, menus, actions, props=props, **kwargs)
	model = MenuModel(session, FakeWindow(props))
	model._update_menus()
	return session, model


@pytest.fixture
def app():
	return load(MENUS, ACTIONS)


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
	session, model = app
	for state in states:
		actions_changed(session, WIN_PATH, state={'size': state})
	small = find(json_tree(model), '_View', '_Small')
	large = find(json_tree(model), '_View', '_Large')
	assert (small['toggleState'], large['toggleState']) == want


def test_stateful_item_without_target_is_a_plain_item():
	# gtkmenutrackeritem.c: an item is a radio item when it has a target and
	# its action a state, a check item when the state is boolean
	_, model = load({
		(0, 0): [gtk_item(label='_Mode', submenu=(1, 0))],
		(1, 0): [gtk_item(label='Mode _A', action='win.mode')],
	}, {'win.mode': gtk_describe(True, 'a')})
	node = find(json_tree(model), '_Mode', 'Mode _A')
	assert (node['toggleType'], node['toggleState']) == ('', False)


def test_actions_are_described_once_per_group(app):
	# One DescribeAll per exported action group, not one Describe per item:
	# the tree is rebuilt on every menu change
	session, _ = app
	assert sorted(c[1] for c in session.calls_to('DescribeAll')) == sorted([APP_PATH, WIN_PATH])
	assert session.calls_to('Describe') == []


def test_item_whose_action_is_missing_is_greyed():
	# gtkmenutrackeritem.c leaves an item insensitive until its action
	# exists. A prefix nobody exports over D-Bus says nothing either way.
	_, model = load({
		(0, 0): [gtk_item(label='_File', submenu=(1, 0))],
		(1, 0): [
			gtk_item(label='_Gone', action='win.gone'),
			gtk_item(label='_Save', action='doc.save'),
		],
	}, {'win.other': gtk_describe(True)})
	tree = json_tree(model)
	assert find(tree, '_File', '_Gone')['enabled'] is False
	assert find(tree, '_File', '_Save')['enabled'] is True


def test_enabled_change_signal_updates_every_item_of_the_action(app):
	# win.open backs both File > Open and File > Recent > a.txt
	session, model = app
	actions_changed(session, WIN_PATH, enabled={'open': True})
	tree = json_tree(model)
	assert find(tree, '_File', '_Open')['enabled'] is True
	assert find(tree, '_File', 'Recent', 'a.txt')['enabled'] is True


def test_checkbox_change_signal(app):
	session, model = app
	actions_changed(session, WIN_PATH, state={'grid': False})
	assert find(json_tree(model), '_View', 'Show _Grid')['toggleState'] is False


def test_action_changes_are_heard_where_gtk_exports_actions(app):
	# GTK exports org.gtk.Actions at the application and window paths only,
	# never at the menubar path
	session, _ = app
	paths = {s[1] for s in session.signals if s[2] == 'org.gtk.Actions' and s[3].signal == 'Changed'}
	assert {APP_PATH, WIN_PATH} <= paths


def test_change_at_the_app_path_leaves_win_actions_alone(app):
	session, model = app
	actions_changed(session, APP_PATH, enabled={'grid': False}, state={'grid': False})
	grid = find(json_tree(model), '_View', 'Show _Grid')
	assert (grid['enabled'], grid['toggleState']) == (True, True)


def test_enabled_and_state_change_in_one_signal(app):
	session, model = app
	actions_changed(session, WIN_PATH, enabled={'grid': False}, state={'grid': False})
	grid = find(json_tree(model), '_View', 'Show _Grid')
	assert (grid['enabled'], grid['toggleState']) == (False, False)


def test_removed_and_added_actions(app):
	# gtkmenutrackeritem.c: an item whose action goes away is insensitive and
	# plain; when the action comes back it takes the new description
	session, model = app
	actions_changed(session, WIN_PATH, removed=['grid'])
	grid = find(json_tree(model), '_View', 'Show _Grid')
	assert (grid['enabled'], grid['toggleType'], grid['toggleState']) == (False, '', False)
	actions_changed(session, WIN_PATH, added={'grid': (dbus.Boolean(True), dbus.Signature(''),
		dbus.Array([dbus.Boolean(True, variant_level=1)], signature='v'))})
	grid = find(json_tree(model), '_View', 'Show _Grid')
	assert (grid['enabled'], grid['toggleType'], grid['toggleState']) == (True, 'checkmark', True)


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


def test_activating_any_targeted_item_passes_its_target():
	# A stateless action with a parameter, as Mousepad's targeted items are
	session, model = load({
		(0, 0): [gtk_item(label='_Go', submenu=(1, 0))],
		(1, 0): [
			gtk_item(label='Tab _2', action='win.go-tab', target='2'),
			gtk_item(label='_Home', action='win.home'),
		],
	}, {'win.go-tab': gtk_describe(True), 'win.home': gtk_describe(True)})
	model.activate('_Go  »  Tab _2')
	model.activate('_Go  »  _Home')
	sent = [(c[4][0], [str(v) for v in c[4][1]]) for c in session.calls_to('Activate')]
	assert sent == [('go-tab', ['2']), ('home', [])]


APP_MENU = {
	(0, 0): [gtk_item(section=(0, 1)), gtk_item(section=(0, 2))],
	(0, 1): [gtk_item(label='_About Demo', action='app.about')],
	(0, 2): [gtk_item(label='_Quit', action='app.quit')],
}
APP_MENU_ACTIONS = {'app.new': gtk_describe(True), 'app.about': gtk_describe(True), 'app.quit': gtk_describe(True)}


def test_app_menu_and_menubar_both_reach_the_tree():
	# Each export numbers its groups from (0, 0), so neither may overwrite
	# the other. The app menu is one more top-level node, after the menubar
	session, model = load({
		(0, 0): [gtk_item(label='_File', submenu=(1, 0))],
		(1, 0): [gtk_item(label='_New', action='app.new')],
	}, APP_MENU_ACTIONS, props=GTK_APP_MENU_PROPS, app_menus=APP_MENU)
	tree = json_tree(model)
	assert [(n['label'], n.get('appMenu', False)) for n in tree] == [('_File', False), ('', True)]
	assert find(tree, '_File', '_New')['key'] == '_File  »  _New'
	app_menu = tree[1]
	assert [n.get('label', '---') for n in app_menu['children']] == ['_About Demo', '---', '_Quit']
	assert app_menu['children'][0]['key'] == '  »  _About Demo'
	assert model.top_level_menus == ['_File']

	model.activate(app_menu['children'][0]['key'])
	model.activate('_File  »  _New')
	sent = [(c[1], c[4][0]) for c in session.calls_to('Activate')]
	assert sent == [(APP_PATH, 'about'), (APP_PATH, 'new')]


def test_app_menu_only():
	_, model = load({}, APP_MENU_ACTIONS, props=GTK_APP_MENU_PROPS, app_menus=APP_MENU)
	tree = json_tree(model)
	assert [(n['label'], n.get('appMenu', False)) for n in tree] == [('', True)]
	assert model.top_level_menus == []


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
