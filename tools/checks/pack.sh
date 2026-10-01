#!/usr/bin/env bash
# pack: the extensions.gnome.org zip holds only files the extension loads.
#
# Copies the tracked files of global-menu@unmade.space (git ls-files, so a
# stray gschemas.compiled or editor backup in the working tree does not
# count) to a scratch directory and runs `gnome-extensions pack` on it with
# every top-level entry pack does not take by default passed as
# --extra-source. That is the zip a release would upload. pack only reads
# and writes files; it still runs inside its own dbus-run-session with no
# display, so it never reaches the host session or shell.
#
# tools/lib/pack-audit.py then lists every file in the zip that the
# extension never loads (not reached from extension.js or prefs.js by a
# relative import, not metadata.json, the stylesheet, the settings schema,
# shortcuts/index.json or a mapping index.json lists) and every loaded file
# the zip lacks. The zip is kept at $GM_LOG_DIR/pack/ for inspection.
#
# Run through tools/check.sh pack.

set -uo pipefail
cd "${GM_REPO:?run through tools/check.sh}" || exit 2

for tool in gnome-extensions dbus-run-session python3 git; do
	if ! command -v "$tool" >/dev/null; then
		echo "summary: $tool not installed"
		exit 1
	fi
done

uuid=global-menu@unmade.space
scratch=$(mktemp -d -t gm-pack.XXXXXX)
trap 'rm -rf -- "$scratch"' EXIT
out_dir=${GM_LOG_DIR:?}/pack
rm -rf -- "$out_dir"
mkdir -p -- "$out_dir" "$scratch/src"

git ls-files -z -- "$uuid" | xargs -0 cp --parents -t "$scratch/src" || {
	echo "summary: could not copy the tracked extension files"
	exit 1
}

cd "$scratch/src/$uuid" || exit 2
extras=()
for entry in *; do
	case $entry in
		metadata.json | extension.js | prefs.js | stylesheet.css | schemas | po) ;;
		*) extras+=(--extra-source="$entry") ;;
	esac
done
printf 'extra source: %s\n' "${extras[@]#--extra-source=}"

env -u DISPLAY -u WAYLAND_DISPLAY -u DBUS_SESSION_BUS_ADDRESS \
	GIO_USE_VFS=local GSETTINGS_BACKEND=memory \
	dbus-run-session -- gnome-extensions pack . --force \
	--out-dir="$out_dir" "${extras[@]}" 2>&1
status=$?
zip="$out_dir/$uuid.shell-extension.zip"
if ((status != 0)) || [[ ! -f $zip ]]; then
	echo "summary: gnome-extensions pack failed (exit $status)"
	exit 1
fi
echo "zip: $zip ($(stat -c %s "$zip") bytes)"

python3 "$GM_REPO/tools/lib/pack-audit.py" "$zip"
