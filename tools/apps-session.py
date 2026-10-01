#!/usr/bin/env python3
"""One app, one private session: start it, wait for its window, record what
menu it exports. Run by tools/apps-runner.py inside a dbus-run-session; it
does not touch the user's display or session bus.

    dbus-run-session -- python3 tools/apps-session.py --app-json FILE \
        --out RESULT.json --logdir DIR

Inside the session it starts
    mutter --headless --wayland   Wayland plus Xwayland on demand (as in
                                  tools/checks/daemon.sh)
    tests/apps/registrar_stub.py  a com.canonical.AppMenu.Registrar, for the
                                  X11 export paths (dbusmenu) that need one
                                  on the bus before the app starts
then the app (one process tree, no other app), waits until a window exists
(X11: a new _NET_CLIENT_LIST entry; Wayland: a new client on the compositor
socket), lets it settle, and records:
    bus names the app owns (unique name, pid, command) and the object tree
    under them
    org.gtk.Menus: every group reachable from the menubar, via Start
    org.gtk.Actions: DescribeAll on every exported action group, and from it
        the enabled, check and radio state of every menu item
    com.canonical.dbusmenu: GetLayout, with AboutToShow for lazy submenus
    the registrar's RegisterWindow calls
    X11 window properties (WM_CLASS, _GTK_*, _KDE_NET_WM_APPMENU_*)
    accelerators in the export, and whether a GTK shortcuts window exists
The result is one JSON file. A second pass at the end re-reads the menus
and records whether the item count moved.
"""

import argparse
import glob
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

import gi

gi.require_version('Gio', '2.0')
from gi.repository import Gio, GLib  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Commands that the private bus starts on its own (portals, keyring, dconf
# and so on). Their bus names are not the app's.
SERVICE_COMM_PREFIXES = (
	'xdg-', 'gnome-keyring', 'dconf', 'gvfs', 'mutter', 'at-spi', 'flatpak-session',
	'flatpak-portal', 'gsd-', 'pipewire', 'wireplumber', 'ibus', 'tracker', 'localsearch',
	'goa-', 'evolution', 'gnome-shell', 'xwayland', 'Xwayland', 'dbus-', 'python3', 'bwrap-none',
)
KEEP_COMM = ('xdg-dbus-proxy',)
WAYLAND_SERVICE_COMM = ('Xwayland', 'xwayland', 'mutter', 'xdg-desktop-por', 'xdg-', 'gsd-', 'gvfs', 'gnome-shell')

X11_PROPS = [
	'WM_CLASS', '_NET_WM_NAME', '_NET_WM_PID', '_NET_WM_WINDOW_TYPE',
	'_GTK_UNIQUE_BUS_NAME', '_GTK_APPLICATION_ID', '_GTK_APPLICATION_OBJECT_PATH',
	'_GTK_APP_MENU_OBJECT_PATH', '_GTK_MENUBAR_OBJECT_PATH', '_GTK_WINDOW_OBJECT_PATH',
	'_KDE_NET_WM_APPMENU_OBJECT_PATH', '_KDE_NET_WM_APPMENU_SERVICE_NAME',
]

SHORTCUT_STRINGS = [b'help-overlay.ui', b'shortcuts-dialog', b'shortcuts-window', b'ShortcutsWindow',
	b'shortcuts.ui', b'AdwShortcutsDialog', b'GtkShortcutsWindow']
SHORTCUT_ACTION_RE = re.compile(r'shortcut|help-overlay|keybinding|keyboard', re.I)

STANDARD_IFACES = ('org.freedesktop.DBus.Introspectable', 'org.freedesktop.DBus.Peer',
	'org.freedesktop.DBus.Properties', 'org.freedesktop.DBus.ObjectManager')


def now():
	return time.monotonic()


def log(msg):
	print('[session] ' + msg, flush=True)


def run(argv, env=None, timeout=10):
	try:
		res = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=timeout, check=False)
		return res.returncode, res.stdout
	except (subprocess.TimeoutExpired, OSError) as err:
		return 1, 'error: %s' % err


