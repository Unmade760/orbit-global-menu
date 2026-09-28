#!/usr/bin/env bash
# imports: every extension module parses as an ES module under gjs, and every
# module that can load outside the shell does load.
#
# How (tools/lib/imports-driver.js does the work, one gjs -m process per
# module so GTK 4 and St never share a process):
#   1. classify: a module whose local import graph never reaches a
#      resource:/// specifier is a "load" module, the rest are "parse"
#      modules (they need gnome-shell's own JS, which exists only inside a
#      running shell).
#   2. load modules are imported for real from the source tree, so their
#      top level runs.
#   3. parse modules are imported from a copy of the tree in which every
#      resource:/// specifier points at a generated stub that exports each
#      name the code imports, and line 1 of every copied module throws a
#      sentinel error. ES module linking parses every file in the graph and
#      resolves every import binding and gi:// typelib before any module body
#      runs, so seeing the sentinel proves the graph parsed and linked; a
#      syntax error or a missing export shows up as a different error.
#
# gi://St, Shell, Meta and Clutter resolve from the host's gnome-shell and
# mutter typelib directories (GI_TYPELIB_PATH). Everything runs inside its
# own dbus-run-session with no display and GIO_USE_VFS=local, so nothing
# reaches the user's session. Run through tools/check.sh imports.

set -uo pipefail
cd "${GM_REPO:?run through tools/check.sh}" || exit 2

ext=$GM_REPO/global-menu@unmade.space
driver=$GM_REPO/tools/lib/imports-driver.js

for tool in gjs dbus-run-session; do
	if ! command -v "$tool" >/dev/null; then
		echo "summary: $tool not installed"
		exit 1
	fi
done
gjs --version

# Private typelib directories of gnome-shell and the newest mutter.
typelib_dirs=()
for d in /usr/lib64/gnome-shell /usr/lib/gnome-shell /usr/lib/*-linux-gnu/gnome-shell; do
	[[ -d $d ]] && typelib_dirs+=("$d")
done
mutter_dir=$(find /usr/lib64 /usr/lib /usr/lib/*-linux-gnu -maxdepth 1 -type d -name 'mutter-*' 2>/dev/null | sort -V | tail -n 1)
[[ -n $mutter_dir ]] && typelib_dirs+=("$mutter_dir")
gi_path=$(
	IFS=:
	echo "${typelib_dirs[*]}"
)
echo "GI_TYPELIB_PATH additions: ${gi_path:-none}"

run_gjs() {
	env -u DISPLAY -u WAYLAND_DISPLAY -u DBUS_SESSION_BUS_ADDRESS \
		GI_TYPELIB_PATH="$gi_path${GI_TYPELIB_PATH:+:$GI_TYPELIB_PATH}" \
		LD_LIBRARY_PATH="$gi_path${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
		GIO_USE_VFS=local GSETTINGS_BACKEND=memory \
		dbus-run-session -- gjs -m "$driver" "$@"
}

copy=$(mktemp -d "${TMPDIR:-/tmp}/gm-imports.XXXXXX")
trap 'rm -rf -- "$copy"' EXIT

if ! out=$(run_gjs stub "$ext" "$copy" 2>&1); then
	printf '%s\n' "$out"
	echo "summary: could not build the stubbed copy"
	exit 1
fi
grep '^OK' <<<"$out"

if ! classes=$(run_gjs classify "$ext" 2>&1); then
	printf '%s\n' "$classes"
	echo "summary: could not classify modules"
	exit 1
fi
mapfile -t rows < <(grep -E '^(load|parse) ' <<<"$classes")
if ((${#rows[@]} == 0)); then
	printf '%s\n' "$classes"
	echo "summary: no modules found under $ext"
	exit 1
fi

loaded=0 parsed=0 bad=()
for row in "${rows[@]}"; do
	mode=${row%% *}
	rel=${row#* }
	if [[ $mode == load ]]; then
		target=$ext/$rel
	else
		target=$copy/$rel
	fi
	out=$(run_gjs "$mode" "$target" 2>&1)
	status=$?
	result=$(grep -E '^(OK|ERR) ' <<<"$out" | tail -n 1)
	printf '[%s] %s: %s\n' "$mode" "$rel" "${result:-no result line}"
	if ((status != 0)) || [[ $result != OK* ]]; then
		printf '%s\n' "$out" | sed 's/^/    /'
		bad+=("$rel")
	elif [[ $mode == load ]]; then
		loaded=$((loaded + 1))
	else
		parsed=$((parsed + 1))
	fi
done

if ((${#bad[@]} > 0)); then
	echo "summary: ${#bad[@]} of ${#rows[@]} modules failed: ${bad[*]}"
	exit 1
fi
echo "summary: ${#rows[@]} modules: $loaded loaded, $parsed parsed and linked with shell imports stubbed"
