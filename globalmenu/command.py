#! /usr/bin/python3

import atexit
import ctypes
import os
import signal
import subprocess
import sys

from globalmenu.handlers.default import HudMenu
from globalmenu.handlers.global_menu import GlobalMenu
from globalmenu.handlers.rofi import RofiMenu

# reader and service run in separate processes
# or blocking calls deadlock one main loop
_children = []


def _die_with_parent():
	# pdeathsig makes children die with a killed parent
	try:
		ctypes.CDLL('libc.so.6', use_errno=True).prctl(1, signal.SIGTERM)
	except Exception:
		pass


def run_command(module, function):
	proc = subprocess.Popen(
		[sys.executable, '-c', 'from globalmenu.%s import %s as run; run()' % (module, function)],
		preexec_fn=_die_with_parent,
	)
	_children.append(proc)
	return proc


def _terminate_children():
	for proc in _children:
		if proc.poll() is None:
			try:
				proc.terminate()
			except OSError:
				pass
	for proc in _children:
		try:
			proc.wait(timeout=3)
		except Exception:
			proc.kill()


def _on_signal(signum, frame):
	_terminate_children()
	sys.exit(0)


def run_hud_menu(menu):
	atexit.register(_terminate_children)
	signal.signal(signal.SIGTERM, _on_signal)
	signal.signal(signal.SIGINT, _on_signal)

	run_command('appmenu', 'main')
	run_command('keybinder', menu)

	try:
		os.wait()
	except (ChildProcessError, InterruptedError):
		pass
	_terminate_children()


def global_hud_menu(accel, dbus_menu):
	menu = GlobalMenu(dbus_menu)
	menu.run()

def default_hud_menu(accel, dbus_menu):
	menu = HudMenu(dbus_menu)
	menu.run()

def rofi_hud_menu(*args):
	menu = RofiMenu()
	menu.run()

def main():
	run_hud_menu('main')

def global_menu():
	run_hud_menu('global_menu')

def rofi():
	run_hud_menu('rofi')


if __name__ == "__main__":
	main()
