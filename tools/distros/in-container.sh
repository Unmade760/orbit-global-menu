#!/usr/bin/env bash
# One distros run inside a localhost/gm-distros:<id> container, as root.
#
#   in-container.sh <image-id> <apt|dnf> <gnome-major> <cycles>
#
# Started by tools/checks/distros.sh with the repo read-only at /src and the
# image's log directory at /out, no network, and no host socket of any kind.
# Steps, each writing a JSON piece to /work (copied to /out at the end):
#   1. env.json     versions of gnome-shell, gjs and python3 in the image
#   2. a system bus with python-dbusmock's logind template on it, because
#      gnome-shell aborts at start when it cannot reach logind
#   3. deps.json    the daemon's imports, required and optional, as the test
#                   user sees them
#   4. install.json the README's line (pip install --user ., run with
#                   --no-build-isolation --no-index so it needs no network),
#                   and on Debian and Ubuntu the deb from the Makefile; which
#                   one the next steps use; on apt images, whether the deb's
#                   Depends pull in the typelibs the daemon imports
#   5. daemon.json  global-menu started under its own dbus-run-session:
#                   does it own its bus names, does SIGTERM stop it
#   6. shell-*.json (the portal D-Bus services are masked first, see below)
#                   gnome-shell --headless under dbus-run-session with the
#                   extension in ~/.local/share/gnome-shell/extensions and
#                   tests/apps/gtk_menubar_app.py (GTK 4) focused on its
#                   display, enabled and disabled <cycles> times over D-Bus,
#                   then enabled once more for the log-out. A baseline pass
#                   first runs the same session and window changes without
#                   ever enabling the extension. When the
#                   extension is OUT_OF_DATE as shipped, a second pass runs
#                   with disable-extension-version-validation set, so the
#                   code itself still gets its cycles
#   7. result.json  tools/distros/report.py scans the logs and judges
# Everything runs as the user gmtest except the system bus and the installs.

set -uo pipefail

id=${1:?image id}
family=${2:?apt or dnf}
gnome=${3:?gnome major}
cycles=${4:-20}

src=/src
tools=$src/tools/distros
work=/work
user=gmtest
home=/home/$user
uuid=global-menu@unmade.space

mkdir -p "$work"
chmod 777 "$work"

finish() {
	python3 "$tools/report.py" --dir "$work" --image "$id" --cycles "$cycles" \
		|| echo "report.py failed"
	cp -r "$work"/. /out/ 2>/dev/null
	echo "done: $id"
}
trap finish EXIT

as_user() {
	runuser -u "$user" -- env -i HOME="$home" USER="$user" LOGNAME="$user" \
		LANG=C.UTF-8 PATH="${user_path:-/usr/local/bin:/usr/bin:/bin}" "$@"
}

# 1. Versions
python3 - "$gnome" >"$work/env.json" <<'EOF'
import json, subprocess, sys, platform
def out(cmd):
	try:
		return subprocess.run(cmd, capture_output=True, text=True).stdout.strip()
	except OSError as e:
		return 'missing (%s)' % e
pretty = ''
with open('/etc/os-release') as f:
	for line in f:
		if line.startswith('PRETTY_NAME='):
			pretty = line.split('=', 1)[1].strip().strip('"')
json.dump({'os': pretty, 'gnome_major': sys.argv[1],
	'gnome_shell': out(['gnome-shell', '--version']),
	'gjs': out(['gjs', '--version']), 'python': platform.python_version()}, sys.stdout)
EOF
echo "== env"; cat "$work/env.json"; echo

# 2. System bus and logind stand-in. Also the X11 socket directory, which
# systemd-tmpfiles makes on a real system; mutter 48 aborts without it.
mkdir -p /tmp/.X11-unix
chmod 1777 /tmp/.X11-unix
mkdir -p /run/dbus
dbus-daemon --system --fork
python3 -m dbusmock --template logind --system >"$work/logind.log" 2>&1 &
gdbus wait --system --timeout 20 org.freedesktop.login1 || echo "logind mock did not appear"

