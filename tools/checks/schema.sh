#!/usr/bin/env bash
# schema: glib-compile-schemas --strict --dry-run on the extension's schemas
# directory. --dry-run writes no gschemas.compiled, so the tree stays clean.
# Run through tools/check.sh schema.

set -uo pipefail
cd "${GM_REPO:?run through tools/check.sh}" || exit 2

dir=global-menu@unmade.space/schemas
if ! command -v glib-compile-schemas >/dev/null; then
	echo "summary: glib-compile-schemas not installed"
	exit 1
fi
mapfile -t files < <(find "$dir" -name '*.gschema.xml' | sort)
if ((${#files[@]} == 0)); then
	echo "summary: no *.gschema.xml in $dir"
	exit 1
fi
printf 'schema file: %s\n' "${files[@]}"
out=$(glib-compile-schemas --strict --dry-run "$dir" 2>&1)
status=$?
printf '%s\n' "$out"
if ((status != 0)); then
	echo "summary: glib-compile-schemas --strict: $(grep -v '^$' <<<"$out" | head -n 1)"
	exit 1
fi
echo "summary: ${#files[@]} schema file(s) compile with --strict"
