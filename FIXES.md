# Fixes for REVIEW-FINDINGS.md

Branch `fix/review-2026-10-09`, based on `until-ready/2026-09-28` (3910fbe).
Every finding was re-checked against the code before it was fixed. One commit
per finding; the finding ID is in each commit body.

Checks on the final commit: `tools/check.sh unit`, `mappings`, `pack` and
`attribution` pass. `lint` reports only the known 4 ruff errors and 3
pyflakes messages in `globalmenu/handlers/global_menu.py`,
`globalmenu/treelib/tree.py` and `globalmenu/utils/fuzzy.py`.

Counts: 33 fixed, 0 skipped, 0 partly fixed.

## Findings

| ID | Status | Commit | Summary |
| --- | --- | --- | --- |
| J1 | fixed | 3669aa3 | Each WindowSwitched carries a request id. The daemon announces it in a new `MenuTreeRequest` signal before every `SendMenuTree`, whose type is unchanged, so old and new extension and daemon versions still work together. A tree for a superseded request is dropped, and a tree is cached under the app it was built for. |
| J2 | fixed | 28ca170 | The 100 ms after-menu delay moves into `keySynth.js` (`sendShortcutAfterMenu`). The shortcut menu and the fallback menu both use it, and `disable()` removes pending sends. |
| J3 | fixed | e2b6ace | Papers and Ptyxis no longer claim "Document Viewer" and "Terminal". |
| J4 | fixed | 582a987 | Nautilus, Loupe, Calculator and File Roller no longer claim "Files", "Image Viewer", "Calculator" and "Archive Manager". |
| J5 | fixed | 722fe47 | 25 items in 15 mappings that sent Ctrl+Alt+arrow or Ctrl+Shift+Alt+arrow are placeholders now. |
| J6 | fixed | e77c458 | Zen "Toggle DOM", Nextcloud "Open Nextcloud in Browser" and QGIS "Pan Map" are placeholders now. |
| J7 | fixed | b4a7f70 | A GMenu entry with both a label and `:section` is followed as a section. |
| J8 | fixed | f767b9f | dbusmenu LayoutUpdated and ItemsPropertiesUpdated changes now call the same `on_changed` push as the GTK path. |
| J9 | fixed | f88dc90 | dbusmenu calls catch `DBusException` and leave an empty tree. The refresh timer resets before any call. |
| J10 | fixed | a5e02e8 | Every call to a client app passes a 2 second timeout. |
| J11 | fixed | 378bec2 | The PKGBUILD source is named `global-menu::`, matching its `cd` lines. |
| J12 | fixed | 6ab635c | The .deb is built with `dpkg-deb --root-owner-group`. |
| M1 | fixed | c6cfcb3 | A blank mapping only applies while the mapping itself is switched on. |
| M2 | fixed | 04a1347 | The extension reads mappings with `ShortcutStore.loadAsync()`, which is cancelled by a newer reload or by `disable()`. The prefs process keeps the sync `load()`. |
| M3 | fixed | d31d9ea | With no window focused, the pending request is superseded, so a re-sent tree for a closed window is dropped. |
| M4 | fixed | b10693e | The stray doc comment sits on `cancelPendingActions()`. |
| M5 | fixed | 8d45fc2 | The choice of menu source uses `hasBarMenus()`, the same test NativeMenu uses to build bar buttons. |
| M6 | fixed | 98b41d6 | A tree equal to the shown one re-applies its state to an open menu. |
| M7 | fixed | 9b981a2 | A repeated item key gets a " #2", " #3" suffix in menu order, for GTK and dbusmenu items. |
| M8 | fixed | f433a58 | Screenshot of Area calls the shell's `showScreenshotUI()` instead of sending Shift+Print. |
| M9 | fixed | 5fa4b0e | The System menu is rebuilt on each open, and Lock Screen, Suspend, Log Out and Power Off are greyed out when SystemActions says they are unavailable. |
| M10 | fixed | fb32053 | "Switch Between Windows" is now "Switch Between Applications". "Switch Windows of Same App" is removed because the shell has no stable call for it. The zh_CN translation is updated. |
| M11 | fixed | 20dbf75 | The mapping editor keeps `"blank": true` on save. |
| M12 | fixed | d6197ed | The app-name container is hidden again whenever the panel shows it while Hide app name is on. |
| M13 | fixed | a2bd8ad | The listed prefs strings are wrapped in `_()`, with zh_CN translations and a recompiled .mo. |
| M14 | fixed | 96b58af | 8 items that sent other shell-grabbed chords are placeholders now (Alt+F2, Shift+Alt+F6, Print, Ctrl+Shift+Alt+R, Ctrl+Alt+Delete, Super+1, Alt+Space). |
| M15 | fixed | a5b242e | FreeCAD uses its own two-key sequences (V 3, V 6, V 7, V S, A C). GParted's and BleachBit's repeated Alt+letter mnemonics are placeholders. |
| M16 | fixed | 352aca0 | The registrar drops a client's windows when its bus name loses its owner. |
| M17 | fixed | b724949 | The menu reader waits up to 10 s for the service's bus name before it starts. |
| M18 | fixed | 9ce24b4 | `GDK_BACKEND=x11` is no longer forced on Wayland. |
| M19 | fixed | da7aedf | The HUD removes its ListWindowActionsSignal receiver when it hides. |
| M20 | fixed | 92297cb | The HUD key on X11 is Ctrl+Super+Space instead of Alt+Space, and a failed grab is logged. The README and PKGBUILD are updated. |
| M21 | fixed | 888e7d1 | The daemon no longer grabs Alt plus each menu mnemonic on X11. |

