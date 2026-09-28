# GNOME Shell test image for Debian and Ubuntu.
#
#   podman build --build-arg BASE=docker.io/library/debian:trixie \
#       -t localhost/gm-test:debian-13 -f tests/containers/apt.Containerfile tests/containers
#
# Built and cached by tools/lib/containers.sh, which the compat and distros
# checks share. Only packages from the distribution's own archive: the shell,
# mutter and their typelibs, gjs, the GTK 4 and libadwaita typelibs the
# preferences window loads, g-ir-generate to dump typelibs as GIR, and a
# session bus. Checks add what else they need in a layer of their own.
ARG BASE=docker.io/library/debian:trixie
FROM ${BASE}
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
	&& apt-get install -y --no-install-recommends \
		gnome-shell gjs gir1.2-adw-1 gir1.2-gtk-4.0 \
		gobject-introspection dbus ca-certificates \
	&& rm -rf /var/lib/apt/lists/*
