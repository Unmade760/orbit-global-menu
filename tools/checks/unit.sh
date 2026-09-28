#!/usr/bin/env bash
# unit: tests for the pure logic, in two suites.
#   gjs     every tests/js/test-*.js, each in its own gjs -m process
#           (tests/js/lib/testlib.js prints ok, not ok and skip lines and a
#           RESULT line): accelerator parsing, shortcut labels, mapping
#           resolution, menu spec building.
#   pytest  tests/py: the daemon's menu model conversion from org.gtk.Menus
#           and com.canonical.dbusmenu layouts to the extension's JSON tree.
# Skipped tests cover behaviour that is not built yet and do not fail the
# check. Everything runs in its own dbus-run-session with no display, and
# TMPDIR points at a directory removed on exit. Run through
# tools/check.sh unit.

set -uo pipefail
cd "${GM_REPO:?run through tools/check.sh}" || exit 2

for tool in gjs dbus-run-session python3; do
	if ! command -v "$tool" >/dev/null; then
		echo "summary: $tool not installed"
		exit 1
	fi
done

scratch=$(mktemp -d "${TMPDIR:-/tmp}/gm-unit.XXXXXX")
trap 'rm -rf -- "$scratch"' EXIT

isolated() {
	env -u DISPLAY -u WAYLAND_DISPLAY -u DBUS_SESSION_BUS_ADDRESS \
		TMPDIR="$scratch" GIO_USE_VFS=local GSETTINGS_BACKEND=memory \
		NO_AT_BRIDGE=1 GTK_A11Y=none GTK_USE_PORTAL=0 GDK_DEBUG=no-portals \
		PYTHONDONTWRITEBYTECODE=1 \
		dbus-run-session -- "$@"
}

failures=()

# Section: gjs
printf '=== gjs (%s) ===\n' "$(gjs --version)"
js_pass=0 js_fail=0 js_skip=0
mapfile -t js_files < <(find tests/js -maxdepth 1 -name 'test-*.js' | sort)
if ((${#js_files[@]} == 0)); then
	failures+=("no tests/js/test-*.js found")
fi
for f in "${js_files[@]}"; do
	echo "--- $f"
	out=$(isolated gjs -m "$f" 2>&1)
	status=$?
	grep -vE '^dbus-daemon\[' <<<"$out"
	result=$(grep -E '^RESULT ' <<<"$out" | tail -n 1)
	if [[ $result =~ ([0-9]+)\ passed,\ ([0-9]+)\ failed,\ ([0-9]+)\ skipped ]]; then
		js_pass=$((js_pass + BASH_REMATCH[1]))
		js_fail=$((js_fail + BASH_REMATCH[2]))
		js_skip=$((js_skip + BASH_REMATCH[3]))
	fi
	if ((status != 0)) || [[ -z $result ]]; then
		if [[ -z $result ]]; then
			failures+=("$(basename -- "$f") crashed (exit $status)")
		else
			failures+=("$(basename -- "$f"): $(grep -m 1 -E '^not ok ' <<<"$out" | sed -e 's/^not ok //')")
		fi
	fi
done
echo "gjs: $js_pass passed, $js_fail failed, $js_skip skipped"

# Section: pytest
echo
echo "=== pytest ==="
if ! python3 -c 'import pytest' 2>/dev/null; then
	failures+=("pytest not installed")
	py_line="not run"
else
	out=$(isolated python3 -m pytest -p no:cacheprovider -q -rfs tests/py 2>&1)
	status=$?
	printf '%s\n' "$out"
	py_line=$(grep -E '^[0-9]+ (passed|failed)|^=+ .*(passed|failed|error).* =+$|[0-9]+ (passed|failed)' <<<"$out" | tail -n 1 | sed -e 's/^=* *//' -e 's/ *=*$//' -e 's/ in [0-9.]*s.*//' -e 's/, [0-9]* warnings\?//')
	if ((status != 0)); then
		first=$(grep -m 1 -E '^FAILED ' <<<"$out" | sed -e 's/^FAILED //' -e 's/ - .*//')
		if [[ -n $first ]]; then
			failures+=("pytest first failure $first")
		else
			failures+=("pytest exit $status")
		fi
	fi
fi

echo
tally="gjs $js_pass passed, $js_fail failed, $js_skip skipped; pytest ${py_line:-no result}"
if ((${#failures[@]} > 0)); then
	joined=$(printf '%s; ' "${failures[@]}")
	echo "summary: ${joined%; } ($tally)"
	exit 1
fi
echo "summary: $tally"
