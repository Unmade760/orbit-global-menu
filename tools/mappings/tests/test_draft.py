"""draft-sources: propose provenance records from extract-shortcuts output."""

import json
import unittest
from pathlib import Path

from helpers import make_repo, run_cli
from mtools import draft

EXTRACT = {
    "root": "/somewhere/demo-src", "commit": "abc123", "url": "https://example.org/demo.git",
    "shortcuts": [
        {"accel_raw": "<Primary>s", "accel": "<Ctrl>S", "label": "Save", "action": "win.save",
         "file": "src/menus.ui", "line": 5, "kind": "gmenu-accel"},
        {"accel_raw": "Ctrl+S", "accel": "<Ctrl>S", "label": "Save All", "action": "file_save_all",
         "file": "src/window.cpp", "line": 9, "kind": "qt-shortcut"},
        {"accel_raw": "GDK_KEY_o, GDK_CONTROL_MASK", "accel": "<Ctrl>O", "label": None, "action": "win.open",
         "file": "src/window.c", "line": 20, "kind": "gtk-binding"},
        {"accel_raw": "Ctrl+O", "accel": "<Ctrl>O", "label": None, "action": None,
         "file": "README.md", "line": 3, "kind": "doc-text"},
        {"accel_raw": "<Meta>x", "accel": None, "label": "Broken", "action": None,
         "file": "src/x.c", "line": 1, "kind": "gtk-accel-literal", "error": "no"},
    ],
    "menus": [],
}
MAPPING = {
    "format": 1, "app": "demo", "name": "Demo", "identifiers": ["demo"],
    "menus": [{"label": "File", "items": [
        {"label": "Save", "shortcut": "<Ctrl>S"},
        {"label": "Save All", "shortcut": "<Primary>s"},
        {"label": "Open File", "shortcut": "<Ctrl>O"},
        {"label": "Quit", "shortcut": "<Ctrl>Q"},
        {"label": "Recent"},
    ]}],
}


