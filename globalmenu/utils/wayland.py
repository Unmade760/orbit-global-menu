import os


def is_wayland():
	# session type can be inherited from an x11 login
	# so a wayland display wins
	if os.environ.get('WAYLAND_DISPLAY'):
		return True

	return os.environ.get('XDG_SESSION_TYPE') == 'wayland'
