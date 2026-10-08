#!/usr/bin/python3

import dbus
import functools
import traceback
import time

from gi.repository import GLib

from ..treelib import Tree

from globalmenu.menu_model.menu_item import DbusGtkMenuItem, DbusAppMenuItem

# Seconds to wait for a client app on the main loop; a frozen app would
# otherwise hold the daemon for libdbus' 25 second default
CLIENT_TIMEOUT = 2


class DbusGtkMenu(object):

	def __init__(self, session, window, on_changed=None):
		# object path -> {(group, menu): [items]}, and the groups started there
		self.results      = {}
		self.groups       = {}
		self.menu_interfaces = {}
		self.actions      = {}
		self.targets      = {}
		self.accels       = {}
		self.tree         = Tree()
		# Gtk action names are not unique node ids: submenu entries carry no
		# action at all, and the same action can appear in several menus
		self.nodes_by_action = {}
		# 'app.', 'win.', 'unity.' -> {action name: (enabled, [state])} from
		# DescribeAll, kept current by org.gtk.Actions.Changed; None when
		# nothing answers for that prefix
		self.action_groups = {}
		self._node_seq    = 0
		self._rebuild_id = 0
		self.session      = session
		self.bus_name     = window.get_utf8_prop('_GTK_UNIQUE_BUS_NAME')
		# with app. prefix
		self.app_path     = window.get_utf8_prop('_GTK_APPLICATION_OBJECT_PATH')
		# with win. prefix
		self.win_path     = window.get_utf8_prop('_GTK_WINDOW_OBJECT_PATH')
		# with unity. prefix
		self.menubar_path = window.get_utf8_prop('_GTK_MENUBAR_OBJECT_PATH')
		self.appmenu_path = window.get_utf8_prop('_GTK_APP_MENU_OBJECT_PATH')

		self.top_level_menus = []
		self.signal_matcher = []
		# Called after the tree changed without being asked for
		self.on_changed = on_changed

	def activate(self, selection):
		action = self.actions.get(selection, '')
		target = self.targets.get(selection)

		if 'app.' in action:
			self.send_action(action, 'app.', self.app_path, target)
		elif 'win.' in action:
			self.send_action(action, 'win.', self.win_path, target)
		elif 'unity.' in action:
			self.send_action(action, 'unity.', self.menubar_path, target)

	def send_action(self, name, prefix, path, target=None):
		obj       = self.session.get_object(self.bus_name, path)
		interface = dbus.Interface(obj, dbus_interface='org.gtk.Actions')

		# The target keeps the D-Bus type it came with, which must match the
		# action's parameter type
		parameter = dbus.Array([] if target is None else [target], signature='v')
		interface.Activate(name.replace(prefix, ''), parameter, dbus.Dictionary({}, signature='sv'), timeout=CLIENT_TIMEOUT)

	def get_results(self):
		for path in filter(None, (self.menubar_path, self.appmenu_path)):
			obj       = self.session.get_object(self.bus_name, path)
			interface = dbus.Interface(obj, dbus_interface='org.gtk.Menus')
			# Listen first, so no change falls between Start and the match
			s = interface.connect_to_signal('Changed', functools.partial(self.on_menus_changed, path))
			self.signal_matcher.append(s)
			self.menu_interfaces[path] = interface
			# Each exported model numbers its own groups from (0, 0)
			self.results[path] = {}
			self.groups[path] = set()
			try:
				self._sync_groups(path)
			except dbus.exceptions.DBusException:
				del self.results[path]

		if self.results:
			self.watch_actions()
		self.build_tree()

	def _sync_groups(self, path):
		"""Start every group the menus at path link to and End the ones
		nothing links to any more. GMenuExporter reports changes only in
		started groups, and treats a Start for an id it has not created as a
		placeholder that a later submenu replaces, so only linked ids are
		started. A group id is never reused once its submenu is gone."""
		menus = self.results[path]
		groups = self.groups[path]
		interface = self.menu_interfaces[path]
		while True:
			linked = self._linked_groups(menus)
			new = sorted(linked - groups)
			if not new:
				break
			groups.update(new)
			for group, menu, items in interface.Start(dbus.Array(new, signature='u'), timeout=CLIENT_TIMEOUT):
				menus[(int(group), int(menu))] = list(items)

		dead = sorted(groups - linked)
		if dead:
			groups.difference_update(dead)
			for key in [k for k in menus if k[0] in dead]:
				del menus[key]
			interface.End(dbus.Array(dead, signature='u'), ignore_reply=True)

	@staticmethod
	def _linked_groups(menus):
		"""Groups reachable from the root menu through sections and submenus."""
		groups = set()
		seen = set()
		todo = [(0, 0)]
		while todo:
			key = todo.pop()
			if key in seen:
				continue
			seen.add(key)
			groups.add(key[0])
			for item in menus.get(key, []):
				for link in (':section', ':submenu'):
					if link in item:
						todo.append((int(item[link][0]), int(item[link][1])))
		return groups

	def on_menus_changed(self, path, changes):
		"""org.gtk.Menus.Changed: a(uuuuaa{sv}), each change being group,
		menu, position, number of items removed there, items added there."""
		menus = self.results.get(path)
		if menus is None:
			return
		changed = False
		for group, menu, position, removed, added in changes:
			# The signal reaches every listener; a group not started here
			# belongs to some other client
			if group not in self.groups.get(path, ()):
				continue
			items = menus.setdefault((int(group), int(menu)), [])
			items[position:position + removed] = list(added)
			changed = True
		# One rebuild for a burst: GTK sends one signal per changed menu
		if changed and not self._rebuild_id:
			self._rebuild_id = GLib.idle_add(self._rebuild)

	def _rebuild(self):
		self._rebuild_id = 0
		try:
			for path in self.results:
				self._sync_groups(path)
		except dbus.exceptions.DBusException:
			# The app is going away; show what was read
			pass
		self.build_tree()
		self._notify()
		return False

	def _notify(self):
		if self.on_changed is not None:
			self.on_changed()

	def build_tree(self):
		self.tree = Tree()
		self.tree.create_node('Root', 'Root')
		self.actions = {}
		self.targets = {}
		self.nodes_by_action = {}
		self.top_level_menus = []
		self._node_seq = 0

		menubar = self.results.get(self.menubar_path)
		if menubar:
			self.collect_entries(menubar, [], 'Root')

		# The app menu goes after the menubar as one unlabelled node; its item
		# keys start with an empty label, so they never collide with the bar's
		app_menu = self.results.get(self.appmenu_path)
		if app_menu:
			menu_item = DbusGtkMenuItem({'label': ''})
			menu_item.app_menu = True
			node_id = self._new_node_id()
			self.tree.create_node('', node_id, 'Root', data=menu_item)
			self.collect_entries(app_menu, [''], node_id)
			if not self.tree.children(node_id):
				self.tree.remove_node(node_id)

		if not self.tree.children('Root'):
			self.tree = Tree()

	def collect_entries(self, menus, labels, treelib_parent, link=(0, 0)):
		# link: the (group, menu) pair of a :section or :submenu
		section = (link[0], link[1])
		for menu in menus.get(section, []):
			# A section may carry a label as a heading; its items still belong here
			if ':section' in menu:
				self.collect_entries(menus, labels, treelib_parent, menu[':section'])

			elif 'label' in menu:
				if len(labels) == 0:
					self.top_level_menus.append(menu.get('label', None))

				menu_item = DbusGtkMenuItem(menu, labels)
				menu_item.section = section
				self._apply_action(menu_item)

				menu_path = labels + [menu_item.label]

				node_id = self._new_node_id()
				self.tree.create_node(menu_item.label, node_id, treelib_parent, data=menu_item)
				if menu_item.action:
					self.nodes_by_action.setdefault(menu_item.action, []).append(node_id)

				if ':submenu' in menu:
					self.collect_entries(menus, menu_path, node_id, menu[':submenu'])
				elif 'action' in menu:
					self.actions[menu_item.text] = menu_item.action
					if menu_item.target is not None:
						self.targets[menu_item.text] = menu_item.target

	def _new_node_id(self):
		self._node_seq += 1
		return 'n%d' % self._node_seq

	def _actions_path(self, prefix):
		# GTK exports org.gtk.Actions at the application and window paths,
		# not at the menubar path; unity-gtk-module serves unity.* there
		return {'app.': self.app_path, 'win.': self.win_path, 'unity.': self.menubar_path}.get(prefix)

	def _action_group(self, prefix):
		if prefix in self.action_groups:
			return self.action_groups[prefix]
		path = self._actions_path(prefix)
		if not path:
			self.action_groups[prefix] = None
			return None
		try:
			group = self._describe_all(path)
		except dbus.exceptions.DBusException:
			# A freshly started app may not answer yet. Not cached, so the
			# next lookup asks again.
			return None
		self.action_groups[prefix] = group
		return group

	def _describe_all(self, path):
		obj = self.session.get_object(self.bus_name, path)
		# a{s(bgav)}: name -> (enabled, parameter type, [state])
		described = dbus.Interface(obj, dbus_interface='org.gtk.Actions').DescribeAll(timeout=CLIENT_TIMEOUT)
		return {str(name): (desc[0], list(desc[2])) for name, desc in described.items()}

	def _apply_action(self, item):
		"""Set the item's enabled flag and check or radio state from its action."""
		prefix, dot, name = item.action.partition('.')
		group = self._action_group(prefix + dot)
		if group is None:
			return
		# gtkmenutrackeritem.c: an item is insensitive while its action is missing
		enabled, state = group.get(name, (False, []))
		item.enabled = bool(enabled)
		item.toggle_type = ''
		item.toggle_state = False
		item.set_toggle(state)

	def watch_actions(self):
		for prefix in ('app.', 'win.', 'unity.'):
			path = self._actions_path(prefix)
			if not path:
				continue
			obj = self.session.get_object(self.bus_name, path)
			iface = dbus.Interface(obj, dbus_interface='org.gtk.Actions')
			s = iface.connect_to_signal('Changed', functools.partial(self.on_gtk_actions_changed, prefix))
			self.signal_matcher.append(s)

	def on_gtk_actions_changed(self, prefix, removed, enabled_changed, state_changed, added):
		"""org.gtk.Actions.Changed from the path that exports the prefix.* actions.
		Action names in the signal carry no prefix."""
		group = self.action_groups.get(prefix)
		if group is not None:
			for name in removed:
				group.pop(name, None)
			for name, (enabled, _parameter_type, state) in added.items():
				group[name] = (enabled, list(state))
			for name, enabled in enabled_changed.items():
				group[name] = (enabled, group.get(name, (True, []))[1])
			for name, state in state_changed.items():
				group[name] = (group.get(name, (True, []))[0], [state])

		touched = False
		for name in {*removed, *enabled_changed, *state_changed, *added}:
			# One action can back several menu entries; update all of them
			for node_id in self.nodes_by_action.get(prefix + name, []):
				node = self.tree.get_node(node_id)
				if node is not None:
					self._apply_action(node.data)
					touched = True
		if touched:
			self._notify()

	def remove_actions_listener(self):
		for s in self.signal_matcher:
			s.remove()
		self.signal_matcher = []
		if self._rebuild_id:
			GLib.source_remove(self._rebuild_id)
			self._rebuild_id = 0
		for path, groups in self.groups.items():
			if not groups:
				continue
			try:
				self.menu_interfaces[path].End(dbus.Array(sorted(groups), signature='u'), ignore_reply=True)
			except dbus.exceptions.DBusException:
				# Gone already; the app drops our groups when our name vanishes
				pass
		self.groups = {}


