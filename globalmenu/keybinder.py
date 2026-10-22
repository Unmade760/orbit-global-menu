#! /usr/bin/python3

import logging
import time

import dbus
from gi.repository import GLib

from dbus.mainloop.glib import DBusGMainLoop

from globalmenu.command import default_hud_menu, rofi_hud_menu, global_hud_menu
from globalmenu.utils.global_keybinder import Keybinder
from globalmenu.utils.menu import DbusMenu
from globalmenu.utils.service import MyService

# gnome grabs alt space and super space itself
# so use ctrl super space
HUD_KEY = '<Ctrl><Super>space'

SERVICE_WAIT_S = 10


def wait_for_service():
	bus = dbus.SessionBus()
	end = time.monotonic() + SERVICE_WAIT_S
	while not bus.name_has_owner(MyService.BUS_NAME) and time.monotonic() < end:
		time.sleep(0.05)


def run_keybinder(callback):
	DBusGMainLoop(set_as_default=True)
	# dbus python cannot build a proxy for a name nobody owns
	wait_for_service()
	dbus_menu = DbusMenu()

	if Keybinder is not None:
		if not Keybinder.bind(HUD_KEY, callback, dbus_menu):
			logging.warning('Could not bind %s, the HUD will not open from the keyboard', HUD_KEY)
	try:
		GLib.MainLoop().run()
	except KeyboardInterrupt:
		GLib.MainLoop().quit()

def main():
	run_keybinder(default_hud_menu)


def rofi():
	run_keybinder(rofi_hud_menu)


def global_menu():
	run_keybinder(global_hud_menu)


if __name__ == "__main__":
	main()
