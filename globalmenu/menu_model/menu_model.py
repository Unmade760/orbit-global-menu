#!/usr/bin/python3

import dbus
import traceback
import time

from gi.repository import GLib

from ..treelib import Tree

from globalmenu.menu_model.menu_item import DbusGtkMenuItem, DbusAppMenuItem


class DbusGtkMenu(object):

	def __init__(self, session, window):
		self.results      = {}
		self.actions      = {}
		self.targets      = {}
		self.accels       = {}
		self.tree         = Tree()
		# Gtk action names are not unique node ids: submenu entries carry no
		# action at all, and the same action can appear in several menus
		self.nodes_by_action = {}
		self._node_seq    = 0
		self._update_timer = 0
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
		interface.Activate(name.replace(prefix, ''), parameter, dbus.Dictionary({}, signature='sv'))

	def get_results(self):
		paths = [self.appmenu_path, self.menubar_path]

		for path in filter(None, paths):
			obj       = self.session.get_object(self.bus_name, path)
			interface = dbus.Interface(obj, dbus_interface='org.gtk.Menus')
			try:
				results   = interface.Start([x for x in range(1024)])
				interface.End([x for x in range(1024)])
			except Exception:
				continue

			s = interface.connect_to_signal('Changed', self.on_actions_changed)
			self.signal_matcher.append(s)
			self.connect_to_actions_iface(obj)

			for menu in results:
				self.results[(menu[0], menu[1])] = menu[2]

		self.tree.create_node('Root', 'Root')
		self.nodes_by_action = {}
		self._node_seq = 0
		self.collect_entries(treelib_parent='Root')
		if not len(self.tree.children(self.tree[self.tree.root].identifier)):
			self.tree = Tree()

	def collect_entries(self, menu=(0, 0), labels=[], treelib_parent=None):
		section = (menu[0], menu[1])
		for menu in self.results.get(section, []):
			if 'label' in menu:
				if len(labels) == 0:
					self.top_level_menus.append(menu.get('label', None))

				menu_item = DbusGtkMenuItem(menu, labels)
				menu_item.section = section
				description = self.describe(menu_item.action)
				if description is not None:
					menu_item.enabled = description[0]
					menu_item.set_toggle(description[1])

				menu_path = labels + [menu_item.label]

				node_id = self._new_node_id()
				self.tree.create_node(menu_item.label, node_id, treelib_parent, data=menu_item)
				if menu_item.action:
					self.nodes_by_action.setdefault(menu_item.action, []).append(node_id)

				if ':submenu' in menu:
					self.collect_entries(menu[':submenu'], menu_path, node_id)
				elif 'action' in menu:
					self.actions[menu_item.text] = menu_item.action
					if menu_item.target is not None:
						self.targets[menu_item.text] = menu_item.target

			elif ':section' in menu:
				self.collect_entries(menu[':section'], labels, treelib_parent)

	def _new_node_id(self):
		self._node_seq += 1
		return 'n%d' % self._node_seq

	def describe(self, action):
		"""
		Describe return this:
		dbus.Struct((
		 dbus.Boolean(True), # enabled
		 dbus.Signature(''),
		 dbus.Array([ # This is empty in a not checked item
		  dbus.Boolean(True, variant_level=1)], # Checked or not
		  signature=dbus.Signature('v'))),
		 signature=None)
		"""
		if action.startswith('unity'):
			path = self.menubar_path
		elif action.startswith('win'):
			path = self.win_path
		elif action.startswith('app'):
			path = self.app_path
		else:
			return None

		dot = action.find('.')
		action = action[dot+1:]
		obj = self.session.get_object(self.bus_name, path)
		interface = dbus.Interface(obj, dbus_interface='org.gtk.Actions')

		try:
			description = interface.Describe(action)
		except Exception as e:
			return None
		enabled = description[0]
		checked = description[2]
		return enabled, checked

	def connect_to_actions_iface(self, obj):
		try:
			iface = dbus.Interface(obj, dbus_interface='org.gtk.Actions')
			s = iface.connect_to_signal('Changed', self.on_gtk_actions_changed)
			self.signal_matcher.append(s)
		except Exception as e:
			pass

	def on_actions_changed(self, *args):
		print(f'on_actions_changed {args=}')

	def on_gtk_actions_changed(self, removed, enabled_changed, state_changed, new_actions):
		"""
		The name of the actions doesn't have the unity. app. or win. preprended
		"""
		prefixes = ['unity.', 'win.', 'app.']
		for action_name in [*enabled_changed, *state_changed]:
			node_ids = []
			for prefix in prefixes:
				node_ids += self.nodes_by_action.get(prefix + action_name, [])
			items = filter(None, (self.tree.get_node(i) for i in node_ids))

			found = False
			# One action can back several menu entries; update all of them
			for item in items:
				found = True
				if action_name in enabled_changed:
					item.data.enabled = enabled_changed[action_name]
				else:
					item.data.set_toggle([state_changed[action_name]])

			if not found:
				print('Item does not exists:', action_name)

	def remove_actions_listener(self):
		for s in self.signal_matcher:
			s.remove()
		self.signal_matcher = []


