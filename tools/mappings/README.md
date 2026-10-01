# mapping-tools

Command line tools that pull keyboard shortcuts and menus out of an application's source code, turn them into a Global Menu mapping (`global-menu@unmade.space/shortcuts/apps/<app>.json`, format in `docs/shortcut-mappings.md`), and prove every shortcut in a mapping against the source it came from.

The proof is the point. Shortcuts pulled in bulk from app sources can be misread or invented. `verify-mapping` accepts a shortcut only when a cited source line, at a cited commit, holds that exact chord, or when a cited web quote holds it and `rloop verify` finds the quote on the page. Everything else fails.

Every tool is a CLI in `bin/`, prints JSON on stdout, and has `--help`. Python 3 standard library only, plus `git`. `normalize --gjs` and the tests need `gjs`; URL records need `rloop` on `PATH` (or `$RLOOP`).

## One app, start to finish

```sh
T=tools/mappings/bin
M=global-menu@unmade.space/shortcuts/apps

$T/fetch-source gnome-text-editor https://gitlab.gnome.org/GNOME/gnome-text-editor.git
$T/extract-shortcuts ~/fildem-work/sources/gnome-text-editor > gte.extract.json
$T/desktop-ids ~/fildem-work/sources/gnome-text-editor > gte.desktop.json

# An existing mapping: propose a record for each item, then check them
$T/draft-sources $M/text-editor.json gte.extract.json > text-editor.sources.json
$T/verify-mapping $M/text-editor.json text-editor.sources.json

# A new app: draft the mapping and its records from the source, then check them
$T/draft-mapping kate.extract.json ktexteditor.extract.json --app kate --name Kate \
    --desktop kate.desktop.json --out-dir draft/
$T/verify-mapping draft/kate.json draft/kate.sources.json
```

A mapping ships only when `verify-mapping` exits 0. The SOURCES.json file travels with the mapping so the proof can be re-run at any time.

## The tools

### fetch-source ID URL [--ref REF] [--path P ...]

Shallow, blobless clone into `/home/ravi/fildem-work/sources/ID` (or `--root`, or `$MAPPING_SOURCES`). `--ref` takes a branch, tag or commit hash. An existing clone of the same URL is reused and moved to `--ref` if one is given; a clone of another URL under the same id is refused. `--path` narrows a large tree with a sparse checkout.

```json
{"id": "kate", "url": "https://invent.kde.org/utilities/kate.git", "ref": null,
 "commit": "038bfab9f15694d71288c40d9d7feb87f53bac1b", "path": "/home/ravi/fildem-work/sources/kate",
 "reused": false, "sparse": []}
```

### extract-shortcuts DIR [--all] [--kind K] [--path PREFIX] [--no-errors] [--summary]

A deterministic scan (same tree, same output) for shortcut declarations and menu definitions. Test, vendored, build and translation directories, and macOS-only files (`menu.darwin.ts`, `Default (OSX).sublime-keymap`) are skipped unless `--all`. Files named for Windows are scanned and their rows tagged `"platform": "windows"`, because apps such as Zettlr use their Windows menu on Linux too.

Output: `{root, commit, url, stats, shortcuts, menus, actions}`. Each shortcut row:

| Field | Meaning |
| --- | --- |
| `accel_raw` | the text as the source wrote it |
| `accel` | the same chord in the mapping grammar, or `null` with `error` when the grammar cannot express it |
| `label`, `action` | what the source says the shortcut does, when it says it |
| `file`, `line` | where; the line is the one holding the key token |
| `kind` | which declaration form (table below) |
| `context` | shortcut-window section, DocBook menu path, VS Code `when` clause |
| `via` | for standard shortcuts: the upstream table line the default came from |
| `label_source`, `action_source` | the label or action was found in another file (same action name, or a constant) |

`menus` holds menu trees (GMenu `<menu>` and Blueprint `menu`, KXMLGUI `.rc` menubars, Qt Designer menus, Electron templates) with each item's label, action, accelerator and `accel_line` (the line that proves the accelerator). `actions` lists named actions that have a label but no shortcut, used to label menu items defined elsewhere.

Kinds:

