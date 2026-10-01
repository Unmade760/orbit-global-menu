"""bin/normalize: one accelerator (or several) to the mapping grammar."""

import unittest

from helpers import run_cli


class NormalizeCliTest(unittest.TestCase):
    def test_qt_text(self):
        code, out, err = run_cli("normalize", "Ctrl+Shift+S", "--from", "qt")
        self.assertEqual(code, 0, err)
        self.assertEqual(out["accel"], "<Ctrl><Shift>S")
        self.assertEqual(out["from"], "qt")

    def test_auto_detects_dialect(self):
        code, out, err = run_cli("normalize", "CmdOrCtrl+S")
        self.assertEqual(code, 0, err)
        self.assertEqual(out["from"], "electron")
        self.assertEqual(out["accel"], "<Ctrl>S")

    def test_alternatives_are_all_listed(self):
        code, out, err = run_cli("normalize", "<Control>q|<Control>w", "--from", "gtk")
        self.assertEqual(code, 0, err)
        self.assertEqual(out["accel"], "<Ctrl>Q")
        self.assertEqual(out["alternatives"], ["<Ctrl>Q", "<Ctrl>W"])

    def test_error_exits_non_zero(self):
        code, out, _ = run_cli("normalize", "<Meta>q", "--from", "gtk")
        self.assertEqual(code, 1)
        self.assertIsNone(out["accel"])
        self.assertIn("Meta", out["error"])

    def test_several_inputs(self):
        code, out, err = run_cli("normalize", "ctrl+k ctrl+s", "f12", "--from", "vscode")
        self.assertEqual(code, 0, err)
        self.assertEqual([r["accel"] for r in out["results"]], ["<Ctrl>K <Ctrl>S", "F12"])

    def test_gjs_check_uses_the_extension_parser(self):
        code, out, err = run_cli("normalize", "Ctrl+,", "--from", "text", "--gjs")
        self.assertEqual(code, 0, err)
        self.assertEqual(out["accel"], "<Ctrl>comma")
        self.assertTrue(out["extension_parses"])

    def test_unknown_dialect_rejected(self):
        code, _, _ = run_cli("normalize", "Ctrl+S", "--from", "cobol")
        self.assertNotEqual(code, 0)

    def test_help(self):
        code, _, _ = run_cli("normalize", "--help")
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
