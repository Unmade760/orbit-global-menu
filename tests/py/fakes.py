"""Stand-ins for dbus-python proxies, for the menu model tests.

dbus.Interface(obj, iface) forwards method calls to
obj.get_dbus_method(member, iface) and signal hookups to
obj.connect_to_signal(...), so a FakeSession whose get_object() returns
FakeObject gives the daemon a scripted bus without any bus at all. Handlers
are registered per (bus name, object path, interface, member) and every call
is recorded in FakeSession.calls.
"""

import time

import dbus
import dbus.exceptions
from gi.repository import GLib


def pump(seconds=0.0):
	"""Run the default main context, where the daemon's idle and timeout
	sources fire."""
	ctx = GLib.MainContext.default()
	end = time.monotonic() + seconds
	while True:
		while ctx.pending():
			ctx.iteration(False)
		if time.monotonic() >= end:
			return
		time.sleep(0.01)


class FakeMatch:
	def __init__(self, signal, handler):
		self.signal = signal
		self.handler = handler
		self.removed = False

	def remove(self):
		self.removed = True


class FakeObject:
	def __init__(self, session, bus_name, path):
		self.session = session
		self.bus_name = bus_name
		self.object_path = path

	def get_dbus_method(self, member, dbus_interface=None):
		key = (self.bus_name, self.object_path, dbus_interface, member)

		def call(*args, **kwargs):
			self.session.calls.append(key + (args,))
			handler = self.session.handlers.get(key)
			if handler is None:
				raise dbus.exceptions.DBusException(
					'no handler for %s %s %s.%s' % key,
					name='org.freedesktop.DBus.Error.UnknownMethod')
			return handler(*args)
		return call

	def __getattr__(self, member):
		# proxy.Method(...), which dbus-python allows without an interface
		if member.startswith('_'):
			raise AttributeError(member)
		return self.get_dbus_method(member)

	def connect_to_signal(self, signal_name, handler, dbus_interface=None, **keywords):
		match = FakeMatch(signal_name, handler)
		self.session.signals.append((self.bus_name, self.object_path, dbus_interface, match))
		return match


class FakeSession:
	def __init__(self):
		self.handlers = {}
		self.calls = []
		self.signals = []

	def get_object(self, bus_name, path):
		return FakeObject(self, bus_name, path)

	def on(self, bus_name, path, iface, member, handler):
		self.handlers[(bus_name, path, iface, member)] = handler

	def calls_to(self, member):
		return [c for c in self.calls if c[3] == member]

	def emit(self, bus_name, path, iface, member, *args):
		"""Deliver a signal to every handler still subscribed to it."""
		for name, obj_path, obj_iface, match in list(self.signals):
			if (name, obj_path, obj_iface, match.signal) == (bus_name, path, iface, member) and not match.removed:
				match.handler(*args)


class FakeWindow:
	def __init__(self, props=None, xid=0x4200001, app_name='Demo'):
		self.props = props or {}
		self.xid = xid
		self.app_name = app_name

	def get_utf8_prop(self, name):
		return self.props.get(name)

	def get_xid(self):
		return self.xid

	def get_app_name(self):
		return self.app_name


REGISTRAR = ('com.canonical.AppMenu.Registrar', '/com/canonical/AppMenu/Registrar')


def no_registrar(session):
	"""GetMenuForWindow fails, as it does for a window with no dbusmenu."""
	def fail(xid):
		raise dbus.exceptions.DBusException(
			'no menu for window', name='com.canonical.AppMenu.Registrar.WindowNotFound')
	session.on(*REGISTRAR, 'com.canonical.AppMenu.Registrar', 'GetMenuForWindow', fail)


# org.gtk.Menus


GTK_BUS = ':1.42'
GTK_PROPS = {
	'_GTK_UNIQUE_BUS_NAME': GTK_BUS,
	'_GTK_APPLICATION_OBJECT_PATH': '/org/example/Demo',
	'_GTK_WINDOW_OBJECT_PATH': '/org/example/Demo/window/1',
	'_GTK_MENUBAR_OBJECT_PATH': '/org/example/Demo/menus/menubar',
	'_GTK_APP_MENU_OBJECT_PATH': None,
}
GTK_APP_MENU_PROPS = dict(GTK_PROPS, _GTK_APP_MENU_OBJECT_PATH='/org/example/Demo/menus/appmenu')


