#!/usr/bin/env python3
"""Drives the daemon headless and checks the menu trees it sends.

Run by tools/checks/daemon.sh inside a private dbus-run-session. It starts:
    mutter --headless --wayland with one virtual monitor (Xwayland on demand)
    the daemon from the working tree (globalmenu.run:main, the entry point of
    the global-menu console script)
    tests/apps/gtk_menubar_app.py as GTK 4 on Wayland, then GTK 3 on X11
    tests/apps/dbusmenu_app.py, an X11 window serving com.canonical.dbusmenu
    tests/apps/registrar_stub.py for the last scenario
and plays the extension's side of the protocol: WindowSwitched with the
window data extension.js sends, then SendMenuTree, ActivateMenuItem and
RequestMenuTree.

Prints "ok <name>", "not ok <name>: <why>" or "skip <name>: <why>" per
assertion, then "RESULT <n> passed, <n> failed, <n> skipped". Exit status 1
when anything failed. Every process it starts is stopped before it exits;
tools/checks/daemon.sh also kills the whole process group as a backstop.
"""

import argparse
import atexit
import glob
import json
import os
import re
import signal
import subprocess
import sys
import time

from gi.repository import Gio, GLib

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
APPS = os.path.join(REPO, 'tests', 'apps')
SEP = '  »  '

DAEMON_NAME = 'space.unmade.GlobalMenu'
DAEMON_PATH = '/space/unmade/GlobalMenu'
REGISTRAR = 'com.canonical.AppMenu.Registrar'
REGISTRAR_PATH = '/com/canonical/AppMenu/Registrar'
APP_ID = 'space.unmade.GlobalMenuTestApp'
APP_PATH = '/space/unmade/GlobalMenuTestApp'
APP_TITLE = 'Global Menu test app'

# The trees the daemon should send, as (label, children) pairs; '---' is a
# separator. Taken from the menus in tests/apps/*.py.
GTK_SHAPE = [
	('_File', ['_New', '_Open', '---', ('_Export', ['As _PDF', 'As P_NG']), '---', '_Quit']),
	('_View', ['Show _Sidebar', '---', '_Small', '_Large', '---', '_Unavailable']),
]
GTK_ACCELS = {
	('_File', '_New'): '<Primary>n',
	('_File', '_Open'): '<Primary>o',
	('_File', '_Export', 'As _PDF'): '<Primary><Shift>e',
	('_File', '_Export', 'As P_NG'): '',
	('_File', '_Quit'): '<Primary>q',
	('_View', 'Show _Sidebar'): 'F9',
	('_View', '_Small'): '<Primary>1',
	('_View', '_Large'): '<Primary>2',
	('_View', '_Unavailable'): '<Primary>u',
}
DBUSMENU_SHAPE = [
	('_File', ['_New', '_Open', '---', ('_Recent', ['a.txt'])]),
	('_View', ['Show _Toolbar', '---', '_Small', '_Large']),
]
DBUSMENU_ACCELS = {
	('_File', '_New'): '<Control>n',
	('_File', '_Open'): '<Control>o',
	('_File', '_Recent', 'a.txt'): '',
	('_View', 'Show _Toolbar'): '<Control><Shift>t',
	('_View', '_Small'): '',
	('_View', '_Large'): '',
}

# ---------------------------------------------------------------- results

results = {'ok': 0, 'not ok': 0, 'skip': 0}


def record(status, name, detail=''):
	results[status] += 1
	line = '%s %s' % (status, name)
	if detail:
		line += ': ' + detail
	print(line, flush=True)
	return status == 'ok'


def check(name, passed, detail=''):
	return record('ok' if passed else 'not ok', name, '' if passed else detail)


def info(text):
	print('# ' + text, flush=True)

# ---------------------------------------------------------------- main loop


def pump(seconds=0.0):
	ctx = GLib.MainContext.default()
	end = time.monotonic() + seconds
	while True:
		while ctx.pending():
			ctx.iteration(False)
		if time.monotonic() >= end:
			return
		time.sleep(0.02)


def wait_until(predicate, timeout):
	end = time.monotonic() + timeout
	while True:
		pump()
		value = predicate()
		if value:
			return value
		if time.monotonic() >= end:
			return value
		time.sleep(0.02)

