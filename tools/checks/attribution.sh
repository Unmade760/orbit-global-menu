#!/usr/bin/env bash
# attribution: no tracked file and no commit names an AI assistant, model or
# agent (product names, co-author trailers, "generated with" lines).
#
# tools/lib/attribution-scan.py does the work: every tracked file plus
# untracked files git does not ignore, and every commit reachable from HEAD
# (message, author, committer). Mapping labels are exempt because they
# quote an application's own menu text. Run through
# tools/check.sh attribution.

set -uo pipefail
cd "${GM_REPO:?run through tools/check.sh}" || exit 2

for tool in git python3; do
	if ! command -v "$tool" >/dev/null; then
		echo "summary: $tool not installed"
		exit 1
	fi
done

python3 "$GM_REPO/tools/lib/attribution-scan.py"
