"""draft-mapping: a mapping and its SOURCES.json built from extracted menus and rows."""

import json
import unittest
from pathlib import Path

from helpers import make_repo, run_cli
from mtools import draft_mapping, gjs

MAIN = {
    "root": "/src/kate", "commit": "c1", "url": "https://example.org/kate.git",
    "shortcuts": [],
    "menus": [
        {"file": "apps/kateui.rc", "line": 3, "kind": "kxmlgui", "id": "file", "label": "File", "items": [
            {"action": "file_new", "label": "New", "accel": "<Ctrl>N", "accel_line": 4, "line": 4},
            {"separator": True},
            {"separator": True},
            {"action": "file_save_all", "label": "Save All", "accel": "<Ctrl>L", "line": 7,
             "accel_source": {"file": "apps/mainwindow.cpp", "line": 40}},
            {"action": "file_mystery", "line": 8},
            {"label": "Export", "id": "file_export", "line": 9, "items": [
                {"action": "file_export_html", "label": "HTML", "accel": "<Ctrl><Shift>E", "accel_line": 30,
                 "line": 10}]},
            {"label": "Empty", "id": "file_empty", "line": 12, "items": []},
            {"action": "file_close_all", "label": "Close All", "line": 13},
            {"separator": True},
        ]},
        {"file": "apps/kateui.rc", "line": 20, "kind": "kxmlgui", "id": "tools", "label": "Tools", "items": [
            {"action": "tools_a", "label": "Spelling", "line": 21},
            {"action": "tools_b", "label": "External Tools", "accel": "<Ctrl><Alt>E", "accel_line": 22, "line": 22},
        ]},
        {"file": "src/gtk-primary.ui", "line": 1, "kind": "gmenu", "id": "primary", "items": [
            {"action": "app.x", "label": "Not a menubar", "line": 2}]},
    ],
}
PLUGIN = {
    "root": "/src/kate-plugins", "commit": "c2", "url": "https://example.org/plugins.git",
    "shortcuts": [],
    "menus": [
        {"file": "addons/ui.rc", "line": 2, "kind": "kxmlgui", "id": "tools", "label": "Tools", "items": [
            {"action": "tools_b", "label": "External Tools", "accel": "<Ctrl><Alt>E", "accel_line": 3, "line": 3},
            {"action": "tools_a", "label": "Spelling", "line": 4},
            {"action": "tools_c", "label": "Word Count", "accel": "<Ctrl><Alt>W", "accel_line": 5, "line": 5},
        ]},
    ],
}
DOCS = {
    "root": "/src/app", "commit": "c3", "url": None, "menus": [],
    "shortcuts": [
        {"accel_raw": "Ctrl+N", "accel": "<Ctrl>N", "label": "New", "action": None, "file": "doc/menus.docbook",
         "line": 5, "kind": "docbook-menuchoice", "context": "File"},
        {"accel_raw": "Ctrl+6", "accel": "<Ctrl>6", "label": "Go to Matching Bracket", "action": None,
         "file": "doc/menus.docbook", "line": 9, "kind": "docbook-menuchoice", "context": "Edit > Go To"},
        {"accel_raw": "Ctrl+N", "accel": "<Ctrl>N", "label": "New", "action": None, "file": "doc/other.docbook",
         "line": 2, "kind": "docbook-menuchoice", "context": "File"},
        {"accel_raw": "<ctrl>z", "accel": "<Ctrl>Z", "label": "Undo previous command", "action": None,
         "file": "src/shortcuts.ui", "line": 7, "kind": "adw-shortcuts-dialog", "context": "Undo and Redo"},
        {"accel_raw": "Ctrl+Q", "accel": "<Ctrl>Q", "label": "Quit", "action": None, "file": "README.md",
         "line": 3, "kind": "doc-text", "context": "Keys"},
        {"accel_raw": "<Meta>x", "accel": None, "label": "Broken", "action": None, "file": "doc/x.docbook",
         "line": 1, "kind": "docbook-menuchoice", "context": "File", "error": "no"},
    ],
}


def labels(items):
    return ["---" if i.get("separator") else i["label"] for i in items]


