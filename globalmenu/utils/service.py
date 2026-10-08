import dbus
import dbus.service

from gi.repository import GLib

BUS_NAME = 'com.canonical.AppMenu.Registrar'
BUS_PATH = '/com/canonical/AppMenu/Registrar'


class AppMenuService(dbus.service.Object):
	"""
		Types:
			- u: int
			- a: array
			- y: byte
			- s: string
			- o: DBus object path
			- g: DBus type signature

		https://people.gnome.org/~ryanl/glib-docs/gvariant-format-strings.html
	"""
	def __init__(self):
		self.window_dict = dict()

		bus = dbus.SessionBus()
		bus.add_signal_receiver(self.name_owner_changed, 'NameOwnerChanged',
			'org.freedesktop.DBus', 'org.freedesktop.DBus', '/org/freedesktop/DBus')

		bus_name = dbus.service.BusName(BUS_NAME, bus=bus)
		dbus.service.Object.__init__(self, bus_name, BUS_PATH)

	def name_owner_changed(self, name, old_owner, new_owner):
		# A client that exits or crashes never calls UnregisterWindow
		if not new_owner:
			for window_id, (sender, _) in list(self.window_dict.items()):
				if sender == name:
					del self.window_dict[window_id]

	@dbus.service.method(BUS_NAME, in_signature='uo', sender_keyword='sender')
	def RegisterWindow(self, windowId, menuObjectPath, sender):
		self.window_dict[windowId] = [dbus.String(sender), dbus.ObjectPath(menuObjectPath)]

	@dbus.service.method(BUS_NAME, in_signature='u')
	def UnregisterWindow(self, windowId):
		if windowId in self.window_dict:
			del self.window_dict[windowId]

	@dbus.service.method(BUS_NAME, in_signature='u', out_signature='so')
	def GetMenuForWindow(self, windowId):
		if windowId in self.window_dict:
			return self.window_dict[windowId]

	@dbus.service.method(BUS_NAME, out_signature='a{u(so)}')
	def GetMenus(self):
		return self.window_dict

	@dbus.service.method(BUS_NAME)
	def Q(self):
		GLib.MainLoop().quit()


class MyService(dbus.service.Object):

	BUS_PATH = '/space/unmade/GlobalMenu'
	BUS_NAME = 'space.unmade.GlobalMenu'

	def __init__(self):
		self.bus_name = dbus.service.BusName(self.BUS_NAME, bus=dbus.SessionBus())
		dbus.service.Object.__init__(self, self.bus_name, self.BUS_PATH)

	@dbus.service.signal(BUS_NAME, signature='su')
	def MenuActivated(self, menu, x):
		pass

	@dbus.service.method(BUS_NAME, in_signature='su')
	def EchoSignal(self, menu, x):
		self.MenuActivated(menu, x)

	@dbus.service.method(BUS_NAME, in_signature='a{ss}')
	def WindowSwitched(self, window_data):
		self.WindowSwitchedSignal(window_data)

	@dbus.service.signal(BUS_NAME, signature='a{ss}')
	def WindowSwitchedSignal(self, window_data):
		pass

	@dbus.service.method(BUS_NAME, in_signature='as')
	def EchoSendTopLevelMenus(self, top_level_menus):
		self.SendTopLevelMenus(top_level_menus)

	# Full menu tree as JSON, rendered by the shell extension. It is
	# preceded by the request id of the WindowSwitched it describes, in a
	# signal of its own so that SendMenuTree keeps the type every extension
	# version declares.
	@dbus.service.method(BUS_NAME, in_signature='ss')
	def EchoSendMenuTree(self, tree_json, request):
		self.MenuTreeRequest(request)
		self.SendMenuTree(tree_json)

	@dbus.service.signal(BUS_NAME, signature='s')
	def MenuTreeRequest(self, request):
		pass

	@dbus.service.signal(BUS_NAME, signature='s')
	def SendMenuTree(self, tree_json):
		pass

	# The extension activates a menu item by its full path key
	@dbus.service.method(BUS_NAME, in_signature='s')
	def ActivateMenuItem(self, item_path):
		self.ActivateMenuItemSignal(item_path)

	@dbus.service.signal(BUS_NAME, signature='s')
	def ActivateMenuItemSignal(self, item_path):
		pass

	# The extension asks for a fresh tree (e.g. when a menu is opened)
	@dbus.service.method(BUS_NAME)
	def RequestMenuTree(self):
		self.RequestMenuTreeSignal()

	@dbus.service.signal(BUS_NAME)
	def RequestMenuTreeSignal(self):
		pass

	@dbus.service.signal(BUS_NAME, signature='as')
	def SendTopLevelMenus(self, top_level_menus):
		pass

	@dbus.service.method(BUS_NAME, in_signature='b')
	def EchoMenuOnOff(self, on):
		self.MenuOnOff(on)

	@dbus.service.signal(BUS_NAME, signature='b')
	def MenuOnOff(self, on):
		pass

	# Window action stuff (the menu on alt-space)
	@dbus.service.method(BUS_NAME)
	def RequestWindowActions(self):
		self.RequestWindowActionsSignal()

	@dbus.service.signal(BUS_NAME)
	def RequestWindowActionsSignal(self):
		pass

	@dbus.service.method(BUS_NAME, in_signature='as')
	def ListWindowActions(self, action_list):
		self.ListWindowActionsSignal(action_list)

	@dbus.service.signal(BUS_NAME, signature='as')
	def ListWindowActionsSignal(self, top_level_menus):
		pass

	@dbus.service.method(BUS_NAME, in_signature='s')
	def ActivateWindowAction(self, action):
		self.ActivateWindowActionSignal(action)

	@dbus.service.signal(BUS_NAME, signature='s')
	def ActivateWindowActionSignal(self, action):
		pass

	# Needed to activate the hud on wayland
	@dbus.service.method(BUS_NAME)
	def EmitHudActivated(self):
		self.HudActivated()

	@dbus.service.signal(BUS_NAME)
	def HudActivated(self):
		pass
