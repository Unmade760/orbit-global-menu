#!/usr/bin/env bash
# Negative test for tools/check.sh distros. Copies the extension to a scratch
# directory, plants the breakages the check claims to catch, runs the check
# on the copy in one image, and asserts that each shows up in result.json.
#
#   tests/distros/negative-test.sh [image-id]   (default fedora-44; about
#                                               40 s once the image exists)
#
# Planted:
#   - shell-version lists every version, so the as-shipped pass runs cycles
#   - enable() throws on its second call: that cycle must end in ERROR and
#     the JS ERROR must be blamed on the extension
#   - disable() prints a warning with the [global-menu] tag: blamed
#   - enable() prints a Gjs CRITICAL with no mention of the extension:
#     it must show up as new against the baseline
# Exit 0 when every expectation holds. The real logs are not touched.

set -uo pipefail
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
image=${1:-fedora-44}
scratch=$(mktemp -d "${TMPDIR:-/tmp}/gm-distros-neg.XXXXXX")
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

python3 - "$ext/metadata.json" <<'EOF'
import json, sys
path = sys.argv[1]
meta = json.load(open(path))
meta['shell-version'] = ['48', '49', '50', '51']
json.dump(meta, open(path, 'w'), indent=2)
EOF
plant extension.js "		globalThis.gmNegativeTest = (globalThis.gmNegativeTest ?? 0) + 1; if (globalThis.gmNegativeTest === 2) throw new Error('planted by the distros negative test');" '	enable() {'
plant extension.js "		console.warn('[global-menu] planted warning from the distros negative test');" '	disable() {'
plant extension.js "		GLib.log_structured('Gjs', GLib.LogLevelFlags.LEVEL_CRITICAL, {MESSAGE: 'unattributed planted critical'});" '	enable() {'

logs=$scratch/logs
GM_DISTROS_IMAGES=$image GM_DISTROS_CYCLES=3 GM_DISTROS_EXT=$ext GM_LOG_DIR=$logs \
	"$repo/tools/check.sh" distros
result=$logs/distros/$image/result.json

python3 - "$result" <<'EOF'
import json, sys
res = json.load(open(sys.argv[1]))
problems = ' | '.join(res.get('problems', []))
shell = res['shell'].get('as_shipped', {})
cycles = shell.get('cycles', [])
blamed = '\n'.join(b['text'] for b in shell.get('scan', {}).get('blamed', []))
new = '\n'.join(b['text'] for b in shell.get('scan', {}).get('new_with_extension', []))
checks = [
	('the image fails', res.get('pass') is False),
	('first enable is ACTIVE', shell.get('first_state') == 'ACTIVE'),
	('cycle 2 ends in ERROR', len(cycles) >= 2 and cycles[1].get('enabled_state') == 'ERROR'),
	('the problems name the unclean cycles', 'cycles clean' in problems),
	('the thrown error is blamed', 'planted by the distros negative test' in blamed),
	('the tagged warning is blamed', 'planted warning' in blamed),
	('the untagged critical is new against the baseline', 'unattributed planted critical' in new),
	('the baseline ran', res['shell'].get('baseline', {}).get('started') is True),
]
failed = 0
for name, ok in checks:
	print('%s %s' % ('ok' if ok else 'not ok', name))
	failed += not ok
print('problems: ' + problems[:800])
sys.exit(1 if failed else 0)
EOF
