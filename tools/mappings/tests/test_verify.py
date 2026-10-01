"""verify-mapping: every shortcut in a mapping must be proven by its cited source."""

import json
import stat
import unittest
from pathlib import Path

from helpers import make_repo, run_cli

WINDOW_C = """\
#include <gtk/gtk.h>
static void
editor_window_class_init (EditorWindowClass *klass)
{
  gtk_widget_class_add_binding_action (klass, GDK_KEY_s, GDK_CONTROL_MASK, "win.save", NULL);
  gtk_widget_class_add_binding_action (klass, GDK_KEY_F11, 0, "win.fullscreen", NULL);
}

static const char *open_accels[] = {
  "<Primary>o", NULL
};
/* padding */
/* padding */
/* padding */
/* padding */
/* padding */
/* padding */
/* padding */
/* padding */
/* padding */
"""
KEYS_JSON = """\
[
  { "key": "ctrl+k ctrl+s", "command": "workbench.action.openGlobalKeybindings" }
]
"""
MENUS_DOCBOOK = """\
<sect1 id="file">
<para><menuchoice><shortcut><keycombo action="simul">&Ctrl;&Shift;<keycap>E</keycap></keycombo></shortcut>
<guimenu>File</guimenu><guimenuitem>Export</guimenuitem></menuchoice></para>
</sect1>
"""
KDE_CPP = """\
void MainWindow::setupActions()
{
    KStandardAction::quit(this, &MainWindow::close, actionCollection());
}
"""

MAPPING = {
    "format": 1, "app": "demo", "name": "Demo", "identifiers": ["demo"],
    "menus": [
        {"label": "File", "items": [
            {"label": "Save", "shortcut": "<Ctrl>S"},
            {"label": "Open", "shortcut": "<Ctrl>O"},
            {"label": "Keyboard Shortcuts", "shortcut": "<Ctrl>k <Ctrl>s"},
            {"separator": True},
            {"label": "Export", "items": [{"label": "HTML", "shortcut": "<Ctrl><Shift>E"}]},
            {"label": "Recent Files"},
            {"label": "Quit", "shortcut": "<Ctrl>Q"},
        ]},
        {"label": "View", "items": [
            {"label": "Fullscreen", "shortcut": "F11"},
            {"label": "Zoom In", "shortcut": "<Ctrl>plus"},
        ]},
    ],
}