# 3. The daemon's imports
as_user python3 - >"$work/deps.json" <<'EOF'
import json, sys
def gi_ok(ns, ver):
	try:
		import gi
		gi.require_version(ns, ver)
		__import__('gi.repository.' + ns)
		return True
	except Exception:
		return False
def mod_ok(name):
	try:
		__import__(name)
		return True
	except Exception:
		return False
required = {'gi': mod_ok('gi'), 'dbus': mod_ok('dbus'),
	'dbus.mainloop.glib': mod_ok('dbus.mainloop.glib'),
	'Gtk 3.0': gi_ok('Gtk', '3.0'), 'Gdk 3.0': gi_ok('Gdk', '3.0')}
optional = {'Bamf 3 (X11 only)': gi_ok('Bamf', '3'),
	'Keybinder 3.0 (X11 only)': gi_ok('Keybinder', '3.0')}
try:
	with open('/etc/gm-distros/optional-missing.txt') as f:
		not_in_repos = f.read().split()
except OSError:
	not_in_repos = []
json.dump({'required': required, 'optional': optional,
	'optional_not_in_repos': not_in_repos}, sys.stdout)
EOF
echo "== deps"; cat "$work/deps.json"; echo

# 4. Install
copy_src() {
	mkdir -p "$1"
	tar -C "$src" --exclude=./.git --exclude=./tools/node_modules \
		--exclude=__pycache__ --exclude=./.ruff_cache --exclude='*.deb' \
		--exclude=./debian/usr --exclude=./build --exclude='*.egg-info' \
		-cf - . | tar -C "$1" -xf -
}
methods=$work/methods.jsonl
: >"$methods"
record() { # name documented exit logfile
	python3 - "$@" >>"$methods" <<'EOF'
import json, re, sys
name, documented, code, log = sys.argv[1:5]
with open(log, errors='replace') as f:
	lines = [l.rstrip() for l in f if l.strip()]
reason = ''
for pat in (r'dpkg-deb: error: .*', r'error: externally-managed-environment',
		r'ERROR: .*', r'error: .*', r'dpkg: error.*'):
	for l in lines:
		m = re.search(pat, l)
		if m:
			reason = m.group(0)
			break
	if reason:
		break
print(json.dumps({'name': name, 'documented': documented == 'yes',
	'exit': int(code), 'reason': reason if int(code) else '', 'tail': lines[-6:]}))
EOF
}

copy_src /tmp/pip-src
chown -R "$user:$user" /tmp/pip-src
as_user pip install --user --no-build-isolation --no-index /tmp/pip-src >"$work/install-pip.log" 2>&1
pip_rc=$?
record "pip install --user . (README)" yes "$pip_rc" "$work/install-pip.log"

used=""
if [[ $family == apt ]]; then
	copy_src /tmp/deb-src
	make -C /tmp/deb-src build >"$work/install-deb.log" 2>&1
	deb_rc=$?
	record "make build, then dpkg -i (debian/)" yes "$deb_rc" "$work/install-deb.log"
	if ((deb_rc != 0)) && grep -q 'has bad permissions' "$work/install-deb.log"; then
		# The maintainer scripts are committed without the execute bit and
		# dpkg-deb refuses them. Retry with it set, so the rest of the run
		# still tests the package; the failure above stays on the record.
		# A fresh copy, because "build" is not a phony target and the first
		# run left a build/ directory that makes make skip it.
		rm -rf /tmp/deb-src
		copy_src /tmp/deb-src
		chmod 0755 /tmp/deb-src/debian/DEBIAN/postinst /tmp/deb-src/debian/DEBIAN/prerm
		make -C /tmp/deb-src build >"$work/install-deb-retry.log" 2>&1
		deb_rc=$?
		record "make build with postinst and prerm set to 0755 (harness retry)" no "$deb_rc" "$work/install-deb-retry.log"
	fi
	if ((deb_rc == 0)); then
		dpkg -i /tmp/deb-src/global-menu_*_all.deb >"$work/install-dpkg.log" 2>&1
		dpkg_rc=$?
		record "dpkg -i global-menu_*_all.deb" yes "$dpkg_rc" "$work/install-dpkg.log"
		((dpkg_rc == 0)) && used="deb"
	fi