class DbusAppMenu(object):

	def __init__(self, session, window):
		self.actions   = {}
		self.accels    = {}
		self.tree      = Tree()
		self.session   = session
		self.window    = window
		self._update_timer = 0
		self.signal_matcher = []
		self.interface = self.get_interface()
		self.top_level_menus = []
		self.results = None

	def activate(self, selection):
		action = self.actions[selection]
		try:
			self.interface.Event(action, 'clicked', 0, 0)
		except Exception as e:
			self.retry_activate(selection)

	def retry_activate(self, selection):
		# Electron apps change a lot their menus, we have to update to retry
		self.actions = {}
		self.accels = {}
		self.tree = Tree()
		results = self.interface.GetLayout(0, -1, dbus.Array(signature="s"))
		self.collect_entries(results[1], [])
		action = self.actions[selection]
		self.interface.Event(action, 'clicked', 0, 0)

	def get_interface(self):
		bus_name = 'com.canonical.AppMenu.Registrar'
		bus_path = '/com/canonical/AppMenu/Registrar'

		try:
			obj        = self.session.get_object(bus_name, bus_path)
			interface  = dbus.Interface(obj, bus_name)
			name, path = interface.GetMenuForWindow(self.window.get_xid())
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
			self.results = self.interface.GetLayout(0, -1, dbus.Array(signature="s"))
			self.collect_entries(self.results[1])

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
				self.interface.AboutToShow(item_id)
			except Exception:
				pass
			self.interface.Event(item_id, 'opened', 'not used', dbus.UInt32(time.time()))
			item = self.interface.GetLayout(item_id, -1, dbus.Array(signature="s"))[1]
			try:
				# Qt apps (e.g. DaVinci Resolve) stay in "menu open" state and
				# stop accepting keyboard input unless the menu is closed again
				self.interface.Event(item_id, 'closed', 'not used', dbus.UInt32(time.time()))
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
		for upd in updated:
			item = self.tree.get_node(int(upd[0]))
			if item is not None:
				item.data.update_props(upd[1])
				if 'children-display' in upd[1]:
					# Just update everything
					self.add_timer()
					break


	def layout_updated(self, revision, parent):
		self.add_timer()

	def add_timer(self):
		if self._update_timer == 0:
			self._update_timer = GLib.timeout_add(200, self._update)

	def _update(self):
		self.actions = {}
		self.accels = {}
		self.tree = Tree()
		self.get_results()
		self._update_timer = 0
		return False

	def remove_actions_listener(self):
		for s in self.signal_matcher:
			s.remove()
		self.signal_matcher = []
		if self._update_timer != 0:
			GLib.source_remove(self._update_timer)


class MenuModel:
	# The menubars have to be reused so they are cleanup
	def __init__(self, session, window):
		self.appmenu = None
		self.gtkmenu = None
		self._session = session
		self.window = window
		self._init_window(session, window)

	def _init_window(self, session, window):
		self.appmenu = DbusAppMenu(session, window)
		self.gtkmenu = DbusGtkMenu(session, window)

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
			self.appmenu.get_results()

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
			except Exception as e:
				pass
			print('Gnome HUD: WARNING: (%s) %s' % (promt, alert))

	def __del__(self):
		if self.appmenu is not None:
			self.appmenu.remove_actions_listener()
		if self.gtkmenu is not None:
			self.gtkmenu.remove_actions_listener()
