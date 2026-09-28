#!/usr/bin/env bash
# daemon: the daemon from the working tree, headless, against real apps.
#
# Everything runs inside one private dbus-run-session with its own
# XDG_RUNTIME_DIR, so nothing reaches the user's session bus or display:
#   mutter --headless --wayland --virtual-monitor 1280x800
#       the compositor GNOME Shell itself is built on; it serves Wayland and
#       starts Xwayland on demand, so GTK 4 on Wayland, GTK 3 on X11 and an
#       X11 dbusmenu client all run against one compositor
#   python3 -c 'from globalmenu.run import main; main()'
#       the daemon, with PYTHONPATH at the repo root
#   tests/apps/gtk_menubar_app.py (GTK 4 on Wayland, then GTK 3 on X11)
#   tests/apps/dbusmenu_app.py (X11, com.canonical.dbusmenu)
#   tests/apps/registrar_stub.py (a registrar that is not the daemon's)
# tests/daemon/daemon_check.py plays the extension: it calls WindowSwitched
# with the window's gtk_* data, reads SendMenuTree and asserts the JSON tree
# (labels, submenus, separators, check and radio state, enabled flag,
# accelerators), activates items and checks that changes the app makes reach
# the tree. Logs of every process go to $GM_LOG_DIR/daemon/.
#
# Run through tools/check.sh daemon.

set -uo pipefail
cd "${GM_REPO:?run through tools/check.sh}" || exit 2

missing=()
for tool in dbus-run-session mutter Xwayland xdotool xprop python3; do
	command -v "$tool" >/dev/null || missing+=("$tool")
done
python3 -c 'import dbus' 2>/dev/null || missing+=("python3-dbus")
for typelib in Dbusmenu:0.4 GdkX11:3.0 Gtk:3.0 Gtk:4.0; do
	if ! python3 -c "import gi; gi.require_version('${typelib%%:*}', '${typelib#*:}')" 2>/dev/null; then
		missing+=("typelib $typelib")
	fi
done
if ((${#missing[@]} > 0)); then
	echo "summary: not installed: ${missing[*]}"
	exit 1
fi

logdir="$GM_LOG_DIR/daemon"
rm -rf -- "$logdir"
mkdir -p "$logdir"
runtime=$(mktemp -d "${TMPDIR:-/tmp}/gm-daemon.XXXXXX")
chmod 700 "$runtime"

# The check and everything it starts share one process group; the trap
# kills that group whatever happens, then removes the runtime directory.
cleanup() {
	trap - EXIT INT TERM
	if [[ -n ${pgid:-} ]]; then
		kill -TERM -- "-$pgid" 2>/dev/null
		sleep 1
		kill -KILL -- "-$pgid" 2>/dev/null
	fi
	rm -rf -- "$runtime"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

setsid env -u DISPLAY -u WAYLAND_DISPLAY -u XAUTHORITY -u DBUS_SESSION_BUS_ADDRESS \
	-u XDG_SESSION_TYPE -u GDK_BACKEND -u QT_QPA_PLATFORM \
	XDG_RUNTIME_DIR="$runtime" TMPDIR="$runtime" \
	GSETTINGS_BACKEND=memory GIO_USE_VFS=local NO_AT_BRIDGE=1 GTK_A11Y=none \
	GTK_USE_PORTAL=0 GDK_DEBUG=no-portals PYTHONDONTWRITEBYTECODE=1 \
	dbus-run-session -- python3 tests/daemon/daemon_check.py --logdir "$logdir" \
	>"$logdir/check.out" 2>&1 &
pid=$!
pgid=$pid
wait "$pid"
status=$?
pgid_left=$(pgrep -g "$pgid" 2>/dev/null | wc -l)

cat "$logdir/check.out"
echo
echo "processes left in the check's group before cleanup: $pgid_left"

result=$(grep -E '^RESULT ' "$logdir/check.out" | tail -n 1)
if [[ -z $result ]]; then
	echo "summary: daemon_check.py stopped without a RESULT line (exit $status); see $logdir/check.out"
	exit 1
fi
tally=${result#RESULT }
if ((status != 0)); then
	first=$(grep -m 1 -E '^not ok ' "$logdir/check.out" | sed -e 's/^not ok //')
	echo "summary: ${first:-exit $status} ($tally)"
	exit 1
fi
echo "summary: $tally"