# ---------------------------------------------------------------- processes


class Proc:
	def __init__(self, name, popen, log):
		self.name = name
		self.popen = popen
		self.log = log

	def text(self):
		try:
			with open(self.log, encoding='utf-8', errors='replace') as f:
				return f.read()
		except OSError:
			return ''

	def wait_line(self, pattern, timeout=10):
		regex = re.compile(pattern, re.M)
		return wait_until(lambda: regex.search(self.text()), timeout)

	def alive(self):
		return self.popen.poll() is None

	def send(self, line):
		try:
			self.popen.stdin.write(line + '\n')
			self.popen.stdin.flush()
		except (OSError, AttributeError, ValueError):
			pass

	def children(self):
		"""Pids of this process's children, read from /proc."""
		pids = []
		for task in glob.glob('/proc/%d/task/*/children' % self.popen.pid):
			try:
				with open(task) as f:
					pids += [int(p) for p in f.read().split()]
			except OSError:
				pass
		return pids


class Procs:
	def __init__(self, logdir, env):
		self.logdir = logdir
		self.env = env
		self.running = []
		self.counts = {}

	def start(self, name, argv, extra_env=None, stdin=False, cwd=None):
		self.counts[name] = self.counts.get(name, 0) + 1
		log = os.path.join(self.logdir, '%s-%d.log' % (name, self.counts[name]))
		env = dict(self.env)
		env.update(extra_env or {})
		out = open(log, 'w')
		popen = subprocess.Popen(argv, env=env, cwd=cwd or REPO, stdout=out, stderr=subprocess.STDOUT,
			stdin=subprocess.PIPE if stdin else subprocess.DEVNULL, text=True)
		out.close()
		proc = Proc(name, popen, log)
		self.running.append(proc)
		info('started %s (pid %d), log %s' % (name, popen.pid, log))
		return proc

	def stop(self, proc, timeout=3):
		if proc not in self.running:
			return proc.popen.returncode
		self.running.remove(proc)
		if proc.alive():
			if proc.popen.stdin:
				proc.send('quit')
			try:
				proc.popen.send_signal(signal.SIGTERM)
			except ProcessLookupError:
				pass
			try:
				proc.popen.wait(timeout)
			except subprocess.TimeoutExpired:
				proc.popen.kill()
				proc.popen.wait()
		if proc.popen.stdin:
			try:
				proc.popen.stdin.close()
			except OSError:
				pass
		return proc.popen.returncode

	def stop_all(self):
		for proc in reversed(list(self.running)):
			self.stop(proc)


def pid_alive(pid):
	try:
		os.kill(pid, 0)
	except ProcessLookupError:
		return False
	except PermissionError:
		return True
	# A zombie still answers kill(0); it has exited all the same
	try:
		with open('/proc/%d/stat' % pid) as f:
			return f.read().split(')')[-1].split()[0] != 'Z'
	except OSError:
		return False

# ---------------------------------------------------------------- D-Bus


