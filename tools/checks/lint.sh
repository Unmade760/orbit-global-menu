#!/usr/bin/env bash
# lint: every linter the charter names, all run even when one fails.
#   eslint     GNOME Shell's config (eslint.config.js at the repo root) on
#              every .js under global-menu@unmade.space/, --max-warnings 0.
#              eslint and eslint-config-gnome come from tools/node_modules,
#              installed from tools/package-lock.json on first run.
#   ruff       ruff.toml at the repo root, on globalmenu/.
#   pyflakes   on globalmenu/, minus the vendored treelib/ (pyflakes has no
#              config file, and ruff already covers treelib with the right
#              per-file ignores).
#   ShellCheck: every shell script in the repo, tracked or new files ending
#              in .sh or starting with a sh/bash/dash shebang.
# Run through tools/check.sh lint.

set -uo pipefail
cd "${GM_REPO:?run through tools/check.sh}" || exit 2

failures=()

section() { printf '\n=== %s ===\n' "$1"; }

# Section: eslint
section eslint
eslint_bin=tools/node_modules/.bin/eslint
if [[ ! -x $eslint_bin ]]; then
	echo "tools/node_modules missing, running npm ci"
	npm ci --prefix tools --no-audit --no-fund || true
fi
if [[ ! -x $eslint_bin ]]; then
	failures+=("eslint not installed (npm ci --prefix tools failed)")
else
	"$eslint_bin" --version
	out=$("$eslint_bin" --max-warnings 0 global-menu@unmade.space 2>&1)
	status=$?
	printf '%s\n' "$out"
	if ((status != 0)); then
		count=$(grep -oE '[0-9]+ problems?' <<<"$out" | tail -n 1)
		failures+=("eslint ${count:-exit $status}")
	fi
fi

# Section: ruff
section ruff
if ! command -v ruff >/dev/null; then
	failures+=("ruff not installed")
else
	ruff --version
	out=$(ruff check --no-cache --output-format concise globalmenu 2>&1)
	status=$?
	printf '%s\n' "$out"
	if ((status != 0)); then
		count=$(grep -oE 'Found [0-9]+ errors?' <<<"$out" | grep -oE '[0-9]+ errors?')
		failures+=("ruff ${count:-exit $status}")
	fi
fi

# Section: pyflakes
section pyflakes
if ! command -v pyflakes >/dev/null; then
	failures+=("pyflakes not installed")
else
	pyflakes --version
	mapfile -t pyfiles < <(find globalmenu -name '*.py' -not -path 'globalmenu/treelib/*' | sort)
	out=$(pyflakes "${pyfiles[@]}" 2>&1)
	status=$?
	printf '%s\n' "$out"
	if ((status != 0)); then
		failures+=("pyflakes $(grep -c . <<<"$out") messages")
	fi
fi

# Section: shellcheck
section shellcheck
if ! command -v shellcheck >/dev/null; then
	failures+=("shellcheck not installed")
else
	shellcheck --version | sed -n 2p
	scripts=()
	while IFS= read -r -d '' f; do
		[[ -f $f ]] || continue
		case $f in
		tools/node_modules/*) continue ;;
		*.sh) scripts+=("$f") ;;
		*)
			if head -n 1 -- "$f" | grep -qE '^#!.*\b(sh|bash|dash)\b'; then
				scripts+=("$f")
			fi
			;;
		esac
	done < <(git ls-files -z --cached --others --exclude-standard)
	printf 'checking: %s\n' "${scripts[*]}"
	out=$(shellcheck -x -P SCRIPTDIR "${scripts[@]}" 2>&1)
	status=$?
	printf '%s\n' "$out"
	if ((status != 0)); then
		failures+=("shellcheck $(grep -cE '^In .* line [0-9]+:' <<<"$out") findings")
	fi
fi

echo
if ((${#failures[@]} > 0)); then
	joined=$(printf '%s; ' "${failures[@]}")
	echo "summary: ${joined%; }"
	exit 1
fi
echo "summary: eslint, ruff, pyflakes and shellcheck clean"
