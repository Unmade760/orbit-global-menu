#!/usr/bin/env bash
# compat: every GNOME API the extension touches exists in every supported
# version, or sits behind a runtime guard.
#
# Supported range (Ready.md): GNOME 48 to 51. One distro image per version,
# built from tests/containers/ and cached (tools/lib/containers.sh):
#   debian-13 = 48, fedora-43 = 49, ubuntu-26.04 and fedora-44 = 50,
#   fedora-45 = 51
#
# Steps:
#   1. In each image, dump the typelibs of GLib, Gio, GTK 4, libadwaita,
#      mutter (Meta, Clutter, Cogl, Mtk) and gnome-shell (Shell, St) to GIR
#      (tools/compat/in-container.sh dump), and condense them to one JSON
#      index (tools/compat/gir2json.py). Cached per image id under
#      $GM_COMPAT_CACHE, so reruns skip it.
#   2. tools/compat/resolve.mjs analyze: parse the extension and each
#      version's gnome-shell JS (the worktrees under $GM_GNOME_SRC), follow
#      types through both, and list every external symbol used, with the
#      guard around each use.
#   3. In each image, tools/compat/probe.js checks each GI symbol under that
#      image's gjs (presence, and gjs's own argument count for introspected
#      functions), evaluates the JS features and globals the code uses, and
#      the stubbed module graph from tools/lib/imports-driver.js is parsed
#      and linked under that gjs.
#   4. tools/compat/resolve.mjs report: one table, symbol x version, to
#      $GM_LOG_DIR/compat.json and compat-summary.md. FAIL when a symbol is
#      missing, or called with an argument count gjs rejects, in a supported
#      version with no runtime guard at the call site. A try block around
#      the call is listed but does not count as a guard.
#
# Nothing touches the host session: containers run with --network=none and
# are removed on exit, gjs on the host only copies files.
# Run through tools/check.sh compat.

set -uo pipefail
cd "${GM_REPO:?run through tools/check.sh}" || exit 2
# shellcheck source=tools/lib/containers.sh
. "$GM_REPO/tools/lib/containers.sh"

log_dir=${GM_LOG_DIR:-/home/ravi/fildem-work/logs}
work=$log_dir/compat
cache_root=${GM_COMPAT_CACHE:-/home/ravi/fildem-work/cache/compat}
gnome_src=${GM_GNOME_SRC:-/home/ravi/src/gnome/versions}
# GM_COMPAT_EXT points the check at another copy of the extension (the
# negative test in tests/compat/ uses it).
ext=${GM_COMPAT_EXT:-$GM_REPO/global-menu@unmade.space}
compat=$GM_REPO/tools/compat

for tool in node python3 podman gjs; do
	if ! command -v "$tool" >/dev/null; then
		echo "summary: $tool not installed"
		exit 1
	fi
done
if [[ ! -d $GM_REPO/tools/node_modules/espree || ! -d $GM_REPO/tools/node_modules/eslint-scope ]]; then
	echo "tools/node_modules missing, running npm ci"
	npm ci --prefix tools --no-audit --no-fund || true
fi
if [[ ! -d $GM_REPO/tools/node_modules/espree ]]; then
	echo "summary: espree not installed (npm ci --prefix tools failed)"
	exit 1
fi

rm -rf -- "$work"
mkdir -p "$work/results" "$cache_root"