class Bus:
	def __init__(self):
		self.conn = Gio.bus_get_sync(Gio.BusType.SESSION, None)
		self.trees = []
		self.conn.signal_subscribe(None, DAEMON_NAME, 'SendMenuTree', DAEMON_PATH, None,
			Gio.DBusSignalFlags.NONE, self._on_tree)

	def _on_tree(self, _conn, _sender, _path, _iface, _signal, params, *_args):
		self.trees.append(params.unpack()[0])

	def call(self, name, path, iface, method, args=None, timeout=5000):
		reply = self.conn.call_sync(name, path, iface, method, args, None,
			Gio.DBusCallFlags.NO_AUTO_START, timeout, None)
		return reply.unpack() if reply is not None else ()

	def has_owner(self, name):
		return self.call('org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus',
			'NameHasOwner', GLib.Variant('(s)', (name,)))[0]

	def owner(self, name):
		try:
			return self.call('org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus',
				'GetNameOwner', GLib.Variant('(s)', (name,)))[0]
		except GLib.Error:
			return None

	def child_nodes(self, name, path):
		xml = self.call(name, path, 'org.freedesktop.DBus.Introspectable', 'Introspect')[0]
		return [n.path for n in Gio.DBusNodeInfo.new_for_xml(xml).nodes]

	def interfaces(self, name, path):
		try:
			xml = self.call(name, path, 'org.freedesktop.DBus.Introspectable', 'Introspect')[0]
		except GLib.Error as e:
			return 'error: %s' % e.message
		return [i.name for i in Gio.DBusNodeInfo.new_for_xml(xml).interfaces
			if not i.name.startswith('org.freedesktop.DBus.')]

	def daemon(self, method, args=None):
		return self.call(DAEMON_NAME, DAEMON_PATH, DAEMON_NAME, method, args)

	def window_switched(self, data):
		self.daemon('WindowSwitched', GLib.Variant('(a{ss})', (data,)))

	def gtk_actions(self, method, args):
		return self.call(APP_ID, APP_PATH, 'org.gtk.Actions', method, args)

	def next_tree(self, since, timeout):
		"""The first tree sent after index `since`, parsed, or None."""
		found = wait_until(lambda: len(self.trees) > since, timeout)
		if not found:
			return None
		return json.loads(self.trees[since])

	def tree_matching(self, since, predicate, timeout):
		"""The first tree after index `since` that satisfies predicate."""
		def look():
			for raw in self.trees[since:]:
				tree = json.loads(raw)
				if predicate(tree):
					return tree
			return None
		return wait_until(look, timeout)

# ---------------------------------------------------------------- trees


def shape(nodes):
	out = []
	for node in nodes:
		if node.get('separator'):
			out.append('---')
		elif 'children' in node:
			out.append((node.get('label'), shape(node['children'])))
		else:
			out.append(node.get('label'))
	return out


def find(nodes, *labels):
	for node in nodes or []:
		if node.get('label') == labels[0]:
			if len(labels) == 1:
				return node
			return find(node.get('children'), *labels[1:])
	return None


def walk(nodes, path=()):
	for node in nodes or []:
		if node.get('separator'):
			continue
		here = path + (node.get('label'),)
		yield here, node
		yield from walk(node.get('children'), here)


def describe_node(node):
	if node is None:
		return 'missing'
	keep = {k: node[k] for k in ('toggleType', 'toggleState', 'enabled') if k in node}
	return json.dumps(keep, sort_keys=True)


def assert_tree(prefix, tree, want_shape, accels, toggles, disabled, submenu):
	"""toggles: {path: (toggleType, toggleState)}; disabled: set of paths."""
	got_shape = shape(tree)
	check('%s: labels, order, separators and submenus' % prefix, got_shape == want_shape,
		'got %s, want %s' % (json.dumps(got_shape), json.dumps(want_shape)))

	sub = find(tree, *submenu)
	sub_children = [c.get('label') for c in (sub or {}).get('children', []) if not c.get('separator')]
	want_children = [c for entry in want_shape if entry[0] == submenu[0] for c in entry[1]
		if isinstance(c, tuple) and c[0] == submenu[1]][0][1]
	check('%s: nested submenu %s' % (prefix, SEP.join(submenu)), sub_children == want_children,
		'got %s, want %s' % (sub_children, want_children))

	bad_keys = ['%s has key %r' % ('/'.join(p), n.get('key')) for p, n in walk(tree)
		if n.get('key') != SEP.join(p)]
	check('%s: every item key is its label path' % prefix, not bad_keys, '; '.join(bad_keys[:3]))

	bad = []
	for path, (ttype, tstate) in toggles.items():
		node = find(tree, *path)
		if node is None or node.get('toggleType') != ttype or node.get('toggleState') is not tstate:
			bad.append('%s is %s, want toggleType %r toggleState %s' % (path[-1], describe_node(node), ttype, tstate))
	checks = {p: v for p, v in toggles.items() if v[0] == 'checkmark'}
	radios = {p: v for p, v in toggles.items() if v[0] == 'radio'}
	check_bad = [b for b in bad if any(b.startswith(p[-1] + ' ') for p in checks)]
	radio_bad = [b for b in bad if any(b.startswith(p[-1] + ' ') for p in radios)]
	check('%s: check item type and state' % prefix, not check_bad, '; '.join(check_bad))
	check('%s: radio group marks only the chosen item' % prefix, not radio_bad, '; '.join(radio_bad))

	wrong_enabled = ['%s enabled=%s' % ('/'.join(p), n.get('enabled')) for p, n in walk(tree)
		if n.get('enabled') is not (p not in disabled)]
	check('%s: disabled item greyed, all others enabled' % prefix, not wrong_enabled, '; '.join(wrong_enabled))

	if not any('accel' in n for _p, n in walk(tree)):
		record('skip', '%s: accelerators' % prefix,
			'no node carries an "accel" key (feature F2 not built; tests/py skips the same)')
	else:
		wrong = []
		for path, want in accels.items():
			node = find(tree, *path)
			got = (node or {}).get('accel', '')
			if got != want:
				wrong.append('%s accel %r, want %r' % ('/'.join(path), got, want))
		check('%s: accelerators' % prefix, not wrong, '; '.join(wrong))


