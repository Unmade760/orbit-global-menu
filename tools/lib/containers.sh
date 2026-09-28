# Distro test images shared by the compat and distros checks. Source it:
#
#   . tools/lib/containers.sh
#   gm_ensure_image fedora-45 "$logfile"   # builds or reuses localhost/gm-test:fedora-45
#
# Each image is one Containerfile under tests/containers/ plus a build
# argument. podman's layer cache makes a rebuild of an unchanged Containerfile
# take a second, so checks call gm_ensure_image every run.
# shellcheck shell=bash

# The supported range, in the charter's order (Ready.md, Supported range).
GM_IMAGE_IDS=(debian-13 ubuntu-26.04 fedora-43 fedora-44 fedora-45)
export GM_IMAGE_IDS

# GNOME major version each image ships.
gm_image_gnome() {
	case $1 in
	debian-13) echo 48 ;;
	fedora-43) echo 49 ;;
	ubuntu-26.04 | fedora-44) echo 50 ;;
	fedora-45) echo 51 ;;
	*) return 1 ;;
	esac
}

gm_image_ref() {
	echo "localhost/gm-test:$1"
}

# Prints the podman build arguments for an image id, one per line.
gm_image_build_args() {
	local dir=${GM_REPO:?}/tests/containers
	case $1 in
	debian-13)
		printf '%s\n' -f "$dir/apt.Containerfile" --build-arg BASE=docker.io/library/debian:trixie
		;;
	ubuntu-26.04)
		printf '%s\n' -f "$dir/apt.Containerfile" --build-arg BASE=docker.io/library/ubuntu:26.04
		;;
	fedora-4[0-9])
		printf '%s\n' -f "$dir/dnf.Containerfile" --build-arg "RELEASE=${1#fedora-}"
		;;
	*) return 1 ;;
	esac
}

# Build the image, or reuse the cached layers. Build output goes to $2.
gm_ensure_image() {
	local id=$1 log=${2:-/dev/null} args
	mapfile -t args < <(gm_image_build_args "$id") || return 1
	((${#args[@]} > 0)) || return 1
	podman build --layers -t "$(gm_image_ref "$id")" "${args[@]}" "${GM_REPO:?}/tests/containers" >"$log" 2>&1
}

# Image id (sha) of a built image, empty when it does not exist.
gm_image_sha() {
	podman image inspect --format '{{.Id}}' "$(gm_image_ref "$1")" 2>/dev/null
}