class Bus:
	def __init__(self):
		self.conn = Gio.bus_get_sync(Gio.BusType.SESSION, None)
		self.errors = []

	def call(self, name, path, iface, method, args=None, reply=None, timeout=2500):
		try:
			res = self.conn.call_sync(name, path, iface, method, args,
				GLib.VariantType.new(reply) if reply else None, Gio.DBusCallFlags.NONE, timeout, None)
		except GLib.Error as err:
			if len(self.errors) < 60:
				self.errors.append('%s %s %s.%s: %s' % (name, path, iface, method, err.message[:160]))
			return None
		return res.unpack() if res is not None else ()

	def names(self):
		got = self.call('org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus', 'ListNames', None, '(as)')
		return got[0] if got else []

	def owner(self, name):
		got = self.call('org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus', 'GetNameOwner',
			GLib.Variant('(s)', (name,)), '(s)')
		return got[0] if got else None

	def pid(self, name):
		got = self.call('org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus',
			'GetConnectionUnixProcessID', GLib.Variant('(s)', (name,)), '(u)')
		return got[0] if got else None


def read_comm(pid):
	try:
		with open('/proc/%d/comm' % pid) as handle:
			return handle.read().strip()
	except OSError:
		return ''


def read_cmdline(pid):
	try:
		with open('/proc/%d/cmdline' % pid, 'rb') as handle:
			return handle.read().replace(b'\0', b' ').decode('utf-8', 'replace').strip()[:300]
	except OSError:
		return ''


def tail(path, lines=25):
	try:
		with open(path, errors='replace') as handle:
			return handle.read().splitlines()[-lines:]
	except OSError:
		return []


# ---- X11

class X11:
	def __init__(self, env):
		self.env = env

	def client_list(self):
		if 'DISPLAY' not in self.env:
			return []
		rc, out = run(['xprop', '-root', '_NET_CLIENT_LIST'], self.env, 5)
		if rc != 0:
			return []
		return re.findall(r'0x[0-9a-fA-F]+', out.split('#', 1)[-1])

	def props(self, xid):
		rc, out = run(['xprop', '-id', xid, '-notype'] + X11_PROPS, self.env, 5)
		result = {}
		if rc != 0:
			return result
		for line in out.splitlines():
			if ' = ' not in line:
				continue
			key, value = line.split(' = ', 1)
			result[key.strip()] = value.strip().replace('"', '')
		return result

	def windows(self, baseline):
		found = []
		for xid in self.client_list():
			if xid in baseline:
				continue
			props = self.props(xid)
			props['xid'] = xid
			found.append(props)
		return found


def wayland_clients(sock):
	"""Command names of the clients connected to the compositor's socket.

	ss shows an accepted connection twice: the server end carries the socket
	path and the peer's inode, the client end carries the client's process.
	Session services that talk Wayland (Xwayland, the portal's GTK backend,
	mutter's X11 frame helper) are left out.
	"""
	rc, out = run(['ss', '-xnpH'], None, 5)
	if rc != 0:
		return []
	by_inode = {}
	peers = []
	for line in out.splitlines():
		cols = line.split()
		# Netid State Recv-Q Send-Q Local Local-inode Peer Peer-inode Process
		if len(cols) < 9 or cols[1] != 'ESTAB':
			continue
		by_inode[cols[5]] = line
		if cols[4] == sock:
			peers.append(cols[7])
	names = []
	for inode in peers:
		match = re.search(r'users:\(\("([^"]*)"', by_inode.get(inode, ''))
		comm = match.group(1) if match else '?'
		if comm.startswith(WAYLAND_SERVICE_COMM):
			continue
		names.append(comm)
	return names


# ---- introspection

def introspect(bus, name, path):
	got = bus.call(name, path, 'org.freedesktop.DBus.Introspectable', 'Introspect', None, '(s)', 1500)
	if not got:
		return [], []
	try:
		root = ET.fromstring(got[0])
	except ET.ParseError:
		return [], []
	ifaces = [i.get('name') for i in root.findall('interface') if i.get('name') not in STANDARD_IFACES]
	kids = [n.get('name') for n in root.findall('node') if n.get('name')]
	return ifaces, kids


