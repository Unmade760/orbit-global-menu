#!/usr/bin/env bash
# The one entry point for every check in the charter's Ready.md.
#
#   tools/check.sh <name>...   run the named checks
#   tools/check.sh all         run every check except apps
#   tools/check.sh --list      list the checks it can find
#
# A check is a script at tools/checks/<name>.sh. The runner finds them by
# file name, so a new check needs no change here. Contract for a check
# script:
#   - runs with the repo root as its working directory
#   - writes whatever it likes to stdout and stderr; the runner saves all of
#     it to /home/ravi/fildem-work/logs/<name>.log (override with
#     GM_LOG_DIR)
#   - exits 0 on pass, anything else on fail
#   - may print lines starting with "summary: "; the last one becomes the
#     one-line reason on FAIL. Without one, the last non-empty output line
#     is used.
# Environment given to every check: GM_REPO, GM_EXT_DIR, GM_LOG_DIR,
# GM_TOOLS.
#
# Output is exactly one "PASS <name>" or "FAIL <name>: <reason>" line per
# check, then a totals line when more than one check ran. Exit status is 1
# when any check failed, 2 on a usage error.

set -uo pipefail

GM_TOOLS=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
GM_REPO=$(dirname -- "$GM_TOOLS")
GM_EXT_DIR="$GM_REPO/global-menu@unmade.space"
GM_LOG_DIR=${GM_LOG_DIR:-/home/ravi/fildem-work/logs}
export GM_TOOLS GM_REPO GM_EXT_DIR GM_LOG_DIR

# Checks that "all" leaves out because they are long.
EXCLUDED_FROM_ALL=(apps)
# Order for "all"; any other check found runs after these, sorted by name.
PREFERRED_ORDER=(lint schema imports mappings unit attribution pack daemon compat distros)

available_checks() {
	local f
	for f in "$GM_TOOLS"/checks/*.sh; do
		[[ -e $f ]] || continue
		basename -- "$f" .sh
	done | sort
}

checks_for_all() {
	local all name skip x ordered=() seen=" "
	mapfile -t all < <(available_checks)
	for name in "${PREFERRED_ORDER[@]}" "${all[@]}"; do
		[[ $seen == *" $name "* ]] && continue
		[[ -e $GM_TOOLS/checks/$name.sh ]] || continue
		skip=0
		for x in "${EXCLUDED_FROM_ALL[@]}"; do
			[[ $name == "$x" ]] && skip=1
		done
		((skip)) && continue
		seen+="$name "
		ordered+=("$name")
	done
	printf '%s\n' "${ordered[@]}"
}

reason_from_log() {
	local log=$1 reason
	reason=$(grep -E '^summary: ' "$log" | tail -n 1 | sed -e 's/^summary: //')
	if [[ -z $reason ]]; then
		reason=$(grep -vE '^[[:space:]]*$' "$log" | tail -n 1)
	fi
	[[ -z $reason ]] && reason="exited non-zero with no output"
	printf '%s' "${reason:0:300}"
}

run_check() {
	local name=$1 script="$GM_TOOLS/checks/$1.sh" log="$GM_LOG_DIR/$1.log" status
	if [[ ! -f $script ]]; then
		echo "FAIL $name: no such check (tools/checks/$name.sh not found)"
		return 1
	fi
	{
		echo "# tools/check.sh $name, $(date -Iseconds)"
		echo "# git $(git -C "$GM_REPO" rev-parse --short HEAD 2>/dev/null) on $(git -C "$GM_REPO" branch --show-current 2>/dev/null)"
	} >"$log"
	(cd "$GM_REPO" && bash "$script") >>"$log" 2>&1
	status=$?
	echo "# exit status $status" >>"$log"
	if ((status == 0)); then
		echo "PASS $name"
		return 0
	fi
	echo "FAIL $name: $(reason_from_log "$log")"
	return 1
}

main() {
	if (($# == 0)); then
		echo "usage: tools/check.sh <check>... | all | --list" >&2
		echo "checks: $(available_checks | tr '\n' ' ')" >&2
		return 2
	fi
	if [[ $1 == --list ]]; then
		available_checks
		return 0
	fi
	mkdir -p "$GM_LOG_DIR"

	local names=() arg
	for arg in "$@"; do
		if [[ $arg == all ]]; then
			mapfile -t -O "${#names[@]}" names < <(checks_for_all)
		else
			names+=("$arg")
		fi
	done

	local passed=0 failed=0 name
	for name in "${names[@]}"; do
		if run_check "$name"; then
			passed=$((passed + 1))
		else
			failed=$((failed + 1))
		fi
	done
	if ((${#names[@]} > 1)); then
		echo "TOTAL $((passed + failed)) checks: $passed passed, $failed failed"
	fi
	((failed == 0))
}

main "$@"
