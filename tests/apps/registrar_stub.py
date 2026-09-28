#!/usr/bin/env python3
"""A stand-alone com.canonical.AppMenu.Registrar, for tools/checks/daemon.sh.

It plays a registrar that is not the daemon's own, as on a desktop where
another program (vala-panel-appmenu's appmenu-registrar, a Plasma kded
module) already owns the name. Same four methods and signatures as
globalmenu/utils/service.py. Prints "ready" once it owns the name and
"registered <xid> <sender> <path>" for each RegisterWindow call.
"""

import sys

import dbus
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

NAME = 'com.canonical.AppMenu.Registrar'
PATH = '/com/canonical/AppMenu/Registrar'


class Registrar(dbus.service.Object):
	def __init__(self, bus_name):
		super().__init__(bus_name, PATH)
		self.windows = {}

	@dbus.service.method(NAME, in_signature='uo', sender_keyword='sender')
	def RegisterWindow(self, window_id, menu_path, sender=None):
		self.windows[int(window_id)] = (dbus.String(sender), dbus.ObjectPath(menu_path))
		print('registered', int(window_id), sender, menu_path, flush=True)

	@dbus.service.method(NAME, in_signature='u')
	def UnregisterWindow(self, window_id):
		self.windows.pop(int(window_id), None)

	@dbus.service.method(NAME, in_signature='u', out_signature='so')
	def GetMenuForWindow(self, window_id):
		if int(window_id) not in self.windows:
			raise dbus.exceptions.DBusException('no menu for window %d' % window_id,
				name='com.canonical.AppMenu.Registrar.Error.NoMenu')
		return self.windows[int(window_id)]

	@dbus.service.method(NAME, out_signature='a{u(so)}')
	def GetMenus(self):
		return dbus.Dictionary(self.windows, signature='u(so)')


def main():
	DBusGMainLoop(set_as_default=True)
	bus = dbus.SessionBus()
	name = dbus.service.BusName(NAME, bus=bus, do_not_queue=True)
	registrar = Registrar(name)
	print('ready', flush=True)
	try:
		GLib.MainLoop().run()
	except KeyboardInterrupt:
		pass
	del registrar
	return 0


if __name__ == '__main__':
	sys.exit(main())