def toggle_state(tree, *path):
	node = find(tree, *path)
	return None if node is None else node.get('toggleState')

# ---------------------------------------------------------------- scenarios


class Check:
	def __init__(self, args):
		self.args = args
		self.logdir = args.logdir
		os.makedirs(self.logdir, exist_ok=True)
		self.runtime = os.environ['XDG_RUNTIME_DIR']
		self.env = dict(os.environ)
		for var in ('DISPLAY', 'WAYLAND_DISPLAY', 'XAUTHORITY'):
			self.env.pop(var, None)
		self.procs = Procs(self.logdir, self.env)
		atexit.register(self.procs.stop_all)
		self.bus = Bus()
		self.daemon = None

	# ---- compositor

	def start_compositor(self):
		# The name keeps 'wayland' in it: the daemon's is_wayland() reads
		# WAYLAND_DISPLAY first and treats a name without it as X11 (ledger H-6)
		wl = 'wayland-gm-check-%d' % os.getpid()
		mutter = self.procs.start('mutter', ['mutter', '--headless', '--wayland',
			'--virtual-monitor', '1280x800', '--wayland-display', wl])
		sock = os.path.join(self.runtime, wl)
		match = mutter.wait_line(r'Using public X11 display (:\d+)', 15)
		up = wait_until(lambda: os.path.exists(sock), 5) and match
		auth = glob.glob(os.path.join(self.runtime, '.mutter-Xwaylandauth.*'))
		ok = check('compositor: mutter headless with Wayland and Xwayland', bool(up and auth and mutter.alive()),
			'socket %s, X display %s, Xauthority %s, alive %s; see %s' % (
				os.path.exists(sock), match.group(1) if match else None, auth, mutter.alive(), mutter.log))
		if not ok:
			return False
		self.env.update(WAYLAND_DISPLAY=wl, DISPLAY=match.group(1), XAUTHORITY=auth[0])
		info('WAYLAND_DISPLAY=%s DISPLAY=%s' % (wl, match.group(1)))
		return True

	# ---- daemon

	def start_daemon(self, label):
		env = {'PYTHONPATH': REPO, 'XDG_SESSION_TYPE': 'wayland'}
		since = len(self.bus.trees)
		self.daemon = self.procs.start('daemon', [sys.executable, '-c',
			'from globalmenu.run import main; main()'], env)
		owned = wait_until(lambda: self.bus.has_owner(DAEMON_NAME) and self.bus.has_owner(REGISTRAR), 15)
		ok = check('%s: daemon owns %s and %s' % (label, DAEMON_NAME, REGISTRAR), bool(owned),
			'after 15 s: %s owned %s, %s owned %s, daemon %s; see %s' % (
				DAEMON_NAME, self.bus.has_owner(DAEMON_NAME), REGISTRAR, self.bus.has_owner(REGISTRAR),
				'running' if self.daemon.alive() else 'exited with %s' % self.daemon.popen.returncode,
				self.daemon.log))
		if ok:
			# The menu reader sends one empty tree for the window it starts
			# with, then subscribes to WindowSwitchedSignal
			first = self.bus.next_tree(since, 10)
			info('first tree from the daemon: %s' % (json.dumps(first) if first is not None else 'none in 10 s'))
			pump(0.5)
		return ok

	def stop_daemon(self, label):
		children = self.daemon.children()
		status = self.procs.stop(self.daemon, timeout=5)
		gone = wait_until(lambda: not any(pid_alive(p) for p in children), 5)
		left = [p for p in children if pid_alive(p)]
		check('%s: SIGTERM stops the daemon and its %d child processes' % (label, len(children)),
			bool(gone) and len(children) == 2,
			'exit status %s, children %s, still running %s' % (status, children, left))
		for pid in left:
			try:
				os.kill(pid, signal.SIGKILL)
			except ProcessLookupError:
				pass
		released = wait_until(lambda: not self.bus.has_owner(DAEMON_NAME) and not self.bus.has_owner(REGISTRAR), 5)
		check('%s: bus names released after exit' % label, bool(released),
			'%s owned %s, %s owned %s' % (DAEMON_NAME, self.bus.has_owner(DAEMON_NAME), REGISTRAR,
				self.bus.has_owner(REGISTRAR)))

	def check_working_tree(self):
		env = dict(self.env, PYTHONPATH=REPO)
		out = subprocess.run([sys.executable, '-c', 'import globalmenu; print(globalmenu.__file__)'],
			env=env, cwd=REPO, capture_output=True, text=True)
		path = out.stdout.strip()
		check('daemon: imports globalmenu from the working tree', path.startswith(REPO + '/globalmenu/'),
			'imports %r (%s)' % (path, out.stderr.strip()))

	# ---- GTK

	def gtk_window_data(self, variant, app):
		owner = self.bus.owner(APP_ID)
		menus = self.bus.child_nodes(APP_ID, APP_PATH + '/menus') if owner else []
		windows = self.bus.child_nodes(APP_ID, APP_PATH + '/window') if owner else []
		bus_data = {
			'gtk_unique_bus_name': owner,
			'gtk_application_id': APP_ID,
			'gtk_application_object_path': APP_PATH,
		}
		if windows:
			bus_data['gtk_window_object_path'] = '%s/window/%s' % (APP_PATH, windows[0])
		if 'menubar' in menus:
			bus_data['gtk_menubar_object_path'] = APP_PATH + '/menus/menubar'
		if 'appmenu' in menus:
			bus_data['gtk_app_menu_object_path'] = APP_PATH + '/menus/appmenu'
		info('%s: from the bus: owner %s, menus %s, windows %s' % (variant, owner, menus, windows))
		for key in ('gtk_application_object_path', 'gtk_window_object_path', 'gtk_menubar_object_path'):
			if owner and bus_data.get(key):
				info('%s: interfaces at %s: %s' % (variant, bus_data[key], self.bus.interfaces(owner, bus_data[key])))

		ready = re.search(r'ready bus=(\S+) app_path=(\S+) window_id=(\d+)', app.text())
		want_owner = ready.group(1) if ready else None

		if variant.endswith('x11'):
			# The title also names mutter's frame window; the _GTK_* data sits
			# on the client window, which is what Meta.Window reads
			xid = wait_until(lambda: self.xid_by_title(APP_TITLE, with_gtk_props=True), 5)
			if not xid:
				info('%s: no window titled %r carries _GTK_* properties; all matches: %s' % (
					variant, APP_TITLE, self.xids_by_title(APP_TITLE)))
				xid = self.xid_by_title(APP_TITLE)
			props = self.xprops(xid) if xid else {}
			info('%s: xprop on window %s: %s' % (variant, xid, props))
			mismatch = ['%s xprop %r, bus %r' % (k, props.get(k), v) for k, v in bus_data.items() if props.get(k) != v]
			check('%s: _GTK_* window properties match what the app exports' % variant,
				bool(xid) and not mismatch, 'xid %s; %s' % (xid, '; '.join(mismatch)))
			data = dict(props)
			data['xid'] = str(xid or 0)
		else:
			data = dict(bus_data)
			data['xid'] = '0'

		needed = ['gtk_unique_bus_name', 'gtk_application_object_path', 'gtk_window_object_path',
			'gtk_menubar_object_path']
		missing = [k for k in needed if not data.get(k)]
		check('%s: app exports a menubar, a window and its actions' % variant,
			not missing and data['gtk_unique_bus_name'] == want_owner,
			'missing %s, bus owner %s, app says %s' % (missing, data.get('gtk_unique_bus_name'), want_owner))
		return data

	def xids_by_title(self, title):
		out = subprocess.run(['xdotool', 'search', '--name', '^%s$' % re.escape(title)], env=self.env,
			capture_output=True, text=True)
		return [int(i) for i in out.stdout.split()]

	def xid_by_title(self, title, with_gtk_props=False):
		for xid in self.xids_by_title(title):
			if not with_gtk_props or self.xprops(xid).get('gtk_unique_bus_name'):
				return xid
		return None

	def xprops(self, xid):
		names = ['_GTK_UNIQUE_BUS_NAME', '_GTK_APPLICATION_ID', '_GTK_APPLICATION_OBJECT_PATH',
			'_GTK_WINDOW_OBJECT_PATH', '_GTK_MENUBAR_OBJECT_PATH', '_GTK_APP_MENU_OBJECT_PATH']
		out = subprocess.run(['xprop', '-id', str(xid), '-notype'] + names, env=self.env,
			capture_output=True, text=True)
		props = {}
		for line in out.stdout.splitlines():
			m = re.match(r'(_GTK_\w+) = "(.*)"$', line.strip())
			if m:
				props[m.group(1)[1:].lower()] = m.group(2)
		return props

	def run_gtk(self, variant):
		gtk = '4' if variant.startswith('gtk4') else '3'
		backend = 'wayland' if variant.endswith('wayland') else 'x11'
		app = self.procs.start('%s-app' % variant, [sys.executable, os.path.join(APPS, 'gtk_menubar_app.py'),
			'--gtk', gtk], {'GDK_BACKEND': backend})
		if not check('%s: test app starts' % variant, bool(app.wait_line(r'^ready ', 15)),
				'no ready line in 15 s; see %s' % app.log):
			self.procs.stop(app)
			return
		pump(0.3)
		data = self.gtk_window_data(variant, app)

		since = len(self.bus.trees)
		self.bus.window_switched(data)
		tree = self.bus.tree_matching(since, lambda t: len(t) > 0, 5)
		if not check('%s: WindowSwitched answers with a SendMenuTree' % variant, tree is not None,
				'no non-empty tree in 5 s; trees sent: %s' % self.bus.trees[since:]):
			self.procs.stop(app)
			return
		info('%s tree: %s' % (variant, json.dumps(tree)))
		assert_tree(variant, tree, GTK_SHAPE, GTK_ACCELS,
			toggles={('_View', 'Show _Sidebar'): ('checkmark', True),
				('_View', '_Small'): ('radio', False), ('_View', '_Large'): ('radio', True)},
			disabled={('_View', '_Unavailable')}, submenu=('_File', '_Export'))

		self.gtk_live(variant, app)
		self.procs.stop(app)

	def app_state(self, action):
		try:
			desc = self.bus.gtk_actions('Describe', GLib.Variant('(s)', (action,)))[0]
		except GLib.Error as e:
			return 'error: %s' % e.message
		return desc[2][0] if desc[2] else None

	def gtk_live(self, variant, app):
		sidebar = SEP.join(['_View', 'Show _Sidebar'])
		small = SEP.join(['_View', '_Small'])

		# 1. The extension activates the check item
		since = len(self.bus.trees)
		self.bus.daemon('ActivateMenuItem', GLib.Variant('(s)', (sidebar,)))
		flipped = wait_until(lambda: self.app_state('sidebar') is False, 3)
		tree = self.bus.tree_matching(since, lambda t: toggle_state(t, '_View', 'Show _Sidebar') is False, 3)
		check('%s: activating the check item reaches the app and the resent tree' % variant,
			bool(flipped) and tree is not None,
			'app state %s, trees after activation %s' % (self.app_state('sidebar'),
				[toggle_state(json.loads(t), '_View', 'Show _Sidebar') for t in self.bus.trees[since:]]))

		# 2. The extension activates a radio item
		since = len(self.bus.trees)
		self.bus.daemon('ActivateMenuItem', GLib.Variant('(s)', (small,)))
		chosen = wait_until(lambda: self.app_state('size') == 'small', 3)
		tree = self.bus.tree_matching(since, lambda t: toggle_state(t, '_View', '_Small') is True
			and toggle_state(t, '_View', '_Large') is False, 3)
		warning = re.findall(r'.*CRITICAL.*|.*WARNING.*g_simple_action.*', app.text())
		check('%s: activating a radio item selects it in the app and the tree' % variant,
			bool(chosen) and tree is not None,
			'app state %r, want %r; app log: %s' % (self.app_state('size'), 'small',
				warning[-1].strip() if warning else 'no warning'))

		# 3. The app changes a check state by itself. The new state is the
		# opposite of what the daemon last sent, so a stale tree cannot pass.
		shown = toggle_state(json.loads(self.bus.trees[-1]), '_View', 'Show _Sidebar') if self.bus.trees else None
		want = not shown if isinstance(shown, bool) else True
		if self.app_state('sidebar') is want:
			self.bus.gtk_actions('SetState', GLib.Variant('(sva{sv})', ('sidebar', GLib.Variant('b', not want), {})))
			wait_until(lambda: self.app_state('sidebar') is (not want), 2)
		since = len(self.bus.trees)
		self.bus.gtk_actions('SetState', GLib.Variant('(sva{sv})', ('sidebar', GLib.Variant('b', want), {})))
		info('%s: tree showed sidebar %s, app sets it to %s (app now %s)' % (variant, shown, want,
			self.app_state('sidebar')))
		self.expect_update('%s: app-side check state change reaches the tree' % variant, since,
			lambda t: toggle_state(t, '_View', 'Show _Sidebar') is want)

		# 4. The app adds an item to an existing menu
		since = len(self.bus.trees)
		self.bus.gtk_actions('Activate', GLib.Variant('(sava{sv})', ('test-add-item', [], {})))
		app.wait_line(r'^added item', 3)
		self.expect_update('%s: item the app adds to its menu reaches the tree' % variant, since,
			lambda t: find(t, '_View', 'Added _Later') is not None)

	def expect_update(self, name, since, predicate):
		"""Pass when a tree satisfying predicate arrives: pushed by the
		daemon within 2 s, or else after RequestMenuTree, as the extension
		asks when a menu opens."""
		pushed = self.bus.tree_matching(since, predicate, 2)
		if pushed is not None:
			return check(name, True)
		info('%s: nothing pushed in 2 s, asking with RequestMenuTree' % name)
		asked = len(self.bus.trees)
		self.bus.daemon('RequestMenuTree')
		pulled = self.bus.tree_matching(asked, predicate, 2)
		return check(name, pulled is not None,
			'no tree with the change: none pushed in 2 s (%d trees), none after RequestMenuTree (%d trees)' % (
				asked - since, len(self.bus.trees) - asked))

	# ---- dbusmenu

	def start_dbusmenu_app(self):
		app = self.procs.start('dbusmenu-app', [sys.executable, os.path.join(APPS, 'dbusmenu_app.py')],
			{'GDK_BACKEND': 'x11'}, stdin=True)
		ready = app.wait_line(r'^ready xid=(\d+) bus=(\S+) path=(\S+)', 15)
		if not check('dbusmenu: test client starts on X11', bool(ready), 'no ready line; see %s' % app.log):
			return None, None
		return app, ready

	def dbusmenu_tree(self, label, app, ready, registered_before):
		xid, client, path = int(ready.group(1)), ready.group(2), ready.group(3)
		registered = wait_until(lambda: app.text().count('registered ') > registered_before, 10)
		try:
			got = tuple(self.bus.call(REGISTRAR, REGISTRAR_PATH, REGISTRAR, 'GetMenuForWindow',
				GLib.Variant('(u)', (xid,))))
		except GLib.Error as e:
			got = ('error', e.message)
		check('%s: registrar maps the window to the client menu' % label,
			bool(registered) and got == (client, path),
			'registered %s, GetMenuForWindow(%d) gave %s, want %s' % (bool(registered), xid, got, (client, path)))

		since = len(self.bus.trees)
		self.bus.window_switched({'xid': str(xid)})
		tree = self.bus.tree_matching(since, lambda t: len(t) > 0, 5)
		check('%s: WindowSwitched with the X11 id answers with a SendMenuTree' % label, tree is not None,
			'no non-empty tree in 5 s; trees sent: %s' % self.bus.trees[since:])
		return tree

	def run_dbusmenu(self, app, ready):
		label = 'dbusmenu'
		tree = self.dbusmenu_tree(label, app, ready, 0)
		if tree is None:
			return
		info('dbusmenu tree: %s' % json.dumps(tree))
		assert_tree(label, tree, DBUSMENU_SHAPE, DBUSMENU_ACCELS,
			toggles={('_View', 'Show _Toolbar'): ('checkmark', True),
				('_View', '_Small'): ('radio', False), ('_View', '_Large'): ('radio', True)},
			disabled={('_File', '_Open')}, submenu=('_File', '_Recent'))

		clicks = app.text().count('clicked _New')
		self.bus.daemon('ActivateMenuItem', GLib.Variant('(s)', (SEP.join(['_File', '_New']),)))
		check('%s: activating an item reaches the client' % label,
			bool(wait_until(lambda: app.text().count('clicked _New') > clicks, 3)),
			'no "clicked _New" in %s' % app.log)

		since = len(self.bus.trees)
		app.send('toggle')
		app.wait_line(r'^toolbar 0', 3)
		self.expect_update('%s: client-side check state change reaches the tree' % label, since,
			lambda t: toggle_state(t, '_View', 'Show _Toolbar') is False)

		since = len(self.bus.trees)
		app.send('add')
		app.wait_line(r'^added item', 3)
		self.expect_update('%s: item the client adds to its menu reaches the tree' % label, since,
			lambda t: find(t, '_View', 'Added _Later') is not None)

	def run_foreign_registrar(self, app, ready):
		"""The daemon starting while another program owns the registrar."""
		label = 'foreign registrar'
		registered_before = app.text().count('registered ')
		stub = self.procs.start('registrar-stub', [sys.executable, os.path.join(APPS, 'registrar_stub.py')])
		if not check('%s: stub owns %s' % (label, REGISTRAR), bool(stub.wait_line(r'^ready', 10)),
				'see %s' % stub.log):
			return
		if not self.start_daemon(label):
			if not self.daemon.alive():
				info('%s: daemon exited with status %s' % (label, self.daemon.popen.returncode))
			self.procs.stop(self.daemon)
			self.daemon = None
			return
		tree = self.dbusmenu_tree(label, app, ready, registered_before)
		if tree is not None:
			check('%s: tree read through the other registrar' % label, shape(tree)[:1] == DBUSMENU_SHAPE[:1],
				'got %s' % json.dumps(shape(tree)))

	# ---- all

	def run(self):
		self.check_working_tree()
		if not self.start_compositor():
			return
		if not self.start_daemon('daemon'):
			return
		for variant in ('gtk4-wayland', 'gtk3-x11'):
			self.run_gtk(variant)
		app, ready = self.start_dbusmenu_app()
		if app is not None:
			self.run_dbusmenu(app, ready)
		self.stop_daemon('daemon')
		if app is not None and app.alive():
			self.run_foreign_registrar(app, ready)
		if self.daemon is not None and self.daemon in self.procs.running:
			self.procs.stop(self.daemon)


def main():
	parser = argparse.ArgumentParser()
	parser.add_argument('--logdir', required=True)
	args = parser.parse_args()
	signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
	check_run = Check(args)
	try:
		check_run.run()
	except Exception as e:  # report, then let atexit stop everything
		import traceback
		traceback.print_exc()
		record('not ok', 'harness', '%s: %s' % (type(e).__name__, e))
	finally:
		check_run.procs.stop_all()
	print('RESULT %d passed, %d failed, %d skipped' % (results['ok'], results['not ok'], results['skip']), flush=True)
	return 1 if results['not ok'] else 0


if __name__ == '__main__':
	sys.exit(main())
