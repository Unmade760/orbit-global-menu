"""Normalization of every supported accelerator dialect to the mapping grammar.

Each case is (input, dialect, expected canonical string). The canonical form
orders modifiers Ctrl, Shift, Alt, Super, writes letters in upper case and
punctuation by its X11 keysym name. test_gjs_parser.py checks every expected
string below against the extension's own parser.
"""

import unittest

from mtools import accel

CASES = [
    # GTK accelerator strings
    ("<Primary>s", "gtk", "<Ctrl>S"),
    ("<Control><Shift>z", "gtk", "<Ctrl><Shift>Z"),
    ("<Shift><Control>s", "gtk", "<Ctrl><Shift>S"),
    ("<ctrl><alt>Delete", "gtk", "<Ctrl><Alt>Delete"),
    ("<Primary>comma", "gtk", "<Ctrl>comma"),
    ("<Primary>plus", "gtk", "<Ctrl>plus"),
    ("<Primary>KP_Add", "gtk", "<Ctrl>KP_Add"),
    ("<primary>KP_0", "gtk", "<Ctrl>KP_0"),
    ("F11", "gtk", "F11"),
    ("<Shift>F10", "gtk", "<Shift>F10"),
    ("<Alt>Left", "gtk", "<Alt>Left"),
    ("<Primary>Page_Down", "gtk", "<Ctrl>Page_Down"),
    ("<Primary>Next", "gtk", "<Ctrl>Page_Down"),
    ("<Primary>Prior", "gtk", "<Ctrl>Page_Up"),
    ("<Primary><Shift>ISO_Left_Tab", "gtk", "<Ctrl><Shift>Tab"),
    ("<Primary>question", "gtk", "<Ctrl>question"),
    ("<Primary>0", "gtk", "<Ctrl>0"),
    ("<Super>Up", "gtk", "<Super>Up"),
    ("<Mod1>q", "gtk", "<Alt>Q"),
    ("<Ctl>w", "gtk", "<Ctrl>W"),
    ("Escape", "gtk", "Escape"),
    ("<Control>Return", "gtk", "<Ctrl>Return"),
    ("<Control>KP_Enter", "gtk", "<Ctrl>KP_Enter"),
    ("<Control>BackSpace", "gtk", "<Ctrl>BackSpace"),
    ("<Control>space", "gtk", "<Ctrl>space"),
    ("<Control>S", "gtk", "<Ctrl>S"),
    ("<Control>underscore", "gtk", "<Ctrl>underscore"),
    ("<Control>grave", "gtk", "<Ctrl>grave"),
    ("<Control>/", "gtk", "<Ctrl>slash"),
    # Qt portable text
    ("Ctrl+S", "qt", "<Ctrl>S"),
    ("ctrl+s", "qt", "<Ctrl>S"),
    ("Ctrl+Shift+S", "qt", "<Ctrl><Shift>S"),
    ("Shift+Ctrl+S", "qt", "<Ctrl><Shift>S"),
    ("Ctrl++", "qt", "<Ctrl>plus"),
    ("Ctrl+-", "qt", "<Ctrl>minus"),
    ("Ctrl+=", "qt", "<Ctrl>equal"),
    ("Ctrl+,", "qt", "<Ctrl>comma"),
    ("Meta+Left", "qt", "<Super>Left"),
    ("Alt+F4", "qt", "<Alt>F4"),
    ("Del", "qt", "Delete"),
    ("Shift+Del", "qt", "<Shift>Delete"),
    ("Ins", "qt", "Insert"),
    ("PgUp", "qt", "Page_Up"),
    ("Ctrl+PgDown", "qt", "<Ctrl>Page_Down"),
    ("Ctrl+Page Down", "qt", "<Ctrl>Page_Down"),
    ("Esc", "qt", "Escape"),
    ("Return", "qt", "Return"),
    ("Ctrl+Return", "qt", "<Ctrl>Return"),
    ("Enter", "qt", "KP_Enter"),
    ("Backtab", "qt", "<Shift>Tab"),
    ("Ctrl+Backtab", "qt", "<Ctrl><Shift>Tab"),
    ("Ctrl+Space", "qt", "<Ctrl>space"),
    ("Ctrl+K, Ctrl+S", "qt", "<Ctrl>K <Ctrl>S"),
    ("Ctrl+,, Ctrl+X", "qt", "<Ctrl>comma <Ctrl>X"),
    ("Num++", "qt", "KP_Add"),
    ("Print", "qt", "Print"),
    # Qt enum expressions
    ("Qt::CTRL | Qt::Key_S", "qt", "<Ctrl>S"),
    ("Qt::CTRL | Qt::SHIFT | Qt::Key_Z", "qt", "<Ctrl><Shift>Z"),
    ("Qt::CTRL + Qt::Key_S", "qt", "<Ctrl>S"),
    ("Qt::ControlModifier | Qt::Key_Plus", "qt", "<Ctrl>plus"),
    ("Qt::Key_F5", "qt", "F5"),
    ("Qt::ALT | Qt::Key_Return", "qt", "<Alt>Return"),
    ("Qt::META | Qt::Key_Left", "qt", "<Super>Left"),
    ("Qt::Key_Delete", "qt", "Delete"),
    ("Qt::CTRL | Qt::Key_QuoteLeft", "qt", "<Ctrl>grave"),
    ("Qt::Modifier::CTRL | Qt::Key::Key_B", "qt", "<Ctrl>B"),
    ("Qt.Key.Key_S | Qt.KeyboardModifier.ControlModifier", "qt", "<Ctrl>S"),
    ("Qt::SHIFT | Qt::Key_Backtab", "qt", "<Shift>Tab"),
    # Electron
    ("CmdOrCtrl+S", "electron", "<Ctrl>S"),
    ("CommandOrControl+Shift+Z", "electron", "<Ctrl><Shift>Z"),
    ("Shift+CmdOrCtrl+R", "electron", "<Ctrl><Shift>R"),
    ("CmdOrCtrl+Plus", "electron", "<Ctrl>plus"),
    ("CommandOrControl+-", "electron", "<Ctrl>minus"),
    ("CmdOrCtrl+0", "electron", "<Ctrl>0"),
    ("Ctrl+Shift+I", "electron", "<Ctrl><Shift>I"),
    ("F11", "electron", "F11"),
    ("Super+Up", "electron", "<Super>Up"),
    ("Meta+K", "electron", "<Super>K"),
    ("Cmd+Q", "electron", "<Super>Q"),
    ("Option+X", "electron", "<Alt>X"),
    ("CmdOrCtrl+PageUp", "electron", "<Ctrl>Page_Up"),
    ("Esc", "electron", "Escape"),
    ("Enter", "electron", "Return"),
    ("num1", "electron", "KP_1"),
    ("numadd", "electron", "KP_Add"),
    ("numdec", "electron", "KP_Decimal"),
    ("PrintScreen", "electron", "Print"),
    ("Space", "electron", "space"),
    ("CmdOrCtrl+,", "electron", "<Ctrl>comma"),
    # Java KeyStroke text and VK constants
    ("control S", "java", "<Ctrl>S"),
    ("ctrl shift S", "java", "<Ctrl><Shift>S"),
    ("shift control Z", "java", "<Ctrl><Shift>Z"),
    ("alt F4", "java", "<Alt>F4"),
    ("control EQUALS", "java", "<Ctrl>equal"),
    ("control ADD", "java", "<Ctrl>KP_Add"),
    ("control shift OPEN_BRACKET", "java", "<Ctrl><Shift>bracketleft"),
    ("control BACK_SPACE", "java", "<Ctrl>BackSpace"),
    ("control PAGE_UP", "java", "<Ctrl>Page_Up"),
    ("meta Q", "java", "<Super>Q"),
    ("control NUMPAD0", "java", "<Ctrl>KP_0"),
    ("control ENTER", "java", "<Ctrl>Return"),
    ("control BACK_QUOTE", "java", "<Ctrl>grave"),
    ("control QUOTE", "java", "<Ctrl>apostrophe"),
    ("SPACE", "java", "space"),
    ("control typed a", "java", "<Ctrl>A"),
    ("pressed ESCAPE", "java", "Escape"),
    ("KeyEvent.VK_S, InputEvent.CTRL_DOWN_MASK | InputEvent.SHIFT_DOWN_MASK", "java", "<Ctrl><Shift>S"),
    ("KeyEvent.VK_F4, InputEvent.ALT_MASK", "java", "<Alt>F4"),
    ("VK_N, Toolkit.getDefaultToolkit().getMenuShortcutKeyMaskEx()", "java", "<Ctrl>N"),
    ("KeyEvent.VK_DELETE, 0", "java", "Delete"),
    # VS Code keybinding strings and KeyMod expressions
    ("ctrl+shift+p", "vscode", "<Ctrl><Shift>P"),
    ("ctrl+k ctrl+s", "vscode", "<Ctrl>K <Ctrl>S"),
    ("ctrl+`", "vscode", "<Ctrl>grave"),
    ("ctrl+=", "vscode", "<Ctrl>equal"),
    ("ctrl+numpad0", "vscode", "<Ctrl>KP_0"),
    ("ctrl+numpad_add", "vscode", "<Ctrl>KP_Add"),
    ("meta+k", "vscode", "<Super>K"),
    ("win+k", "vscode", "<Super>K"),
    ("alt+left", "vscode", "<Alt>Left"),
    ("shift+pagedown", "vscode", "<Shift>Page_Down"),
    ("enter", "vscode", "Return"),
    ("f12", "vscode", "F12"),
    ("KeyMod.CtrlCmd | KeyCode.KeyS", "vscode", "<Ctrl>S"),
    ("KeyMod.CtrlCmd | KeyMod.Shift | KeyCode.KeyP", "vscode", "<Ctrl><Shift>P"),
    ("KeyChord(KeyMod.CtrlCmd | KeyCode.KeyK, KeyCode.KeyS)", "vscode", "<Ctrl>K S"),
    ("KeyChord(KeyMod.CtrlCmd | KeyCode.KeyK, KeyMod.CtrlCmd | KeyCode.KeyO)", "vscode", "<Ctrl>K <Ctrl>O"),
    ("KeyMod.Alt | KeyCode.LeftArrow", "vscode", "<Alt>Left"),
    ("KeyMod.WinCtrl | KeyCode.KeyG", "vscode", "<Super>G"),
    ("KeyCode.F12", "vscode", "F12"),
    ("KeyMod.CtrlCmd | KeyCode.Equal", "vscode", "<Ctrl>equal"),
    ("KeyMod.CtrlCmd | KeyCode.Digit1", "vscode", "<Ctrl>1"),
    ("KeyMod.CtrlCmd | KeyCode.Backquote", "vscode", "<Ctrl>grave"),
    ("KeyMod.CtrlCmd | KeyCode.Numpad0", "vscode", "<Ctrl>KP_0"),
    ("KeyMod.Shift + KeyMod.Alt + KeyCode.KeyF", "vscode", "<Shift><Alt>F"),
    ("(KeyMod.CtrlCmd | KeyMod.Shift | KeyCode.KeyP)", "vscode", "<Ctrl><Shift>P"),
    # GDK keysym constants with a modifier mask (C, Python, Rust, Vala, JS)
    ("GDK_KEY_s, GDK_CONTROL_MASK | GDK_SHIFT_MASK", "gdk", "<Ctrl><Shift>S"),
    ("Gdk.KEY_n, Gdk.ModifierType.CONTROL_MASK", "gdk", "<Ctrl>N"),
    ("gdk::Key::w, gdk::ModifierType::CONTROL_MASK", "gdk", "<Ctrl>W"),
    ("Gdk.Key.r, Gdk.ModifierType.CONTROL_MASK", "gdk", "<Ctrl>R"),
    ("GDK_KEY_Escape, 0", "gdk", "Escape"),
    ("GDK_KEY_KP_Add, GDK_CONTROL_MASK", "gdk", "<Ctrl>KP_Add"),
    ("GDK_KEY_1, GDK_ALT_MASK", "gdk", "<Alt>1"),
    # Human text
    ("Ctrl+S", "text", "<Ctrl>S"),
    ("Ctrl + S", "text", "<Ctrl>S"),
    ("Ctrl-S", "text", "<Ctrl>S"),
    ("Control+Shift+Z", "text", "<Ctrl><Shift>Z"),
    ("Shift + Ctrl + Z", "text", "<Ctrl><Shift>Z"),
    ("Super+Left", "text", "<Super>Left"),
    ("Win+E", "text", "<Super>E"),
    ("Ctrl+Enter", "text", "<Ctrl>Return"),
    ("Ctrl+Page Up", "text", "<Ctrl>Page_Up"),
    ("Ctrl+PgDn", "text", "<Ctrl>Page_Down"),
    ("Ctrl+Plus", "text", "<Ctrl>plus"),
    ("Ctrl++", "text", "<Ctrl>plus"),
    ("Ctrl+Minus", "text", "<Ctrl>minus"),
    ("F1", "text", "F1"),
    ("Esc", "text", "Escape"),
    ("Ctrl+K Ctrl+S", "text", "<Ctrl>K <Ctrl>S"),
    ("Ctrl+Shift+/", "text", "<Ctrl><Shift>slash"),
    ("Ctrl+.", "text", "<Ctrl>period"),
    ("Cmd/Ctrl+S", "text", "<Ctrl>S"),
    ("Ctrl/Cmd+S", "text", "<Ctrl>S"),
    ("Ctrl+Alt+Del", "text", "<Ctrl><Alt>Delete"),
    ("Ctrl+Space", "text", "<Ctrl>space"),
    ("Ctrl+↑", "text", "<Ctrl>Up"),
    ("Shift+Tab", "text", "<Shift>Tab"),
    ("Primary+S", "text", "<Ctrl>S"),
    ("<kbd>Ctrl</kbd>+<kbd>S</kbd>", "text", "<Ctrl>S"),
    ("<kbd>Ctrl</kbd><kbd>Shift</kbd><kbd>N</kbd>", "text", "<Ctrl><Shift>N"),
    ("Ctrl+Shift+Page Down", "text", "<Ctrl><Shift>Page_Down"),
    ("ctrl+shift+n", "text", "<Ctrl><Shift>N"),
    ("Ctrl+Backspace", "text", "<Ctrl>BackSpace"),
    ("Ctrl+Insert", "text", "<Ctrl>Insert"),
    ("Alt+Home", "text", "<Alt>Home"),
    ("Ctrl+Comma", "text", "<Ctrl>comma"),
    ("Ctrl+`", "text", "<Ctrl>grave"),
]

