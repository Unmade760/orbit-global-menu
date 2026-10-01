#!/usr/bin/env bash
# mappings: every built-in shortcut mapping is valid and loads whole.
#
# tools/lib/mappings-validator.js does the work under gjs, importing the
# extension's own accelerator.js and shortcutStore.js (both load outside the
# shell, see tools/checks/imports.sh). It checks strict JSON and the format
# in docs/shortcut-mappings.md, parses every shortcut with the extension's
# parseAccelerator, runs validateMapping and ShortcutStore.load on the real
# tree, checks identifier collisions between files and that index.json lists
# exactly the files present. Per-file counts go to the log and to
# $GM_LOG_DIR/mappings.json for the coverage auditors.
#
# Runs in its own dbus-run-session with no display. Run through
# tools/check.sh mappings.

set -uo pipefail
cd "${GM_REPO:?run through tools/check.sh}" || exit 2

summary_json=${GM_LOG_DIR:?}/mappings.json

for tool in gjs dbus-run-session; do
	if ! command -v "$tool" >/dev/null; then
		echo "summary: $tool not installed"
		exit 1
	fi
done
gjs --version

rm -f -- "$summary_json"
out=$(env -u DISPLAY -u WAYLAND_DISPLAY -u DBUS_SESSION_BUS_ADDRESS \
	GIO_USE_VFS=local GSETTINGS_BACKEND=memory \
	dbus-run-session -- gjs -m "$GM_REPO/tools/lib/mappings-validator.js" \
	"$GM_REPO/global-menu@unmade.space" "$summary_json" 2>&1)
status=$?
printf '%s\n' "$out"
echo "summary JSON: $summary_json"

total=$(grep -E '^TOTAL ' <<<"$out" | tail -n 1)
if ((status != 0)); then
	if [[ -z $total ]]; then
		echo "summary: validator crashed (exit $status): $(grep -vE '^[[:space:]]*$' <<<"$out" | tail -n 1)"
	else
		first=$(grep -m 1 -E '^ERROR ' <<<"$out" | sed -e 's/^ERROR //')
		echo "summary: $(grep -cE '^ERROR ' <<<"$out") errors, first: $first"
	fi
	exit 1
fi
if [[ ! -s $summary_json ]]; then
	echo "summary: validator passed but wrote no $summary_json"
	exit 1
fi
echo "summary: ${total#TOTAL }"
