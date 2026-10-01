"""The normalizer checked against the extension's own parser, run under gjs.

keySynth.js parseAccelerator() is the parser the running extension uses, so
every string normalize() emits must parse there, to the chord the Python
side meant. Keyvals for the check come from GDK's keysym table, independent
of both parsers.
"""

import json
import re
import unittest

from mtools import accel, gjs
from test_accel import CASES

MOD_KEYSYMS = {"ctrl": "Control_L", "shift": "Shift_L", "alt": "Alt_L", "super": "Super_L"}


def expected_keyvals(seq, keyvals):
    """The parseAccelerator() result the Python chord model predicts."""
    out = []
    for mods, key in seq:
        name = accel.keysym_name(key)
        out.append({
            "modifiers": sorted(keyvals[MOD_KEYSYMS[m]] for m in mods),
            "keyval": keyvals[name],
        })
    return out


def sorted_mods(parsed):
    if parsed is None:
        return None
    return [{"modifiers": sorted(c["modifiers"]), "keyval": c["keyval"]} for c in parsed]


class GjsParserTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.keysynth = gjs.find_keysynth()

    def run_gjs(self, accels, names=()):
        return gjs.parse_accels(accels, names=names, keysynth=self.keysynth)

    def test_every_normalized_case_parses_to_the_same_chord(self):
        outputs = [accel.normalize(raw, dialect).accel for raw, dialect, _ in CASES]
        seqs = [accel.parse_grammar(o) for o in outputs]
        names = {accel.keysym_name(k) for s in seqs for _, k in s} | set(MOD_KEYSYMS.values())
        result = self.run_gjs(outputs, sorted(names))
        for out, seq, parsed in zip(outputs, seqs, result["parsed"]):
            with self.subTest(accel=out):
                self.assertIsNotNone(parsed, f"extension parser rejects {out}")
                self.assertEqual(sorted_mods(parsed), expected_keyvals(seq, result["keyvals"]))

    def test_grammar_key_names_match_keysynth(self):
        source = self.keysynth.read_text()
        block = source[source.index("const NAMED_KEYVALS"):]
        block = block[:block.index("};")]
        js_names = set(re.findall(r"'([a-z0-9_]+)':", block))
        self.assertEqual(js_names, set(accel.GRAMMAR_NAMES))

    def test_rejected_by_both(self):
        bad = ["<Meta>x", "<Ctrl>F13", "<Hyper>a", "", "<Ctrl>", "<Ctrl>Pause", "<Ctrl>KP_Equal"]
        result = self.run_gjs(bad)
        for text, parsed in zip(bad, result["parsed"]):
            with self.subTest(accel=text):
                self.assertIsNone(parsed)
                self.assertIsNone(accel.parse_grammar(text))

    def test_existing_mapping_corpus(self):
        """Python's grammar agrees with the extension on every shipped shortcut."""
        apps = self.keysynth.parent / "shortcuts" / "apps"
        shortcuts = set()

        def walk(items):
            for item in items:
                if "items" in item:
                    walk(item["items"])
                elif isinstance(item.get("shortcut"), str):
                    shortcuts.add(item["shortcut"])

        for path in sorted(apps.glob("*.json")):
            for menu in json.loads(path.read_text()).get("menus", []):
                walk(menu.get("items", []))
        shortcuts = sorted(shortcuts)
        self.assertGreater(len(shortcuts), 500)
        seqs = [accel.parse_grammar(s) for s in shortcuts]
        canon = [accel.format_seq(s) if s else "" for s in seqs]
        result = self.run_gjs(shortcuts + canon)
        original, recanon = result["parsed"][:len(shortcuts)], result["parsed"][len(shortcuts):]
        for text, seq, a, b in zip(shortcuts, seqs, original, recanon):
            with self.subTest(accel=text):
                self.assertEqual(seq is None, a is None)
                if seq is not None:
                    self.assertEqual(sorted_mods(a), sorted_mods(b))


if __name__ == "__main__":
    unittest.main()
