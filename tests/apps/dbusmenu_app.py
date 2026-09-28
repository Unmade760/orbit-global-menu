#!/usr/bin/env python3
"""An X11 window that exports its menu over com.canonical.dbusmenu, for
tools/checks/daemon.sh.

It does what a Qt app does on the xcb platform: libdbusmenu serves the
menu, and the window registers (X11 window id, object path) with whoever
owns com.canonical.AppMenu.Registrar, again each time that name gets a new
owner. Needs DISPLAY; the window itself is a plain GTK 3 X11 window.

Commands, one per line on stdin:
    toggle     flip "Show _Toolbar"
    add        append "Added _Later" to the View menu
    quit       exit
Printed on stdout, for the check to read: "ready xid=<n> bus=<name>
path=<path>", "registered <registrar owner>" and "clicked <label>" when an
item is activated.
"""

import os
import sys

import gi

gi.require_version('Dbusmenu', '0.4')
gi.require_version('Gtk', '3.0')
gi.require_version('GdkX11', '3.0')
from gi.repository import Dbusmenu, GdkX11, Gio, GLib, Gtk  # noqa: E402

REGISTRAR = 'com.canonical.AppMenu.Registrar'
REGISTRAR_PATH = '/com/canonical/AppMenu/Registrar'
MENU_PATH = '/space/unmade/GlobalMenuTest/MenuBar'


def say(*parts):
	print(*parts, flush=True)


def item(label, *, enabled=True, toggle=None, checked=False, shortcut=None):
	mi = Dbusmenu.Menuitem.new()
	mi.property_set(Dbusmenu.MENUITEM_PROP_LABEL, label)
	if not enabled:
		mi.property_set_bool(Dbusmenu.MENUITEM_PROP_ENABLED, False)
	if toggle is not None:
		mi.property_set(Dbusmenu.MENUITEM_PROP_TOGGLE_TYPE, toggle)
		mi.property_set_int(Dbusmenu.MENUITEM_PROP_TOGGLE_STATE, 1 if checked else 0)
	if shortcut is not None:
		mi.property_set_variant(Dbusmenu.MENUITEM_PROP_SHORTCUT, GLib.Variant('aas', [shortcut]))
	mi.connect(Dbusmenu.MENUITEM_SIGNAL_ITEM_ACTIVATED, lambda m, _t: say('clicked', label))
	return mi


def separator():
	mi = Dbusmenu.Menuitem.new()
	mi.property_set(Dbusmenu.MENUITEM_PROP_TYPE, Dbusmenu.CLIENT_TYPES_SEPARATOR)
	return mi


def submenu(label, children):
	mi = Dbusmenu.Menuitem.new()
	mi.property_set(Dbusmenu.MENUITEM_PROP_LABEL, label)
	mi.property_set(Dbusmenu.MENUITEM_PROP_CHILD_DISPLAY, Dbusmenu.MENUITEM_CHILD_DISPLAY_SUBMENU)
	for child in children:
		mi.child_append(child)
	return mi


def main():
	if not os.environ.get('DISPLAY'):
		say('DISPLAY is not set')
		return 2
	Gtk.init([])

	toolbar = item('Show _Toolbar', toggle=Dbusmenu.MENUITEM_TOGGLE_CHECK, checked=True, shortcut=['Control', 'Shift', 't'])
	view = submenu('_View', [
		toolbar,
		separator(),
		item('_Small', toggle=Dbusmenu.MENUITEM_TOGGLE_RADIO, checked=False),
		item('_Large', toggle=Dbusmenu.MENUITEM_TOGGLE_RADIO, checked=True),
	])
	root = Dbusmenu.Menuitem.new()
	root.child_append(submenu('_File', [
		item('_New', shortcut=['Control', 'n']),
		item('_Open', enabled=False, shortcut=['Control', 'o']),
		separator(),
		submenu('_Recent', [item('a.txt')]),
	]))
	root.child_append(view)

	server = Dbusmenu.Server.new(MENU_PATH)
	server.set_root(root)

	window = Gtk.Window(title='Global Menu dbusmenu test app')
	window.set_default_size(400, 300)
	window.show_all()
	xid = GdkX11.X11Window.get_xid(window.get_window())
	bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
	say('ready xid=%d bus=%s path=%s' % (xid, bus.get_unique_name(), MENU_PATH))

	def register(_conn, _name, owner):
		try:
			bus.call_sync(REGISTRAR, REGISTRAR_PATH, REGISTRAR, 'RegisterWindow',
				GLib.Variant('(uo)', (xid, MENU_PATH)), None, Gio.DBusCallFlags.NONE, 5000, None)
			say('registered', owner)
		except GLib.Error as e:
			say('register failed', e.message)

	Gio.bus_watch_name_on_connection(bus, REGISTRAR, Gio.BusNameWatcherFlags.NONE, register, None)

	loop = GLib.MainLoop()

	def on_stdin(channel, condition):
		if condition & (GLib.IOCondition.HUP | GLib.IOCondition.ERR):
			loop.quit()
			return False
		line = channel.readline().strip()
		if line == 'toggle':
			state = toolbar.property_get_int(Dbusmenu.MENUITEM_PROP_TOGGLE_STATE)
			toolbar.property_set_int(Dbusmenu.MENUITEM_PROP_TOGGLE_STATE, 0 if state else 1)
			say('toolbar', 0 if state else 1)
		elif line == 'add':
			view.child_append(item('Added _Later'))
			say('added item')
		elif line == 'quit' or line == '':
			loop.quit()
			return False
		return True

	channel = GLib.IOChannel.unix_new(sys.stdin.fileno())
	GLib.io_add_watch(channel, GLib.PRIORITY_DEFAULT, GLib.IOCondition.IN | GLib.IOCondition.HUP | GLib.IOCondition.ERR, on_stdin)
	loop.run()
	window.destroy()
	return 0


if __name__ == '__main__':
	sys.exit(main())
