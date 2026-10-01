# App coverage harness

Runs each app in `apps.json` alone, under a headless compositor on its own
session bus, and records what menu it exports. It feeds the coverage matrix.
Run it with `tools/check.sh apps` (`GM_APPS_ONLY=gedit,kate` for a subset).

## Files

| File | Job |
| --- | --- |
| `tests/apps/apps.json` | The apps: id, group, toolkit, packaging, launch command, `mode`, desktop id and window class, the env var, flag or pref that turns on a menu export |
| `tools/checks/apps.sh` | The check: prerequisites, runs the runner, checks every result file, checks nothing is left running |
| `tools/apps-runner.py` | One app at a time: private runtime directory and bus, hard timeout, kills the process group, sweeps strays, writes `SUMMARY.md` |
| `tools/apps-session.py` | Runs inside the session: compositor, registrar stub, the app, the probes, the result JSON |

Output: `/home/ravi/fildem-work/apps/<id>.json`, `SUMMARY.md` and
`summary.json` beside them, per-app process logs in
`/home/ravi/fildem-work/logs/apps/<id>/` (`mutter.log`, `app.log`,
`registrar.log`, `session.log`).

## One app, one session

1. The runner makes `/tmp/gm-apps.XXXX` as `XDG_RUNTIME_DIR`, with `HOME`
   and every XDG directory inside it, so no real profile, lock file or
   single-instance socket is reached. The user's display and session bus
   never appear in the environment (it is built from a short allow list).
2. `dbus-run-session --config-file` starts a private bus. The config is the
   distro's `session.conf` with `<listen>` changed to
   `unix:path=<runtime>/bus`, because xdg-dbus-proxy, which flatpak uses,
   cannot follow the abstract socket that `unix:tmpdir=/tmp` gives.
3. `mutter --headless --wayland --virtual-monitor 1280x800` is the
   compositor, as in the `daemon` check. It serves Wayland and starts
   Xwayland on demand.
4. `tests/apps/registrar_stub.py` owns `com.canonical.AppMenu.Registrar`
   before the app starts, unless the row says `"registrar": false`. The
   daemon owns that name in use, and some apps act on it: Qt on xcb and
   Electron register a dbusmenu with it, and LibreOffice hides its own
   menubar when it is there.
5. The app's environment is `HOME` and the XDG directories in the runtime,
   `XDG_CURRENT_DESKTOP=GNOME`, `GSETTINGS_BACKEND=memory`, `NO_AT_BRIDGE=1`,
   `GTK_A11Y=none`, `GTK_USE_PORTAL=0`, `LIBGL_ALWAYS_SOFTWARE=1`, plus the
   row's own `env`. `GDK_DEBUG=no-portals` is left out on purpose: Chrome 153
   (GTK 4) segfaults at start with it set. The app starts. `mode: x11` forces X11 (`GDK_BACKEND=x11`,
   `QT_QPA_PLATFORM=xcb`, `MOZ_ENABLE_WAYLAND=0`); `mode: wayland` leaves
   Wayland first with Xwayland as the fallback.
6. The window is detected as a new `_NET_CLIENT_LIST` entry on the X
   display, or a new client on the Wayland socket (counted with `ss`). A
   Wayland client is connected before it maps a window, so every row then
   waits `settle` seconds (6 by default, more for heavy apps). Nothing can
   read Wayland toplevels from outside a shell, so "window seen" on
   Wayland means connected.
7. Probes, all read-only: bus names that appeared since the baseline and
   whose process is not a session service; the object tree under each
   (Introspect, at most 500 nodes, 10 deep); `org.gtk.Menus.Start` on every
   group reachable from the menubar, then `End`;
   `org.gtk.Actions.DescribeAll` on every action group; `GetLayout` on each
   `com.canonical.dbusmenu` (with `AboutToShow` for lazy submenus); the
   registrar's `GetMenus`; `xprop` on every X11 client; a second read of the
   menus to see whether the item count moved (`menu_stable`).
8. The runner kills the whole process group, then every process whose
   environment still carries `GM_APPS_SESSION=<runtime>`, unmounts
   `doc`/`gvfs` under the runtime and deletes it. `tools/checks/apps.sh`
   then scans `/proc` for survivors.

## Reading a result

`status` is `ok` (the session ran to the end), `no-window` (no window and
no bus name appeared in the time allowed), `crashed` (the launcher died on a
signal or abort before anything appeared), `timeout`, `harness-error` or
`missing` (the launcher is not installed). The last three fail the check;
the others are data. `summary.export` says what was found:

| Value | Meaning |
| --- | --- |
| `org.gtk.Menus` | A menubar model the extension can read today |
| `com.canonical.dbusmenu` | A dbusmenu registered with, or found on, the bus |
| `org.gtk.Actions only` | The app exports actions but no menu; the shortcut menu path has to build it |
| `none` | Nothing on the bus |

Per menu the JSON keeps the full tree. Every item carries `label`,
`action`, `accel` (GTK) or `shortcut` (dbusmenu), and, once matched with
the action dump, `enabled`, `toggle` (`check` or `radio`) and `checked`.
`stats` counts items, submenus, separators, items with an accelerator,
disabled, check and radio items, and items whose action is not in any
exported group.

`shortcuts_window` lists live action names that look like a shortcuts
window (`show-help-overlay`, `shortcuts`) and static hints: resource names
from `gresource list` on the binary and strings such as
`shortcuts-dialog` and `AdwShortcutsDialog`. Accelerators set with
`set_accels_for_action` are not exported over D-Bus, so a GTK 4 app can
show 0 accelerators in its menu and still have shortcuts.

Limits: a Wayland client is connected before it maps a window, and nothing
outside a shell lists Wayland toplevels, so a Wayland row cannot prove a
window is mapped. Electron apps forced to native Wayland (Cider, Obsidian)
never opened a window under headless mutter here, so there is no Electron
Wayland row; the Setup Log's source reading covers that case. The menu is read
once, a few seconds after the window; a menu an app fills only after focus or a
first click is not seen.

## Flatpak

`flatpak run` works on the private bus as it is. What was found:

- The app owns its own well-known name and its menu objects are reachable
  from the host through xdg-dbus-proxy, so `org.gtk.Menus` and
  `org.gtk.Actions` of a flatpak GTK app can be read. The walk finds them
  under the proxy's unique name, not the app's pid.
- A dbusmenu export needs `--talk-name=com.canonical.AppMenu.Registrar`.
  Without it the proxy hides the registrar from the app. The rows that need
  it carry the flag in `launch`; `vscode-flatpak-no-talk` is the control.
- X11 rows add `--nosocket=wayland --socket=x11`.
- `HOME` is the session's temporary directory, so flatpak's per-app data
  (`~/.var/app/<id>`) is fresh and first-run dialogs can appear. The
  installation directory is passed as `FLATPAK_USER_DIR`.

## Adding an app

Add a row to `apps.json` with `id`, `group`, `toolkit`, `packaging`,
`launch`, `mode`; the launcher must exist (`rpm -q`, `flatpak info`). Try it
with `GM_APPS_ONLY=<id> tools/check.sh apps`. Heavy apps (LibreOffice,
Electron, JetBrains, Blender, browsers) get `"heavy": true`, a longer
`settle` and `timeout`; the runner waits for free memory before starting
one.