def walk(bus, name, deadline, max_nodes=500, max_depth=10):
	"""Object paths under a bus name that carry a non-standard interface."""
	found = {}
	queue = [('/', 0)]
	count = 0
	while queue and count < max_nodes and now() < deadline:
		path, depth = queue.pop(0)
		count += 1
		ifaces, kids = introspect(bus, name, path)
		if ifaces:
			found[path] = ifaces
		if depth >= max_depth:
			continue
		for kid in kids:
			queue.append((path.rstrip('/') + '/' + kid, depth + 1))
	return found, count


# ---- org.gtk.Actions and org.gtk.Menus

def actions_dump(bus, name, path):
	got = bus.call(name, path, 'org.gtk.Actions', 'DescribeAll', None, '(a{s(bgav)})', 3000)
	if not got:
		return None
	actions = {}
	for action, (enabled, param_type, state) in got[0].items():
		actions[action] = {'enabled': bool(enabled), 'param': param_type or None,
			'state': state[0] if state else None}
	return actions


def menus_dump(bus, name, path):
	"""Every reachable (group, menu) of an org.gtk.Menus object."""
	menus = {}
	seen = set()
	pending = [0]
	started = []
	while pending:
		batch = sorted(g for g in set(pending) if g not in seen)
		pending = []
		if not batch:
			break
		seen.update(batch)
		got = bus.call(name, path, 'org.gtk.Menus', 'Start', GLib.Variant('(au)', (batch,)), '(a(uuaa{sv}))', 4000)
		if got is None:
			break
		started.extend(batch)
		for group, menu, items in got[0]:
			menus[(group, menu)] = items
			for item in items:
				for link in (':section', ':submenu'):
					if link in item:
						pending.append(item[link][0])
	if started:
		bus.call(name, path, 'org.gtk.Menus', 'End', GLib.Variant('(au)', (started,)), None, 1500)
	return menus


def build_gtk_tree(menus, group=0, menu=0, depth=0, seen=None):
	seen = seen or set()
	if (group, menu) in seen or depth > 12:
		return []
	seen = seen | {(group, menu)}
	nodes = []
	for item in menus.get((group, menu), []):
		if ':section' in item:
			sub = build_gtk_tree(menus, *item[':section'], depth, seen)
			if nodes and sub:
				nodes.append({'separator': True})
			if item.get('label') and sub:
				nodes.append({'section_label': item['label']})
			nodes.extend(sub)
			if sub:
				nodes.append({'_section_end': True})
			continue
		node = {'label': item.get('label', '')}
		for key in ('action', 'accel', 'target', 'icon', 'hidden-when', 'verb-icon', 'description', 'display-hint'):
			if key in item:
				node[key] = item[key]
		if ':submenu' in item:
			node['children'] = build_gtk_tree(menus, *item[':submenu'], depth + 1, seen)
		nodes.append(node)
	# Drop the section end markers; a separator sits between two sections
	cleaned = []
	for node in nodes:
		if node.get('_section_end'):
			continue
		cleaned.append(node)
	return cleaned


def resolve_actions(node, actions_by_scope):
	"""Fill enabled, toggle type and state from the org.gtk.Actions dumps."""
	action = node.get('action')
	if not action:
		return
	scope, _, short = action.partition('.')
	info = actions_by_scope.get(scope, {}).get(short)
	if info is None:
		node['action_found'] = False
		return
	node['action_found'] = True
	node['enabled'] = info['enabled']
	state = info['state']
	target = node.get('target')
	if isinstance(state, bool) and target is None:
		node['toggle'] = 'check'
		node['checked'] = state
	elif state is not None and target is not None:
		node['toggle'] = 'radio'
		node['checked'] = state == target


def walk_nodes(nodes, fn):
	for node in nodes:
		fn(node)
		if node.get('children'):
			walk_nodes(node['children'], fn)


