# pytest setup for the daemon's menu model tests. Run through
# tools/check.sh unit, which runs pytest inside its own dbus-run-session with
# no display.
#
# The daemon picks X11 or Wayland code at import time (utils/wayland.py), and
# the X11 path needs Bamf and Keybinder. The tests never touch a window
# system, so they take the Wayland path, which needs neither.

import os
import sys

os.environ['XDG_SESSION_TYPE'] = 'wayland'

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, HERE)
