#!/usr/bin/env bash
# distros: the daemon and the extension on each supported distribution.
#
# Per image (Ready.md, Supported range):
#   debian-13 (GNOME 48), fedora-43 (49), ubuntu-26.04 and fedora-44 (50),
#   fedora-45 (51)
# the base image from tools/lib/containers.sh (localhost/gm-test:<id>, shared
# with the compat check) gets one more layer from
# tests/containers/distros-{apt,dnf}.Containerfile: the daemon's runtime
# dependencies from that distribution's own repositories, pip, a logind
# stand-in and a test user. Tagged localhost/gm-distros:<id> and rebuilt only
# when a Containerfile changes, so after the first build the check needs no
# network.
#
# Inside, tools/distros/in-container.sh installs the daemon from the repo as
# the README says (and as the deb on Debian and Ubuntu), starts it under
# dbus-run-session and checks its bus names, then runs gnome-shell --headless
# with one virtual monitor under dbus-run-session, enables and disables the
# extension GM_DISTROS_CYCLES times (default 20) through the
# org.gnome.Shell.Extensions D-Bus interface and scans the shell's log.
# Details in the header of that script and of tools/distros/report.py.
#
# Output: one "PASS <id>" or "FAIL <id>: <reasons>" line per image, a JSON
# summary at $GM_LOG_DIR/distros.json (read by the compat auditor for
# Compatibility.md) and every log under $GM_LOG_DIR/distros/<id>/.
#
# Isolation: --network=none, --rm, no host socket, display or session bus is
# mounted; the repo is mounted read-only. The trap removes a running
# container on exit, INT or TERM.
#
# GM_DISTROS_IMAGES="debian-13 fedora-45" limits the run to some images.
# GM_DISTROS_EXT=<dir> tests another copy of the extension (negative tests).
# Run through tools/check.sh distros.

set -uo pipefail
cd "${GM_REPO:?run through tools/check.sh}" || exit 2
# shellcheck source=tools/lib/containers.sh
. "$GM_REPO/tools/lib/containers.sh"

log_dir=${GM_LOG_DIR:-/home/ravi/fildem-work/logs}
out_root=$log_dir/distros
summary_json=$log_dir/distros.json
cycles=${GM_DISTROS_CYCLES:-20}
read -r -a images <<<"${GM_DISTROS_IMAGES:-${GM_IMAGE_IDS[*]}}"

for tool in podman python3; do
	if ! command -v "$tool" >/dev/null; then
		echo "summary: $tool not installed"
		exit 1
	fi
done

current=""
cleanup() {
	trap - EXIT INT TERM
	if [[ -n $current ]]; then
		podman rm -f -t 5 "$current" >/dev/null 2>&1
	fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

family_of() {
	case $1 in
	debian-* | ubuntu-*) echo apt ;;
	fedora-*) echo dnf ;;
	*) return 1 ;;
	esac
}

rm -rf -- "$out_root"
mkdir -p "$out_root"

lines=()
failed=()
for id in "${images[@]}"; do
	dir=$out_root/$id
	mkdir -p "$dir"
	family=$(family_of "$id") || {
		lines+=("FAIL $id: unknown image id")
		failed+=("$id")
		continue
	}
	gnome=$(gm_image_gnome "$id")
	start=$SECONDS

	if ! gm_ensure_image "$id" "$dir/build-base.log"; then
		echo "{\"image\": \"$id\", \"pass\": false, \"problems\": [\"base image build failed, see build-base.log\"]}" >"$dir/result.json"
		lines+=("FAIL $id: base image build failed (see $dir/build-base.log)")
		failed+=("$id")
		continue
	fi
	if ! podman build --layers -t "localhost/gm-distros:$id" \
		--build-arg "BASE=$(gm_image_ref "$id")" \
		-f "$GM_REPO/tests/containers/distros-$family.Containerfile" \
		"$GM_REPO/tests/containers" >"$dir/build.log" 2>&1; then
		echo "{\"image\": \"$id\", \"pass\": false, \"problems\": [\"distros layer build failed, see build.log\"]}" >"$dir/result.json"
		lines+=("FAIL $id: distros layer build failed (see $dir/build.log)")
		failed+=("$id")
		continue
	fi

	ext_mount=()
	if [[ -n ${GM_DISTROS_EXT:-} ]]; then
		ext_mount=(-v "$GM_DISTROS_EXT:/ext:ro")
	fi
	current=gm-distros-$id-$$
	echo "== $id: running (GNOME $gnome, $family, $cycles cycles)"
	timeout 1500 podman run --rm --name "$current" --network=none --memory=3g \
		--security-opt label=disable \
		-v "$GM_REPO:/src:ro" -v "$dir:/out" "${ext_mount[@]}" \
		"localhost/gm-distros:$id" \
		bash /src/tools/distros/in-container.sh "$id" "$family" "$gnome" "$cycles" \
		>"$dir/run.log" 2>&1 &
	# In the background with wait, so INT and TERM reach the trap at once
	wait "$!"
	rc=$?
	current=""
	echo "   container exit $rc after $((SECONDS - start)) s, log $dir/run.log"

	line=$(python3 - "$dir/result.json" "$id" "$rc" <<'EOF'
import json, sys
path, image, rc = sys.argv[1:4]
try:
	res = json.load(open(path))
except (OSError, ValueError):
	print('FAIL %s: no result.json (container exit %s)' % (image, rc))
	sys.exit()
if res.get('pass'):
	print('PASS %s' % image)
else:
	print('FAIL %s: %s' % (image, '; '.join(res.get('problems', ['unknown']))))
EOF
)
	lines+=("$line")
	[[ $line == PASS* ]] || failed+=("$id")
done

python3 - "$summary_json" "$out_root" "$cycles" "$(git rev-parse --short HEAD)" "${images[@]}" <<'EOF'
import datetime, json, os, sys
out, root, cycles, head = sys.argv[1:5]
images = {}
for image in sys.argv[5:]:
	try:
		images[image] = json.load(open(os.path.join(root, image, 'result.json')))
	except (OSError, ValueError) as e:
		images[image] = {'image': image, 'pass': False, 'problems': ['no result.json: %s' % e]}
json.dump({'generated': datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
	'git': head, 'cycles': int(cycles), 'logs': root, 'images': images},
	open(out, 'w'), indent=1)
EOF

echo
printf '%s\n' "${lines[@]}"
echo "JSON summary: $summary_json"
if ((${#failed[@]} > 0)); then
	echo "summary: ${#failed[@]} of ${#images[@]} images fail (${failed[*]}); $(printf '%s | ' "${lines[@]}" | cut -c1-600)"
	exit 1
fi
echo "summary: ${#images[@]} of ${#images[@]} images pass"