class DbusAppMenu(object):

	def __init__(self, session, window, on_changed=None):
		self.actions   = {}
		self.accels    = {}
		self.tree      = Tree()
		self.session   = session
		self.window    = window
		self._update_timer = 0
		self.signal_matcher = []
		# Called after the tree changed without being asked for
		self.on_changed = on_changed
		self.interface = self.get_interface()
		self.top_level_menus = []
		self.results = None

	def activate(self, selection):
		action = self.actions[selection]
		try:
			self.interface.Event(action, 'clicked', 0, 0, timeout=CLIENT_TIMEOUT)
		except Exception:
			self.retry_activate(selection)

	def retry_activate(self, selection):
		# Electron apps change a lot their menus, we have to update to retry
		self.actions = {}
		self.accels = {}
		self.tree = Tree()
		try:
			results = self.interface.GetLayout(0, -1, dbus.Array(signature="s"), timeout=CLIENT_TIMEOUT)
			self.collect_entries(results[1], [])
			action = self.actions[selection]
			self.interface.Event(action, 'clicked', 0, 0, timeout=CLIENT_TIMEOUT)
		except dbus.exceptions.DBusException:
			# The app is gone
			self.clear()

	def clear(self):
		self.actions = {}
		self.accels = {}
		self.tree = Tree()
		self.top_level_menus = []

	def get_interface(self):
		bus_name = 'com.canonical.AppMenu.Registrar'
		bus_path = '/com/canonical/AppMenu/Registrar'

		try:
			obj        = self.session.get_object(bus_name, bus_path)
			interface  = dbus.Interface(obj, bus_name)
			name, path = interface.GetMenuForWindow(self.window.get_xid(), timeout=CLIENT_TIMEOUT)
			obj        = self.session.get_object(name, path)
			interface  = dbus.Interface(obj, 'com.canonical.dbusmenu')

			s = interface.connect_to_signal('ItemsPropertiesUpdated', self.on_actions_changed)
			self.signal_matcher.append(s)
			s = interface.connect_to_signal('LayoutUpdated', self.layout_updated)
			self.signal_matcher.append(s)

			return interface
		except dbus.exceptions.DBusException:
			return None

	def get_results(self):
		if self.interface:
			try:
				self.results = self.interface.GetLayout(0, -1, dbus.Array(signature="s"), timeout=CLIENT_TIMEOUT)
				self.collect_entries(self.results[1])
			except dbus.exceptions.DBusException:
				# The app exited or is rebuilding its menu
				self.clear()
				return

			if not len(self.tree.children(self.tree[self.tree.root].identifier)):
				self.tree = Tree()

	def collect_entries(self, item=None, labels=None, treelib_parent=None):
		if self.results is None:
			return
		if item is None:
			item = self.results[1]
		if labels is None:
			labels = []
		menu_item = DbusAppMenuItem(item, labels)
		menu_path = labels

		if 'children-display' in item[1]:
			item_id = item[0]
			try:
				self.interface.AboutToShow(item_id, timeout=CLIENT_TIMEOUT)
			except Exception:
				pass
			self.interface.Event(item_id, 'opened', 'not used', dbus.UInt32(time.time()), timeout=CLIENT_TIMEOUT)
			item = self.interface.GetLayout(item_id, -1, dbus.Array(signature="s"), timeout=CLIENT_TIMEOUT)[1]
			try:
				# Qt apps (e.g. DaVinci Resolve) stay in "menu open" state and
				# stop accepting keyboard input unless the menu is closed again
				self.interface.Event(item_id, 'closed', 'not used', dbus.UInt32(time.time()), timeout=CLIENT_TIMEOUT)
			except Exception:
				pass

		if bool(menu_item.label) and menu_item.label != 'Root' and menu_item.label != 'DBusMenuRoot':
			menu_path = labels + [menu_item.label]

		self.tree.create_node(menu_item.label, menu_item.action, treelib_parent, data=menu_item)
		if len(item[2]):
			if not self.top_level_menus:
				self.top_level_menus = list(map(lambda c: c[1].get('label', ''), item[2]))

			for child in item[2]:
				self.collect_entries(child, menu_path, menu_item.action)

		elif bool(menu_item.label) or menu_item.separator:
			self.actions[menu_item.text] = menu_item.action

	def on_actions_changed(self, updated, removed):
		touched = False
		for upd in updated:
			item = self.tree.get_node(int(upd[0]))
			if item is not None:
				item.data.update_props(upd[1])
				if 'children-display' in upd[1]:
					# Just update everything
					self.add_timer()
					break
				touched = True
		if touched:
			self._notify()

	def _notify(self):
		if self.on_changed is not None:
			self.on_changed()

	def layout_updated(self, revision, parent):
		self.add_timer()

	def add_timer(self):
		if self._update_timer == 0:
			self._update_timer = GLib.timeout_add(200, self._update)

	def _update(self):
		self._update_timer = 0
		self.actions = {}
		self.accels = {}
		self.tree = Tree()
		self.get_results()
		self._notify()
		return False

	def remove_actions_listener(self):
		for s in self.signal_matcher:
			s.remove()
		self.signal_matcher = []
		if self._update_timer != 0:
			GLib.source_remove(self._update_timer)


