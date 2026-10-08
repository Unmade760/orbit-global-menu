import os


def is_wayland():
	# A set WAYLAND_DISPLAY wins: it names a live compositor socket, while
	# XDG_SESSION_TYPE can be inherited from an X11 login (a nested session)
	if os.environ.get('WAYLAND_DISPLAY'):
		return True

	return os.environ.get('XDG_SESSION_TYPE') == 'wayland'
