#! /usr/bin/python3

from gi.repository import GLib

from dbus.mainloop.glib import DBusGMainLoop

from globalmenu.command import default_hud_menu, rofi_hud_menu, global_hud_menu
from globalmenu.utils.global_keybinder import Keybinder
from globalmenu.utils.menu import DbusMenu


def run_keybinder(callback):
	# for wayland
	DBusGMainLoop(set_as_default=True)
	dbus_menu = DbusMenu()

	if Keybinder is not None:
		Keybinder.bind('<Alt>space', callback, dbus_menu)
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