ERRORS = [
    ("<Meta>q", "gtk"),
    ("<Hyper>q", "gtk"),
    ("<Primary>F13", "gtk"),
    ("<Primary>XF86Search", "gtk"),
    ("<Control>", "gtk"),
    ("", "gtk"),
    ("<Primary>KP_Home", "gtk"),
    ("F13", "qt"),
    ("Media Play", "qt"),
    ("Ctrl+", "qt"),
    ("AltGr+X", "electron"),
    ("VolumeUp", "electron"),
    ("CmdOrCtrl+", "electron"),
    ("altGraph X", "java"),
    ("button1 X", "java"),
    ("F13", "java"),
    ("ctrl+f13", "vscode"),
    ("GDK_KEY_q, GDK_META_MASK", "gdk"),
    ("GDK_KEY_F13, 0", "gdk"),
    ("ctrl+pausebreak", "vscode"),
    ("Ctrl+Mouse Wheel", "text"),
    ("⌘S", "text"),
    ("Ctrl+1 … Ctrl+9", "text"),
    ("Save the file", "text"),
]


class NormalizeTest(unittest.TestCase):
    def test_cases(self):
        for raw, dialect, expected in CASES:
            with self.subTest(raw=raw, dialect=dialect):
                result = accel.normalize(raw, dialect)
                self.assertIsNone(result.error, result.error)
                self.assertEqual(result.accel, expected)

    def test_errors(self):
        for raw, dialect in ERRORS:
            with self.subTest(raw=raw, dialect=dialect):
                result = accel.normalize(raw, dialect)
                self.assertIsNone(result.accel)
                self.assertTrue(result.error)

    def test_auto_detects_dialect(self):
        for raw, expected in [
            ("<Primary>s", "<Ctrl>S"),
            ("Qt::CTRL | Qt::Key_S", "<Ctrl>S"),
            ("CmdOrCtrl+Shift+S", "<Ctrl><Shift>S"),
            ("KeyMod.CtrlCmd | KeyCode.KeyP", "<Ctrl>P"),
            ("control shift S", "<Ctrl><Shift>S"),
            ("KeyEvent.VK_S, InputEvent.CTRL_DOWN_MASK", "<Ctrl>S"),
            ("Ctrl+Shift+S", "<Ctrl><Shift>S"),
            ("GDK_KEY_s, GDK_CONTROL_MASK", "<Ctrl>S"),
        ]:
            with self.subTest(raw=raw):
                self.assertEqual(accel.normalize(raw).accel, expected)

    def test_text_alternatives(self):
        results = accel.normalize_all("Ctrl+Y, Ctrl+Shift+Z", "text")
        self.assertEqual([r.accel for r in results], ["<Ctrl>Y", "<Ctrl><Shift>Z"])
        results = accel.normalize_all("Ctrl+Y or Ctrl+Shift+Z", "text")
        self.assertEqual([r.accel for r in results], ["<Ctrl>Y", "<Ctrl><Shift>Z"])

    def test_gtk_trigger_alternatives(self):
        results = accel.normalize_all("<Control>q|<Control>w", "gtk")
        self.assertEqual([r.accel for r in results], ["<Ctrl>Q", "<Ctrl>W"])


