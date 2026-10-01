# Orbit Global Menu

A menu bar for GNOME. The focused application's menus move out of its window
and into the top panel.

GNOME has no global menu, and most applications no longer export one, so the
extension falls back twice before giving up:

1. Applications that publish a menu over D-Bus get their real one, with
   working checkmarks and greyed-out items. A companion daemon called
   `global-menu` reads it and sends it to the extension as JSON.
2. For 285 applications that publish nothing, the extension ships a menu built
   from the app's documented keyboard shortcuts. Clicking an item sends that
   key combination to the window. This is how an Electron app gets a menu bar
   on Wayland unless you switch on its own export (see
   [docs/enabling-menus.md](docs/enabling-menus.md)).
3. Everything else gets window, workspace and session actions, so the bar is
   never empty.

Steps 2 and 3 need nothing but GNOME Shell. Step 1 is the only part with
dependencies, and it is optional.

## Installing the extension

Needs GNOME Shell 48 to 51. Wayland on every version; Xorg only on 48 (Debian 13).
Nothing else.

```sh
git clone https://github.com/Unmade760/orbit-global-menu.git
cd orbit-global-menu
cp -r 'global-menu@unmade.space' ~/.local/share/gnome-shell/extensions/
glib-compile-schemas ~/.local/share/gnome-shell/extensions/'global-menu@unmade.space'/schemas
```

Log out and back in. GNOME Shell cannot load a new extension into a running
Wayland session. Then:

```sh
gnome-extensions enable global-menu@unmade.space
```

The menu bar should appear as soon as you focus a window.

## Installing the daemon

Skip this unless you want the menus applications export themselves. Without
it the extension still works, and says so once in the journal instead of
failing.

Debian and Ubuntu mark the system Python as externally managed (PEP 668), so
`pip install --user .` fails there with `externally-managed-environment`. On
those two, build the package and let `apt` install its dependencies.

### Debian 13 and Ubuntu 26.04

```sh
sudo apt install git make python3-setuptools
git clone https://github.com/Unmade760/orbit-global-menu.git
cd orbit-global-menu
make build
sudo apt install ./global-menu_*.deb
```

`make build` writes `global-menu_<version>_all.deb` into the repository.
`apt install` then pulls in `python3-gi`, `python3-dbus`, `gir1.2-gtk-3.0` and
`appmenu-gtk3-module`. Once it is installed, `make clean` removes the
build files and the `.deb`.

### Fedora

```sh
sudo dnf install python3-gobject python3-dbus gtk3
pip install --user .
```

Run `pip` from the repository. Fedora has no `appmenu-gtk3-module`, so GTK 3
apps with an in-window menubar stay on the shortcut menu.

### Arch

```sh
sudo pacman -S python-gobject python-dbus gtk3
```

`PKGBUILD` in the repository builds a package from there. It has not been run
on Arch.

### After installing

Nothing goes in autostart. The extension starts `global-menu` when nobody owns
its bus name and stops the process it started when it is disabled.

On Xorg only, Bamf improves window matching and Keybinder enables the Alt+Space
menu search. Both are optional and do nothing on Wayland. The deb recommends
`gir1.2-bamf-3`, `bamfdaemon` and `gir1.2-keybinder-3.0`; on Fedora the
packages are `bamf` and `keybinder3`, on Arch `bamf` and `libkeybinder3`.
Packaging for Arch and Debian is in
`PKGBUILD` and `debian/`.

## Which applications export a menu

Few do by default, and what an app needs depends on its toolkit. Applications
that publish nothing get the shortcut menu below, so the bar is never empty.

| Toolkit | Exports a menu | Switch |
| --- | --- | --- |
| GTK 3 and 4 using `gtk_application_set_menubar` | Yes, on Wayland and Xorg | none |
| GTK 3 with an in-window `GtkMenuBar` | Through `appmenu-gtk3-module`, not tested end to end | load the module for that app; Debian, Ubuntu and Arch only |
| Qt 5 and 6 | Under XWayland or Xorg, not on native Wayland | `QT_QPA_PLATFORM=xcb` |
| Electron | Under XWayland or Xorg | `--ozone-platform=x11`; VS Code also `window.titleBarStyle` native |
| Chrome and Chromium | Under XWayland or Xorg | `--ozone-platform=x11` |
| Firefox | Under XWayland or Xorg, not in the Flathub build | `widget.gtk.global-menu.enabled` and `MOZ_ENABLE_WAYLAND=0` |
| LibreOffice | Yes, with its GTK 3 plugin | none |
| JetBrains IDEs and Java Swing | No | none, shortcut menu only |

Qt, Electron, Chrome, Chromium and Firefox register their menu with a
registrar on the session bus, which the daemon provides. Start those apps after
the extension is enabled. The exact steps, per-app launcher overrides and the
Flatpak permissions are in [docs/enabling-menus.md](docs/enabling-menus.md).

## Shortcut menus

The built-in mappings live in
`global-menu@unmade.space/shortcuts/apps`. Each is one JSON file naming
the application, the identifiers it is recognised by, and its menus.

Preferences has an editor for them: pick an application, click the shortcut
button on an item, and press the combination the way GNOME Settings does it.
Editing a built-in writes a copy to
`~/.config/global-menu/shortcuts/apps` and leaves the built-in alone.
Individual applications can be switched off from the same list.

The file format is written up in [docs/shortcut-mappings.md](docs/shortcut-mappings.md).

## Preferences

General turns the shortcut menus or the generic fallback off. Applications
holds the mapping list and its editor.

Appearance covers popup translucency, corner radius, the pointer arrow, button
spacing, font size, and whether the workspace pill stays in the panel. It can
also blur what is behind a popup, which needs
[Blur My Shell](https://extensions.gnome.org/extension/3193/blur-my-shell/)
installed and does nothing without it.

## Credits

The daemon and the D-Bus plumbing come from
[Fildem](https://github.com/gonzaarcr/Fildem), which is itself a fork of
gnomehud. Reading an application's exported menu off the bus is that project's
work.

The generic fallback menu is adapted from Global Menu for GNOME
(`globalmenu@ShiroOSL.github.io`).

## License

GPL-3.0-or-later. See [LICENSE.txt](LICENSE.txt).
