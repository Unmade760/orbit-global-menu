# Orbit Global Menu

A menu bar for GNOME. The focused application's menus move out of its window
and into the top panel.

GNOME has no global menu, and most applications no longer export one, so the
extension falls back twice before giving up:

1. Applications that publish a menu over D-Bus get their real one, with
   working checkmarks and greyed-out items. A companion daemon called
   `global-menu` reads it and sends it to the extension as JSON.
2. For 170 applications that publish nothing, the extension ships a menu built
   from the app's documented keyboard shortcuts. Clicking an item sends that
   key combination to the window. This is how an Electron app gets a menu bar
   on Wayland.
3. Everything else gets window, workspace and session actions, so the bar is
   never empty.

Steps 2 and 3 need nothing but GNOME Shell. Step 1 is the only part with
dependencies, and it is optional.

## Installing the extension

Needs GNOME Shell 49 or 50, on Wayland or X11. Nothing else.

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

Install the GTK 3 bindings and dbus-python for your distribution:

```sh
# Fedora
sudo dnf install python3-gobject python3-dbus gtk3

# Debian and Ubuntu
sudo apt install python3-gi python3-dbus gir1.2-gtk-3.0

# Arch
sudo pacman -S python-gobject python-dbus gtk3
```

Then, from the repository:

```sh
pip install --user .
```

Nothing goes in autostart. The extension starts `global-menu` when nobody owns
its bus name and stops the process it started when it is disabled.

On X11 only, `bamf` improves window matching and `libkeybinder` enables the
Alt+Space menu search. Both are optional, and neither does anything on
Wayland. Packaging for Arch and Debian is in `PKGBUILD` and `debian/`.

## Which applications export a menu

Not many, and it depends on the toolkit and the session:

| Toolkit | Exports a menu |
| --- | --- |
| GTK 3 and 4 using `gtk_application_set_menubar` | Yes, on Wayland and X11 |
| Qt 5 and 6 | Yes, under X11 or XWayland |
| Electron | Only under real X11 |
| GtkMenuBar with appmenu-gtk-module | No, broken on Wayland |

The registrar that Qt and Electron use is keyed on an X11 window id, so it
cannot work on Wayland at all. Anything in the last three rows running on
Wayland falls through to a shortcut menu.

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
