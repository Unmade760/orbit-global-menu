# Enabling application menus

Most applications publish no menu on GNOME Wayland. For those the extension draws a menu from the app's documented shortcuts, which needs no setup. This page is for the other route: getting an application to publish its own menu, so you see its real items with working checkmarks, greyed-out entries and live updates.

Each toolkit has a different switch, and some have none. Set a switch for one application at a time, in its launcher, as described under [Setting a switch for one app](#setting-a-switch-for-one-app). None of these needs a session-wide environment variable, and setting one for every app changes how all your other programs run.

## Before you start

The daemon from the README has to be installed. It owns `com.canonical.AppMenu.Registrar` on the session bus, the name Qt, Chromium, Electron and Firefox register their menus with, and the extension starts it when it is enabled. Start each application after the extension is enabled. Qt creates no menu object at all if the registrar is missing when the app starts.

Xorg exists on GNOME 48 only (Debian 13). On an Xorg session none of the `--ozone-platform=x11`, `QT_QPA_PLATFORM=xcb` or `MOZ_ENABLE_WAYLAND=0` switches below are needed, because the apps already run on X11.

## What each toolkit needs

| Toolkit or app | On GNOME Wayland | Switch | Measured |
| --- | --- | --- | --- |
| GTK 3 and 4 apps that call `set_menubar()` | Exports | none | yes |
| GTK 3 apps with an in-window `GtkMenuBar` | Exports through `appmenu-gtk3-module` | load the module for that app | no |
| Qt 5 and Qt 6, KDE apps | Exports under XWayland only | `QT_QPA_PLATFORM=xcb` | yes |
| Electron: VS Code, Obsidian, Discord | Exports under XWayland only | `--ozone-platform=x11` | yes |
| Chrome, Chromium | Exports under XWayland only | `--ozone-platform=x11` | yes |
| Firefox | Exports under XWayland only | `widget.gtk.global-menu.enabled` and `MOZ_ENABLE_WAYLAND=0` | yes, not in Flathub |
| LibreOffice | Exports | none | yes |
| JetBrains IDEs, Java Swing | No export path | none, shortcut menu only | yes |

"Measured" means the `tools/check.sh apps` run on 2026-10-01 saw the app put a menu on a private session bus. Where the column says no, the row follows the toolkit's source code and has not been run end to end.

### GTK 3 and GTK 4 with a menubar

An app that sets a menubar with `gtk_application_set_menubar()` publishes it over `org.gtk.Menus`, and mutter 48 to 51 passes the bus name and object path to the shell. Nothing to switch on.

### GTK 3 with an in-window menubar

An app that draws its own `GtkMenuBar` publishes nothing until `appmenu-gtk3-module` converts the bar.

- Package: `appmenu-gtk3-module` on Debian 13 (25.04-1), Ubuntu 26.04 (25.04-1build1) and Arch (`appmenu-gtk-module`, 25.04). Fedora 43, 44 and 45 have no package.
- Switch: the Debian and Arch packages of the daemon install `/usr/lib/environment.d/60-global-menu-gtk-module.conf`, which adds `appmenu-gtk-module` to `GTK_MODULES` for every app started after the next login. With a pip install, put the same line in `~/.config/environment.d/60-global-menu-gtk-module.conf`:

	```
	GTK_MODULES=${GTK_MODULES:+$GTK_MODULES:}appmenu-gtk-module
	```

	For one app only, start it with `GTK_MODULES=appmenu-gtk-module`.
- On Wayland the module's code path is gated by the GSettings key `org.appmenu.gtk-module run-on-wayland`, which defaults to true. The module also hides the in-window bar when a registrar is on the bus.
- Debian ships a systemd user unit in `appmenu-gtk-module-common` that adds the module to `GTK_MODULES` for the whole session. Whether the package enables it by default has not been checked.
- Not tested end to end. The module is read from source, not run on a Wayland session in this project.

### Qt 5 and Qt 6

Qt publishes `com.canonical.dbusmenu` and registers it with the registrar, which keys the menu on an X11 window id. On native Wayland Qt 6.9.1 and later skip the registration, and earlier versions (Debian 13 ships 6.8.2) register an id that is not a window. The Wayland client only speaks KDE's appmenu protocol, which mutter does not implement.

- Switch: `QT_QPA_PLATFORM=xcb`, so the app runs under XWayland.
- The registrar has to be on the bus before the app starts.
- Measured with Qt 6 on `xcb`: Kate 230 items, Dolphin 322. On native Wayland the same menu is on the bus and nothing ties it to a window.
- Qt 5 registers with no platform check and exports under `xcb` too: VLC (Qt 5) published 93 items. Native Wayland is not measured for Qt 5.

### Electron

VS Code, Obsidian, Discord and other Electron apps load `libdbusmenu-glib` at run time, and only the X11 backend contains the menu code. Chromium 140 made the platform follow the session, so on GNOME Wayland Electron apps run native Wayland unless told otherwise.

- Switch: start the app with `--ozone-platform=x11`.
- `libdbusmenu-glib` has to be installed: `libdbusmenu-glib4` on Debian and Ubuntu, `libdbusmenu` on Fedora, `libdbusmenu-glib` on Arch.
- Measured: Obsidian 25 items, Discord 13.
- VS Code also needs `"window.titleBarStyle": "native"` in its `settings.json`. Measured: 221 items. With the default custom title bar it publishes no menu.

### Chrome and Chromium

The X11 backend turns on the global menu. The Wayland backend turns it on only when the compositor offers KDE's appmenu protocol, and mutter does not.

- Switch: `--ozone-platform=x11`, with the registrar on the bus.
- Measured: Chrome 45 items, Chromium 43. On native Wayland both publish nothing. Brave published nothing on X11 either, so it is not in the working list.

### Firefox

Firefox exports its menu through libdbusmenu, off by default.

- Switch: set `widget.gtk.global-menu.enabled` to `true` in `about:config`, and start Firefox with `MOZ_ENABLE_WAYLAND=0` so it runs on XWayland.
- Measured on the Fedora 44 package: 63 items, 35 with accelerators.
- The Flathub build does nothing with the pref. It ships no `libdbusmenu` file in the app or in its runtime. Use the distribution package.
- Thunderbird reads the same prefs. Not measured.

### LibreOffice

The GTK 3 VCL plugin, the default on GNOME, exports a menubar for every window. Nothing to switch on. Writer measured 668 items on Wayland and X11. When a registrar is on the bus LibreOffice hides its own in-window menubar. If LibreOffice picked another plugin, `SAL_USE_VCLPLUGIN=gtk3` brings the GTK 3 one back. The Qt 6 plugin (`SAL_USE_VCLPLUGIN=qt6`) follows the Qt row and needs `QT_QPA_PLATFORM=xcb`.

### JetBrains IDEs and Java Swing

No switch works on GNOME Wayland. JetBrains removed its own Linux global menu in 2024 (change IJPL-156149), and Swing apps publish nothing by themselves. IntelliJ IDEA from Flathub, and SwingSet2 on JDK 25 and 26 without a Java agent, published no menu on X11. These apps get the shortcut menu.

Two third-party routes exist for X11 or XWayland and have not been tried here: the jayatana Java agent (Ubuntu 26.04 only) for Swing, and the "Global Menu and Decoration" plugin (JetBrains Marketplace id 25530) for the IDEs.

## Setting a switch for one app

Edit the launcher, not your profile. Copy the app's `.desktop` file into your own applications folder and change its `Exec=` line. Your copy wins over the system one.

```sh
cp /usr/share/applications/org.kde.kate.desktop ~/.local/share/applications/
```

Then edit `~/.local/share/applications/org.kde.kate.desktop`, for every `Exec=` line in it:

```ini
# Qt
Exec=env QT_QPA_PLATFORM=xcb kate %U

# Electron or Chromium
Exec=code --ozone-platform=x11 %F

# Firefox
Exec=env MOZ_ENABLE_WAYLAND=0 firefox %u

# GTK 3 app with an in-window menubar
Exec=env GTK_MODULES=appmenu-gtk-module gedit %U
```

Keep the original arguments and field codes (`%U`, `%F`, `%u`) from the system file. A terminal launch takes the same form: `env QT_QPA_PLATFORM=xcb kate`, or `code --ozone-platform=x11`.

### Flatpak

A Flatpak app also needs the sandbox to let it reach X11 and the registrar. The `apps` check ran these command lines:

```sh
# Qt (Kate, Telegram)
flatpak run --nosocket=wayland --socket=x11 \
	--talk-name=com.canonical.AppMenu.Registrar \
	--env=QT_QPA_PLATFORM=xcb org.kde.kate

# Electron or Chromium (Obsidian, Discord, VS Code, Chrome)
flatpak run --nosocket=wayland --socket=x11 \
	--talk-name=com.canonical.AppMenu.Registrar \
	md.obsidian.Obsidian --ozone-platform=x11
```

Without `--talk-name=com.canonical.AppMenu.Registrar` the sandbox blocks the registration and the app exports nothing. Firefox from Flathub cannot export a menu at all, as above.

## Sources

Every row of the table comes from the app's own code or documentation, checked on 2026-09-28 to 2026-10-01.

- GTK on Wayland: [gtkapplication-wayland.c](https://gitlab.gnome.org/GNOME/gtk/-/raw/main/gtk/gtkapplication-wayland.c) calls `gdk_wayland_toplevel_set_dbus_properties`. Mutter implements the receiving side in `src/wayland/meta-wayland-gtk-shell.c`, 48.0 and 51.0.
- appmenu-gtk3-module: [support.c](https://gitlab.com/vala-panel-project/vala-panel-appmenu/-/raw/master/subprojects/appmenu-gtk-module/src/support.c) has the Wayland branch (`GDK_IS_WAYLAND_DISPLAY`). Package versions are on [packages.debian.org](https://packages.debian.org/trixie/appmenu-gtk3-module) and [packages.ubuntu.com](https://packages.ubuntu.com/resolute/appmenu-gtk3-module).
- Qt: [qtbase fa1fab99](https://github.com/qt/qtbase/commit/fa1fab994e76c19a08903e9b641732ce388a30bd) "dbusmenu: Skip registration with the registrar on Wayland". [qwaylandappmenu.cpp](https://codebrowser.dev/qt6/qtbase/src/plugins/platforms/wayland/qwaylandappmenu.cpp.html) uses `org_kde_kwin_appmenu`.
- Electron: [global_menu_bar_x11.cc](https://github.com/electron/electron/blob/main/shell/browser/ui/views/global_menu_bar_x11.cc) loads `libdbusmenu-glib.so` with `dlopen`. [electron#48001](https://github.com/electron/electron/issues/48001) records the Chromium 140 platform default.
- Chromium: [ozone_platform_x11.cc](https://raw.githubusercontent.com/chromium/chromium/main/ui/ozone/platform/x11/ozone_platform_x11.cc) sets `supports_global_application_menus = true`. [ozone_platform_wayland.cc](https://raw.githubusercontent.com/chromium/chromium/main/ui/ozone/platform/wayland/ozone_platform_wayland.cc) gates it on `org_kde_kwin_appmenu_manager`.
- Firefox: [bug 1883184](https://bugzilla.mozilla.org/show_bug.cgi?id=1883184) added the `widget.gtk.global-menu.enabled` pref, off by default. The Arch wiki documents [`MOZ_ENABLE_WAYLAND=0`](https://wiki.archlinux.org/title/Firefox).
- LibreOffice: [gtkframe.cxx](https://raw.githubusercontent.com/LibreOffice/core/master/vcl/unx/gtk3/gtkframe.cxx) exports the menu model and watches `com.canonical.AppMenu.Registrar`.
- JetBrains: [intellij-community 3362652](https://github.com/JetBrains/intellij-community/commit/336265215c1ae9bf9fd7f9c23ebfabc8fc810743) "IJPL-156149 Drop support of GLobalMenuLinux".