class MenuModel:
	# The menubars have to be reused so they are cleanup
	def __init__(self, session, window, on_changed=None):
		self.appmenu = None
		self.gtkmenu = None
		self._session = session
		self.window = window
		self._init_window(session, window, on_changed)

	def _init_window(self, session, window, on_changed):
		self.appmenu = DbusAppMenu(session, window, on_changed)
		self.gtkmenu = DbusGtkMenu(session, window, on_changed)

	def _update_menus(self):
		try:
			self.gtkmenu.get_results()
		except Exception:
			# A malformed Gtk menu must not cost us the dbusmenu (Qt,
			# appmenu-gtk-module) path, which is the fallback for this window
			traceback.print_exc()
			self.gtkmenu.tree = Tree()
			self.gtkmenu.actions = {}
			self.gtkmenu.top_level_menus = []

		if not len(self.gtkmenu.tree):
			try:
				self.appmenu.get_results()
			except Exception:
				traceback.print_exc()
				self.appmenu.clear()

	@property
	def prompt(self):
		return self.window.get_app_name()

	@property
	def actions(self):
		actions = self.gtkmenu.actions
		if not len(actions):
			actions = self.appmenu.actions

		self.handle_empty(actions)

		return actions.keys()

	@property
	def accel(self):
		accel = self.gtkmenu.accels
		if not len(accel):
			accel = self.appmenu.accels
		return accel

	@property
	def tree(self):
		tree = self.appmenu.tree
		if tree.root is None:
			tree = self.gtkmenu.tree
		return tree

	@property
	def top_level_menus(self):
		if len(self.gtkmenu.top_level_menus):
			return self.gtkmenu.top_level_menus
		else:
			return self.appmenu.top_level_menus

	def activate(self, selection):
		if selection in self.gtkmenu.actions:
			self.gtkmenu.activate(selection)

		elif selection in self.appmenu.actions:
			self.appmenu.activate(selection)

	def handle_empty(self, actions):
		if not len(actions):
			alert = 'No menu items available!'
			promt = ''
			try:
				promt = self.prompt
			except Exception:
				pass
			print('Gnome HUD: WARNING: (%s) %s' % (promt, alert))

	def __del__(self):
		if self.appmenu is not None:
			self.appmenu.remove_actions_listener()
		if self.gtkmenu is not None:
			self.gtkmenu.remove_actions_listener()