def tally(nodes):
	stats = {'items': 0, 'submenus': 0, 'separators': 0, 'with_accel': 0, 'disabled': 0, 'check': 0, 'radio': 0,
		'action_missing': 0, 'with_action': 0, 'max_depth': 0}

	def visit(nodes, depth):
		stats['max_depth'] = max(stats['max_depth'], depth)
		for node in nodes:
			if node.get('separator'):
				stats['separators'] += 1
				continue
			if node.get('section_label'):
				continue
			if node.get('children') is not None:
				stats['submenus'] += 1
				visit(node['children'], depth + 1)
				continue
			stats['items'] += 1
			if node.get('accel') or node.get('shortcut'):
				stats['with_accel'] += 1
			if node.get('action'):
				stats['with_action'] += 1
				if node.get('action_found') is False:
					stats['action_missing'] += 1
			if node.get('enabled') is False:
				stats['disabled'] += 1
			if node.get('toggle') == 'check':
				stats['check'] += 1
			if node.get('toggle') == 'radio':
				stats['radio'] += 1
	visit(nodes, 1)
	return stats


# ---- com.canonical.dbusmenu

def dbusmenu_layout(bus, name, path, parent=0):
	got = bus.call(name, path, 'com.canonical.dbusmenu', 'GetLayout', GLib.Variant('(iias)', (parent, -1, [])),
		'(u(ia{sv}av))', 5000)
	return got[1] if got else None


def dbusmenu_node(raw, bus, name, path, budget):
	item_id, props, children = raw
	node = {'id': item_id}
	label = props.get('label')
	if props.get('type') == 'separator':
		return {'separator': True, 'id': item_id}
	node['label'] = label if label is not None else ''
	node['enabled'] = props.get('enabled', True)
	if props.get('visible') is False:
		node['visible'] = False
	toggle = props.get('toggle-type')
	if toggle:
		node['toggle'] = 'check' if toggle == 'checkmark' else toggle
		node['checked'] = props.get('toggle-state', -1) == 1
	shortcut = props.get('shortcut')
	if shortcut:
		node['shortcut'] = ['+'.join(chord) for chord in shortcut]
	if props.get('children-display') == 'submenu' or children:
		if not children and budget['lazy'] > 0:
			budget['lazy'] -= 1
			bus.call(name, path, 'com.canonical.dbusmenu', 'AboutToShow', GLib.Variant('(i)', (item_id,)), '(b)', 2000)
			sub = dbusmenu_layout(bus, name, path, item_id)
			children = sub[2] if sub else []
		node['children'] = [dbusmenu_node(c, bus, name, path, budget) for c in children]
	return node


# ---- shortcuts window

def find_exe(app):
	argv = app.get('launch') or []
	for word in argv:
		if word.startswith('-') or '=' in word or word in ('env', 'flatpak', 'run', 'sh', 'bash', '-c'):
			continue
		path = shutil.which(word)
		if path:
			return os.path.realpath(path)
	return None


def static_shortcut_hints(app):
	"""Resource names and strings in the app binary that mean a shortcuts window."""
	paths = []
	exe = find_exe(app)
	if exe:
		paths.append(exe)
	if app.get('packaging') == 'flatpak':
		app_id = app.get('flatpak_id')
		for base in ('/home/ravi/.local/share/flatpak/app', '/var/lib/flatpak/app'):
			root = os.path.join(base, app_id or '-', 'current', 'active', 'files')
			paths.extend(glob.glob(os.path.join(root, 'bin', '*'))[:4])
	hints = []
	for path in paths:
		try:
			size = os.path.getsize(path)
		except OSError:
			continue
		if size > 700 * 1024 * 1024:
			continue
		rc, out = run(['gresource', 'list', path], None, 15)
		if rc == 0:
			for line in out.splitlines():
				if re.search(r'help-overlay|shortcuts', line, re.I):
					hints.append('gresource %s: %s' % (os.path.basename(path), line.strip()))
		try:
			with open(path, 'rb') as handle:
				data = handle.read(300 * 1024 * 1024)
		except OSError:
			continue
		for needle in SHORTCUT_STRINGS:
			if needle in data:
				hints.append('string %r in %s' % (needle.decode(), os.path.basename(path)))
	return sorted(set(hints))[:12]


# ---- the session