| Toolkit | Kind | Source form |
| --- | --- | --- |
| GTK | `gmenu-accel` | `<attribute name="accel">` in a `.ui` menu, `accel:` in a `.blp` menu |
| | `gtk-shortcuts-window`, `adw-shortcuts-dialog` | `GtkShortcutsShortcut` / `AdwShortcutsItem` `accelerator` (alternatives, `...` ranges and `+` sequences expanded), with the group title as context |
| | `gtk-set-accels` | `set_accels_for_action` in C, Vala, Python, Rust, JS (also through a named array), Python `create_action(name, cb, [accels])`, relm4 `set_accelerators_for_action::<T>` |
| | `gtk-binding` | `gtk_widget_class_add_binding*`, `add_binding_action`, `gtk_widget_add_accelerator`, keysym plus modifier mask |
| | `gtk-shortcut` | `GtkShortcut` trigger in `.ui`/`.blp`, `gtk_shortcut_trigger_parse_string`, keyval triggers, with the named action nearby |
| | `gtk-accel-table`, `gtk-accel-literal` | `{ "win.x", { "<Primary>t", NULL } }` tables; any other `"<Primary>x"` string |
| | `gtk-builder-accelerator` | GTK 3 `<accelerator key= modifiers=>` |
| Qt, KDE | `kstandardaction`, `kxmlgui-standard-action` | `KStandardAction::save(...)`, standard action names in `.rc` files; defaults from kconfig |
| | `kstandardshortcut` | `KStandardShortcut::preferences()` |
| | `qt-standard-key` | `QKeySequence::Copy` and friends, GNOME scheme defaults from qtbase |
| | `qt-shortcut` | `QKeySequence(...)`, `QKeySequence::fromString`, `Qt::CTRL \| Qt::Key_S`, strings given to `setShortcut`/`setDefaultShortcut(s)`; label and action read back from the `QAction` variable |
| | `qt-designer`, `kxmlgui`, `qml-shortcut` | Designer `.ui` actions, `.rc` `ActionProperties`, QML `Shortcut { sequence(s) }` and `Action { shortcut }` |
| Electron, web | `electron-menu`, `electron-role` | menu templates with `accelerator:` (ternaries resolved for Linux, computed values reported as errors), role items and role submenus (`editMenu`) with Electron's own defaults |
| | `electron-accel-literal`, `js-key-literal`, `js-keybinding` | `'CmdOrCtrl+X'` strings, Mousetrap/hotkeys/tinykeys strings, `{ key: 'Ctrl-Tab' }` objects named by their property |
| | `vscode-keybinding`, `vscode-keymod` | keybindings JSON and `package.json` `contributes` (titles from `package.nls.json`); `KeyMod`/`KeyCode`/`KeyChord` registrations with the `linux` override, `isWeb` resolved false, ids through constants |
| | `codemirror-keymap`, `zed-keymap`, `sublime-keymap` | CodeMirror keymaps and `extraKeys`, Zed `bindings`, `.sublime-keymap` |
| Java | `java-keystroke`, `jetbrains-keymap` | `KeyStroke.getKeyStroke` (strings and `VK_` with masks), JetBrains keymaps and `plugin.xml` (Mac keymaps left out) |
| Docs | `docbook-menuchoice`, `docbook-keycombo` | DocBook `<menuchoice>` with its menu path, `<keycombo>` in tables and variable lists |
| | `mallard`, `doc-text`, `doc-yaml` | Mallard `<keyseq>`/`<key>`, Markdown tables, `<kbd>`, code and bold spans, list items, YAML keymaps |

Prose is never read as a shortcut: "Press Enter to confirm" gives nothing. A key counts only inside key markup, in a table column about keys, or with a modifier.

### normalize ACCEL [ACCEL ...] [--from auto|gtk|gdk|qt|electron|java|vscode|text] [--gjs]

Any dialect to the mapping grammar (`<Ctrl><Shift>S`, modifiers in the order Ctrl, Shift, Alt, Super, punctuation by keysym name, sequences space-separated). `--gjs` also runs the result through the extension's own `parseAccelerator()` in `keySynth.js`. Exit 1 if any input fails.

```sh
$ bin/normalize "Qt::CTRL | Qt::SHIFT | Qt::Key_L" "KeyChord(KeyMod.CtrlCmd | KeyCode.KeyK, KeyCode.KeyS)" \
    "GDK_KEY_s, GDK_CONTROL_MASK | GDK_SHIFT_MASK" "<kbd>Ctrl</kbd>+<kbd>.</kbd>" --gjs
{"results": [
  {"input": "Qt::CTRL | Qt::SHIFT | Qt::Key_L", "from": "qt", "accel": "<Ctrl><Shift>L", "extension_parses": true},
  {"input": "KeyChord(...)", "from": "vscode", "accel": "<Ctrl>K S", "extension_parses": true},
  {"input": "GDK_KEY_s, ...", "from": "gdk", "accel": "<Ctrl><Shift>S", "extension_parses": true},
  {"input": "<kbd>Ctrl</kbd>+<kbd>.</kbd>", "from": "text", "accel": "<Ctrl>period", "extension_parses": true}]}
```

`<Meta>`, AltGr, F13 and up, media keys and mouse buttons are rejected, as the extension rejects them.

