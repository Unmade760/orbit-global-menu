"""extract-shortcuts on the less common declaration forms (fixtures/extras)."""

import unittest

from helpers import FIXTURES
from mtools import extract

ROOT = FIXTURES / "extras"


class ExtrasTest(unittest.TestCase):
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

    def test_gtk3_builder_accelerator(self):
        row = self.find("gtk/gtk3-window.ui", "<Ctrl>Q", kind="gtk-builder-accelerator", label="Quit",
                        action="app.quit")
        self.assertEqual(row["line"], 6)

    def test_python_create_action(self):
        self.find("gtk/main.py", "<Ctrl>Q", action="app.quit", kind="gtk-set-accels")
        self.find("gtk/main.py", "<Ctrl>F", action="win.search", kind="gtk-set-accels")
        self.assertEqual(len([r for r in self.rows if r["file"] == "gtk/main.py"]), 2)

    def test_keyval_trigger_with_named_action(self):
        row = self.find("gtk/shortcuts.c", "<Ctrl><Shift>R", kind="gtk-shortcut", action="win.reload-all")
        self.assertEqual(row["line"], 6)

    def test_relm4_accelerators(self):
        self.find("gtk/app.rs", "<Ctrl>Q", action="QuitAction", kind="gtk-set-accels")

    def test_qt_from_string_and_plain_string_setter(self):
        self.find("qt/editor.cpp", "<Ctrl><Alt>D", label="Duplicate Line", action="edit_duplicate",
                  kind="qt-shortcut")
        self.find("qt/editor.cpp", "<Ctrl>J", label="Join Lines", action="edit_join", kind="qt-shortcut")

    def test_electron_spread_takes_the_linux_branch(self):
        self.find("js/menu.js", "<Ctrl><Alt>T", label="Always on Top", kind="electron-menu")
        self.assertFalse([r for r in self.rows if r["file"] == "js/menu.js" and r["label"] == "Bring All to Front"])
        window = [m for m in self.result["menus"] if m["file"] == "js/menu.js"][0]
        self.assertEqual([i["label"] for i in window["items"]], ["Always on Top"])

    def test_vscode_extension_title_from_nls(self):
        self.find("js/ext/package.json", "<Ctrl><Shift>I", action="ext.format", label="Format Document",
                  kind="vscode-keybinding")

    def test_zed_keymap(self):
        self.find("js/default-linux.json", "<Ctrl><Shift>P", action="command_palette::Toggle", kind="zed-keymap",
                  context="Editor")
        self.find("js/default-linux.json", "<Ctrl>K <Ctrl>S", action="zed::OpenKeymap")
        self.assertFalse([r for r in self.rows if r["file"] == "js/default-linux.json" and r["action"] == "zed::Quit"])

    def test_sublime_keymap(self):
        self.find("js/Default (Linux).sublime-keymap", "<Ctrl><Shift>P", action="show_overlay",
                  kind="sublime-keymap")
        self.find("js/Default (Linux).sublime-keymap", "<Ctrl>K <Ctrl>B", action="toggle_side_bar")

    def test_jetbrains_plugin_xml(self):
        self.find("java/plugin.xml", "<Ctrl><Alt>L", action="Demo.Reformat", label="Reformat Code",
                  kind="jetbrains-keymap")
        # the "Mac OS X 10.5+" keymap's meta alt L is left out
        self.assertEqual([r["accel"] for r in self.rows if r["file"] == "java/plugin.xml"], ["<Ctrl><Alt>L"])

    def test_docbook_table_keycombo(self):
        self.find("docs/keys.docbook", "<Ctrl>D", label="Comment out", kind="docbook-keycombo")

    def test_markdown_plain_list_item(self):
        self.find("docs/README.md", "<Ctrl><Shift>E", label="Focus the editor", kind="doc-text", context="Keys")
        self.assertFalse([r for r in self.rows if r["file"] == "docs/README.md" and r["accel"] == "<Alt>1"])


if __name__ == "__main__":
    unittest.main()