# Every container is started with --rm; this also removes one that is still
# running when the check is interrupted.
containers=()
cleanup() {
	trap - EXIT INT TERM
	local c
	for c in "${containers[@]}"; do
		podman rm -f "$c" >/dev/null 2>&1
	done
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# Runs one throwaway container: no network, repo read-only, $2 writable at
# /work and at its own path (the stubbed copy imports its stubs by absolute
# path).
run_in_image() {
	local id=$1 workdir=$2 name
	shift 2
	name="gm-compat-$id-$$"
	containers+=("$name")
	podman run --rm --name "$name" --network=none --memory=2g \
		--security-opt label=disable \
		-v "$GM_REPO:/repo:ro" -v "$workdir:/work" -v "$workdir:$workdir" \
		"$(gm_image_ref "$id")" "$@"
}

shell_js_for() {
	local dir
	dir=$(find "$gnome_src" -maxdepth 1 -type d -name "gnome-shell-$1.*" | sort -V | tail -n 1)
	[[ -n $dir && -d $dir/js ]] && echo "$dir/js"
}

# Step 1: images and GIR indexes
targets=()
failed_images=()
for id in "${GM_IMAGE_IDS[@]}"; do
	major=$(gm_image_gnome "$id")
	mkdir -p "$work/results/$id"
	echo "=== $id (GNOME $major) ==="
	if ! gm_ensure_image "$id" "$work/results/$id/build.log"; then
		echo "image build failed, see $work/results/$id/build.log" | tee "$work/results/$id/error.txt"
		failed_images+=("$id: image build failed")
		continue
	fi
	sha=$(gm_image_sha "$id")
	cache="$cache_root/$id-${sha:0:12}"
	if [[ ! -s $cache/index.json ]]; then
		rm -rf -- "$cache"
		mkdir -p "$cache"
		if ! run_in_image "$id" "$cache" bash /repo/tools/compat/in-container.sh dump /work >"$cache/dump.log" 2>&1 ||
			! python3 "$compat/gir2json.py" "$cache/index.json" "$cache"/gir/*.gir >>"$cache/dump.log" 2>&1; then
			cat "$cache/dump.log"
			echo "GIR dump failed, see $cache/dump.log" | tee "$work/results/$id/error.txt"
			failed_images+=("$id: GIR dump failed")
			rm -f "$cache/index.json"
			continue
		fi
	fi
	echo "GIR index $cache/index.json"
	sed 's/^/  /' "$cache/versions.txt"
	[[ -e $cache/dump-failed.txt ]] && sed 's/^/  /' "$cache/dump-failed.txt"
	cp "$cache/versions.txt" "$work/results/$id/versions.txt"
	shell_js=$(shell_js_for "$major")
	if [[ -z $shell_js ]]; then
		echo "no gnome-shell-$major.* worktree under $gnome_src" | tee "$work/results/$id/error.txt"
		failed_images+=("$id: no gnome-shell $major source")
		continue
	fi
	echo "gnome-shell JS from $shell_js"
	targets+=(--target "$id:$major:$shell_js:$cache/index.json")
done
if ((${#targets[@]} == 0)); then
	echo "summary: no image usable: ${failed_images[*]}"
	exit 1
fi

# Step 2: static analysis
echo
echo "=== analyze ==="
if ! node "$compat/resolve.mjs" analyze --ext "$ext" "${targets[@]}" \
	--out "$work/analysis.json" --probe "$work/probe.json"; then
	echo "summary: resolve.mjs analyze failed"
	exit 1
fi

# Step 3: the stubbed module graph (built by the host gjs), then the probe
# and the parse inside every image
if ! env -u DISPLAY -u WAYLAND_DISPLAY -u DBUS_SESSION_BUS_ADDRESS GIO_USE_VFS=local \
	gjs -m "$GM_REPO/tools/lib/imports-driver.js" stub "$ext" "$work/stubbed" >"$work/stub.log" 2>&1; then
	cat "$work/stub.log"
	echo "summary: could not build the stubbed copy for the in-image parse"
	exit 1
fi
env -u DISPLAY -u WAYLAND_DISPLAY -u DBUS_SESSION_BUS_ADDRESS GIO_USE_VFS=local \
	gjs -m "$GM_REPO/tools/lib/imports-driver.js" classify "$ext" 2>/dev/null |
	grep -E '^(load|parse) ' >"$work/modules.txt"

echo
echo "=== probe ==="
for ((i = 1; i < ${#targets[@]}; i += 2)); do
	id=${targets[i]%%:*}
	if ! run_in_image "$id" "$work" bash /repo/tools/compat/in-container.sh probe /work/probe.json "/work/results/$id" \
		>"$work/results/$id/probe-run.log" 2>&1; then
		cat "$work/results/$id/probe-run.log"
	fi
	printf '%s: ' "$id"
	cat "$work/results/$id/probe-shell.log" "$work/results/$id/probe-prefs.log" 2>/dev/null | grep -E '^probe ' | tr '\n' ' '
	awk -F'\t' '$2 != 0 {bad++} END {printf "parse: %d modules, %d failed\n", NR, bad}' "$work/results/$id/parse.txt"
	[[ -s $work/results/$id/parse.log ]] && cat "$work/results/$id/parse.log"
done

# Step 4: the table
echo
echo "=== report ==="
node "$compat/resolve.mjs" report --analysis "$work/analysis.json" --results "$work/results" \
	--out "$log_dir/compat.json" --summary "$log_dir/compat-summary.md"
status=$?
echo "table: $log_dir/compat.json, summary: $log_dir/compat-summary.md"
if ((${#failed_images[@]} > 0)); then
	echo "summary: images unusable: ${failed_images[*]}"
	status=1
fi
((status == 0))