class GrammarTest(unittest.TestCase):
    def test_parse_grammar_matches_extension_rules(self):
        self.assertIsNotNone(accel.parse_grammar("<Ctrl>T"))
        self.assertIsNotNone(accel.parse_grammar("<Ctrl>k <Ctrl>o"))
        self.assertIsNotNone(accel.parse_grammar(": w Return"))
        self.assertIsNotNone(accel.parse_grammar("<Control><Primary>x"))
        self.assertIsNone(accel.parse_grammar("<Meta>x"))
        self.assertIsNone(accel.parse_grammar("<Ctrl>F13"))
        self.assertIsNone(accel.parse_grammar(""))
        self.assertIsNone(accel.parse_grammar("<Ctrl> x"))

    def test_same_chord_ignores_spelling(self):
        self.assertTrue(accel.same(accel.parse_grammar("<Ctrl>,"), accel.parse_grammar("<Primary>comma")))
        self.assertTrue(accel.same(accel.parse_grammar("<Shift><Ctrl>s"), accel.parse_grammar("<Ctrl><Shift>S")))
        self.assertFalse(accel.same(accel.parse_grammar("<Ctrl>s"), accel.parse_grammar("<Ctrl><Shift>s")))

    def test_canonical_round_trip(self):
        for raw, dialect, expected in CASES:
            with self.subTest(expected=expected):
                seq = accel.parse_grammar(expected)
                self.assertIsNotNone(seq)
                self.assertEqual(accel.format_seq(seq), expected)


if __name__ == "__main__":
    unittest.main()