## Checks only a running GNOME Shell can confirm

Use GNOME Shell 48 and 51 if you can, Wayland unless the step says X11, with
the daemon installed from this branch.

- **J1:** open a large GTK app with a menubar (for example GIMP), then
  alt-tab at once to an app with no menu of its own. The panel must not show
  GIMP's menus while the other app is focused. Alt-tab away and back to the
  second app: GIMP's menus must not appear for it, not even briefly.
- **M3:** focus a GTK app that is the only open window and choose its own
  File > Quit from the panel. When the window is gone, the panel shows
  nothing, and nothing appears about half a second later.
- **J2:** focus an app with no menu and no mapping (for example `xterm`). In
  the fallback menu choose Edit > Select All, then Edit > Copy, and paste
  elsewhere: the app's text was copied. Window > Snap Window Left tiles the
  window.
- **M5:** with an app that exports only a GTK app menu and has a mapping, the
  mapping's menus stay in the bar and the app menu sits under the app name.
- **M6:** open a menu holding a check item while the app toggles it on and
  off by itself (for example a player's Play/Pause state). The check mark
  follows the app while the menu stays open.
- **M8:** choose Screenshot of Area in the fallback menu. The screenshot UI
  opens in area selection mode, and no file is saved straight away.
- **M9:** on a machine with one local user, open the System fallback menu.
  Log Out is greyed out and nothing happens when it is clicked. Lock Screen
  and Power Off stay active.
- **M10:** Window > Switch Between Applications opens the application
  switcher. The Window menu has no "Switch Windows of Same App" item.
- **M12:** turn Hide app name on, then switch the fallback menu off and on in
  the preferences. The app name stays hidden.
- **M2:** log in, or lock and unlock, with many user mappings. The panel
  does not freeze, and an app with a mapping gets its menu within a moment.
  Save a mapping in the preferences: the change appears without a stall.
- **J5, M14, M15:** in VS Code, Obsidian and Konsole, the affected items
  (Copy Line Up, Navigate Back, Move Tab Left and others) are greyed out, and
  no workspace switches when the menus are used. In FreeCAD, Draw Style
  Wireframe switches the 3D view to wireframe.
- **J3, J4:** focus Evince and GNOME Terminal. Each shows its own menus,
  not those of Papers or Ptyxis.
- **J8:** run a Qt app under X11 (`QT_QPA_PLATFORM=xcb`) whose menus change
  after start-up (for example open a document in Okular). The new menus
  appear in the panel without switching windows.
- **M18:** on Wayland with no X11 client running, `pgrep Xwayland` finds
  no process after the daemon starts. Open the HUD with `global-menu-hud`: it
  shows and works, and the compositor chooses its position.
- **M20, M21 (X11 session, gir1.2-keybinder-3.0 installed):** Ctrl+Super+Space
  opens the HUD and Alt+Space still opens GNOME's window menu. In a GTK app
  with a File menu, Alt+F reaches the app, and no separate popup opens near
  the left of the screen.

## Notes

- The zh_CN strings added for M10 and M13 use standard GNOME UI wording but
  were not checked against l10n.gnome.org. A native speaker should look
  them over.
- `tests/py/test_mapping_conflicts.py` lists the shared chords that remain
  across the mappings, each with a reason. About 15 are marked as not yet
  checked against the app source (in clocks, Zen, Firefox, Pinta,
  Transmission, Insomnia, OBS, Shotwell, Evolution, Anki, Evernote and
  Scrivener). They are worth a follow-up.
- `tools/mapping-sources` still holds the records for chords that are now
  placeholders, because they document what the apps bind. The Konsole and
  VLC tests accept a recorded chord the mapping does not send only when the
  item is a placeholder.
- Moving the HUD key from Alt+Space to Ctrl+Super+Space changes a
  documented shortcut on X11.

## Issue #11: long menus cut off on small screens

| ID | Status | Commit | What changed |
|----|--------|--------|--------------|
| #11 | fixed | see git log | The popup keeps the shell's max-height when text alignment rewrites its style, and its items sit in a scroll view, so a long menu scrolls and a submenu near the bottom scrolls into view. |

By-eye check: set the display scale to 200 % on a 1280x1024 monitor, or use a
small work area. Open a menu with 40 or more items (a long Window menu). Wheel
and arrow keys must scroll it, the last item must be reachable, and a submenu
opened near the bottom must scroll into view. With the shortcut labels, blur
and text alignment settings on, the popup must look as before.