### verify-mapping MAPPING.json SOURCES.json [--src DIR] [--sources-root DIR] [--failures] [--no-cache]

The gate. For every mapping item with a shortcut it needs a record whose evidence holds:

- `{file, line, commit[, repo]}`: the file as it is at that commit (`git show COMMIT:FILE` in the clone) has, on lines `line-3` to `line+3`, a token for the same chord. The extractor's rows for that file are tried first (`"via": "extractor"`), then a plain token scan of those seven lines (`"via": "token"`). The token scan reads GTK strings, `Ctrl+S` text in any spelling, Qt enums, GDK constants, `VK_` expressions, `KeyMod` expressions, standard key names, Electron roles, Mallard, DocBook and `<kbd>` markup. A multi-chord sequence also matches consecutive chords separated by a space or comma.
- `{url, quote}`: the quote holds a token for the chord, and `rloop verify --quote QUOTE --url URL` exits 0. Passes are cached in `~/.cache/mapping-tools/rloop-verify.json` (`$MAPPING_TOOLS_CACHE`).

A record may also carry `shortcut`; it must be the same chord as the mapping's. An item passes when any one of its records passes. Placeholders (no shortcut) are skipped. Records that match no item are listed as `orphans`. Exit 0 when nothing fails, 1 otherwise.

A record's clone is `repos[repo].path`, else `$MAPPING_SOURCES/<repo>` (default `/home/ravi/fildem-work/sources/<repo>`), else `--src`. If the commit is missing from the clone, the item fails and says to run `fetch-source ... --ref COMMIT`.

SOURCES.json:

```json
{
  "format": 1,
  "app": "text-editor",
  "repos": {"gnome-text-editor": {"url": "https://gitlab.gnome.org/GNOME/gnome-text-editor.git",
                                  "commit": "65c089a1b75ccf6e50f3e8e339b299a0ee729880"}},
  "items": [
    {"path": ["File", "Save"], "shortcut": "<Ctrl>S", "repo": "gnome-text-editor",
     "file": "src/editor-window.ui", "line": 367, "commit": "65c089a1b75ccf6e50f3e8e339b299a0ee729880"},
    {"path": ["Edit", "Insert Emoji"], "shortcut": "<Ctrl>period",
     "url": "https://help.gnome.org/...", "quote": "Press Ctrl+. to insert an emoji"}
  ]
}
```

`path` is the chain of labels from the top-level menu to the item. Unknown keys (such as the `match` block `draft-sources` writes) are ignored.

What a pass and a failure look like:

```json
{"path": ["File", "Save"], "shortcut": "<Ctrl>S", "status": "pass",
 "evidence": {"file": "src/editor-window.ui", "commit": "65c089a1...", "cited_line": 367,
              "via": "extractor", "kind": "gmenu-accel", "line": 367, "token": "<control>s"}}
{"path": ["Edit", "Sort Lines"], "shortcut": "<Ctrl><Alt>S", "status": "fail",
 "reason": "lines 397-403 of src/editor-window.c hold no token for <Ctrl><Alt>S"}
```

### desktop-ids DIR [--all]

What the running app is called, for a mapping's `identifiers`: `.desktop` files (also `.desktop.in`, `.desktop.in.in`, intltool `_Name`), the installed name meson gives a template (`output: '@0@.desktop'.format(app_id)`, with the release id preferred over a Devel profile), `@VAR@` placeholders, CMake install rules, AppStream metainfo (`<id>`, `<launchable type="desktop-id">`), Flatpak manifests, and Electron packaging fields (`package.json` `name`/`productName`/`desktopName`, `electron-builder` `appId`, `executableName`, `StartupWMClass`). `identifiers` is a suggested list, Devel and `-dev` builds left out, deduplicated case-insensitively because the extension lowercases them.

```json
"identifiers": ["org.gnome.TextEditor.desktop", "org.gnome.TextEditor", "gnome-text-editor", "Text Editor"]
```

### draft-sources MAPPING.json [EXTRACT.json | --src DIR] [--repo ID]

Proposes a SOURCES.json for an existing mapping. For each item it takes the extracted rows with the same chord and picks the one whose label is closest, preferring menu and shortcut-window declarations over code and code over docs; changelogs rank last because they record what a shortcut used to be. Each pick carries `match.confidence`:

