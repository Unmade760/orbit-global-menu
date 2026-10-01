"""desktop-ids: desktop id, StartupWMClass and name from an app's source tree."""

import json
import tempfile
import unittest
from pathlib import Path

from helpers import make_repo, run_cli
from mtools import desktop

TREE = {
    "data/org.example.App.desktop": (
        "[Desktop Entry]\nName=Example\nName[de]=Beispiel\nExec=example-app %U\n"
        "Icon=org.example.App\nStartupWMClass=example-app\nType=Application\n"
        "[Desktop Action new-window]\nName=New Window\nExec=example-app --new-window\n"),
    "data/org.example.Tool.desktop.in.in": "[Desktop Entry]\n_Name=Tool\nExec=@BIN@\nType=Application\n",
    "meson/meson.build": (
        "project('meson-app', 'c')\n"
        "app_id = 'org.example.Meson'\n"
        "if get_option('profile') == 'development'\n  app_id = 'org.example.Meson.Devel'\nendif\n"
        "conf = configuration_data()\nconf.set('APP_ID', app_id)\n"
        "desktop_file = i18n.merge_file(\n  input: configure_file(input: 'app.desktop.in.in',\n"
        "    output: 'app.desktop.in', configuration: conf),\n"
        "  output: '@0@.desktop'.format(app_id),\n  install: true,\n)\n"),
    "meson/app.desktop.in.in": "[Desktop Entry]\nName=Meson App\nIcon=@APP_ID@\nExec=meson-app\n",
    "kde/CMakeLists.txt": "install(PROGRAMS org.kde.example.desktop DESTINATION ${KDE_INSTALL_APPDIR})\n",
    "kde/org.kde.example.desktop": "[Desktop Entry]\nName=KExample\nExec=kexample %U\n",
    "data/org.example.App.metainfo.xml.in": (
        "<?xml version=\"1.0\"?>\n<component type=\"desktop-application\">\n"
        "  <id>org.example.App</id>\n  <name>Example</name>\n  <name xml:lang=\"de\">Beispiel</name>\n"
        "  <launchable type=\"desktop-id\">org.example.App.desktop</launchable>\n</component>\n"),
    "package.json": json.dumps({
        "name": "zettlr", "productName": "Zettlr",
        "build": {"appId": "com.zettlr.app",
                  "linux": {"executableName": "zettlr", "desktop": {"StartupWMClass": "Zettlr"}}},
    }),
    "build-aux/flatpak/org.example.App.Devel.json": json.dumps(
        {"id": "org.example.App.Devel", "runtime": "org.gnome.Platform", "command": "example-app"}),
    "tests/data/org.test.Ignored.desktop": "[Desktop Entry]\nName=Ignored\n",
    # gnome-text-editor's shape: both assignments conditional, the Devel one first
    "both/meson.build": (
        "if get_option('profile') == 'development'\n  app_id = 'org.example.Both.Devel'\n"
        "else\n  app_id = 'org.example.Both'\nendif\n"
        "i18n.merge_file(input: 'org.example.Both.desktop.in', output: '@0@.desktop'.format(app_id))\n"),
    "both/org.example.Both.desktop.in": "[Desktop Entry]\nName=Both\nExec=both\n",
    # Zettlr's shape: a desktop file for running a development build
    "scripts/assets/tool-dev.desktop": "[Desktop Entry]\nName=Tool (develop)\nStartupWMClass=ToolDev\nExec=ToolDev\n",
}


class DesktopIdsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        for rel, text in TREE.items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        cls.result = desktop.scan(root)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def entry(self, desktop_id):
        for e in self.result["desktop_files"]:
            if e["desktop_id"] == desktop_id:
                return e
        self.fail(f"no {desktop_id} in {[e['desktop_id'] for e in self.result['desktop_files']]}")

    def test_plain_desktop_file(self):
        e = self.entry("org.example.App.desktop")
        self.assertEqual(e["file"], "data/org.example.App.desktop")
        self.assertEqual(e["name"], "Example")
        self.assertEqual(e["startup_wm_class"], "example-app")
        self.assertEqual(e["exec"], "example-app")
        self.assertEqual(e["line"], 1)

    def test_in_in_suffix_and_intltool_name(self):
        e = self.entry("org.example.Tool.desktop")
        self.assertEqual(e["name"], "Tool")

    def test_meson_output_name_and_placeholders(self):
        e = self.entry("org.example.Meson.desktop")
        self.assertEqual(e["file"], "meson/app.desktop.in.in")
        self.assertEqual(e["icon"], "org.example.Meson")
        self.assertEqual(e["name"], "Meson App")
        self.assertEqual(e["installed_by"]["file"], "meson/meson.build")

    def test_release_id_wins_over_devel_profile(self):
        self.entry("org.example.Both.desktop")

    def test_development_desktop_file_is_not_suggested(self):
        self.entry("tool-dev.desktop")
        for value in ("tool-dev.desktop", "ToolDev", "Tool (develop)"):
            self.assertNotIn(value, self.result["identifiers"])

    def test_cmake_install(self):
        e = self.entry("org.kde.example.desktop")
        self.assertEqual(e["installed_by"]["file"], "kde/CMakeLists.txt")

    def test_metainfo(self):
        m = self.result["metainfo"][0]
        self.assertEqual(m["id"], "org.example.App")
        self.assertEqual(m["launchable"], "org.example.App.desktop")
        self.assertEqual(m["name"], "Example")

    def test_electron_builder_hints(self):
        fields = {(b["field"], b["value"]) for b in self.result["build"] if b["file"] == "package.json"}
        self.assertIn(("name", "zettlr"), fields)
        self.assertIn(("productName", "Zettlr"), fields)
        self.assertIn(("build.appId", "com.zettlr.app"), fields)
        self.assertIn(("build.linux.executableName", "zettlr"), fields)
        self.assertIn(("build.linux.desktop.StartupWMClass", "Zettlr"), fields)

    def test_flatpak_manifest(self):
        fields = {(b["kind"], b["value"]) for b in self.result["build"]}
        self.assertIn(("flatpak", "org.example.App.Devel"), fields)

    def test_identifier_suggestions(self):
        ids = self.result["identifiers"]
        for expected in ("org.example.App.desktop", "org.example.App", "example-app", "Example",
                         "org.example.Meson.desktop", "org.kde.example.desktop", "zettlr",
                         "com.zettlr.app"):
            self.assertIn(expected, ids)
        self.assertNotIn("org.example.App.Devel", ids)
        self.assertNotIn("org.example.Meson.Devel.desktop", ids)
        self.assertEqual(len({i.lower() for i in ids}), len(ids))

    def test_skips_tests(self):
        self.assertNotIn("org.test.Ignored.desktop", [e["desktop_id"] for e in self.result["desktop_files"]])


class DesktopIdsCliTest(unittest.TestCase):
    def test_cli_reports_commit(self):
        tmp, repo, commit = make_repo({"data/app.desktop": "[Desktop Entry]\nName=App\nExec=app\n"})
        try:
            code, out, err = run_cli("desktop-ids", repo)
            self.assertEqual(code, 0, err)
            self.assertEqual(out["commit"], commit)
            self.assertEqual(out["desktop_files"][0]["desktop_id"], "app.desktop")
        finally:
            tmp.cleanup()

    def test_missing_dir(self):
        code, out, _ = run_cli("desktop-ids", "/nonexistent/dir")
        self.assertNotEqual(code, 0)
        self.assertIn("error", out)

    def test_help(self):
        code, _, _ = run_cli("desktop-ids", "--help")
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
