import dbus
import json

from gi.repository import GLib

from globalmenu.utils.global_keybinder import GlobalKeybinder
from globalmenu.utils.window import WindowManager
from globalmenu.utils.service import MyService

from globalmenu.handlers.default import HudMenu
from globalmenu.handlers.global_menu import GlobalMenu

from globalmenu.menu_model.menu_model import MenuModel


class DbusMenu:

	def __init__(self):
		self.keyb = GlobalKeybinder.create(self.on_keybind_activated)
		self.app = None
		self.session = dbus.SessionBus()
		self.window = WindowManager.new_window()
		self.tries = 0
		self.retry_timer_id = 0
		self.collect_timer = 0
		self._menu_model = None
		self._push_timer = 0
		# The JSON last sent for the focused window
		self._sent_json = None

		self._init_window()
		self._listen_menu_activated()
		self._listen_hud_activated()
		self._listen_menu_tree_signals()
		WindowManager.add_listener(self.on_window_switched)

	def _init_window(self):
		self._menu_model = MenuModel(self.session, self.window, self._on_menu_changed)
		self._update()

	def _on_menu_changed(self):
		# One push for a burst of changes
		if not self._push_timer:
			self._push_timer = GLib.timeout_add(100, self._push_tree)

	def _push_tree(self):
		self._push_timer = 0
		self._send_tree(only_if_changed=True)
		return False

	def on_window_switched(self, window):
		self.reset_timeout()
		self.window = window
		self._init_window()

	def reset_timeout(self):
		if self.retry_timer_id:
			GLib.source_remove(self.retry_timer_id)
		self.tries = 0
		self.retry_timer_id = 0

		if self.collect_timer:
			GLib.source_remove(self.collect_timer)

		if self._push_timer:
			GLib.source_remove(self._push_timer)
			self._push_timer = 0

	def _listen_menu_activated(self):
		proxy = self.session.get_object(MyService.BUS_NAME, MyService.BUS_PATH)
		proxy.connect_to_signal("MenuActivated", self.on_menu_activated)

	def _listen_hud_activated(self):
		proxy = self.session.get_object(MyService.BUS_NAME, MyService.BUS_PATH)
		proxy.connect_to_signal("HudActivated", self.on_hud_activated)

	def _listen_menu_tree_signals(self):
		proxy = self.session.get_object(MyService.BUS_NAME, MyService.BUS_PATH)
		proxy.connect_to_signal("ActivateMenuItemSignal", self.on_activate_menu_item)
		proxy.connect_to_signal("RequestMenuTreeSignal", self.on_request_menu_tree)

	def on_activate_menu_item(self, item_path):
		self._menu_model.activate(str(item_path))
		# The activation likely changed some state (checkboxes, enabled
		# items); give the app a moment and re-send the tree
		GLib.timeout_add(300, self._send_tree_once)

	def on_request_menu_tree(self):
		self._send_tree()

	def _send_tree_once(self):
		self._send_tree()
		return False

	def on_menu_activated(self, menu: str, x: int):
		if menu == '__global_menu_move':
			self._move_menu(x)
			return

		if x != -1:
			self._start_app(menu, x)
		else:
			self._start_app(menu)

	def on_hud_activated(self):
		menu = HudMenu(self)
		menu.run()

	def on_keybind_activated(self, character: str):
		self.on_app_started()
		self._start_app(character)

	def _move_menu(self, x: int):
		if self.app is None:
			return

		self.app.move_window(x)

	def _start_app(self, menu_activated: str, offset=300):
		if self.app is None:
			self.app = GlobalMenu(self, menu_activated, offset)
			self.app.connect('shutdown', self.on_app_shutdown)
			self.app.run()

	def on_app_started(self):
		self._echo_onoff(True)

	def on_app_shutdown(self, app):
		self._echo_onoff(False)
		self.app = None

	def _echo_onoff(self, on: bool):
		self.proxy = dbus.SessionBus().get_object(MyService.BUS_NAME, MyService.BUS_PATH)
		self.proxy.EchoMenuOnOff(on)

	def _handle_shortcuts(self, top_level_menus):
		self.keyb.remove_all_keybindings()
		for label in top_level_menus:
			idx = label.find('_')
			if idx == -1:
				continue
			c = label[idx + 1]
			self.keyb.add_keybinding(c)

	def _retry_init(self):
		self.retry_timer_id = 0
		self._init_window()
		return False

	def _update_menus(self):
		self._menu_model._update_menus()

		max_tries = 2
		if self.tries < max_tries and self.tree.root is None:
			self.tries += 1
			self.retry_timer_id = GLib.timeout_add_seconds(2, self._retry_init)

	def _update(self):
		self._update_menus()
		self._handle_shortcuts(self._menu_model.top_level_menus)
		self._send_msg(self._menu_model.top_level_menus)
		self._send_tree()

	def _send_msg(self, top_level_menus):
		if len(top_level_menus) == 0:
			top_level_menus = dbus.Array(signature="s")
		proxy = self.session.get_object(MyService.BUS_NAME, MyService.BUS_PATH)
		proxy.EchoSendTopLevelMenus(top_level_menus)

	def _node_to_dict(self, tree, node):
		data = node.data
		d = {
			'label': str(getattr(data, 'label', '') or node.tag or ''),
			'key': str(getattr(data, 'text', '')),
			'enabled': bool(getattr(data, 'enabled', True)),
			'toggleType': str(getattr(data, 'toggle_type', '')),
			'toggleState': bool(getattr(data, 'toggle_state', False)),
		}
		# GTK's accel attribute as exported ('<Primary>n'), or the dbusmenu
		# shortcut in the same form ('<Control>n')
		accel = str(getattr(data, 'accel', '') or '')
		if accel:
			d['accel'] = accel
		if getattr(data, 'app_menu', False):
			d['appMenu'] = True
		children = self._children_list(tree, node)
		if len(children):
			d['children'] = children
		return d

	def _children_list(self, tree, node):
		# Mirrors handlers.global_menu.Menu.add_items: a section change
		# between Gtk items becomes a separator
		out = []
		current_section = None
		for c in tree.children(node.identifier):
			data = c.data
			if not getattr(data, 'visible', True):
				continue
			if getattr(data, 'separator', False):
				out.append({'separator': True})
				continue
			if getattr(data, 'app_menu', False):
				out.append(self._node_to_dict(tree, c))
				continue
			section = getattr(data, 'section', None)
			if current_section is not None and section != current_section:
				out.append({'separator': True})
			current_section = section

			d = self._node_to_dict(tree, c)
			if not d['label'] and 'children' not in d:
				continue
			out.append(d)
		return out

	def _send_tree(self, only_if_changed=False):
		tree = self._menu_model.tree
		if tree.root is None:
			payload = []
		else:
			payload = self._children_list(tree, tree[tree.root])
		tree_json = json.dumps(payload)
		if only_if_changed and tree_json == self._sent_json:
			return
		try:
			proxy = self.session.get_object(MyService.BUS_NAME, MyService.BUS_PATH)
			# The extension drops a tree whose request is not its latest
			proxy.EchoSendMenuTree(tree_json, self.window.get_utf8_prop('_REQUEST') or '')
		except dbus.exceptions.DBusException:
			# The service may not be up yet (startup race); the tree is
			# re-sent on every window switch anyway
			pass
		else:
			self._sent_json = tree_json

	@property
	def prompt(self):
		return self.window.get_app_name()

	@property
	def actions(self):
		return self._menu_model.actions

	def accel(self):
		return self._menu_model.accel

	@property
	def tree(self):
		return self._menu_model.tree

	def activate(self, selection):
		self._menu_model.activate(selection)
