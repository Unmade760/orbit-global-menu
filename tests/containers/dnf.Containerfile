# GNOME Shell test image for Fedora.
#
#   podman build --build-arg RELEASE=45 \
#       -t localhost/gm-test:fedora-45 -f tests/containers/dnf.Containerfile tests/containers
#
# Built and cached by tools/lib/containers.sh, which the compat and distros
# checks share. Same contents as apt.Containerfile: the shell, mutter and
# their typelibs, gjs, the GTK 4 and libadwaita typelibs, g-ir-generate
# (gobject-introspection-devel on Fedora) and a session bus. The fedora:45
# image enables updates-testing, which is where GNOME 51.0 is until the
# release.
ARG RELEASE=45
FROM registry.fedoraproject.org/fedora:${RELEASE}
RUN dnf -y install --setopt=install_weak_deps=False \
		gnome-shell gjs gtk4 libadwaita \
		gobject-introspection-devel dbus-daemon \
	&& dnf clean all