class MenusStrategyTest(unittest.TestCase):
    def setUp(self):
        self.out = draft_mapping.draft_mapping([MAIN, PLUGIN], app="kate", name="Kate",
                                               identifiers=["org.kde.kate.desktop", "kate"])
        self.mapping = self.out["mapping"]
        self.menus = {m["label"]: m for m in self.mapping["menus"]}

    def test_mapping_header(self):
        self.assertEqual(self.mapping["format"], 1)
        self.assertEqual(self.mapping["app"], "kate")
        self.assertEqual(self.mapping["identifiers"], ["org.kde.kate.desktop", "kate"])
        self.assertEqual(self.out["strategy"], "menus")

    def test_menubar_menus_only_in_source_order(self):
        self.assertEqual([m["label"] for m in self.mapping["menus"]], ["File", "Tools"])

    def test_items_separators_and_placeholders(self):
        self.assertEqual(labels(self.menus["File"]["items"]), ["New", "---", "Save All", "Export", "Close All"])
        self.assertEqual(self.menus["File"]["items"][0], {"label": "New", "shortcut": "<Ctrl>N"})
        self.assertEqual(self.menus["File"]["items"][-1], {"label": "Close All"})

    def test_unlabeled_and_empty_are_dropped_and_reported(self):
        dropped = {tuple(d["path"]): d["reason"] for d in self.out["report"]["dropped"]}
        self.assertIn("no label", dropped[("File", "file_mystery")])
        self.assertIn("empty", dropped[("File", "Empty")])

    def test_menus_with_the_same_id_merge_across_repos(self):
        self.assertEqual(labels(self.menus["Tools"]["items"]), ["Spelling", "External Tools", "Word Count"])

    def test_every_shortcut_has_a_record_at_its_proving_line(self):
        recs = {tuple(r["path"]): r for r in self.out["sources"]["items"]}
        self.assertEqual(recs[("File", "New")], {"path": ["File", "New"], "shortcut": "<Ctrl>N",
                                                 "repo": "kate", "file": "apps/kateui.rc", "line": 4,
                                                 "commit": "c1"})
        self.assertEqual(recs[("File", "Save All")]["file"], "apps/mainwindow.cpp")
        self.assertEqual(recs[("File", "Save All")]["line"], 40)
        self.assertEqual(recs[("File", "Export", "HTML")]["line"], 30)
        self.assertEqual(recs[("Tools", "Word Count")]["repo"], "kate-plugins")
        self.assertEqual(recs[("Tools", "Word Count")]["commit"], "c2")
        self.assertEqual(set(self.out["sources"]["repos"]), {"kate", "kate-plugins"})

    def test_one_record_per_item_and_no_orphans(self):
        leaves = []

        def walk(items, prefix):
            for i in items:
                if "items" in i:
                    walk(i["items"], prefix + [i["label"]])
                elif "shortcut" in i:
                    leaves.append(prefix + [i["label"]])
        for m in self.mapping["menus"]:
            walk(m["items"], [m["label"]])
        paths = [r["path"] for r in self.out["sources"]["items"]]
        self.assertEqual(sorted(paths), sorted(leaves))
        tools = [r for r in self.out["sources"]["items"] if r["path"] == ["Tools", "External Tools"]][0]
        self.assertEqual((tools["repo"], tools["line"]), ("kate", 22))

    def test_shortcuts_parse_with_the_extension_parser(self):
        found = []

        def walk(items):
            for i in items:
                if "items" in i:
                    walk(i["items"])
                elif "shortcut" in i:
                    found.append(i["shortcut"])
        for m in self.mapping["menus"]:
            walk(m["items"])
        parsed = gjs.parse_accels(found)["parsed"]
        self.assertTrue(found)
        self.assertTrue(all(p is not None for p in parsed))


class SectionsStrategyTest(unittest.TestCase):
    def setUp(self):
        self.out = draft_mapping.draft_mapping([DOCS], app="app", name="App", identifiers=["app"])
        self.menus = {m["label"]: m for m in self.out["mapping"]["menus"]}

    def test_auto_falls_back_to_sections(self):
        self.assertEqual(self.out["strategy"], "sections")

    def test_grouped_by_context_with_submenus(self):
        self.assertEqual(labels(self.menus["File"]["items"]), ["New"])
        go_to = self.menus["Edit"]["items"][0]
        self.assertEqual(go_to["label"], "Go To")
        self.assertEqual(go_to["items"], [{"label": "Go to Matching Bracket", "shortcut": "<Ctrl>6"}])
        self.assertEqual(self.menus["Undo and Redo"]["items"][0]["shortcut"], "<Ctrl>Z")

    def test_prose_docs_are_not_menus(self):
        self.assertNotIn("Keys", self.menus)

    def test_records(self):
        recs = {tuple(r["path"]): r for r in self.out["sources"]["items"]}
        self.assertEqual(recs[("Edit", "Go To", "Go to Matching Bracket")]["line"], 9)
        self.assertEqual(recs[("File", "New")]["file"], "doc/menus.docbook")


class DraftMappingCliTest(unittest.TestCase):
    def test_round_trip_through_verify(self):
        tmp, repo, commit = make_repo({
            "src/appui.rc": ('<gui name="app"><MenuBar>\n<Menu name="file"><text>&amp;File</text>\n'
                             '<Action name="file_save"/>\n<Action name="file_export"/>\n</Menu>\n</MenuBar>\n'
                             '<ActionProperties><Action shortcut="Ctrl+Shift+E" name="file_export"/>'
                             '</ActionProperties>\n</gui>\n'),
            "src/main.cpp": ('void W::setup() {\n  QAction *a = actionCollection()->addAction(QStringLiteral("file_export"));\n'
                             '  a->setText(i18n("&Export"));\n}\n'),
        })
        try:
            d = Path(tmp.name)
            code, out, err = run_cli("extract-shortcuts", repo)
            self.assertEqual(code, 0, err)
            (d / "extract.json").write_text(json.dumps(out))
            code, out, err = run_cli("draft-mapping", d / "extract.json", "--app", "demo", "--name", "Demo",
                                     "--identifier", "demo", "--out-dir", d / "out")
            self.assertEqual(code, 0, err)
            mapping = json.loads((d / "out" / "demo.json").read_text())
            self.assertEqual(labels(mapping["menus"][0]["items"]), ["Save", "Export"])
            code, result, err = run_cli("verify-mapping", d / "out" / "demo.json", d / "out" / "demo.sources.json",
                                        "--src", repo, env={"MAPPING_TOOLS_CACHE": str(d / "cache")})
            self.assertEqual(code, 0, json.dumps(result, indent=1) if result else err)
            self.assertEqual(result["summary"]["passed"], 2)
        finally:
            tmp.cleanup()

    def test_help(self):
        code, _, _ = run_cli("draft-mapping", "--help")
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
