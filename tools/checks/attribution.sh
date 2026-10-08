#!/usr/bin/env bash
# attribution: no tracked file and no commit contains a word from the
# private deny list kept outside the repo.
#
# tools/lib/attribution-scan.py does the work: every tracked file (this
# wrapper and the scanner included) plus untracked files git does not
# ignore, and every commit reachable from HEAD (message, author, committer).
# The list is read from $GM_ATTRIBUTION_WORDS, or from
# /home/ravi/fildem-work/attribution-words.txt; without it the check fails.
# Mapping labels are exempt because they quote an application's own menu
# text. Run through tools/check.sh attribution.

set -uo pipefail
cd "${GM_REPO:?run through tools/check.sh}" || exit 2

for tool in git python3; do
	if ! command -v "$tool" >/dev/null; then
		echo "summary: $tool not installed"
		exit 1
	fi
done

python3 "$GM_REPO/tools/lib/attribution-scan.py"