class DraftTest(unittest.TestCase):
    def setUp(self):
        self.out = draft.draft(MAPPING, EXTRACT, repo="demo-src")
        self.items = {tuple(r["path"]): r for r in self.out["items"]}

    def test_label_match_wins(self):
        self.assertEqual(self.items[("File", "Save")]["line"], 5)
        self.assertEqual(self.items[("File", "Save All")]["line"], 9)

    def test_record_shape_is_what_verify_reads(self):
        rec = self.items[("File", "Save")]
        self.assertEqual(rec["file"], "src/menus.ui")
        self.assertEqual(rec["commit"], "abc123")
        self.assertEqual(rec["repo"], "demo-src")
        self.assertEqual(rec["shortcut"], "<Ctrl>S")
        self.assertEqual(self.out["repos"]["demo-src"], {"url": "https://example.org/demo.git", "commit": "abc123"})

    def test_chord_only_match_is_flagged_and_prefers_code(self):
        rec = self.items[("File", "Open File")]
        self.assertEqual(rec["match"]["confidence"], "chord-only")
        self.assertEqual(rec["file"], "src/window.c")
        self.assertEqual(self.items[("File", "Save")]["match"]["confidence"], "label")

    def test_short_label_inside_a_longer_one_is_a_label_match(self):
        # gnome-text-editor's shortcuts dialog: "Undo previous command", "Move current or selected lines up"
        extract = {"commit": "c", "url": None, "shortcuts": [
            {"accel_raw": "<ctrl>z", "accel": "<Ctrl>Z", "label": "Undo previous command", "action": None,
             "file": "s.ui", "line": 1, "kind": "adw-shortcuts-dialog"},
            {"accel_raw": "<alt>Up", "accel": "<Alt>Up", "label": "Move current or selected lines up",
             "action": None, "file": "s.ui", "line": 2, "kind": "adw-shortcuts-dialog"}]}
        mapping = {"app": "x", "menus": [{"label": "Edit", "items": [
            {"label": "Undo", "shortcut": "<Ctrl>Z"}, {"label": "Move Line Up", "shortcut": "<Alt>Up"}]}]}
        out = draft.draft(mapping, extract, repo="x")
        self.assertEqual([r["match"]["confidence"] for r in out["items"]], ["label", "label"])

    def test_changelog_ranks_below_a_declaration(self):
        # Zettlr: CHANGELOG.md mentions Ctrl+Shift+V for pasting plain text; menu.win32.ts binds it
        extract = {"commit": "c", "url": None, "shortcuts": [
            {"accel_raw": "Ctrl+Shift+V", "accel": "<Ctrl><Shift>V",
             "label": "Using the shortcut to paste something as plain text will no longer fail",
             "action": None, "file": "CHANGELOG.md", "line": 3453, "kind": "doc-text"},
            {"accel_raw": "Ctrl+Shift+V", "accel": "<Ctrl><Shift>V", "label": "Paste without style",
             "action": "menu.paste_plain", "file": "source/menu.win32.ts", "line": 377, "kind": "electron-menu"}]}
        mapping = {"app": "x", "menus": [{"label": "Edit", "items": [
            {"label": "Paste Plain Text", "shortcut": "<Ctrl><Shift>V"}]}]}
        rec = draft.draft(mapping, extract, repo="x")["items"][0]
        self.assertEqual(rec["file"], "source/menu.win32.ts")

    def test_one_shared_word_in_a_sentence_is_not_a_label_match(self):
        extract = {"commit": "c", "url": None, "shortcuts": [
            {"accel_raw": "Ctrl+Shift+T", "accel": "<Ctrl><Shift>T",
             "label": "Added the shortcuts to focus the editor and to focus the file list",
             "action": None, "file": "docs/guide.md", "line": 4, "kind": "doc-text"}]}
        mapping = {"app": "x", "menus": [{"label": "Edit", "items": [
            {"label": "Filter Files", "shortcut": "<Ctrl><Shift>T"}]}]}
        rec = draft.draft(mapping, extract, repo="x")["items"][0]
        self.assertEqual(rec["match"]["confidence"], "chord-only")

    def test_action_name_match_has_its_own_confidence(self):
        # Zettlr shortcuts.ts: 'next-tab': { key: 'Ctrl-Tab' }; default.ts: run: applyComment
        extract = {"commit": "c", "url": None, "shortcuts": [
            {"accel_raw": "Ctrl-Tab", "accel": "<Ctrl>Tab", "label": None, "action": "next-tab",
             "file": "shortcuts.ts", "line": 36, "kind": "js-keybinding"},
            {"accel_raw": "Mod-Shift-c", "accel": "<Ctrl><Shift>C", "label": None, "action": "applyComment",
             "file": "default.ts", "line": 270, "kind": "codemirror-keymap"}]}
        mapping = {"app": "x", "menus": [{"label": "Go", "items": [
            {"label": "Next Tab", "shortcut": "<Ctrl>Tab"}, {"label": "Comment", "shortcut": "<Ctrl><Shift>C"}]}]}
        out = draft.draft(mapping, extract, repo="x")
        self.assertEqual([r["match"]["confidence"] for r in out["items"]], ["action", "action"])
        self.assertEqual(out["summary"]["action_match"], 2)

    def test_generic_shared_words_are_not_a_label_match(self):
        # VS Code: Ctrl+W is also "Kill the Active Terminal in Editor Area"; Ctrl+Shift+I "Format Notebook"
        extract = {"commit": "c", "url": None, "shortcuts": [
            {"accel_raw": "k", "accel": "<Ctrl>W", "label": "Kill the Active Terminal in Editor Area",
             "action": None, "file": "t.ts", "line": 1, "kind": "vscode-keymod"},
            {"accel_raw": "k", "accel": "<Ctrl><Shift>I", "label": "Format Notebook",
             "action": "notebook.format", "file": "n.ts", "line": 1, "kind": "vscode-keymod"}]}
        mapping = {"app": "x", "menus": [{"label": "File", "items": [
            {"label": "Close Active Editor Tab", "shortcut": "<Ctrl>W"},
            {"label": "Format Document", "shortcut": "<Ctrl><Shift>I"}]}]}
        out = draft.draft(mapping, extract, repo="x")
        self.assertEqual([r["match"]["confidence"] for r in out["items"]], ["chord-only", "chord-only"])

    def test_unmatched_items_are_listed(self):
        self.assertNotIn(("File", "Quit"), self.items)
        self.assertEqual(self.out["unmatched"], [{"path": ["File", "Quit"], "shortcut": "<Ctrl>Q"}])

    def test_placeholders_are_left_out(self):
        self.assertNotIn(("File", "Recent"), self.items)

    def test_summary(self):
        self.assertEqual(self.out["summary"], {"with_shortcut": 4, "label_match": 2, "action_match": 0,
                                               "chord_only": 1, "unmatched": 1})


class DraftCliTest(unittest.TestCase):
    def test_draft_then_verify_round_trip(self):
        tmp, repo, commit = make_repo({
            "src/window.c": 'gtk_application_set_accels_for_action (app, "app.quit", (const char *[]) '
                            '{ "<Primary>q", NULL });\n',
        })
        try:
            d = Path(tmp.name)
            mapping = {"format": 1, "app": "demo", "name": "Demo", "identifiers": ["demo"],
                       "menus": [{"label": "File", "items": [{"label": "Quit", "shortcut": "<Ctrl>Q"}]}]}
            (d / "demo.json").write_text(json.dumps(mapping))
            code, out, err = run_cli("draft-sources", d / "demo.json", "--src", repo)
            self.assertEqual(code, 0, err)
            self.assertEqual(out["items"][0]["commit"], commit)
            (d / "demo.sources.json").write_text(json.dumps(out))
            code, result, err = run_cli("verify-mapping", d / "demo.json", d / "demo.sources.json",
                                        "--src", repo, env={"MAPPING_TOOLS_CACHE": str(d / "cache")})
            self.assertEqual(code, 0, json.dumps(result, indent=1) if result else err)
        finally:
            tmp.cleanup()

    def test_help(self):
        code, _, _ = run_cli("draft-sources", "--help")
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
