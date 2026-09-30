#!/usr/bin/env python3
"""Drives one private session bus inside a distros test container.

Run by tools/distros/in-container.sh as the unprivileged test user, always
inside its own dbus-run-session, so every name it asks about lives on a bus
that only this container can see.

    session_driver.py daemon --out FILE --log FILE
        Starts the installed global-menu program the way the extension does
        (from PATH, no arguments) with XDG_SESSION_TYPE=wayland and no
        display, waits for it to own its two bus names, sends SIGTERM and
        checks that it exits and releases them.

    session_driver.py shell --out FILE --log FILE --cycles N
        Starts gnome-shell headless with one virtual monitor, waits for
        org.gnome.Shell, then enables and disables the extension through the
        org.gnome.Shell.Extensions interface N times. After each step it
        records the extension state, whether the daemon owns its name and how
        many daemon processes run, and the shell's resident memory. With
        --app, the GTK test app runs on the shell's display first, so each
        enable finds a focused window with a menubar to read. When the
        first enable leaves the extension OUT_OF_DATE it stops there; the
        caller runs it again with version validation off. With --baseline
        the extension is never enabled and each cycle only opens and closes
        the helper window: that run is the baseline for the log scan.

Both write one JSON object to --out. The shell's own output goes to --log;
in-container.sh scans it afterwards.
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import time

from gi.repository import Gio, GLib

UUID = 'global-menu@unmade.space'
DAEMON_NAME = 'space.unmade.GlobalMenu'
REGISTRAR = 'com.canonical.AppMenu.Registrar'
PROGRAM = 'global-menu'
APP_ID = 'space.unmade.GlobalMenuTestApp'
APP_TITLE = 'Global Menu test app'
INTROSPECT_NAME = 'org.freedesktop.impl.portal.desktop.gnome'

# js/misc/extensionUtils.js, identical in gnome-shell 48.8 and 51.0
STATES = {
	1: 'ACTIVE', 2: 'INACTIVE', 3: 'ERROR', 4: 'OUT_OF_DATE',
	5: 'DOWNLOADING', 6: 'INITIALIZED', 7: 'DEACTIVATING', 8: 'ACTIVATING',
	99: 'UNINSTALLED',
}
SETTLED = {'ACTIVE', 'INACTIVE', 'ERROR', 'OUT_OF_DATE', 'UNINSTALLED'}


def bus():
	return Gio.bus_get_sync(Gio.BusType.SESSION, None)


def call(conn, dest, path, iface, method, args=None, reply=None, timeout=10000):
	return conn.call_sync(dest, path, iface, method, args,
		GLib.VariantType.new(reply) if reply else None,
		Gio.DBusCallFlags.NO_AUTO_START, timeout, None)


def has_owner(conn, name):
	res = call(conn, 'org.freedesktop.DBus', '/org/freedesktop/DBus',
		'org.freedesktop.DBus', 'NameHasOwner', GLib.Variant('(s)', (name,)), '(b)')
	return res.unpack()[0]


def wait_for(predicate, timeout, step=0.1):
	"""Polls predicate until it returns a true value or timeout seconds pass."""
	end = time.monotonic() + timeout
	while True:
		value = predicate()
		if value or time.monotonic() >= end:
			return value
		time.sleep(step)


def daemon_pids():
	"""Processes of this user that run the daemon or one of its children."""
	pids = []
	me = os.getpid()
	for entry in os.listdir('/proc'):
		if not entry.isdigit() or int(entry) == me:
			continue
		try:
			with open('/proc/%s/cmdline' % entry, 'rb') as f:
				argv = f.read().split(b'\0')
		except OSError:
			continue
		text = b' '.join(argv)
		if b'session_driver' in text:
			continue
		if (argv and os.path.basename(argv[0]) == b'global-menu') \
				or b'/bin/global-menu' in text or b'from globalmenu.' in text:
			pids.append(int(entry))
	return sorted(pids)


def rss_kib(pid):
	try:
		with open('/proc/%d/status' % pid) as f:
			for line in f:
				if line.startswith('VmRSS:'):
					return int(line.split()[1])
	except OSError:
		pass
	return None


def run_daemon(args):
	result = {'program': None, 'owned': {}, 'exit': None, 'left_after_term': None}
	path = GLib.find_program_in_path(PROGRAM)
	result['program'] = path
	if not path:
		result['error'] = '%s is not on PATH' % PROGRAM
		return result
	env = dict(os.environ)
	env['XDG_SESSION_TYPE'] = 'wayland'
	for var in ('DISPLAY', 'WAYLAND_DISPLAY'):
		env.pop(var, None)
	conn = bus()
	with open(args.log, 'w') as log:
		proc = subprocess.Popen([path], stdout=log, stderr=subprocess.STDOUT, env=env)
		start = time.monotonic()
		for name in (DAEMON_NAME, REGISTRAR):
			ok = wait_for(lambda n=name: has_owner(conn, n), 15)
			result['owned'][name] = bool(ok)
		result['seconds_to_own'] = round(time.monotonic() - start, 2)
		result['alive_after_own'] = proc.poll() is None
		result['pids_while_running'] = len(daemon_pids())
		if proc.poll() is None:
			proc.send_signal(signal.SIGTERM)
		try:
			result['exit'] = proc.wait(timeout=10)
		except subprocess.TimeoutExpired:
			proc.kill()
			result['exit'] = 'killed after 10 s'
	result['released'] = {n: bool(wait_for(lambda n=n: not has_owner(conn, n), 5))
		for n in (DAEMON_NAME, REGISTRAR)}
	left = wait_for(lambda: not daemon_pids(), 5)
	result['left_after_term'] = 0 if left else len(daemon_pids())
	return result


def shell_flags():
	"""The flag set this gnome-shell accepts, read from its own --help."""
	help_text = subprocess.run(['gnome-shell', '--help'], capture_output=True,
		text=True, check=False).stdout
	flags = ['--headless']
	# 48 still has an X11 session and needs --wayland to pick Wayland; 49 and
	# later list it too, where it is the only choice.
	if '--wayland ' in help_text:
		flags.append('--wayland')
	flags += ['--virtual-monitor', '1280x800']
	return flags


class BusMonitor:
	"""dbus-monitor on the daemon's interface, to count what the extension
	and the daemon say to each other in each cycle."""

	def __init__(self, log_path):
		self.path = log_path
		self.log = open(log_path, 'w')
		self.proc = subprocess.Popen(['dbus-monitor', '--session',
			"interface='%s'" % DAEMON_NAME], stdout=self.log, stderr=subprocess.STDOUT)

	def counts(self):
		"""(WindowSwitched calls, SendMenuTree signals, of those non-empty)"""
		self.log.flush()
		calls = trees = full = 0
		tree_next = False
		with open(self.path, errors='replace') as f:
			for line in f:
				if tree_next:
					tree_next = False
					if line.strip().startswith('string') and line.strip() != 'string "[]"':
						full += 1
				if line.startswith('method call') and 'member=WindowSwitched' in line:
					calls += 1
				elif line.startswith('signal') and 'member=SendMenuTree' in line:
					trees += 1
					tree_next = True
		return calls, trees, full

	def stop(self):
		self.proc.terminate()
		try:
			self.proc.wait(timeout=5)
		except subprocess.TimeoutExpired:
			self.proc.kill()
		self.log.close()


class Shell:
	def __init__(self, log_path):
		self.flags = shell_flags()
		self.log_path = log_path
		self.log = open(log_path, 'w')
		self.proc = subprocess.Popen(['gnome-shell'] + self.flags,
			stdout=self.log, stderr=subprocess.STDOUT)
		self.conn = bus()

	def ext_call(self, method, args=None, reply=None):
		return call(self.conn, 'org.gnome.Shell', '/org/gnome/Shell',
			'org.gnome.Shell.Extensions', method, args, reply)

	def info(self):
		res = self.ext_call('GetExtensionInfo', GLib.Variant('(s)', (UUID,)), '(a{sv})')
		return res.unpack()[0]

	def state(self):
		info = self.info()
		if not info:
			return 'UNINSTALLED', ''
		num = int(info.get('state', 99))
		return STATES.get(num, str(num)), info.get('error', '')

	def overview_active(self):
		res = call(self.conn, 'org.gnome.Shell', '/org/gnome/Shell',
			'org.freedesktop.DBus.Properties', 'Get',
			GLib.Variant('(ss)', ('org.gnome.Shell', 'OverviewActive')), '(v)')
		return res.unpack()[0]

	def set_overview(self, visible):
		call(self.conn, 'org.gnome.Shell', '/org/gnome/Shell',
			'org.freedesktop.DBus.Properties', 'Set',
			GLib.Variant('(ssv)', ('org.gnome.Shell', 'OverviewActive',
				GLib.Variant('b', visible))))

	def windows(self):
		"""(title, app-id, has-focus) of every window Introspect lists."""
		try:
			res = call(self.conn, 'org.gnome.Shell', '/org/gnome/Shell/Introspect',
				'org.gnome.Shell.Introspect', 'GetWindows', None, '(a{ta{sv}})')
		except GLib.Error as e:
			return 'GetWindows failed: %s' % e.message
		return [(p.get('title'), p.get('app-id'), p.get('has-focus'))
			for p in res.unpack()[0].values()]

	def startup_complete(self):
		self.log.flush()
		try:
			with open(self.log_path, errors='replace') as f:
				return 'GNOME Shell started at' in f.read()
		except OSError:
			return False

	def focused_title(self):
		try:
			res = call(self.conn, 'org.gnome.Shell', '/org/gnome/Shell/Introspect',
				'org.gnome.Shell.Introspect', 'GetWindows', None, '(a{ta{sv}})')
		except GLib.Error:
			return None
		for props in res.unpack()[0].values():
			if props.get('has-focus'):
				return props.get('title')
		return None

	def ready(self):
		if self.proc.poll() is not None:
			return 'exited'
		try:
			if not has_owner(self.conn, 'org.gnome.Shell'):
				return None
			# The interface answers only once the extension system is up
			return 'ok' if self.info() is not None else None
		except GLib.Error:
			return None

	def stop(self):
		if self.proc.poll() is None:
			self.proc.send_signal(signal.SIGTERM)
			try:
				self.proc.wait(timeout=15)
			except subprocess.TimeoutExpired:
				self.proc.kill()
				self.proc.wait()
		self.log.close()
		return self.proc.returncode


def start_app(shell, args):
	"""Starts the GTK test app on the headless shell's Wayland display, so the
	extension has a focused window with an exported menubar to build from.

	The shell starts in the overview, and a window that maps there does not
	take focus, so the overview is closed first (the OverviewActive property
	of org.gnome.Shell is writable without unsafe mode). Focus is then read
	with org.gnome.Shell.Introspect.GetWindows, which answers only the
	desktop portal's names; this private bus has no portal of that name, so
	the driver takes it. in-container.sh masks the portal services (Exec of
	/bin/false in the user's dbus-1/services), so no real portal can get the
	name first.
	"""
	info = {}
	# The shell shows the overview itself once its startup animation ends, and
	# a window that maps under it gets no focus. "GNOME Shell started at" in
	# its log is the startup-complete signal.
	info['startup_complete'] = bool(wait_for(lambda: shell.startup_complete(), 60, step=0.5))
	time.sleep(1.5)
	shell.set_overview(False)
	info['overview_closed'] = bool(wait_for(lambda: not shell.overview_active(), 10))
	time.sleep(1.5)
	if shell.overview_active():
		shell.set_overview(False)
		info['overview_closed'] = bool(wait_for(lambda: not shell.overview_active(), 10))
	reply = shell.conn.call_sync('org.freedesktop.DBus', '/org/freedesktop/DBus',
		'org.freedesktop.DBus', 'RequestName', GLib.Variant('(su)', (INTROSPECT_NAME, 4)),
		GLib.VariantType.new('(u)'), Gio.DBusCallFlags.NONE, 5000, None)
	# 1 = primary owner. 3 = someone else owns it (a real portal that got
	# activated), and then every GetWindows is refused.
	info['portal_name_reply'] = reply.unpack()[0]
	env = dict(os.environ)
	env.update({'WAYLAND_DISPLAY': 'wayland-0', 'GDK_BACKEND': 'wayland',
		'GSK_RENDERER': 'cairo', 'GTK_A11Y': 'none', 'NO_AT_BRIDGE': '1'})
	env.pop('DISPLAY', None)
	log = open(args.app_log, 'w')
	proc = None
	info['launches'] = 0
	for _ in range(2):
		info['launches'] += 1
		proc = subprocess.Popen([sys.executable, args.app, '--gtk', '4'],
			stdout=log, stderr=subprocess.STDOUT, env=env)
		info['bus_name_owned'] = bool(wait_for(lambda: has_owner(shell.conn, APP_ID), 20))
		info['focused'] = bool(wait_for(lambda: shell.focused_title() == APP_TITLE, 10))
		info['alive'] = proc.poll() is None
		if not info['focused']:
			# mutter 49 sometimes maps the first window without giving it
			# focus (about one run in two on fedora:43), though every later
			# window gets it. Opening a second window and closing it hands
			# focus back; up to two tries per launch.
			info['focus_nudged'] = info.get('focus_nudged', 0)
			info['windows_seen'] = shell.windows()
			for _ in range(2):
				info['focus_nudged'] += 1
				helper = subprocess.Popen([sys.executable, '-c', HELPER], env=env,
					stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
				wait_for(lambda: shell.focused_title() == HELPER_TITLE, 10)
				helper.terminate()
				try:
					helper.wait(timeout=5)
				except subprocess.TimeoutExpired:
					helper.kill()
				info['focused'] = bool(wait_for(lambda: shell.focused_title() == APP_TITLE, 5))
				if info['focused']:
					break
		if info['focused']:
			break
		# A fresh launch often gets the focus the first one missed
		proc.terminate()
		try:
			proc.wait(timeout=5)
		except subprocess.TimeoutExpired:
			proc.kill()
		wait_for(lambda: not has_owner(shell.conn, APP_ID), 5)
	return proc, info


def settle(shell, want, timeout=15):
	"""Waits until the state is settled and, if possible, the wanted one."""
	last = [None, '']

	def check():
		last[:] = list(shell.state())
		# ERROR and OUT_OF_DATE do not change without another call
		return last[0] in (want, 'ERROR', 'OUT_OF_DATE')
	wait_for(check, timeout)
	if last[0] not in SETTLED:
		wait_for(lambda: shell.state()[0] in SETTLED, 5)
		last[:] = list(shell.state())
	return last[0], last[1]


def run_shell(args):
	result = {'flags': None, 'started': False, 'cycles': [], 'first_state': None}
	shell = Shell(args.log)
	result['flags'] = shell.flags
	started = wait_for(shell.ready, 90, step=0.5)
	if started != 'ok':
		result['error'] = 'gnome-shell exited during start' if started == 'exited' \
			else 'org.gnome.Shell.Extensions did not answer within 90 s'
		result['shell_exit'] = shell.stop()
		return result
	result['started'] = True
	app = None
	can_focus = False
	if args.app:
		app, result['app'] = start_app(shell, args)
		can_focus = bool(result['app'].get('focused'))
	# Let the startup animation and the first idle pass finish
	time.sleep(2)
	state, error = shell.state()
	result['discovered_state'] = state
	result['shell_pid'] = shell.proc.pid
	result['rss_kib_before'] = rss_kib(shell.proc.pid)
	result['log_offset_before_enable'] = os.path.getsize(args.log)
	monitor = BusMonitor(args.log + '.dbus') if args.monitor else None
	# dbus-monitor has to be listening before the first enable
	time.sleep(0.5)

	if args.baseline:
		# Same windows opening and closing, the extension never enabled
		for n in range(1, args.cycles + 1):
			entry = {'cycle': n}
			if can_focus and monitor:
				focus_round_trip(shell, entry, monitor)
			entry['rss_kib'] = rss_kib(shell.proc.pid)
			result['cycles'].append(entry)
	for n in range(1, 0 if args.baseline else args.cycles + 1):
		entry = {'cycle': n}
		if app:
			entry['app_focused'] = shell.focused_title() == APP_TITLE
		state = enable(shell, entry, monitor, app)
		if n == 1:
			result['first_state'] = state
		if state == 'OUT_OF_DATE':
			result['cycles'].append(entry)
			break
		if state == 'ACTIVE' and can_focus and monitor:
			focus_round_trip(shell, entry, monitor)
		t0 = time.monotonic()
		shell.ext_call('DisableExtension', GLib.Variant('(s)', (UUID,)), '(b)')
		state, error = settle(shell, 'INACTIVE')
		entry['disabled_state'] = state
		if error and 'error' not in entry:
			entry['error'] = error
		entry['disable_seconds'] = round(time.monotonic() - t0, 2)
		entry['daemon_released'] = bool(wait_for(lambda: not has_owner(shell.conn, DAEMON_NAME), 10))
		entry['daemon_pids_disabled'] = 0 if wait_for(lambda: not daemon_pids(), 5) \
			else len(daemon_pids())
		entry['rss_kib'] = rss_kib(shell.proc.pid)
		result['cycles'].append(entry)
		if shell.proc.poll() is not None:
			result['error'] = 'gnome-shell exited during cycle %d' % n
			break

	# A session ends with the extension enabled: log out, shut down. Enable it
	# once more and stop the shell under it, so the log shows what the
	# extension does while the shell tears its UI down.
	if result['first_state'] == 'ACTIVE' and shell.proc.poll() is None:
		final = {}
		enable(shell, final, monitor, app)
		result['shutdown_with_extension_enabled'] = final

	if monitor:
		monitor.stop()
	result['shell_alive_at_end'] = shell.proc.poll() is None
	# Log-out order: the apps quit, then the shell stops. The shell's
	# shutdown handler runs a main loop of its own, so the window going away
	# reaches whatever still listens for focus changes.
	if app:
		result['app']['alive_at_end'] = app.poll() is None
		app.terminate()
	result['shell_exit'] = shell.stop()
	if app:
		try:
			app.wait(timeout=5)
		except subprocess.TimeoutExpired:
			app.kill()
	result['daemon_pids_after_shell'] = 0 if wait_for(lambda: not daemon_pids(), 5) \
		else len(daemon_pids())
	return result


def enable(shell, entry, monitor, app):
	"""EnableExtension, then what followed on the bus within 5 s."""
	seen = monitor.counts() if monitor else (0, 0, 0)
	t0 = time.monotonic()
	shell.ext_call('EnableExtension', GLib.Variant('(s)', (UUID,)), '(b)')
	state, error = settle(shell, 'ACTIVE')
	entry['enabled_state'] = state
	if error:
		entry['error'] = error
	entry['enable_seconds'] = round(time.monotonic() - t0, 2)
	if state != 'ACTIVE':
		return state
	entry['daemon_owned'] = bool(wait_for(lambda: has_owner(shell.conn, DAEMON_NAME), 15))
	entry['daemon_pids_enabled'] = len(daemon_pids())
	if monitor and app:
		# With a window focused, enabling should report it to the daemon, as
		# a focus change does
		wait_for(lambda: monitor.counts()[0] > seen[0], 5)
		after = monitor.counts()
		entry['window_switched_on_enable'] = after[0] - seen[0]
		entry['menu_trees_non_empty_on_enable'] = after[2] - seen[2]
	return state


# A second, plain GTK 4 window. Mapping it takes focus from the test app;
# closing it gives focus back, and each step is a real focus-window change.
HELPER_TITLE = 'Global Menu focus helper'
HELPER = """
import gi, signal, sys
gi.require_version('Gtk', '4.0')
from gi.repository import GLib, Gtk
win = Gtk.Window(title=%r)
win.set_default_size(200, 100)
win.present()
loop = GLib.MainLoop()
GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, loop.quit)
loop.run()
""" % HELPER_TITLE


def focus_round_trip(shell, entry, monitor):
	"""Opens a second window and closes it again, so focus leaves the test
	window and comes back, and counts what the extension and the daemon
	send. Opening the overview is no use for this: focus-window does not
	change while it shows."""
	seen = monitor.counts()
	env = dict(os.environ)
	env.update({'WAYLAND_DISPLAY': 'wayland-0', 'GDK_BACKEND': 'wayland',
		'GSK_RENDERER': 'cairo', 'GTK_A11Y': 'none', 'NO_AT_BRIDGE': '1'})
	helper = subprocess.Popen([sys.executable, '-c', HELPER], env=env,
		stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
	entry['helper_focused'] = bool(wait_for(lambda: shell.focused_title() == HELPER_TITLE, 10))
	helper.terminate()
	try:
		helper.wait(timeout=5)
	except subprocess.TimeoutExpired:
		helper.kill()
	entry['app_refocused'] = bool(wait_for(lambda: shell.focused_title() == APP_TITLE, 5))
	wait_for(lambda: monitor.counts()[2] > seen[2], 5)
	after = monitor.counts()
	entry['window_switched_on_focus'] = after[0] - seen[0]
	entry['menu_trees_non_empty_on_focus'] = after[2] - seen[2]


def main():
	parser = argparse.ArgumentParser()
	parser.add_argument('mode', choices=['daemon', 'shell'])
	parser.add_argument('--out', required=True)
	parser.add_argument('--log', required=True)
	parser.add_argument('--cycles', type=int, default=20)
	parser.add_argument('--app', help='tests/apps/gtk_menubar_app.py, run during the cycles')
	parser.add_argument('--app-log')
	parser.add_argument('--baseline', action='store_true',
		help='never enable the extension; only open and close the helper window')
	parser.add_argument('--monitor', action='store_true',
		help='count WindowSwitched calls and SendMenuTree signals per cycle')
	args = parser.parse_args()
	try:
		result = run_daemon(args) if args.mode == 'daemon' else run_shell(args)
	except Exception as e:  # recorded, so the caller sees why
		result = {'error': '%s: %s' % (type(e).__name__, e)}
	with open(args.out, 'w') as f:
		json.dump(result, f, indent=1)
	return 0


if __name__ == '__main__':
	sys.exit(main())