fi
if [[ -z $used && $pip_rc == 0 ]]; then
	used="pip --user"
fi
if [[ -z $used && $family == apt ]]; then
	as_user pip install --user --break-system-packages --no-build-isolation --no-index /tmp/pip-src \
		>"$work/install-pip-bsp.log" 2>&1
	bsp_rc=$?
	record "pip install --user --break-system-packages . (harness fallback)" no "$bsp_rc" "$work/install-pip-bsp.log"
	((bsp_rc == 0)) && used="pip --user --break-system-packages (harness fallback)"
fi
if [[ $used == pip* ]]; then
	user_path="$home/.local/bin:/usr/local/bin:/usr/bin:/bin"
else
	# Leave ~/.local/bin out, so a pip copy cannot shadow the deb
	user_path="/usr/local/bin:/usr/bin:/bin"
fi

closure_missing=""
if [[ $used == deb ]]; then
	# Walk the Depends of the installed package through dpkg's own database
	# and see whether it reaches the package that owns each typelib the
	# daemon loads on every start.
	closure_missing=$(python3 - <<'EOF'
import subprocess
def field(pkg, name):
	r = subprocess.run(['dpkg-query', '-W', '-f', '${%s}' % name, pkg],
		capture_output=True, text=True)
	return r.stdout if r.returncode == 0 else None
def provided_by():
	r = subprocess.run(['dpkg-query', '-W', '-f', '${Package}\t${Provides}\n'],
		capture_output=True, text=True)
	m = {}
	for line in r.stdout.splitlines():
		pkg, _, prov = line.partition('\t')
		for p in prov.split(','):
			p = p.strip().split(' ')[0]
			if p:
				m.setdefault(p, []).append(pkg)
	return m
prov = provided_by()
seen, todo = set(), ['global-menu']
while todo:
	pkg = todo.pop()
	if pkg in seen:
		continue
	seen.add(pkg)
	deps = (field(pkg, 'Depends') or '') + ',' + (field(pkg, 'Pre-Depends') or '')
	for alt in deps.split(','):
		for choice in alt.split('|'):
			name = choice.strip().split(' ')[0].split(':')[0]
			if not name:
				continue
			if (field(name, 'Status') or '').endswith('ok installed'):
				todo.append(name)
				break
			if name in prov:
				todo.extend(prov[name])
				break
# One line per owning package, so Gtk and Gdk from one package count once
typelibs = {'Gtk-3.0.typelib': 'Gtk 3.0', 'Gdk-3.0.typelib': 'Gdk 3.0'}
unmet = {}
for fname, label in typelibs.items():
	r = subprocess.run(['dpkg', '-S', '*/girepository-1.0/' + fname],
		capture_output=True, text=True)
	owners = {l.split(':')[0] for l in r.stdout.splitlines() if ':' in l}
	if not owners & seen:
		unmet.setdefault(' or '.join(sorted(owners)) or fname, []).append(label)
for pkg, labels in unmet.items():
	print('%s (%s, which the daemon imports)' % (pkg, ' and '.join(labels)))
EOF
)
fi

global_menu_path=$(as_user sh -c 'command -v global-menu' || true)
module_file=$(cd / && as_user python3 -c 'import globalmenu; print(globalmenu.__file__)' 2>&1 | tail -n 1)
python3 - "$methods" "$used" "$global_menu_path" "$module_file" "$closure_missing" >"$work/install.json" <<'EOF'
import json, sys
methods_file, used, path, module, missing = sys.argv[1:6]
with open(methods_file) as f:
	methods = [json.loads(l) for l in f if l.strip()]
json.dump({'methods': methods, 'used': used, 'program': path, 'module_file': module,
	'depends_closure_missing': [m for m in missing.splitlines() if m.strip()]}, sys.stdout)
EOF
echo "== install"; cat "$work/install.json"; echo

