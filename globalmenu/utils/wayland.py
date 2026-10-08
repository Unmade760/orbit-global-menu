import os


def is_wayland():
	# XDG_SESSION_TYPE first: a compositor may name its socket anything, so
	# WAYLAND_DISPLAY only counts when the session type is not set
	type = os.environ.get('XDG_SESSION_TYPE')
	if type:
		return type == 'wayland'

	return bool(os.environ.get('WAYLAND_DISPLAY'))
