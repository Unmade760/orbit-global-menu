#!/usr/bin/env bash
# Negative test for tools/check.sh compat. Copies the extension to a scratch
# directory, plants one breakage of each kind the check claims to catch,
# runs the check on the copy, and asserts that each breakage shows up in
# compat.json with the right verdict, and that a guarded use does not fail.
#
#   tests/compat/negative-test.sh      (about 40 s; needs the gm-test images)
#
# Exit 0 when every expectation holds.

set -uo pipefail
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
scratch=$(mktemp -d "${TMPDIR:-/tmp}/gm-compat-neg.XXXXXX")
trap 'rm -rf -- "$scratch"' EXIT

ext=$scratch/global-menu@unmade.space
cp -r "$repo/global-menu@unmade.space" "$ext"

# Inserts $2 after the first line of file $1 that contains $3.
plant() {
	local file=$ext/$1 text=$2 anchor=$3
	if ! grep -qF -- "$anchor" "$file"; then
		echo "anchor not found in $1: $anchor" >&2
		exit 2
	fi
	awk -v anchor="$anchor" -v text="$text" \
		'{print} !done && index($0, anchor) {print text; done = 1}' "$file" >"$file.new" &&
		mv "$file.new" "$file"
}

# A GI method no version has, on a typed receiver
plant windowActions.js '		win.gm_no_such_method();' 'const type = win.get_window_type();'
# The same, behind a feature test: must be reported as guarded, not failed
plant windowActions.js "		if (typeof win.gm_guarded_method === 'function') win.gm_guarded_method();" 'const type = win.get_window_type();'
# An introspected method called with more arguments than gjs accepts
plant windowActions.js "		win.get_wm_class('extra');" 'const type = win.get_window_type();'
# A construct property the class does not have
plant menuBarButton.js '		new St.Label({gm_bogus_prop: 1});' 'super._init(0.0, label);'
# An export gnome-shell does not have
plant nativeMenu.js "import {GmNoSuchExport} from 'resource:///org/gnome/shell/ui/popupMenu.js';" "import * as PopupMenu from"
plant nativeMenu.js '		void GmNoSuchExport;' 'hasMenus() {'
# A field of a gnome-shell class that does not exist
plant panelBar.js '	void Main.panel._gmNoSuchPanelField;' 'function runStart() {'
# A JS builtin newer than SpiderMonkey 128 (gjs 1.82, Debian 13)
plant shortcutStore.js 'const GM_PROMISE_TRY = typeof Promise.try;' "import {parseAccelerator} from './keySynth.js';"
# A shell-only namespace in a preferences module
plant prefsPages/appearancePage.js "import St from 'gi://St';" "import Gtk from 'gi://Gtk';"
plant prefsPages/appearancePage.js '	void St;' 'function blurMyShellInstalled() {'

logs=$scratch/logs
mkdir -p "$logs"
out=$(GM_REPO=$repo GM_EXT_DIR=$ext GM_LOG_DIR=$logs GM_TOOLS=$repo/tools GM_COMPAT_EXT=$ext \
	bash "$repo/tools/checks/compat.sh" 2>&1)
status=$?
printf '%s\n' "$out" | grep -E '^(FAIL|guarded|summary)' | sed 's/^/  | /'

fails=0
expect() {
	local what=$1 query=$2
	if python3 - "$logs/compat.json" "$query" <<'PY'
import json, sys
data = json.load(open(sys.argv[1]))
ok = eval(sys.argv[2], {'f': data['failures'], 'n': data['notes']})
sys.exit(0 if ok else 1)
PY
	then
		echo "ok   $what"
	else
		echo "FAIL $what"
		fails=$((fails + 1))
	fi
}

if ((status == 0)); then
	echo "FAIL check exited 0 on a broken copy"
	fails=$((fails + 1))
fi
expect 'missing GI method fails on every image' \
	"len({x['target'] for x in f if x['symbol'] == 'Meta.Window#gm_no_such_method()'}) == 5"
expect 'guarded GI method is a note, not a failure' \
	"not any('gm_guarded_method' in x['symbol'] for x in f) and any('gm_guarded_method' in x['symbol'] for x in n)"
expect 'too many arguments to an introspected method' \
	"any(x['symbol'] == 'Meta.Window#get_wm_class()' and x['status'] == 'too many arguments' for x in f)"
expect 'unknown construct property' \
	"any(x['symbol'] == 'new St.Label({gm_bogus_prop})' for x in f)"
expect 'missing gnome-shell export' \
	"any(x['symbol'] == 'import {GmNoSuchExport} from ui/popupMenu.js' for x in f)"
expect 'missing gnome-shell field' \
	"any(x['symbol'] == 'ui/panel.js:Panel#_gmNoSuchPanelField' for x in f)"
expect 'Promise.try missing in gjs 1.82 (Debian 13)' \
	"any(x['symbol'] == 'JS Promise.try' and x['target'] == 'debian-13' for x in f)"
expect 'St imported by a preferences module' \
	"any(x['symbol'] == 'process separation' and 'gi://St' in x['status'] for x in f)"
expect 'the real findings are still there' \
	"any(x['symbol'] == 'Clutter.get_default_backend()' and x['target'] == 'fedora-45' for x in f)"

if ((fails > 0)); then
	echo "negative test: $fails expectation(s) failed"
	exit 1
fi
echo "negative test: every planted breakage reported"
