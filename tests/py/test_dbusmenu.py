"""com.canonical.dbusmenu to the JSON tree the extension renders.

Covers DbusAppMenu and MenuModel in globalmenu/menu_model/menu_model.py and
DbusAppMenuItem in menu_item.py, plus DbusMenu._children_list in
globalmenu/utils/menu.py, against a scripted Qt or appmenu-gtk-module style
exporter reached through the AppMenu registrar.
"""

import pytest

from fakes import DBUSMENU_BUS, DBUSMENU_PATH, FakeSession, FakeWindow, dm, install_dbusmenu_app, pump

from globalmenu.menu_model.menu_item import DbusAppMenuItem
from globalmenu.menu_model.menu_model import MenuModel
from globalmenu.utils.menu import DbusMenu


SUB = {'children-display': 'submenu'}

LAYOUT = dm(0, SUB, [
	dm(1, {'label': '_File', **SUB}, [
		dm(2, {'label': '_New', 'shortcut': [['Control', 'n']]}),
		dm(3, {'type': 'separator'}),
		dm(4, {'label': 'Word Wrap', 'toggle-type': 'checkmark', 'toggle-state': 1}),
		dm(5, {'label': 'Hidden', 'visible': False}),
		dm(6, {'label': 'Print', 'enabled': False}),
		dm(7, {'label': 'Recent', **SUB}, [
			dm(8, {'label': 'a.txt'}),
		]),
		dm(9, {'label': 'Small', 'toggle-type': 'radio', 'toggle-state': 1}),
		dm(10, {'label': 'Large', 'toggle-type': 'radio', 'toggle-state': 0}),
	]),
	dm(11, {'label': '_Help', **SUB}, [
		dm(12, {'label': 'About', 'shortcut': [['Control', 'Shift', 'F1']]}),
	]),
])


def json_tree(model):
	tree = model.tree
	if tree.root is None:
		return []
	return DbusMenu._children_list(DbusMenu.__new__(DbusMenu), tree, tree[tree.root])


def find(nodes, *labels):
	node = None
	for label in labels:
		node = next(n for n in nodes if n.get('label') == label)
		nodes = node.get('children', [])
	return node


@pytest.fixture
def app():
	session = FakeSession()
	window = FakeWindow({})
	install_dbusmenu_app(session, LAYOUT, window)
	model = MenuModel(session, window)
	model._update_menus()
	return session, model


def test_top_level_menus(app):
	_, model = app
	assert model.top_level_menus == ['_File', '_Help']
	assert [n['label'] for n in json_tree(model)] == ['_File', '_Help']


def test_items_separators_and_hidden(app):
	_, model = app
	shape = ['---' if n.get('separator') else n['label'] for n in find(json_tree(model), '_File')['children']]
	assert shape == ['_New', '---', 'Word Wrap', 'Print', 'Recent', 'Small', 'Large']


def test_states(app):
	_, model = app
	tree = json_tree(model)
	assert find(tree, '_File', 'Print')['enabled'] is False
	wrap = find(tree, '_File', 'Word Wrap')
	assert (wrap['toggleType'], wrap['toggleState']) == ('checkmark', True)
	small, large = find(tree, '_File', 'Small'), find(tree, '_File', 'Large')
	assert (small['toggleType'], small['toggleState'], large['toggleState']) == ('radio', True, False)


def test_submenu(app):
	_, model = app
	recent = find(json_tree(model), '_File', 'Recent')
	assert [c['label'] for c in recent['children']] == ['a.txt']


def test_every_opened_submenu_is_closed_again(app):
	# Qt apps stay in "menu open" state and ignore the keyboard otherwise
	session, _ = app
	events = [(int(c[4][0]), str(c[4][1])) for c in session.calls_to('Event')]
	opened = [i for i, kind in events if kind == 'opened']
	closed = [i for i, kind in events if kind == 'closed']
	assert opened and sorted(opened) == sorted(closed)
	for item_id in opened:
		assert events.index((item_id, 'opened')) < events.index((item_id, 'closed'))


def test_activate_sends_clicked_for_the_item_id(app):
	session, model = app
	key = find(json_tree(model), '_File', 'Recent', 'a.txt')['key']
	model.activate(key)
	clicked = [c for c in session.calls_to('Event') if c[4][1] == 'clicked']
	assert len(clicked) == 1
	assert (clicked[0][0], clicked[0][1], int(clicked[0][4][0])) == (DBUSMENU_BUS, DBUSMENU_PATH, 8)


def test_properties_update_signal(app):
	_, model = app
	model.appmenu.on_actions_changed([(4, {'toggle-state': 0}), (6, {'enabled': True})], [])
	tree = json_tree(model)
	assert find(tree, '_File', 'Word Wrap')['toggleState'] is False
	assert find(tree, '_File', 'Print')['enabled'] is True


def test_shortcut_to_accelerator():
	item = DbusAppMenuItem((2, {'label': 'x', 'shortcut': [['Control', 'Shift', 'n']]}))
	assert item.accel == '<Control><Shift>n'
	assert DbusAppMenuItem((2, {'label': 'x'})).accel == ''


def test_json_carries_the_shortcut(app):
	_, model = app
	tree = json_tree(model)
	assert find(tree, '_File', '_New').get('accel') == '<Control>n'
	assert find(tree, '_Help', 'About').get('accel') == '<Control><Shift>F1'
	assert 'accel' not in find(tree, '_File', 'Print')


def test_remove_listener_disconnects_every_signal(app):
	session, model = app
	dbusmenu_signals = [s for s in session.signals if s[2] == 'com.canonical.dbusmenu']
	assert {s[3].signal for s in dbusmenu_signals} == {'ItemsPropertiesUpdated', 'LayoutUpdated'}
	model.appmenu.remove_actions_listener()
	assert all(s[3].removed for s in dbusmenu_signals)


def changing_app(layout):
	session = FakeSession()
	window = FakeWindow({})
	install_dbusmenu_app(session, layout, window)
	changed = []
	model = MenuModel(session, window, lambda: changed.append(json_tree(model)))
	model._update_menus()
	return session, window, model, changed


def emit_layout_updated(session):
	session.emit(DBUSMENU_BUS, DBUSMENU_PATH, 'com.canonical.dbusmenu', 'LayoutUpdated', 8, 0)


def test_layout_update_reaches_on_changed():
	# An app that fills in its menubar after it registers must reach the panel
	session, window, model, changed = changing_app(dm(0, SUB, []))
	assert json_tree(model) == []
	install_dbusmenu_app(session, LAYOUT, window)
	emit_layout_updated(session)
	emit_layout_updated(session)
	assert changed == []
	pump(0.5)
	assert len(changed) == 1
	assert [n['label'] for n in changed[0]] == ['_File', '_Help']


def test_properties_update_reaches_on_changed():
	_, _, model, changed = changing_app(LAYOUT)
	model.appmenu.on_actions_changed([(4, {'toggle-state': 0}), (6, {'enabled': True})], [])
	assert len(changed) == 1
	assert find(changed[0], '_File', 'Print')['enabled'] is True
