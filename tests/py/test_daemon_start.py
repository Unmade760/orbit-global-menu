# The daemon has to start on an X11 session that has none of the optional
# X11 libraries (Bamf, libkeybinder), and next to a registrar that is not its
# own. The X11 cases run in a child process: the session type is read when
# globalmenu.utils.wayland and utils/window.py are imported, and conftest.py
# has already imported them for Wayland.

import os
import subprocess
import sys
import textwrap

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Makes gi.require_version fail the way it does when the typelib is absent
HIDE_TYPELIBS = '''
import gi
_real_require_version = gi.require_version
def _require_version(namespace, version):
	if namespace in ('Bamf', 'Keybinder'):
		raise ValueError('Namespace %s not available' % namespace)
	return _real_require_version(namespace, version)
gi.require_version = _require_version
'''


def run_child(code, **env):
	child_env = {k: v for k, v in os.environ.items()
		if k not in ('XDG_SESSION_TYPE', 'WAYLAND_DISPLAY')}
	child_env.update(PYTHONPATH=ROOT, PYTHONDONTWRITEBYTECODE='1')
	child_env.update(env)
	return subprocess.run([sys.executable, '-c', HIDE_TYPELIBS + textwrap.dedent(code)],
		env=child_env, capture_output=True, text=True, timeout=60)


@pytest.mark.parametrize('module', [
	'globalmenu.command',
	'globalmenu.keybinder',
	'globalmenu.utils.global_keybinder',
	'globalmenu.utils.menu',
	'globalmenu.utils.window',
])
def test_modules_import_on_x11_without_bamf_and_keybinder(module):
	out = run_child('import %s' % module, XDG_SESSION_TYPE='x11')
	assert out.returncode == 0, out.stderr


def test_global_keybinder_is_a_no_op_without_keybinder():
	out = run_child('''
		from globalmenu.utils.global_keybinder import GlobalKeybinder, DummyKeybinder
		assert isinstance(GlobalKeybinder.create(lambda c: None), DummyKeybinder)
		''', XDG_SESSION_TYPE='x11')
	assert out.returncode == 0, out.stderr


def test_x11_window_comes_from_the_extension_data():
	# The extension sends xid and the gtk_* properties on both session types
	out = run_child('''
		from globalmenu.utils.window import WindowManager
		win = WindowManager.new_window({'xid': '4194307', 'gtk_unique_bus_name': ':1.42'})
		assert win.get_xid() == 4194307, win.get_xid()
		assert win.get_utf8_prop('_GTK_UNIQUE_BUS_NAME') == ':1.42'
		assert win.get_app_name() == ''
		''', XDG_SESSION_TYPE='x11')
	assert out.returncode == 0, out.stderr


def test_x11_listens_for_window_switched_signal():
	out = run_child('''
		import dbus
		seen = []
		class Proxy:
			def connect_to_signal(self, name, handler):
				seen.append(name)
		class Bus:
			def get_object(self, name, path):
				return Proxy()
		dbus.SessionBus = lambda: Bus()
		from globalmenu.utils.window import WindowManager
		WindowManager.add_listener(lambda win: None)
		assert seen == ['WindowSwitchedSignal'], seen
		''', XDG_SESSION_TYPE='x11')
	assert out.returncode == 0, out.stderr


@pytest.mark.parametrize('env, want', [
	({'XDG_SESSION_TYPE': 'wayland', 'WAYLAND_DISPLAY': 'gm-check-1'}, True),
	({'XDG_SESSION_TYPE': 'wayland'}, True),
	({'XDG_SESSION_TYPE': 'x11', 'WAYLAND_DISPLAY': 'wayland-0'}, False),
	({'XDG_SESSION_TYPE': 'x11'}, False),
	({'WAYLAND_DISPLAY': 'gm-check-1'}, True),
	({}, False),
])
def test_is_wayland_reads_the_session_type_first(monkeypatch, env, want):
	from globalmenu.utils.wayland import is_wayland
	monkeypatch.delenv('XDG_SESSION_TYPE', raising=False)
	monkeypatch.delenv('WAYLAND_DISPLAY', raising=False)
	for key, value in env.items():
		monkeypatch.setenv(key, value)
	assert is_wayland() is want
