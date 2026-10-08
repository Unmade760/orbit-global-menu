#!/usr/bin/env bash
# Negative test for tools/check.sh attribution. Builds a scratch git repo
# with copies of the scanner and its wrapper, points them at a made-up deny
# list, plants one mention of each kind the check claims to catch, and
# asserts that the check fails on each with the right file and line or
# commit, passes on a mapping label, and fails when the list is missing,
# empty or does not compile. The made-up list keeps every real deny-list
# word out of this file.
#
#   tests/attribution/negative-test.sh      (about 3 s)
#
# Exit 0 when every expectation holds.

set -uo pipefail
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
scratch=$(mktemp -d "${TMPDIR:-/tmp}/gm-attribution-neg.XXXXXX")
trap 'rm -rf -- "$scratch"' EXIT

# Keep the machine's git config out of the scratch repo (signing, hooks).
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null
export GIT_AUTHOR_NAME=Tester GIT_AUTHOR_EMAIL=tester@example.invalid
export GIT_COMMITTER_NAME=Tester GIT_COMMITTER_EMAIL=tester@example.invalid

word=zorbquux
words=$scratch/words.txt
printf '%s\n' '# made-up deny list' '' "\\b${word}\\b" '\bplugh-?[0-9]\b' >"$words"

work=$scratch/repo
mapping=global-menu@unmade.space/shortcuts/apps/demo.json
mkdir -p "$work/tools/lib" "$work/tools/checks" "$work/${mapping%/*}"
cp "$repo/tools/lib/attribution-scan.py" "$work/tools/lib/"
cp "$repo/tools/checks/attribution.sh" "$work/tools/checks/"
printf 'print(1)\n' >"$work/hello.py"
printf '{"app": "demo", "items": [{"label": "Open"}]}\n' >"$work/$mapping"
git -C "$work" init -q
git -C "$work" add -A
git -C "$work" commit -q -m 'start'
base=$(git -C "$work" rev-parse HEAD)

out='' status=0 list=$words
run() {
	out=$(cd "$work" && env GM_REPO="$work" GM_ATTRIBUTION_WORDS="$list" \
		bash tools/checks/attribution.sh 2>&1)
	status=$?
}

# Back to the clean commit with the made-up list.
reset() {
	git -C "$work" reset -q --hard "$base"
	git -C "$work" clean -fdq
	list=$words
}

fails=0
expect() {
	local name=$1 want=$2 pattern=${3-}
	if ((status == want)) && { [[ -z $pattern ]] || grep -qE -- "$pattern" <<<"$out"; }; then
		echo "ok   $name"
	else
		echo "FAIL $name (exit $status, want $want, pattern '$pattern')"
		printf '%s\n' "$out" | sed 's/^/  | /'
		fails=$((fails + 1))
	fi
}

reset
run
expect 'clean repo passes' 0 'summary: no mention'

reset
printf '# note: %s here\n' "$word" >>"$work/hello.py"
run
expect 'word in a code comment fails with file and line' 1 '^hello\.py:2: '

reset
printf 'see %s\n' "$word" >"$work/notes.txt"
run
expect 'word in an untracked file fails' 1 '^notes\.txt:1: '

reset
printf 'ignored.txt\n' >>"$work/.git/info/exclude"
printf '%s\n' "$word" >"$work/ignored.txt"
run
expect 'word in an ignored file passes' 0 'summary: no mention'

reset
git -C "$work" commit -q --allow-empty -m "fix $word thing"
run
expect 'word in a commit message fails with the commit' 1 \
	"^commit $(git -C "$work" rev-parse --short=10 HEAD): "

reset
git -C "$work" commit -q --allow-empty -m 'plain' --author="$word <a@example.invalid>"
run
expect 'word in a commit author fails with the commit' 1 \
	"^commit $(git -C "$work" rev-parse --short=10 HEAD): "

reset
printf 'also plugh-4 here\n' >>"$work/hello.py"
run
expect 'second list entry matches' 1 '^hello\.py:2: '

reset
printf '# %s\n' "$word" >>"$work/tools/lib/attribution-scan.py"
run
expect 'the scanner scans itself' 1 '^tools/lib/attribution-scan\.py:[0-9]+: '

reset
printf '# %s\n' "$word" >>"$work/tools/checks/attribution.sh"
run
expect 'the wrapper is scanned too' 1 '^tools/checks/attribution\.sh:[0-9]+: '

reset
printf '{"app": "demo", "items": [{"label": "%s"}]}\n' "$word" >"$work/$mapping"
run
expect 'word in a mapping label passes' 0 'summary: no mention'

reset
printf '{"app": "demo", "title": "%s", "items": [{"label": "Open"}]}\n' "$word" >"$work/$mapping"
run
expect 'word in a mapping field other than label fails' 1 "^${mapping//./\\.}:"

reset
printf '%s\n' "# $word" '\bplugh\b' >"$scratch/commented.txt"
list=$scratch/commented.txt
printf '%s\n' "$word" >>"$work/hello.py"
run
expect 'a commented list line is not a pattern' 0 'summary: no mention'

reset
list=$scratch/missing.txt
run
expect 'missing list fails and names its path' 1 "summary: .*$scratch/missing\.txt"

reset
printf '%s\n' '# nothing' '' >"$scratch/empty.txt"
list=$scratch/empty.txt
run
expect 'empty list fails' 1 'summary: .*no entries'

reset
printf '%s\n' '(unclosed' >"$scratch/bad.txt"
list=$scratch/bad.txt
run
expect 'list that does not compile fails' 1 'summary: .*does not compile'

if ((fails > 0)); then
	echo "negative test: $fails expectation(s) failed"
	exit 1
fi
echo "negative test: every planted mention reported"
