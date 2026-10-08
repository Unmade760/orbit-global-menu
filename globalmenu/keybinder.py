#! /usr/bin/python3

import logging

from gi.repository import GLib

from dbus.mainloop.glib import DBusGMainLoop

from globalmenu.command import default_hud_menu, rofi_hud_menu, global_hud_menu
from globalmenu.utils.global_keybinder import Keybinder
from globalmenu.utils.menu import DbusMenu

# GNOME binds <Alt>space (activate-window-menu), <Super>space and
# <Shift><Super>space (switch-input-source) itself, so a grab on them fails
HUD_KEY = '<Ctrl><Super>space'


def run_keybinder(callback):
	# for wayland
	DBusGMainLoop(set_as_default=True)
	dbus_menu = DbusMenu()

	if Keybinder is not None:
		if not Keybinder.bind(HUD_KEY, callback, dbus_menu):
			logging.warning('Could not bind %s, the HUD will not open from the keyboard', HUD_KEY)
	# GLib.timeout_add_seconds(1, callback)
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