class Session:
	def __init__(self, app, out, logdir):
		self.app = app
		self.out = out
		self.logdir = logdir
		self.runtime = os.environ['XDG_RUNTIME_DIR']
		self.home = os.path.join(self.runtime, 'home')
		self.procs = []
		self.result = {
			'id': app['id'], 'name': app.get('name'), 'toolkit': app.get('toolkit'),
			'packaging': app.get('packaging'), 'mode': app.get('mode', 'wayland'),
			'launch': app.get('launch'), 'desktop_id': app.get('desktop_id'), 'wm_class': app.get('wm_class'),
			'export_hint': app.get('export_hint'), 'status': 'error', 'started': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
		}
		self.timings = {}
		self.env = self.base_env()

	def base_env(self):
		env = {k: v for k, v in os.environ.items() if k in (
			'PATH', 'LANG', 'LC_ALL', 'USER', 'LOGNAME', 'SHELL', 'XDG_RUNTIME_DIR', 'DBUS_SESSION_BUS_ADDRESS',
			'FLATPAK_USER_DIR', 'TMPDIR', 'JAVA_HOME', 'GM_APPS_SESSION')}
		os.makedirs(os.path.join(self.home, '.cache'), exist_ok=True)
		real_fc = os.path.expanduser('/home/ravi/.cache/fontconfig')
		link = os.path.join(self.home, '.cache', 'fontconfig')
		if os.path.isdir(real_fc) and not os.path.exists(link):
			try:
				os.symlink(real_fc, link)
			except OSError:
				pass
		env.update(
			HOME=self.home,
			XDG_CONFIG_HOME=os.path.join(self.home, '.config'),
			XDG_DATA_HOME=os.path.join(self.home, '.local', 'share'),
			XDG_CACHE_HOME=os.path.join(self.home, '.cache'),
			XDG_STATE_HOME=os.path.join(self.home, '.local', 'state'),
			XDG_CURRENT_DESKTOP='GNOME', DESKTOP_SESSION='gnome',
			GSETTINGS_BACKEND='memory', GIO_USE_VFS='local', NO_AT_BRIDGE='1', GTK_A11Y='none',
			GTK_USE_PORTAL='0', LIBGL_ALWAYS_SOFTWARE='1', TERM='xterm-256color',
			PYTHONDONTWRITEBYTECODE='1', LANG=env.get('LANG', 'C.UTF-8'))
		for sub in ('.config', '.local/share', '.local/state'):
			os.makedirs(os.path.join(self.home, sub), exist_ok=True)
		return env

	def spawn(self, name, argv, env=None, cwd=None):
		path = os.path.join(self.logdir, name + '.log')
		out = open(path, 'w')
		proc = subprocess.Popen(argv, env=env or self.env, cwd=cwd or self.home, stdout=out,
			stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True)
		out.close()
		self.procs.append((name, proc, path))
		log('started %s pid %d' % (name, proc.pid))
		return proc, path

	def wait_line(self, path, pattern, timeout):
		end = now() + timeout
		while now() < end:
			try:
				with open(path, errors='replace') as handle:
					match = re.search(pattern, handle.read())
				if match:
					return match
			except OSError:
				pass
			time.sleep(0.2)
		return None

	def start_compositor(self):
		wl = 'wayland-gm-apps-%d' % os.getpid()
		proc, path = self.spawn('mutter', ['mutter', '--headless', '--wayland', '--virtual-monitor', '1280x800',
			'--wayland-display', wl])
		match = self.wait_line(path, r'Using public X11 display (:\d+)', 20)
		sock = os.path.join(self.runtime, wl)
		for _ in range(40):
			if os.path.exists(sock):
				break
			time.sleep(0.25)
		auth = glob.glob(os.path.join(self.runtime, '.mutter-Xwaylandauth.*'))
		if not (match and os.path.exists(sock) and auth and proc.poll() is None):
			self.result['error'] = 'compositor did not start; see mutter.log'
			return False
		self.wl, self.display, self.auth, self.sock = wl, match.group(1), auth[0], sock
		return True

	def app_env(self):
		env = dict(self.env)
		mode = self.result['mode']
		env['XDG_SESSION_TYPE'] = mode
		if mode == 'x11':
			env.update(DISPLAY=self.display, XAUTHORITY=self.auth, GDK_BACKEND='x11',
				QT_QPA_PLATFORM='xcb', MOZ_ENABLE_WAYLAND='0', SDL_VIDEODRIVER='x11')
		else:
			env.update(WAYLAND_DISPLAY=self.wl, DISPLAY=self.display, XAUTHORITY=self.auth,
				QT_QPA_PLATFORM='wayland;xcb', MOZ_ENABLE_WAYLAND='1')
		env.update(self.app.get('env') or {})
		return env

	def tracked_names(self, baseline):
		"""Unique bus names that appeared since the baseline and are not session services."""
		bus = self.bus
		owners = {}
		for name in bus.names():
			if name.startswith(':'):
				owners.setdefault(name, [])
			elif name != 'org.freedesktop.DBus':
				owner = bus.owner(name)
				if owner:
					owners.setdefault(owner, []).append(name)
		mine = {}
		for unique, wells in owners.items():
			if unique in baseline:
				continue
			pid = bus.pid(unique)
			comm = read_comm(pid) if pid else ''
			if pid == os.getpid():
				continue
			if comm not in KEEP_COMM and comm.startswith(SERVICE_COMM_PREFIXES):
				continue
			mine[unique] = {'unique': unique, 'names': sorted(wells), 'pid': pid, 'comm': comm,
				'cmdline': read_cmdline(pid) if pid else ''}
		return mine

	def run(self):
		app = self.app
		self.bus = Bus()
		if not self.start_compositor():
			self.result['status'] = 'error'
			return
		registrar = None
		if app.get('registrar', True):
			registrar, rpath = self.spawn('registrar', [sys.executable, os.path.join(REPO, 'tests', 'apps', 'registrar_stub.py')])
			if not self.wait_line(rpath, r'ready', 10):
				self.result['error'] = 'registrar stub did not start'
		self.has_registrar = registrar is not None
		time.sleep(1.0)
		x11 = X11({'DISPLAY': self.display, 'XAUTHORITY': self.auth, 'PATH': self.env['PATH']})
		x_base = set(x11.client_list())
		bus_base = set(n for n in self.bus.names() if n.startswith(':'))
		wl_base = len(wayland_clients(self.sock))
		self.result['baseline'] = {'x11_clients': len(x_base), 'wayland_clients': wl_base}

		argv = list(app['launch'])
		t0 = now()
		proc, app_log = self.spawn('app', argv, self.app_env(), cwd=self.home)
		self.result['launch_pid'] = proc.pid

		timeout = app.get('timeout', 40)
		settle = app.get('settle', 5)
		mode = self.result['mode']
		signal_at = None
		exited_at = None
		while now() - t0 < timeout:
			tracked = self.tracked_names(bus_base)
			have_window = bool(x11.windows(x_base))
			if not have_window and mode == 'wayland':
				have_window = len(wayland_clients(self.sock)) > wl_base
			if have_window:
				signal_at = now() - t0
				break
			if proc.poll() is not None and exited_at is None:
				exited_at = now() - t0
			if exited_at is not None and now() - t0 > exited_at + 6 and not tracked:
				break
			time.sleep(1.0)
		self.timings['window_after_s'] = round(signal_at, 1) if signal_at is not None else None
		self.result['window_seen'] = signal_at is not None
		self.result['window_signal'] = 'x11 _NET_CLIENT_LIST' if mode == 'x11' else 'new X11 window or Wayland client'
		if proc.poll() is not None:
			self.result['launcher_exit'] = proc.returncode
		# Settle: menus often appear a moment after the window
		settle_end = now() + settle
		while now() < settle_end:
			time.sleep(0.5)
		# Late starters (Electron, Java): wait for bus names as well, within the timeout
		if signal_at is None:
			late_end = min(now() + 6, t0 + timeout + 6)
			while now() < late_end and not self.tracked_names(bus_base):
				time.sleep(1)

		self.timings['probe_at_s'] = round(now() - t0, 1)
		self.probe(x11, x_base, bus_base)
		self.timings['total_s'] = round(now() - t0, 1)
		alive = proc.poll() is None
		self.result['app_alive_at_probe'] = alive or bool(self.result.get('bus', {}).get('names'))
		if proc.poll() is not None:
			self.result['launcher_exit'] = proc.returncode
		summary = self.result['summary']
		code = self.result.get('launcher_exit')
		if not self.result['window_seen'] and not summary['bus_names']:
			# A launcher that died on a signal or abort is a crash, not a quiet app
			self.result['status'] = 'crashed' if code is not None and (code < 0 or code in (134, 139)) else 'no-window'
		else:
			self.result['status'] = 'ok'
		self.result['app_log_tail'] = tail(app_log, 15)

	def probe(self, x11, x_base, bus_base):
		bus = self.bus
		result = self.result
		mine = self.tracked_names(bus_base)
		result['x11_windows'] = x11.windows(x_base)
		deadline = now() + 45
		objects = {}
		names_out = []
		for unique, info in mine.items():
			paths, count = walk(bus, unique, deadline)
			info['nodes_walked'] = count
			info['objects'] = {p: i for p, i in paths.items()}
			names_out.append(info)
			objects[unique] = paths
		result['bus'] = {'names': names_out, 'errors': bus.errors[:20]}

		gtk_menus, gtk_actions, dbusmenus = [], [], []
		actions_by_name = {}
		for unique, paths in objects.items():
			for path, ifaces in paths.items():
				if 'org.gtk.Actions' in ifaces:
					dump = actions_dump(bus, unique, path)
					if dump is not None:
						scope = 'win' if '/window/' in path or path.endswith('/window') else 'app'
						actions_by_name.setdefault(unique, {}).setdefault(scope, {}).update(dump)
						gtk_actions.append({'name': unique, 'path': path, 'scope': scope, 'count': len(dump),
							'names': sorted(dump)[:400]})
		for unique, paths in objects.items():
			for path, ifaces in paths.items():
				if 'org.gtk.Menus' in ifaces:
					menus = menus_dump(bus, unique, path)
					if not menus:
						continue
					tree = build_gtk_tree(menus)
					by_scope = dict(actions_by_name.get(unique, {}))
					by_scope.setdefault('unity', {})
					walk_nodes(tree, lambda n, s=by_scope: resolve_actions(n, s))
					gtk_menus.append({'name': unique, 'path': path, 'groups': len(menus),
						'top_level': [n.get('label') for n in tree if n.get('label')], 'stats': tally(tree),
						'tree': tree})
				if 'com.canonical.dbusmenu' in ifaces:
					layout = dbusmenu_layout(bus, unique, path)
					if layout:
						budget = {'lazy': 80}
						tree = [dbusmenu_node(c, bus, unique, path, budget) for c in layout[2]]
						dbusmenus.append({'name': unique, 'path': path,
							'top_level': [n.get('label') for n in tree if n.get('label')], 'stats': tally(tree),
							'tree': tree})
		result['gtk_menus'] = gtk_menus
		result['gtk_actions'] = gtk_actions
		result['dbusmenu'] = dbusmenus

		registered = []
		if self.has_registrar:
			got = bus.call('com.canonical.AppMenu.Registrar', '/com/canonical/AppMenu/Registrar',
				'com.canonical.AppMenu.Registrar', 'GetMenus', None, '(a{u(so)})')
			if got:
				registered = [{'window': w, 'sender': s, 'path': p} for w, (s, p) in got[0].items()]
		result['registrar'] = {'present': self.has_registrar, 'registered': registered}

		# A menu that is registered but the walk missed
		for reg in registered:
			if not any(d['path'] == reg['path'] and d['name'] == reg['sender'] for d in dbusmenus):
				layout = dbusmenu_layout(bus, reg['sender'], reg['path'])
				if layout:
					budget = {'lazy': 80}
					tree = [dbusmenu_node(c, bus, reg['sender'], reg['path'], budget) for c in layout[2]]
					dbusmenus.append({'name': reg['sender'], 'path': reg['path'], 'via': 'registrar',
						'top_level': [n.get('label') for n in tree if n.get('label')], 'stats': tally(tree), 'tree': tree})

		# Can the extension find the menu? A dbusmenu nobody registered has no
		# window property and no registrar entry to be found by.
		for menu in dbusmenus:
			menu['registered'] = any(r['sender'] == menu['name'] and r['path'] == menu['path'] for r in registered)

		# Shortcuts window: live action names and static resource hints
		action_names = sorted({n for a in gtk_actions for n in a['names'] if SHORTCUT_ACTION_RE.search(n)})
		static = static_shortcut_hints(self.app)
		result['shortcuts_window'] = {'actions': action_names[:20], 'static_hints': static,
			'present': bool(action_names or static)}

		# Second pass: did the menus move
		stable = []
		for menu in gtk_menus:
			again = menus_dump(bus, menu['name'], menu['path'])
			stable.append(tally(build_gtk_tree(again))['items'] == menu['stats']['items'])
		for menu in dbusmenus:
			layout = dbusmenu_layout(bus, menu['name'], menu['path'])
			if layout:
				budget = {'lazy': 80}
				again = [dbusmenu_node(c, bus, menu['name'], menu['path'], budget) for c in layout[2]]
				stable.append(tally(again)['items'] == menu['stats']['items'])
		result['menu_stable'] = all(stable) if stable else None

		kind = 'none'
		if gtk_menus:
			kind = 'org.gtk.Menus'
		elif dbusmenus:
			kind = 'com.canonical.dbusmenu'
			if not any(m['registered'] for m in dbusmenus):
				kind += ' (not registered)'
		elif gtk_actions:
			kind = 'org.gtk.Actions only'
		main = (gtk_menus or dbusmenus or [None])[0]
		all_menus = gtk_menus + dbusmenus
		result['summary'] = {
			'export': kind,
			'bus_names': sorted({n for info in names_out for n in info['names']} | {i['unique'] for i in names_out}),
			'top_level': main['top_level'] if main else [],
			'items': sum(m['stats']['items'] for m in all_menus),
			'submenus': sum(m['stats']['submenus'] for m in all_menus),
			'with_accel': sum(m['stats']['with_accel'] for m in all_menus),
			'disabled': sum(m['stats']['disabled'] for m in all_menus),
			'check': sum(m['stats']['check'] for m in all_menus),
			'radio': sum(m['stats']['radio'] for m in all_menus),
			'actions': sum(a['count'] for a in gtk_actions),
			'shortcuts_window': result['shortcuts_window']['present'],
			'registrar_registrations': len(registered),
			'dbusmenu_registered': any(m['registered'] for m in dbusmenus),
			'x11_gtk_menubar_property': any(w.get('_GTK_MENUBAR_OBJECT_PATH') for w in result['x11_windows']),
			'x11_kde_appmenu_property': any(w.get('_KDE_NET_WM_APPMENU_OBJECT_PATH') for w in result['x11_windows']),
		}

	def finish(self):
		self.result['timings'] = self.timings
		self.result['logs'] = {'dir': self.logdir}
		tmp = self.out + '.tmp'
		with open(tmp, 'w') as handle:
			json.dump(self.result, handle, indent=1, sort_keys=False, default=str)
		os.replace(tmp, self.out)


def main():
	parser = argparse.ArgumentParser()
	parser.add_argument('--app-json', required=True)
	parser.add_argument('--out', required=True)
	parser.add_argument('--logdir', required=True)
	args = parser.parse_args()
	with open(args.app_json) as handle:
		app = json.load(handle)
	os.makedirs(args.logdir, exist_ok=True)
	session = Session(app, args.out, args.logdir)
	signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
	try:
		session.run()
	except Exception as err:  # the harness records it; the runner decides
		import traceback
		session.result['status'] = 'harness-error'
		session.result['error'] = '%s: %s' % (type(err).__name__, err)
		session.result['traceback'] = traceback.format_exc()
	finally:
		session.finish()
	return 0


if __name__ == '__main__':
	sys.exit(main())
