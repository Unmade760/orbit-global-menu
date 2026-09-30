# Daemon and shell-session layer for the distros check, Debian and Ubuntu.
#
#   podman build --build-arg BASE=localhost/gm-test:debian-13 \
#       -t localhost/gm-distros:debian-13 -f tests/containers/distros-apt.Containerfile tests/containers
#
# Built on top of apt.Containerfile by tools/checks/distros.sh and cached by
# tag, so the check runs offline once both layers exist. Everything comes
# from the distribution's own archive:
#   - what the daemon imports on every start: python3-gi, python3-dbus and
#     the Gtk/Gdk 3 typelib (gir1.2-gtk-3.0)
#   - what debian/DEBIAN/control names in Depends (appmenu-gtk3-module)
#   - what building the deb with the Makefile needs (python3-setuptools,
#     make; dpkg-deb is in the base system)
#   - pip, to try the README's install line
#   - gsettings and gdbus (libglib2.0-bin), runuser (util-linux)
#   - python3-dbusmock, which stands in for logind on the system bus;
#     gnome-shell exits at start without a system bus
#   - at-spi2-core, the accessibility bus every GNOME desktop has; without
#     it each GTK process, the daemon too, warns at start
# The X11-only extras the daemon imports when it finds no Wayland session
# (the Bamf and Keybinder typelibs) and the Recommends of the control file
# are installed one by one when the archive has them; the ones it lacks are
# listed in /etc/gm-distros/optional-missing.txt.
# A plain user, gmtest, runs the daemon and the shell.
ARG BASE=localhost/gm-test:debian-13
FROM ${BASE}
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
	&& apt-get install -y --no-install-recommends \
		python3 python3-gi python3-dbus gir1.2-gtk-3.0 \
		appmenu-gtk3-module python3-setuptools python3-pip make \
		libglib2.0-bin util-linux python3-dbusmock at-spi2-core \
	&& mkdir -p /etc/gm-distros \
	&& : >/etc/gm-distros/optional-missing.txt \
	&& for p in gir1.2-bamf-3 bamfdaemon gir1.2-keybinder-3.0 libkeybinder-3.0-0; do \
		apt-get install -y --no-install-recommends "$p" || echo "$p" >>/etc/gm-distros/optional-missing.txt; \
	done \
	&& rm -rf /var/lib/apt/lists/* \
	&& useradd -m -s /bin/bash gmtest
