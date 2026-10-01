"""extract-shortcuts over fixtures that mirror each source syntax."""

import unittest

from helpers import FIXTURES, make_repo, run_cli
from mtools import accel, extract

ROOT = FIXTURES / "extract"


def line_with(rel, needle, nth=1):
    count = 0
    for number, line in enumerate((ROOT / rel).read_text().splitlines(), 1):
        if needle in line:
            count += 1
            if count == nth:
                return number
    raise AssertionError(f"{needle!r} not in {rel}")


class ExtractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = extract.scan(ROOT)
        cls.rows = cls.result["shortcuts"]

    def find(self, file, accel_str, **fields):
        hits = [r for r in self.rows if r["file"] == file and r["accel"] == accel_str
                and all(r.get(k) == v for k, v in fields.items())]
        if not hits:
            near = [(r["accel"], r.get("label"), r.get("action"), r["kind"], r["line"])
                    for r in self.rows if r["file"] == file]
            self.fail(f"no row {accel_str} {fields} in {file}; rows: {near}")
        return hits[0]

    def absent(self, file, accel_str):
        hits = [r for r in self.rows if r["file"] == file and r["accel"] == accel_str]
        self.assertEqual(hits, [], f"unexpected {accel_str} in {file}")

    def menu(self, file, label=None, ident=None):
        for m in self.result["menus"]:
            if m["file"] == file and (label is None or m.get("label") == label) \
                    and (ident is None or m.get("id") == ident):
                return m
        self.fail(f"no menu {label or ident} in {file}: {[m.get('label') or m.get('id') for m in self.result['menus'] if m['file'] == file]}")

    # --- GTK -----------------------------------------------------------

    def test_gmenu_accel_in_ui(self):
        row = self.find("gtk/menus.ui", "<Ctrl>N", label="New Window", action="app.new-window",
                        kind="gmenu-accel")
        self.assertEqual(row["line"], line_with("gtk/menus.ui", "&lt;Primary&gt;n"))
        self.assertEqual(row["accel_raw"], "<Primary>n")
        self.find("gtk/menus.ui", "<Ctrl>plus", label="Zoom In", action="win.zoom-in")

    def test_gmenu_tree_in_ui(self):
        menu = self.menu("gtk/menus.ui", ident="primary_menu")
        labels = [i.get("label") if not i.get("separator") else "---" for i in menu["items"]]
        self.assertEqual(labels, ["New Window", "View", "---", "Preferences"])
        view = menu["items"][1]
        self.assertEqual(view["items"][0]["label"], "Zoom In")
        self.assertEqual(view["items"][0]["accel"], "<Ctrl>plus")
        self.assertEqual(menu["items"][3]["action"], "app.preferences")

    def test_gtk_shortcut_trigger_alternatives(self):
        self.find("gtk/menus.ui", "<Ctrl>Q", action="app.quit", kind="gtk-shortcut")
        self.find("gtk/menus.ui", "<Ctrl>W", action="app.quit", kind="gtk-shortcut")

    def test_shortcuts_window(self):
        row = self.find("gtk/help-overlay.ui", "<Ctrl>O", label="Open a document",
                        kind="gtk-shortcuts-window")
        self.assertEqual(row["context"], "Documents")

    def test_shortcuts_window_range_expands(self):
        tabs = [r for r in self.rows if r["file"] == "gtk/help-overlay.ui" and r.get("label") == "Switch to tab"]
        self.assertEqual([r["accel"] for r in tabs], [f"<Alt>{d}" for d in range(1, 10)])

    def test_shortcuts_window_range_with_one_modifier_prefix(self):
        # Nautilus writes "<alt>0...8": the modifiers on the first key cover the last.
        tabs = [r for r in self.rows if r["file"] == "gtk/short-range.ui" and r.get("label") == "Open tab"]
        self.assertEqual([r["accel"] for r in tabs], [f"<Alt>{d}" for d in range(0, 9)])

    def test_shortcuts_window_alternatives_and_sequence(self):
        self.find("gtk/help-overlay.ui", "<Ctrl>W", action="win.close")
        self.find("gtk/help-overlay.ui", "<Ctrl>F4", action="win.close")
        self.find("gtk/help-overlay.ui", "<Ctrl>X <Ctrl>S", label="Emacs save")

    def test_blueprint_shortcuts_dialog(self):
        row = self.find("gtk/shortcuts-dialog.blp", "<Ctrl><Shift>C", label="Copy All",
                        kind="adw-shortcuts-dialog")
        self.assertEqual(row["context"], "Editing")
        self.assertEqual(row["line"], line_with("gtk/shortcuts-dialog.blp", '"<ctrl><shift>c"'))
        self.find("gtk/shortcuts-dialog.blp", "<Ctrl>Z", label="Undo", action="text.undo")

    def test_blueprint_menu(self):
        self.find("gtk/shortcuts-dialog.blp", "<Ctrl>F", label="Find", action="win.find", kind="gmenu-accel")
        menu = self.menu("gtk/shortcuts-dialog.blp", ident="primary_menu")
        labels = [i.get("label") if not i.get("separator") else "---" for i in menu["items"]]
        self.assertEqual(labels, ["Find", "Keyboard Shortcuts", "---", "Sort"])
        self.assertEqual(menu["items"][1]["action"], "app.shortcuts")

    def test_blueprint_shortcut_controller(self):
        self.find("gtk/shortcuts-dialog.blp", "<Ctrl>comma", action="app.preferences", kind="gtk-shortcut")

    def test_c_accel_table(self):
        self.find("gtk/window.c", "<Ctrl>T", action="win.new-tab")
        self.find("gtk/window.c", "F11", action="win.fullscreen")

    def test_c_binding_action(self):
        self.find("gtk/window.c", "<Ctrl>S", action="win.save", kind="gtk-binding")
        row = self.find("gtk/window.c", "<Ctrl><Shift>S", action="win.save-as", kind="gtk-binding")
        # The multi-line call: the row sits on its key argument, the second "GDK_KEY_s,"
        self.assertEqual(row["line"], line_with("gtk/window.c", "GDK_KEY_s,", nth=2))
        self.find("gtk/window.c", "Escape", action="editor_window_escape_cb", kind="gtk-binding")

    def test_c_set_accels_and_comments(self):
        self.find("gtk/window.c", "<Ctrl>Q", action="app.quit", kind="gtk-set-accels")
        self.absent("gtk/window.c", "<Ctrl>X")
        self.absent("gtk/window.c", "<Ctrl>J")

    def test_c_set_accels_with_named_array(self):
        # gnome-text-editor: static const char *help_accels[] = { "F1", NULL }; then
        # gtk_application_set_accels_for_action (app, "app.help", help_accels);
        row = self.find("gtk/window.c", "F1", action="app.help", kind="gtk-set-accels")
        self.assertEqual(row["line"], line_with("gtk/window.c", '"F1"'))
        self.find("gtk/window.c", "<Ctrl>W", action="app.quit-all", kind="gtk-set-accels")
        self.find("gtk/window.c", "<Ctrl>Q", action="app.quit-all", kind="gtk-set-accels")

    def test_python_gtk(self):
        self.find("gtk/application.py", "<Ctrl>Q", action="app.quit")
        self.find("gtk/application.py", "F9", action="win.toggle-sidebar")
        self.find("gtk/application.py", "<Ctrl>backslash", action="win.toggle-sidebar")
        self.find("gtk/application.py", "<Ctrl>F", action="win.find", kind="gtk-set-accels")
        self.absent("gtk/application.py", "<Ctrl>K")
        self.find("gtk/application.py", "<Ctrl><Shift>P", action="win.palette", kind="gtk-shortcut")
        self.find("gtk/application.py", "<Ctrl>N", action="win.new-note", kind="gtk-binding")

    def test_rust_vala_js(self):
        self.find("gtk/window.rs", "<Ctrl>W", action="window.close", kind="gtk-binding")
        self.find("gtk/window.rs", "<Ctrl>Q", action="app.quit", kind="gtk-set-accels")
        self.find("gtk/app.vala", "F1", action="app.about", kind="gtk-set-accels")
        self.find("gtk/app.vala", "<Ctrl>R", action="win.reload", kind="gtk-binding")
        self.find("gtk/extension.js", "<Alt>Left", action="win.go-back", kind="gtk-set-accels")
        self.find("gtk/extension.js", "<Ctrl>L", action="win.location", kind="gtk-binding")

    # --- Qt and KDE ----------------------------------------------------

    def test_kstandardaction(self):
        self.find("qt/mainwindow.cpp", "<Ctrl>S", label="Save", action="file_save", kind="kstandardaction")
        self.find("qt/mainwindow.cpp", "<Ctrl>Q", action="file_quit", kind="kstandardaction")
        self.find("qt/mainwindow.cpp", "<Ctrl>F", action="edit_find", kind="kstandardaction")

    def test_kde_default_shortcut_with_label(self):
        self.find("qt/mainwindow.cpp", "<Ctrl>L", label="Save All", action="file_save_all", kind="qt-shortcut")
        self.find("qt/mainwindow.cpp", "<Ctrl><Shift>L", label="Split Vertical", action="view_split_vert")
        self.find("qt/mainwindow.cpp", "<Ctrl>K <Ctrl>V", label="Split Vertical")

    def test_qt_actions_without_shortcut_are_catalogued(self):
        actions = {(a["action"], a["label"]) for a in self.result["actions"] if a["file"] == "qt/mainwindow.cpp"}
        self.assertIn(("file_close_all", "Close All"), actions)
        self.assertIn(("file_reload_all", "Reload All"), actions)

    def test_qt_standard_key(self):
        self.find("qt/mainwindow.cpp", "<Ctrl>C", label="Copy", kind="qt-standard-key")
        self.find("qt/mainwindow.cpp", "<Ctrl>O", label="Open...", kind="qt-standard-key")
        self.find("qt/mainwindow.cpp", "F5")
        self.absent("qt/mainwindow.cpp", "<Ctrl>J")

    def test_kstandardshortcut_accessor(self):
        self.find("qt/mainwindow.cpp", "<Ctrl><Shift>comma", kind="kstandardshortcut")

    def test_kxmlgui_rc(self):
        self.find("qt/kateui.rc", "<Ctrl><Shift>E", action="file_export_html", kind="kxmlgui")
        self.find("qt/kateui.rc", "<Ctrl>N", action="file_new", label="New", kind="kxmlgui-standard-action")
        menu = self.menu("qt/kateui.rc", label="File")
        actions = [i.get("action") if not i.get("separator") else "---" for i in menu["items"]]
        self.assertEqual(actions, ["file_new", "file_save_all", "---", None, "file_quit"])
        export = menu["items"][3]
        self.assertEqual(export["label"], "Export")
        self.assertEqual(export["items"][0]["accel"], "<Ctrl><Shift>E")
        self.assertEqual(menu["items"][0]["accel"], "<Ctrl>N")

    def test_menu_labels_filled_from_code(self):
        # kateui.rc names file_save_all; its label is set in C++ (a->setText(i18n("Save A&ll")))
        item = self.menu("qt/kateui.rc", label="File")["items"][1]
        self.assertEqual(item["action"], "file_save_all")
        self.assertEqual(item["label"], "Save All")
        self.assertEqual(item["label_source"]["file"], "qt/mainwindow.cpp")
        self.assertEqual(item["accel"], "<Ctrl>L")

    def test_menu_items_point_at_the_line_that_proves_their_accel(self):
        gmenu = self.menu("gtk/menus.ui", ident="primary_menu")["items"][0]
        self.assertEqual(gmenu["accel_line"], line_with("gtk/menus.ui", "&lt;Primary&gt;n"))
        export = self.menu("qt/kateui.rc", label="File")["items"][3]["items"][0]
        self.assertEqual(export["accel_line"], line_with("qt/kateui.rc", 'shortcut="Ctrl+Shift+E"'))
        new = self.menu("qt/kateui.rc", label="File")["items"][0]
        self.assertEqual(new["accel_line"], line_with("qt/kateui.rc", '"file_new"'))
        window = self.menu("electron/menu.ts", label="File")["items"][0]
        self.assertEqual(window["accel_line"], line_with("electron/menu.ts", "CmdOrCtrl+Shift+N"))
        prefs = self.menu("electron/menu.ts", label="File")["items"][1]
        self.assertEqual(prefs["accel_line"], line_with("electron/menu.ts", "Ctrl+,"))
        opened = self.menu("qt/mainwindow.ui", label="File")["items"][0]
        self.assertEqual(opened["accel_line"], line_with("qt/mainwindow.ui", "Ctrl+O"))

    def test_qt_designer_ui(self):
        self.find("qt/mainwindow.ui", "<Ctrl>O", label="Open...", action="actionOpen", kind="qt-designer")
        self.find("qt/mainwindow.ui", "<Ctrl>Q", label="Quit", action="actionQuit")
        menu = self.menu("qt/mainwindow.ui", label="File")
        labels = [i.get("label") if not i.get("separator") else "---" for i in menu["items"]]
        self.assertEqual(labels, ["Open...", "---", "Quit"])

    def test_qml(self):
        self.find("qt/Main.qml", "<Ctrl>E", kind="qml-shortcut")
        self.find("qt/Main.qml", "<Ctrl>C", kind="qml-shortcut")
        self.find("qt/Main.qml", "<Ctrl>Insert", kind="qml-shortcut")
        self.find("qt/Main.qml", "<Ctrl>O", label="Open File…")
        self.find("qt/Main.qml", "<Ctrl>T", label="New Tab")

    def test_pyqt(self):
        self.find("qt/window.py", "<Ctrl>S", label="Save")
        self.find("qt/window.py", "<Ctrl>Q", label="Quit")
        self.find("qt/window.py", "<Ctrl><Shift>F")

    def test_docbook_menuchoice(self):
        row = self.find("qt/menus.docbook", "<Ctrl>N", label="New", kind="docbook-menuchoice")
        self.assertEqual(row["context"], "File")
        self.find("qt/menus.docbook", "<Ctrl><Shift>S", label="Save As…")

    # --- Electron and web ----------------------------------------------

    def test_electron_template(self):
        self.find("electron/menu.ts", "<Ctrl><Shift>N", label="New Window", kind="electron-menu")
        self.find("electron/menu.ts", "<Ctrl>comma", label="Preferences…")
        self.absent("electron/menu.ts", "<Super>comma")
        self.find("electron/menu.ts", "<Ctrl>Q", label="Quit", kind="electron-role")
        self.find("electron/menu.ts", "<Ctrl>R", label="Reload", kind="electron-role")
        self.find("electron/menu.ts", "<Ctrl><Shift>I", kind="electron-role")
        self.find("electron/menu.ts", "<Ctrl>B", label="Toggle Sidebar", action="toggle-sidebar")
        self.absent("electron/menu.ts", "<Ctrl>J")

    def test_electron_menu_tree(self):
        file_menu = self.menu("electron/menu.ts", label="File")
        labels = [i.get("label") if not i.get("separator") else "---" for i in file_menu["items"]]
        self.assertEqual(labels, ["New Window", "Preferences…", "---", "Quit"])
        edit = self.menu("electron/menu.ts", label="Edit")
        self.assertEqual([i.get("label") for i in edit["items"] if not i.get("separator")],
                         ["Undo", "Redo", "Cut", "Copy", "Paste", "Delete", "Select All"])
        self.assertEqual(edit["items"][0]["accel"], "<Ctrl>Z")

    def test_mac_only_files_are_skipped(self):
        self.assertFalse([r for r in self.rows if r["file"] == "electron/menu.darwin.ts"])
        everything = extract.scan(ROOT, include_all=True)["shortcuts"]
        self.assertTrue([r for r in everything if r["file"] == "electron/menu.darwin.ts"])

    def test_windows_named_file_is_tagged(self):
        row = self.find("electron/menu.win32.ts", "<Ctrl><Alt>C", label="Copy as HTML")
        self.assertEqual(row["platform"], "windows")

    def test_computed_accelerator_is_reported(self):
        rows = [r for r in self.rows if r["file"] == "electron/menu.win32.ts" and r["label"] == "Filter files"]
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]["accel"])
        self.assertIn("computed", rows[0]["error"])
        self.assertEqual(rows[0]["accel_raw"], "sc('filter-files')")

    def test_electron_accel_literal(self):
        self.find("electron/menu.ts", "<Ctrl><Alt>K", kind="electron-accel-literal")

    def test_vscode_keybindings_json(self):
        self.find("electron/keybindings.json", "<Ctrl><Shift>P", action="workbench.action.showCommands",
                  kind="vscode-keybinding")
        self.find("electron/keybindings.json", "<Ctrl>K <Ctrl>S")
        self.find("electron/keybindings.json", "<Ctrl>B", action="workbench.action.toggleSidebarVisibility")
        self.absent("electron/keybindings.json", "<Super>B")

    def test_vscode_package_json(self):
        self.find("electron/package.json", "<Ctrl><Alt>R", action="demo.run", label="Run Demo",
                  kind="vscode-keybinding")

    def test_vscode_keymod(self):
        self.find("electron/actions.ts", "<Ctrl><Alt>S", action="workbench.action.files.save",
                  label="Save", kind="vscode-keymod")
        self.absent("electron/actions.ts", "<Ctrl>S")
        self.find("electron/actions.ts", "<Ctrl>K <Ctrl>R", action="workbench.action.openRecent")

    def test_key_objects_named_by_their_property(self):
        self.find("electron/shortcuts.ts", "<Ctrl><Shift>Tab", action="previous-tab", kind="js-keybinding")
        self.find("electron/shortcuts.ts", "<Ctrl><Shift>T", action="filter-files", kind="js-keybinding")
        self.assertEqual(len([r for r in self.rows if r["file"] == "electron/shortcuts.ts"]), 2)

    def test_vscode_web_conditions_resolve_for_the_desktop_app(self):
        self.find("electron/actions.ts", "<Ctrl><Shift>P", action="workbench.action.showCommands",
                  kind="vscode-keymod")
        self.find("electron/actions.ts", "<Ctrl>O", action="workbench.action.files.openFile")
        self.absent("electron/actions.ts", "<Ctrl>E")

    def test_vscode_ids_through_constants(self):
        self.find("electron/actions.ts", "<Ctrl>W", action="workbench.action.closeActiveEditor")
        self.find("electron/actions.ts", "<Ctrl><Shift>I", action="editor.action.formatDocument",
                  label="Format Document", kind="vscode-keymod")
        self.absent("electron/actions.ts", "<Shift><Alt>F")

    def test_codemirror_and_mousetrap(self):
        self.find("electron/editor.js", "<Ctrl>S", action="saveDocument", kind="codemirror-keymap")
        self.find("electron/editor.js", "<Ctrl><Shift>Z", action="redo")
        self.find("electron/editor.js", "<Ctrl>slash", action="toggleComment")
        self.find("electron/editor.js", "<Ctrl>K", kind="js-key-literal")

    # --- Java ----------------------------------------------------------

    def test_java(self):
        self.find("java/MainFrame.java", "<Ctrl>S", label="Save", kind="java-keystroke")
        self.find("java/MainFrame.java", "<Ctrl>O", label="Open")
        self.absent("java/MainFrame.java", "O")
        row = self.find("java/MainFrame.java", "<Ctrl><Shift>F", label="Find")
        self.assertEqual(row["line"], line_with("java/MainFrame.java", "VK_F"))

    def test_jetbrains_keymap(self):
        self.find("java/keymap.xml", "<Ctrl>S", action="SaveAll", kind="jetbrains-keymap")
        self.find("java/keymap.xml", "<Ctrl><Shift>A", action="GotoAction")
        self.find("java/keymap.xml", "<Ctrl>K <Ctrl>V", action="Vcs.QuickListPopupAction")

    # --- Docs ----------------------------------------------------------

    def test_markdown(self):
        self.find("docs/shortcuts.md", "<Ctrl>O", label="Open a file", kind="doc-text")
        self.find("docs/shortcuts.md", "F11", label="Toggle full screen")
        self.find("docs/shortcuts.md", "<Ctrl>W", label="Close tab")
        self.find("docs/shortcuts.md", "<Ctrl><Shift>T", label="Reopen closed tab")
        self.find("docs/shortcuts.md", "<Ctrl>Tab")
        self.absent("docs/shortcuts.md", "Return")

    def test_markdown_punctuation_is_not_a_label(self):
        # kate addons/keyboardmacros/README.md: "[`Ctrl+Shift+K`]." alone on a line
        row = self.find("docs/shortcuts.md", "<Ctrl><Alt>M")
        self.assertIsNone(row["label"])

    def test_mallard(self):
        self.find("docs/keys.page", "<Ctrl>N", label="Create a new window", kind="mallard")
        self.find("docs/keys.page", "F1", label="Show help")

    def test_yaml(self):
        self.find("docs/keymap.yml", "<Ctrl><Shift>T", label="Toggle Terminal")
        self.find("docs/keymap.yml", "<Alt>Right", label="Next Pane")

    # --- General -------------------------------------------------------

    def test_skips_tests_and_vendored_by_default(self):
        self.assertFalse([r for r in self.rows if r["file"].startswith("skip/")])
        everything = extract.scan(ROOT, include_all=True)["shortcuts"]
        files = {r["file"] for r in everything}
        self.assertIn("skip/tests/test_menu.c", files)
        self.assertIn("skip/node_modules/lib/menu.js", files)

    def test_every_accel_is_grammar_or_has_error(self):
        for row in self.rows:
            with self.subTest(row=row):
                if row["accel"] is None:
                    self.assertTrue(row.get("error"))
                else:
                    self.assertIsNotNone(accel.parse_grammar(row["accel"]))
                for key in ("accel_raw", "accel", "label", "action", "file", "line", "kind"):
                    self.assertIn(key, row)

    def test_rows_sorted_and_deterministic(self):
        keys = [(r["file"], r["line"]) for r in self.rows]
        self.assertEqual(keys, sorted(keys))
        self.assertEqual(extract.scan(ROOT), self.result)


class ExtractCliTest(unittest.TestCase):
    def test_cli_on_git_clone_reports_commit(self):
        tmp, repo, commit = make_repo({
            "src/app.py": 'app.set_accels_for_action("app.quit", ["<primary>q"])\n',
        })
        try:
            code, out, err = run_cli("extract-shortcuts", repo)
            self.assertEqual(code, 0, err)
            self.assertEqual(out["commit"], commit)
            self.assertEqual(out["shortcuts"][0]["accel"], "<Ctrl>Q")
            self.assertEqual(out["shortcuts"][0]["file"], "src/app.py")
            self.assertIn("stats", out)
        finally:
            tmp.cleanup()

    def test_help(self):
        code, _, _ = run_cli("extract-shortcuts", "--help")
        self.assertEqual(code, 0)

    def test_missing_dir(self):
        code, out, _ = run_cli("extract-shortcuts", "/nonexistent/dir")
        self.assertNotEqual(code, 0)
        self.assertIn("error", out)


if __name__ == "__main__":
    unittest.main()
