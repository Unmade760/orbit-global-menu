#!/usr/bin/env bash
# Rebuild the translation template from the extension's sources, merge it into
# every po/<lang>.po, and compile each into the extension's locale/ folder,
# which users get by copying the extension directory.
#
# Run from anywhere: tools/i18n.sh

set -euo pipefail
cd "$(dirname "$0")/.."

uuid=global-menu@unmade.space
domain=global-menu

mapfile -t sources < <(git ls-files -- "$uuid/*.js" "$uuid/prefsPages/*.js")
xgettext --from-code=UTF-8 --language=JavaScript \
	--keyword=_ --keyword=N_ --keyword=ngettext:1,2 --keyword=actionSpec:1 \
	--add-comments=Translators --package-name="$domain" \
	--msgid-bugs-address=https://github.com/Unmade760/orbit-global-menu/issues \
	-o "po/$domain.pot" "${sources[@]}"

for po in po/*.po; do
	lang=$(basename "$po" .po)
	msgmerge --quiet --update --backup=none "$po" "po/$domain.pot"
	mkdir -p "$uuid/locale/$lang/LC_MESSAGES"
	msgfmt --check -o "$uuid/locale/$lang/LC_MESSAGES/$domain.mo" "$po"
done