new_runtime() {
	local rt
	rt=$(mktemp -d /tmp/rt.XXXXXX)
	chown "$user:$user" "$rt"
	chmod 700 "$rt"
	echo "$rt"
}

# 5. The daemon on its own
if [[ -n $used ]]; then
	rt=$(new_runtime)
	timeout 90 runuser -u "$user" -- env -i HOME="$home" USER="$user" LOGNAME="$user" \
		LANG=C.UTF-8 PATH="$user_path" XDG_RUNTIME_DIR="$rt" \
		dbus-run-session -- python3 "$tools/session_driver.py" daemon \
		--out "$work/daemon.json" --log "$work/daemon.log" >"$work/daemon-session.log" 2>&1
	echo "== daemon"; cat "$work/daemon.json" 2>/dev/null; echo
else
	echo '{"error": "not installed"}' >"$work/daemon.json"
fi

# 6. The shell
ext_dir=$home/.local/share/gnome-shell/extensions/$uuid
as_user mkdir -p "$(dirname "$ext_dir")"
# The driver answers for the desktop portal's bus name, which is what lets it
# call org.gnome.Shell.Introspect. A real portal, D-Bus-activated by the GTK
# test app, would take the name first (seen on fedora:43), so the portal
# services are masked with a service file that runs /bin/false. The user's
# directory comes first in the session bus's search path.
as_user mkdir -p "$home/.local/share/dbus-1/services"
for n in org.freedesktop.impl.portal.desktop.gnome org.freedesktop.impl.portal.desktop.gtk \
	org.freedesktop.portal.Desktop; do
	printf '[D-BUS Service]\nName=%s\nExec=/bin/false\n' "$n" \
		>"$home/.local/share/dbus-1/services/$n.service"
done
# /ext is mounted only when the caller points GM_DISTROS_EXT at another copy
ext_src=$src/$uuid
[[ -d /ext ]] && ext_src=/ext
cp -r "$ext_src" "$ext_dir"
chown -R "$user:$user" "$home/.local"
as_user glib-compile-schemas "$ext_dir/schemas" || echo "glib-compile-schemas failed"

shell_pass() { # label, cycles, then --baseline or gsettings key=value pairs
	local label=$1 n=$2 rt kv extra=()
	shift 2
	rm -f "$home/.config/glib-2.0/settings/keyfile"
	for kv in "$@"; do
		if [[ $kv == --baseline ]]; then
			extra+=(--baseline)
			continue
		fi
		as_user env GSETTINGS_BACKEND=keyfile gsettings set org.gnome.shell "${kv%%=*}" "${kv#*=}"
	done
	rt=$(new_runtime)
	timeout 600 runuser -u "$user" -- env -i HOME="$home" USER="$user" LOGNAME="$user" \
		LANG=C.UTF-8 PATH="$user_path" XDG_RUNTIME_DIR="$rt" \
		GSETTINGS_BACKEND=keyfile XDG_SESSION_TYPE=wayland XDG_CURRENT_DESKTOP=GNOME \
		dbus-run-session -- python3 "$tools/session_driver.py" shell --cycles "$n" \
		--out "$work/shell-$label.json" --log "$work/shell-$label.log" \
		--app "$src/tests/apps/gtk_menubar_app.py" --app-log "$work/app-$label.log" --monitor "${extra[@]}" \
		>"$work/shell-$label-session.log" 2>&1
	echo "== shell $label (exit $?)"
	python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); c=d.get("cycles",[]); print({k:v for k,v in d.items() if k!="cycles"}); print(c[:2], "...", c[-1:])' \
		"$work/shell-$label.json" 2>&1
}

# The baseline never enables the extension but opens and closes the helper
# window as often as the cycles do; report.py uses its log to tell the
# shell's own noise from what appears only with the extension
shell_pass baseline "$cycles" --baseline
shell_pass as_shipped "$cycles"
first=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("first_state"))' \
	"$work/shell-as_shipped.json" 2>/dev/null)
if [[ $first == OUT_OF_DATE ]]; then
	shell_pass validation_off "$cycles" disable-extension-version-validation=true
fi