class VerifyTest(unittest.TestCase):
    def setUp(self):
        self.tmp, self.repo, self.commit = make_repo({
            "src/window.c": WINDOW_C,
            "keybindings.json": KEYS_JSON,
            "doc/menus.docbook": MENUS_DOCBOOK,
            "src/mainwindow.cpp": KDE_CPP,
        })
        self.dir = Path(self.tmp.name)
        self.rloop = self.dir / "fake-rloop"
        self.rloop.write_text("#!/bin/sh\necho \"$@\" >> \"$0.log\"\nexit \"${FAKE_RLOOP_EXIT:-0}\"\n")
        self.rloop.chmod(self.rloop.stat().st_mode | stat.S_IEXEC)

    def tearDown(self):
        self.tmp.cleanup()

    def record(self, path, file=None, line=None, **extra):
        rec = {"path": path}
        if file:
            rec.update({"file": file, "line": line, "commit": self.commit})
        rec.update(extra)
        return rec

    def good_records(self):
        return [
            self.record(["File", "Save"], "src/window.c", 5),
            self.record(["File", "Open"], "src/window.c", 10),
            self.record(["File", "Keyboard Shortcuts"], "keybindings.json", 2),
            self.record(["File", "Export", "HTML"], "doc/menus.docbook", 2),
            self.record(["File", "Quit"], "src/mainwindow.cpp", 3),
            self.record(["View", "Fullscreen"], "src/window.c", 6),
            self.record(["View", "Zoom In"], url="https://example.org/keys",
                        quote="Press Ctrl++ to zoom in"),
        ]

    def run_verify(self, records, mapping=None, extra_env=None, args=()):
        mapping_path = self.dir / "demo.json"
        mapping_path.write_text(json.dumps(mapping or MAPPING))
        sources_path = self.dir / "demo.sources.json"
        sources_path.write_text(json.dumps({"format": 1, "app": "demo", "items": records}))
        env = {"RLOOP": str(self.rloop), "MAPPING_TOOLS_CACHE": str(self.dir / "cache")}
        env.update(extra_env or {})
        return run_cli("verify-mapping", mapping_path, sources_path, "--src", self.repo, *args, env=env)

    def item(self, out, path):
        for item in out["items"]:
            if item["path"] == path:
                return item
        self.fail(f"no item {path}")

    def test_all_proven_passes(self):
        code, out, err = self.run_verify(self.good_records())
        self.assertEqual(code, 0, json.dumps(out, indent=1) if out else err)
        self.assertEqual(out["summary"]["failed"], 0)
        self.assertEqual(out["summary"]["passed"], 7)
        self.assertEqual(self.item(out, ["File", "Recent Files"])["status"], "skip")

    def test_evidence_names_how_it_passed(self):
        code, out, _ = self.run_verify(self.good_records())
        save = self.item(out, ["File", "Save"])
        self.assertEqual(save["evidence"]["via"], "extractor")
        self.assertEqual(save["evidence"]["kind"], "gtk-binding")
        self.assertEqual(save["evidence"]["line"], 5)
        quit_ = self.item(out, ["File", "Quit"])
        self.assertEqual(quit_["evidence"]["kind"], "kstandardaction")
        zoom = self.item(out, ["View", "Zoom In"])
        self.assertEqual(zoom["evidence"]["via"], "url")

    def test_missing_record_fails(self):
        records = [r for r in self.good_records() if r["path"] != ["File", "Save"]]
        code, out, _ = self.run_verify(records)
        self.assertEqual(code, 1)
        item = self.item(out, ["File", "Save"])
        self.assertEqual(item["status"], "fail")
        self.assertIn("no provenance", item["reason"])

    def test_invented_shortcut_fails(self):
        mapping = json.loads(json.dumps(MAPPING))
        mapping["menus"][0]["items"][0]["shortcut"] = "<Ctrl><Shift>S"
        code, out, _ = self.run_verify(self.good_records(), mapping=mapping)
        self.assertEqual(code, 1)
        item = self.item(out, ["File", "Save"])
        self.assertEqual(item["status"], "fail")
        self.assertIn("<Ctrl>S", item["reason"])

    def test_line_outside_window_fails(self):
        records = self.good_records()
        records[1] = self.record(["File", "Open"], "src/window.c", 18)
        code, out, _ = self.run_verify(records)
        self.assertEqual(self.item(out, ["File", "Open"])["status"], "fail")

    def test_window_is_three_lines_each_side(self):
        records = self.good_records()
        records[1] = self.record(["File", "Open"], "src/window.c", 13)
        code, out, _ = self.run_verify(records)
        self.assertEqual(self.item(out, ["File", "Open"])["status"], "pass")

    def test_unknown_commit_fails(self):
        records = self.good_records()
        records[0]["commit"] = "0" * 40
        code, out, _ = self.run_verify(records)
        item = self.item(out, ["File", "Save"])
        self.assertEqual(item["status"], "fail")
        self.assertIn("commit", item["reason"])

    def test_missing_file_fails(self):
        records = self.good_records()
        records[0]["file"] = "src/nope.c"
        code, out, _ = self.run_verify(records)
        self.assertEqual(self.item(out, ["File", "Save"])["status"], "fail")

    def test_record_shortcut_must_match_mapping(self):
        records = self.good_records()
        records[0]["shortcut"] = "<Ctrl>W"
        code, out, _ = self.run_verify(records)
        item = self.item(out, ["File", "Save"])
        self.assertEqual(item["status"], "fail")
        self.assertIn("<Ctrl>W", item["reason"])

    def test_record_shortcut_spelling_does_not_matter(self):
        records = self.good_records()
        records[0]["shortcut"] = "<Primary>s"
        code, out, _ = self.run_verify(records)
        self.assertEqual(self.item(out, ["File", "Save"])["status"], "pass")

    def test_any_passing_record_is_enough(self):
        records = self.good_records()
        records.insert(0, self.record(["File", "Save"], "src/window.c", 20))
        code, out, _ = self.run_verify(records)
        self.assertEqual(code, 0)

    def test_url_quote_must_contain_the_key(self):
        records = self.good_records()
        records[-1]["quote"] = "Zoom in with the plus button"
        code, out, _ = self.run_verify(records)
        item = self.item(out, ["View", "Zoom In"])
        self.assertEqual(item["status"], "fail")
        self.assertIn("quote", item["reason"])

    def test_url_quote_not_on_page_fails(self):
        code, out, _ = self.run_verify(self.good_records(), extra_env={"FAKE_RLOOP_EXIT": "6"})
        item = self.item(out, ["View", "Zoom In"])
        self.assertEqual(item["status"], "fail")
        self.assertIn("rloop verify", item["reason"])

    def test_rloop_called_with_quote_and_url(self):
        self.run_verify(self.good_records())
        log = (self.dir / "fake-rloop.log").read_text()
        self.assertIn("--quote Press Ctrl++ to zoom in --url https://example.org/keys", log)

    def test_orphan_records_are_listed(self):
        records = self.good_records() + [self.record(["File", "Sav"], "src/window.c", 5)]
        code, out, _ = self.run_verify(records)
        self.assertEqual(code, 0)
        self.assertEqual(out["orphans"][0]["path"], ["File", "Sav"])

    def test_invalid_mapping_shortcut_fails(self):
        mapping = json.loads(json.dumps(MAPPING))
        mapping["menus"][1]["items"][0]["shortcut"] = "<Meta>F11"
        code, out, _ = self.run_verify(self.good_records(), mapping=mapping)
        self.assertIn("grammar", self.item(out, ["View", "Fullscreen"])["reason"])

    def test_repo_by_id(self):
        root = self.repo.parent
        records = self.good_records()
        for r in records:
            if "file" in r:
                r["repo"] = self.repo.name
        mapping_path = self.dir / "demo.json"
        mapping_path.write_text(json.dumps(MAPPING))
        sources_path = self.dir / "demo.sources.json"
        sources_path.write_text(json.dumps({"format": 1, "app": "demo", "items": records}))
        code, out, err = run_cli("verify-mapping", mapping_path, sources_path,
                                 env={"RLOOP": str(self.rloop), "MAPPING_SOURCES": str(root),
                                      "MAPPING_TOOLS_CACHE": str(self.dir / "cache")})
        self.assertEqual(code, 0, json.dumps(out, indent=1) if out else err)

    def test_help(self):
        code, _, _ = run_cli("verify-mapping", "--help")
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