def gtk_item(**attrs):
	"""One org.gtk.Menus item: a{sv} with label, action, target, accel,
	:section and :submenu (the last two as (uu) group and menu ids)."""
	out = {}
	for key, value in attrs.items():
		key = {'section': ':section', 'submenu': ':submenu'}.get(key, key)
		if isinstance(value, tuple):
			value = dbus.Struct((dbus.UInt32(value[0]), dbus.UInt32(value[1])), variant_level=1)
		elif isinstance(value, str):
			value = dbus.String(value, variant_level=1)
		out[dbus.String(key)] = value
	return dbus.Dictionary(out, signature='sv')


def gtk_describe(enabled, state=None):
	"""One action as org.gtk.Actions describes it: (enabled, parameter type, [state])."""
	states = []
	sig = ''
	if isinstance(state, bool):
		states = [dbus.Boolean(state, variant_level=1)]
	elif isinstance(state, str):
		states = [dbus.String(state, variant_level=1)]
		sig = 's'
	return dbus.Struct((dbus.Boolean(enabled), dbus.Signature(sig), dbus.Array(states, signature='v')))


def install_gtk_app(session, menus, actions, props=GTK_PROPS, app_menus=None):
	"""menus: {(group, menu): [gtk_item(...)]} for the menubar path, and
	app_menus the same for the app menu path (props must name one).
	actions: {'app.new': gtk_describe(...), 'win.grid': ...}."""
	bus = props['_GTK_UNIQUE_BUS_NAME']

	def serve_menus(path, menus):
		def start(groups):
			return dbus.Array([
				dbus.Struct((dbus.UInt32(g), dbus.UInt32(m), dbus.Array(items, signature='a{sv}')))
				for (g, m), items in sorted(menus.items()) if g in groups
			], signature='(uuaa{sv})')

		session.on(bus, path, 'org.gtk.Menus', 'Start', start)
		session.on(bus, path, 'org.gtk.Menus', 'End', lambda groups: None)

	serve_menus(props['_GTK_MENUBAR_OBJECT_PATH'], menus)
	if app_menus is not None:
		serve_menus(props['_GTK_APP_MENU_OBJECT_PATH'], app_menus)

	for prefix, prop in (('app.', '_GTK_APPLICATION_OBJECT_PATH'), ('win.', '_GTK_WINDOW_OBJECT_PATH')):
		path = props[prop]

		def describe_all(prefix=prefix):
			return dbus.Dictionary({name[len(prefix):]: desc for name, desc in actions.items()
				if name.startswith(prefix)}, signature='s(bgav)')
		session.on(bus, path, 'org.gtk.Actions', 'DescribeAll', describe_all)
		session.on(bus, path, 'org.gtk.Actions', 'Activate', lambda name, param, data: None)


# com.canonical.dbusmenu


DBUSMENU_BUS = ':1.77'
DBUSMENU_PATH = '/MenuBar/1'


def dm(item_id, props, children=()):
	"""One dbusmenu layout node: (id, a{sv} properties, av children)."""
	return (item_id, props, list(children))


def _to_dbus(node, variant_level=0):
	item_id, props, children = node
	return dbus.Struct((
		dbus.Int32(item_id),
		dbus.Dictionary(props, signature='sv'),
		dbus.Array([_to_dbus(c, 1) for c in children], signature='v'),
	), variant_level=variant_level)


def _find(node, item_id):
	if node[0] == item_id:
		return node
	for child in node[2]:
		hit = _find(child, item_id)
		if hit is not None:
			return hit
	return None


def install_dbusmenu_app(session, layout, window):
	"""layout: the dm(...) tree rooted at id 0. Registers the window with the
	registrar and serves GetLayout, AboutToShow and Event."""
	session.on(*REGISTRAR, 'com.canonical.AppMenu.Registrar', 'GetMenuForWindow',
		lambda xid: (dbus.String(DBUSMENU_BUS), dbus.ObjectPath(DBUSMENU_PATH)) if xid == window.get_xid() else None)

	def get_layout(parent, depth, props):
		return (dbus.UInt32(7), _to_dbus(_find(layout, int(parent))))

	iface = 'com.canonical.dbusmenu'
	session.on(DBUSMENU_BUS, DBUSMENU_PATH, iface, 'GetLayout', get_layout)
	session.on(DBUSMENU_BUS, DBUSMENU_PATH, iface, 'AboutToShow', lambda item_id: dbus.Boolean(False))
	session.on(DBUSMENU_BUS, DBUSMENU_PATH, iface, 'Event', lambda *args: None)
