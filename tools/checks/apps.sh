#!/usr/bin/env bash
# apps: run every app in tests/apps/apps.json under a headless compositor on
# its own session bus and record what menu it exports.
#
# Long (21 minutes for the 110 apps listed on 2026-10-01), so
# tools/check.sh leaves it out of "all". Run it with
#     tools/check.sh apps
# and limit it with GM_APPS_ONLY=gedit,kate,firefox.
#
# The work is in tools/apps-runner.py (the loop, the private runtime and bus,
# the kill and sweep) and tools/apps-session.py (one app inside one
# dbus-run-session: mutter --headless, the registrar stub, the probes). One
# JSON per app goes to /home/ravi/fildem-work/apps/<id>.json, the table to
# SUMMARY.md beside them, process logs to $GM_LOG_DIR/apps/<id>/.
#
# PASS: every listed app ran and produced a result file. What the app
# exports, including nothing, is data and does not fail the check. FAIL: an
# app that is listed but not installed, a session that hit its hard timeout
# or ended without a result file, a result file that does not parse, fewer
# than 45 apps listed, or a process left running afterwards.

set -uo pipefail
cd "${GM_REPO:?run through tools/check.sh}" || exit 2

missing=()
for tool in dbus-run-session mutter Xwayland xprop ss gresource python3; do
	command -v "$tool" >/dev/null || missing+=("$tool")
done
python3 -c 'import gi; gi.require_version("Gio", "2.0")' 2>/dev/null || missing+=("python3-gobject")
if grep -q '"packaging": "flatpak"' tests/apps/apps.json; then
	command -v flatpak >/dev/null || missing+=("flatpak")
fi
if ((${#missing[@]} > 0)); then
	echo "summary: not installed: ${missing[*]}"
	exit 1
fi

count=$(python3 - <<'PY'
import json
apps = json.load(open('tests/apps/apps.json'))['apps']
ids = [a['id'] for a in apps]
assert len(ids) == len(set(ids)), 'duplicate ids'
for a in apps:
    for key in ('id', 'toolkit', 'group', 'packaging', 'launch', 'mode'):
        assert key in a, '%s lacks %s' % (a.get('id'), key)
print(len(apps))
PY
)
status=$?
if ((status != 0)); then
	echo "summary: tests/apps/apps.json is not valid"
	exit 1
fi
if [[ -z ${GM_APPS_ONLY:-} ]] && ((count < 45)); then
	echo "summary: $count apps listed, the charter wants at least 45"
	exit 1
fi

args=()
[[ -n ${GM_APPS_ONLY:-} ]] && args+=(--only "$GM_APPS_ONLY")
python3 tools/apps-runner.py "${args[@]}"
status=$?

# Every result file must parse and carry a status
bad=$(python3 - <<'PY'
import json, os
apps = json.load(open('tests/apps/apps.json'))['apps']
only = os.environ.get('GM_APPS_ONLY')
if only:
    apps = [a for a in apps if a['id'] in only.split(',')]
out = os.environ.get('GM_APPS_OUT', '/home/ravi/fildem-work/apps')
bad = []
for a in apps:
    try:
        d = json.load(open(os.path.join(out, a['id'] + '.json')))
        assert d['status'] and 'summary' in d
    except Exception as err:
        bad.append('%s (%s)' % (a['id'], err))
print(', '.join(bad))
PY
)

# Nothing of ours may be left running
left=$(grep -lazs '^GM_APPS_SESSION=' /proc/[0-9]*/environ 2>/dev/null | wc -l)
echo "processes left with GM_APPS_SESSION in their environment: $left"

if [[ -n $bad ]]; then
	echo "summary: result file missing or unreadable: $bad"
	exit 1
fi
if ((left > 0)); then
	echo "summary: $left processes left running after the run"
	exit 1
fi
if ((status != 0)); then
	echo "summary: $(grep -E '^summary: ' "$GM_LOG_DIR/apps.log" 2>/dev/null | tail -n 1 | sed -e 's/^summary: //')"
	exit 1
fi
echo "summary: $(tail -n 3 "${GM_APPS_OUT:-/home/ravi/fildem-work/apps}/SUMMARY.md" | grep -E 'apps,' )"
exit 0
