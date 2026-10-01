"""Standard shortcut tables generated from upstream source (mtools/data).

Expected values are the upstream lines themselves: qplatformtheme.cpp
keyBindings[] for QKeySequence::StandardKey, kstandardshortcut.cpp and
kstandardaction_p.h for KDE, electron_api_menu_roles.cc for Electron roles.
"""

import json
import tempfile
import unittest
from pathlib import Path

from mtools import accel, tables
from mtools.gen_tables import SOURCES_ROOT, generate


def accels(entries):
    return [e["accel"] for e in entries if e["accel"]]


class QtStandardKeysTest(unittest.TestCase):
    def test_copy_on_gnome_prefers_ctrl_c(self):
        self.assertEqual(accels(tables.qt_standard_key("Copy")), ["<Ctrl>C", "<Ctrl>Insert"])

    def test_redo_on_gnome(self):
        self.assertEqual(accels(tables.qt_standard_key("Redo")), ["<Ctrl><Shift>Z"])

    def test_refresh_on_gnome(self):
        self.assertEqual(accels(tables.qt_standard_key("Refresh")), ["<Ctrl>R", "F5"])

    def test_quit_on_gnome(self):
        self.assertEqual(accels(tables.qt_standard_key("Quit")), ["<Ctrl>Q"])

    def test_preferences_has_no_gnome_default(self):
        self.assertEqual(accels(tables.qt_standard_key("Preferences")), [])

    def test_kde_scheme_differs(self):
        self.assertEqual(accels(tables.qt_standard_key("Preferences", scheme="kde")),
                         ["<Ctrl><Shift>comma"])

    def test_entries_carry_their_line(self):
        entry = tables.qt_standard_key("Save")[0]
        self.assertEqual(entry["file"], "src/gui/kernel/qplatformtheme.cpp")
        self.assertIsInstance(entry["line"], int)

    def test_unknown_key(self):
        self.assertIsNone(tables.qt_standard_key("NoSuchKey"))


class KdeTest(unittest.TestCase):
    def test_kstandardshortcut_defaults(self):
        self.assertEqual(accels(tables.kstandard_shortcut("Save")), ["<Ctrl>S"])
        self.assertEqual(accels(tables.kstandard_shortcut("Redo")), ["<Ctrl><Shift>Z"])
        self.assertEqual(accels(tables.kstandard_shortcut("Cut")), ["<Ctrl>X", "<Shift>Delete"])
        self.assertEqual(accels(tables.kstandard_shortcut("Close")), ["<Ctrl>W", "<Ctrl>Escape"])

    def test_linux_branch_of_ifdef(self):
        self.assertEqual(accels(tables.kstandard_shortcut("DeleteWordBack")), ["<Ctrl>BackSpace"])
        self.assertEqual(accels(tables.kstandard_shortcut("FindNext")), ["F3"])

    def test_bare_qt_key(self):
        self.assertEqual(accels(tables.kstandard_shortcut("Help")), ["F1"])
        self.assertEqual(accels(tables.kstandard_shortcut("RenameFile")), ["F2"])
        reload = tables.kstandard_shortcut("Reload")
        self.assertEqual([e["raw"] for e in reload], ["Qt::Key_F5", "Qt::Key_Refresh"])
        self.assertEqual(accels(reload), ["F5"])

    def test_kstandardaction_function(self):
        info = tables.kstandard_action("save")
        self.assertEqual(info["action_name"], "file_save")
        self.assertEqual(info["label"], "Save")
        self.assertEqual(accels(info["shortcuts"]), ["<Ctrl>S"])

    def test_kstandardaction_open_new(self):
        info = tables.kstandard_action("openNew")
        self.assertEqual(info["action_name"], "file_new")
        self.assertEqual(accels(info["shortcuts"]), ["<Ctrl>N"])

    def test_kstandardaction_by_enum_and_action_name(self):
        self.assertEqual(tables.kstandard_action("Quit")["action_name"], "file_quit")
        self.assertEqual(tables.kstandard_action("file_quit")["label"], "Quit")

    def test_kstandardshortcut_accessor_to_enum(self):
        # kstandardshortcut.cpp: const QList<QKeySequence> &openNew() { return shortcut(New); }
        self.assertEqual(tables.kstandard_shortcut_function("openNew"), "New")
        self.assertEqual(tables.kstandard_shortcut_function("preferences"), "Preferences")
        self.assertEqual(tables.kstandard_shortcut_function("completion"), "TextCompletion")
        self.assertIsNone(tables.kstandard_shortcut_function("shortcut"))
        self.assertIsNone(tables.kstandard_shortcut_function("noSuchAccessor"))

    def test_action_without_shortcut(self):
        self.assertEqual(accels(tables.kstandard_action("openRecent")["shortcuts"]), [])


class ElectronRolesTest(unittest.TestCase):
    def test_role_defaults_on_linux(self):
        self.assertEqual(tables.electron_role("redo")["accel"], "<Ctrl><Shift>Z")
        self.assertEqual(tables.electron_role("quit")["accel"], "<Ctrl>Q")
        self.assertEqual(tables.electron_role("quit")["label"], "Quit")
        self.assertEqual(tables.electron_role("togglefullscreen")["accel"], "F11")
        self.assertEqual(tables.electron_role("toggleDevTools")["accel"], "<Ctrl><Shift>I")
        self.assertEqual(tables.electron_role("zoomIn")["accel"], "<Ctrl>plus")

    def test_mac_only_role(self):
        self.assertFalse(tables.electron_role("hide")["linux"])

    def test_edit_menu_expands(self):
        roles = tables.electron_submenu("editMenu")
        self.assertEqual(roles, ["undo", "redo", None, "cut", "copy", "paste", "delete", None, "selectall"])


class GrammarTest(unittest.TestCase):
    def test_every_generated_accel_is_grammar(self):
        data = tables.load()
        found = 0
        for value in json.dumps(data).split('"accel": ')[1:]:
            if value.startswith("null"):
                continue
            text = json.loads(value[:value.index('"', 1) + 1])
            self.assertIsNotNone(accel.parse_grammar(text), text)
            found += 1
        self.assertGreater(found, 150)


@unittest.skipUnless(Path(SOURCES_ROOT, "qtbase", ".git").exists(), "upstream sources not cloned")
class RegenerateTest(unittest.TestCase):
    def test_committed_tables_match_the_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "standard_keys.json"
            generate(SOURCES_ROOT, out)
            self.assertEqual(json.loads(out.read_text()), tables.load())


if __name__ == "__main__":
    unittest.main()
