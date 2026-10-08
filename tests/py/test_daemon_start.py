# Session detection and daemon start-up checks. The X11 cases run in a child
# process: the session type is read when globalmenu.utils.wayland and
# utils/window.py are imported, and conftest.py has already imported them for
# Wayland.

import pytest


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
