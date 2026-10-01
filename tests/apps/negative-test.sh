#!/usr/bin/env bash
# Negative test for tools/check.sh apps: the check has to FAIL, and leave
# nothing running, when the harness itself breaks. Three cases, each run
# through tools/apps-runner.py with a scratch app list and output directory:
#   hang      the session script sleeps past the hard timeout   -> status timeout
#   no result the session script exits without a result file    -> status harness-error
#   missing   the launcher is not installed                     -> status missing
# and one positive control, a real session with a launcher that is a plain
# sleep: that is data ("no-window"), not a failure of the harness.
#
#   tests/apps/negative-test.sh      (about 1 minute)
#
# Exit 0 when every expectation holds.

set -uo pipefail
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
scratch=$(mktemp -d "${TMPDIR:-/tmp}/gm-apps-neg.XXXXXX")
trap 'rm -rf -- "$scratch"' EXIT
failed=0

expect() {
	local name=$1 want=$2 got=$3
	if [[ $got == "$want" ]]; then
		echo "ok   $name: $got"
	else
		echo "FAIL $name: wanted '$want', got '$got'"
		failed=1
	fi
}

cat >"$scratch/apps.json" <<'JSON'
{"apps": [
 {"id": "neg-hang", "group": "Other", "toolkit": "none", "packaging": "rpm", "mode": "wayland", "launch": ["sleep", "1000"], "timeout": 1, "settle": 1},
 {"id": "neg-missing", "group": "Other", "toolkit": "none", "packaging": "rpm", "mode": "wayland", "launch": ["gm-no-such-program"]},
 {"id": "neg-quiet", "group": "Other", "toolkit": "none", "packaging": "rpm", "mode": "wayland", "launch": ["sleep", "1000"], "timeout": 4, "settle": 1}
]}
JSON
cat >"$scratch/hang.py" <<'PY'
import time
time.sleep(1000)
PY
cat >"$scratch/nores.py" <<'PY'
import sys
sys.exit(3)
PY

run() { # run <only> <session script or empty> [probe budget in seconds]
	local only=$1 script=$2 budget=${3:-3}
	env GM_APPS_JSON="$scratch/apps.json" GM_APPS_OUT="$scratch/out" GM_LOG_DIR="$scratch/logs" \
		GM_APPS_PROBE_BUDGET="$budget" ${script:+GM_APPS_SESSION_SCRIPT=$script} \
		python3 "$repo/tools/apps-runner.py" --only "$only" >"$scratch/run-$only.log" 2>&1
	echo $?
}
status_of() { python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['status'])" "$scratch/out/$1.json" 2>/dev/null; }
left() {
	grep -lazs '^GM_APPS_SESSION=' /proc/[0-9]*/environ 2>/dev/null | wc -l
}

expect "hang: runner exit status" 1 "$(run neg-hang "$scratch/hang.py")"
expect "hang: status" timeout "$(status_of neg-hang)"
expect "hang: processes left" 0 "$(left)"

# Reuse neg-hang's entry for the no-result case
expect "no result: runner exit status" 1 "$(run neg-hang "$scratch/nores.py")"
expect "no result: status" harness-error "$(status_of neg-hang)"

expect "missing: runner exit status" 1 "$(run neg-missing "")"
expect "missing: status" missing "$(status_of neg-missing)"

expect "quiet app: runner exit status" 0 "$(run neg-quiet "" 40)"
expect "quiet app: status" no-window "$(status_of neg-quiet)"
expect "quiet app: processes left" 0 "$(left)"

exit "$failed"
