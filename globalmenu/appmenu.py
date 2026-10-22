#! /usr/bin/python3

import dbus

from gi.repository import GLib
from dbus.mainloop.glib import DBusGMainLoop

from globalmenu.utils.service import BUS_NAME
from globalmenu.utils.service import AppMenuService, MyService


def run_service(own_registrar=True):
	if own_registrar:
		AppMenuService()
	MyService()

	try:
		GLib.MainLoop().run()
	except KeyboardInterrupt:
		GLib.MainLoop().quit()


def main():
	DBusGMainLoop(set_as_default=True)
	session_bus = dbus.SessionBus()

	# another registrar may own the bus name
	# so only our menu service starts
	if not session_bus.name_has_owner(MyService.BUS_NAME):
		run_service(not session_bus.name_has_owner(BUS_NAME))


if __name__ == "__main__":
	main()
