#!/usr/bin/env bash
# Runs inside a localhost/gm-test:<id> image (tests/containers/), started by
# tools/checks/compat.sh with the repo mounted read-only at /repo and a
# writable work directory at /work.
#
#   in-container.sh dump  /work/out     GIR of every typelib the extension
#                                       can reach, plus versions.txt
#   in-container.sh probe /work/probe.json /work/out
#                                       runs tools/compat/probe.js twice (shell
#                                       and preferences namespaces), then parses
#                                       and links every extension module under
#                                       this gjs (tools/lib/imports-driver.js)
#                                       from the stubbed copy in /work/stubbed

set -euo pipefail

# Private typelib directories: mutter's (Meta, Clutter, Cogl, Mtk) and
# gnome-shell's (Shell, St). Their shared libraries live in the same place.
private_dirs() {
	find /usr/lib /usr/lib64 \( -name 'Meta-*.typelib' -o -name 'St-*.typelib' \) \
		-printf '%h\n' 2>/dev/null | sort -u
}

private_path() {
	local dirs
	mapfile -t dirs < <(private_dirs)
	local IFS=:
	echo "${dirs[*]}"
}

cmd_dump() {
	local out=$1 gi_path d f ns
	mkdir -p "$out/gir"
	gi_path=$(private_path)
	{
		echo "gnome-shell $(gnome-shell --version 2>/dev/null | awk '{print $NF}')"
		echo "gjs $(gjs --version 2>/dev/null | awk '{print $NF}')"
		if command -v rpm >/dev/null; then
			for p in gnome-shell mutter gjs gtk4 libadwaita glib2; do
				echo "pkg $p $(rpm -q --qf '%{VERSION}-%{RELEASE}' "$p" 2>/dev/null)"
			done
		else
			for p in gnome-shell mutter-common gjs libgtk-4-1 libadwaita-1-0 libglib2.0-0t64; do
				echo "pkg $p $(dpkg-query -W -f '${Version}' "$p" 2>/dev/null)"
			done
		fi
		echo "typelib-dirs $gi_path"
		echo "os $(sed -n 's/^PRETTY_NAME=//p' /etc/os-release | tr -d '"')"
	} >"$out/versions.txt"

	# Every typelib in the private directories, and the system ones the
	# extension and its preferences import (Gtk and Gdk at 4.0 only, since
	# gi://Gtk means GTK 4 in the preferences process).
	local wanted=(GLib-2.0 GObject-2.0 Gio-2.0 GModule-2.0 Gtk-4.0 Gdk-4.0 Gsk-4.0
		Adw-1 Graphene-1.0 Pango-1.0 PangoCairo-1.0 cairo-1.0 GDesktopEnums-3.0
		freetype2-2.0 Atk-1.0 GdkPixbuf-2.0 xlib-2.0 xfixes-4.0
		GL-1.0 Gvc-1.0 NM-1.0 PolkitAgent-1.0 Polkit-1.0 GWeather-4.0 Gcr-4 Gck-2
		AccountsService-1.0 IBus-1.0 GnomeBluetooth-3.0 GnomeDesktop-4.0 Soup-3.0
		ICal-3.0 ECal-2.0 EDataServer-1.2 Rsvg-2.0 Json-1.0 Xdp-1.0 XdpGtk4-1.0)
	local files=()
	for d in ${gi_path//:/ }; do
		for f in "$d"/*.typelib; do
			[[ -e $f ]] && files+=("$f")
		done
	done
	for ns in "${wanted[@]}"; do
		f=$(find /usr/lib /usr/lib64 -path '*/girepository-*/'"$ns"'.typelib' 2>/dev/null | head -n 1)
		[[ -n $f ]] && files+=("$f")
	done
	# gi-decompile-typelib (GLib's libgirepository-2.0) first: the older
	# g-ir-generate aborts halfway through GObject-2.0 and Gtk-4.0 on every
	# image. A dump counts only when the XML is complete.
	local failed=() tool
	for f in "${files[@]}"; do
		ns=$(basename "$f" .typelib)
		for tool in gi-decompile-typelib g-ir-generate; do
			command -v "$tool" >/dev/null || continue
			GI_TYPELIB_PATH=$gi_path "$tool" "$f" >"$out/gir/$ns.try" 2>"$out/gir/$ns.err" || true
			if tail -c 64 "$out/gir/$ns.try" | grep -q '</repository>'; then
				mv "$out/gir/$ns.try" "$out/gir/$ns.gir"
				rm -f "$out/gir/$ns.err" "$out/gir/$ns.partial"
				break
			fi
			# Keep the longest incomplete dump; gir2json.py salvages it
			if [[ ! -e $out/gir/$ns.partial ]] ||
				(($(stat -c %s "$out/gir/$ns.try") > $(stat -c %s "$out/gir/$ns.partial"))); then
				mv "$out/gir/$ns.try" "$out/gir/$ns.partial"
			else
				rm -f "$out/gir/$ns.try"
			fi
		done
		if [[ ! -e $out/gir/$ns.gir ]]; then
			failed+=("$ns")
			[[ -e $out/gir/$ns.partial ]] && mv "$out/gir/$ns.partial" "$out/gir/$ns.gir"
		fi
	done
	echo "dumped $((${#files[@]} - ${#failed[@]})) of ${#files[@]} typelibs"
	if ((${#failed[@]} > 0)); then
		echo "incomplete dump, salvaged by gir2json.py: ${failed[*]}" | tee "$out/dump-failed.txt" >&2
	fi
}

cmd_probe() {
	local list=$1 out=$2 gi_path mode
	mkdir -p "$out"
	gi_path=$(private_path)
	for mode in shell prefs; do
		env -u DISPLAY -u WAYLAND_DISPLAY -u DBUS_SESSION_BUS_ADDRESS \
			GI_TYPELIB_PATH="$gi_path" LD_LIBRARY_PATH="$gi_path" \
			GIO_USE_VFS=local GSETTINGS_BACKEND=memory \
			gjs -m /repo/tools/compat/probe.js "$mode" "$list" "$out/probe-$mode.json" \
			>"$out/probe-$mode.log" 2>&1 || echo "probe $mode exited $?" >>"$out/probe-$mode.log"
	done

	# Parse and link every module of the stubbed copy under this gjs. The
	# stub step ran on the host; see tools/checks/imports.sh for how it works.
	local rel row status result
	: >"$out/parse.txt"
	while IFS= read -r row; do
		rel=${row#* }
		set +e
		result=$(env -u DISPLAY -u WAYLAND_DISPLAY -u DBUS_SESSION_BUS_ADDRESS \
			GI_TYPELIB_PATH="$gi_path" LD_LIBRARY_PATH="$gi_path" \
			GIO_USE_VFS=local GSETTINGS_BACKEND=memory \
			dbus-run-session -- gjs -m /repo/tools/lib/imports-driver.js parse "/work/stubbed/$rel" 2>&1)
		status=$?
		set -e
		printf '%s\t%s\t%s\n' "$rel" "$status" "$(grep -E '^(OK|ERR) ' <<<"$result" | tail -n 1 | tr '\t' ' ')" >>"$out/parse.txt"
		if ((status != 0)); then
			printf '%s\n' "$result" | sed "s|^|    [$rel] |" >>"$out/parse.log"
		fi
	done <"/work/modules.txt"
}

case ${1:-} in
dump) cmd_dump "${2:?output directory}" ;;
probe) cmd_probe "${2:?probe list}" "${3:?output directory}" ;;
*)
	echo "usage: in-container.sh dump OUT | probe LIST OUT" >&2
	exit 2
	;;
esac