- `label`: the source's label matches the item's (the item's first word, and all of a two-word label, must be there).
- `action`: the source's action name matches (`next-tab` for Next Tab, `applyComment` for Comment).
- `chord-only`: the source has that chord, maybe for another action. Look before trusting it.

Items with no row for their chord are listed in `unmatched`: they need a URL record, or they are wrong.

### draft-mapping EXTRACT.json [...] --app ID [--name N] [--identifier X ...] [--desktop DESKTOP.json] [--strategy auto|menus|sections] [--out-dir DIR]

Drafts a mapping and its SOURCES.json from one or more extract outputs (one per repo; Kate needs `kate` and `ktexteditor`).

- `menus`: the app's menubar (KXMLGUI, Qt Designer, Electron templates). Menus with the same KXMLGUI name or the same label merge across files and repos, as KXMLGUI merges plugin menus.
- `sections`: documented rows grouped by their menu path or section (DocBook `Edit > Go To`, shortcut-window groups, Mallard `<guiseq>`).
- `auto`: `menus` when the source has a menubar, else `sections`.

Every shortcut in the draft has a record at its proving line. Items without a label in the source are dropped and reported, never named by guesswork. The draft keeps the app's wording and order; it still needs a read for menu names, order and which actions belong in a menu bar.

## Tested on real apps (2026-09-29)

| App | Toolkit | Commit | Files scanned | Rows (with chord) | Result |
| --- | --- | --- | --- | --- | --- |
| gnome-text-editor | GTK 4, libadwaita, C | `65c089a1b75c` | 220 | 141 (140) | shipped `text-editor.json`: 43 of 43 shortcuts verified, all 43 matched by label |
| Zettlr | Electron, TypeScript | `e6c7fd8ffebf` | 830 | 353 (332) | shipped `zettlr.json`: 45 of 45 verified (38 label, 6 action, 1 chord-only) |
| VS Code (`src/vs`) | Electron, TypeScript | `f44267726f38` | 7448 | 1141 (1113) | shipped `vscode.json`: 41 of 41 verified; 23 s to scan |
| Kate + KTextEditor | Qt 6, KDE Frameworks | `038bfab9f156` + `90e387402b71` | 970 + 2469 | 460 + 134 | drafted mapping: 14 menus, 197 items, 83 shortcuts, 83 of 83 verified |

Tamper drill on the Text Editor mapping: changing Save to `<Ctrl>J` and adding an invented "Sort Lines" `<Ctrl><Alt>S` with a citation to a real file:

```
verify exit=1
['File', 'Save'] <Ctrl>J -> the record is for <Ctrl>S, the mapping says <Ctrl>J
['Edit', 'Sort Lines'] <Ctrl><Alt>S -> lines 397-403 of src/editor-window.c hold no token for <Ctrl><Alt>S
```

What the runs found in shipped mappings, for the mapping integrator:

- Zettlr's Previous Tab, Next Tab and Filter Files accelerators are computed (`sc('next-tab')`); their defaults are in `source/app/service-providers/menu/shortcuts.ts` lines 35 to 37 (`{ key: 'Ctrl-Tab' }`).
- VS Code draft picks marked `chord-only` or pointing at `when`-scoped commands (Go to Symbol in File cites the accessible view's binding) need a human choice between the commands that share a chord.

## Rules for writing mappings

1. Never write a shortcut without a record. If no record can be found, make the item a placeholder (label only), which the extension shows greyed out.
2. Prefer source records. For closed-source apps (Obsidian, Discord, Slack), cite the vendor's own shortcut page with a quote that contains the key, and run `rloop verify` yourself first. Some pages cannot be fetched by rloop's own fetcher; cite another page.
3. Run `verify-mapping` and fix every failure. Do not edit the SOURCES.json to make a failure pass without re-reading the source.
4. Treat `chord-only` as unproven meaning: the chord exists, the action may not be the item's.

## Known limits

- The gate proves that a chord is written at the cited place. It does not prove the chord triggers the item's action; `draft-sources` confidence and a reader cover that.
- Accelerators computed at run time (function calls, user settings, loops like `KeyCode.Digit0 + i`) are reported as rows with an error, not guessed.
- Context-dependent bindings (VS Code `when`, JetBrains keymaps per context) give several candidates per chord.
- KXMLGUI menu items defined only by action name get their labels from `addAction` plus `setText` in C++; actions built in loops or helpers stay unlabelled and are dropped from drafts.
- Standard shortcuts come from four pinned upstream repos (`mtools/data/standard_keys.json` records qtbase, kconfig, kconfigwidgets and electron, each with its commit). Regenerate with `python3 -m mtools.gen_tables` after `fetch-source` of those repos.

## Tests

```sh
cd tools/mappings && python3 -m pytest -q
```

174 tests. `test_gjs_parser.py` checks every normalized form against the extension's `keySynth.js` under gjs, including every shortcut in the shipped mappings. `test_tables.py::RegenerateTest` rebuilds the standard tables from the upstream clones when they are present. Fixtures under `tests/fixtures/` copy real declaration shapes from the apps above.
