# Daemon and shell-session layer for the distros check, Fedora.
#
#   podman build --build-arg BASE=localhost/gm-test:fedora-45 \
#       -t localhost/gm-distros:fedora-45 -f tests/containers/distros-dnf.Containerfile tests/containers
#
# Built on top of dnf.Containerfile by tools/checks/distros.sh and cached by
# tag, so the check runs offline once both layers exist. Everything comes
# from the release's own repositories (fedora:45 also has updates-testing,
# as the base image does):
#   - what the daemon imports on every start: python3-gobject, python3-dbus
#     and the Gtk/Gdk 3 typelib (gtk3)
#   - pip and setuptools, to install the daemon the way the README says
#   - gsettings and gdbus (glib2), runuser (util-linux)
#   - python3-dbusmock, which stands in for logind on the system bus;
#     gnome-shell exits at start without a system bus
# The X11-only extras the daemon imports when it finds no Wayland session
# (Bamf and Keybinder) are installed one by one when the release has them;
# the ones it lacks are listed in /etc/gm-distros/optional-missing.txt.
# Fedora has no appmenu-gtk3-module at all (Setup Log), so it is not tried.
# A plain user, gmtest, runs the daemon and the shell.
ARG BASE=localhost/gm-test:fedora-45
FROM ${BASE}
RUN dnf -y install --setopt=install_weak_deps=False \
		python3 python3-gobject python3-dbus gtk3 \
		python3-pip python3-setuptools \
		glib2 util-linux python3-dbusmock \
	&& mkdir -p /etc/gm-distros \
	&& : >/etc/gm-distros/optional-missing.txt \
	&& for p in bamf bamf-daemon keybinder3; do \
		dnf -y install --setopt=install_weak_deps=False "$p" || echo "$p" >>/etc/gm-distros/optional-missing.txt; \
	done \
	&& dnf clean all \
	&& useradd -m -s /bin/bash gmtest
