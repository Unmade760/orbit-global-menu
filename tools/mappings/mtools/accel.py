"""Accelerators: the mapping grammar and every dialect that normalizes to it.

The mapping grammar is the one global-menu@unmade.space/accelerator.js
parseAccelerator() accepts (docs/shortcut-mappings.md): modifiers <Ctrl>
(also <Control>, <Primary>), <Shift>, <Alt>, <Super>, then one printable
ASCII character or one of a fixed set of keysym names; chords separated by a
space form a sequence. A capital letter is not Shift.

Internally a chord is (frozenset of "ctrl"/"shift"/"alt"/"super", key id).
The key id is the lower-cased character for printable ASCII (so "comma" and
"," are the same key, as they are in accelerator.js) or the lower-cased keysym
name for everything else. A sequence is a tuple of chords.

Canonical output orders modifiers Ctrl, Shift, Alt, Super, writes letters in
upper case (the style of the shipped mappings) and punctuation by its X11
keysym name, which is what GTK itself writes.
"""

import re
from dataclasses import dataclass, field

MOD_ORDER = ("ctrl", "shift", "alt", "super")
MOD_TOKEN = {"ctrl": "<Ctrl>", "shift": "<Shift>", "alt": "<Alt>", "super": "<Super>"}

# accelerator.js NAMED_KEYVALS: lower-cased name -> canonical spelling.
# tests/test_gjs_parser.py fails if this drifts from the extension.
GRAMMAR_NAMES = {
    **{f"f{i}": f"F{i}" for i in range(1, 13)},
    "return": "Return", "escape": "Escape", "tab": "Tab", "backspace": "BackSpace",
    "delete": "Delete", "home": "Home", "end": "End", "page_up": "Page_Up",
    "page_down": "Page_Down", "left": "Left", "up": "Up", "right": "Right", "down": "Down",
    "space": "space", "exclam": "exclam", "quotedbl": "quotedbl", "numbersign": "numbersign",
    "dollar": "dollar", "percent": "percent", "ampersand": "ampersand",
    "apostrophe": "apostrophe", "parenleft": "parenleft", "parenright": "parenright",
    "asterisk": "asterisk", "plus": "plus", "comma": "comma", "minus": "minus",
    "period": "period", "slash": "slash", "colon": "colon", "semicolon": "semicolon",
    "less": "less", "equal": "equal", "greater": "greater", "question": "question",
    "at": "at", "bracketleft": "bracketleft", "backslash": "backslash",
    "bracketright": "bracketright", "asciicircum": "asciicircum",
    "underscore": "underscore", "grave": "grave", "braceleft": "braceleft", "bar": "bar",
    "braceright": "braceright", "asciitilde": "asciitilde", "print": "Print",
    "insert": "Insert", "menu": "Menu",
    **{f"kp_{i}": f"KP_{i}" for i in range(10)},
    "kp_decimal": "KP_Decimal", "kp_add": "KP_Add", "kp_subtract": "KP_Subtract",
    "kp_multiply": "KP_Multiply", "kp_divide": "KP_Divide", "kp_enter": "KP_Enter",
}

# Printable punctuation and its X11 keysym name
PUNCT = {
    "!": "exclam", '"': "quotedbl", "#": "numbersign", "$": "dollar", "%": "percent",
    "&": "ampersand", "'": "apostrophe", "(": "parenleft", ")": "parenright",
    "*": "asterisk", "+": "plus", ",": "comma", "-": "minus", ".": "period",
    "/": "slash", ":": "colon", ";": "semicolon", "<": "less", "=": "equal",
    ">": "greater", "?": "question", "@": "at", "[": "bracketleft", "\\": "backslash",
    "]": "bracketright", "^": "asciicircum", "_": "underscore", "`": "grave",
    "{": "braceleft", "|": "bar", "}": "braceright", "~": "asciitilde",
}
PUNCT_BY_NAME = {name: char for char, name in PUNCT.items()}

DIALECTS = ("gtk", "gdk", "qt", "electron", "java", "vscode", "text")


class AccelError(ValueError):
    pass


@dataclass
class Result:
    raw: str
    dialect: str
    accel: str | None = None
    seq: tuple | None = None
    error: str | None = None
    notes: list = field(default_factory=list)

    def as_dict(self):
        out = {"input": self.raw, "from": self.dialect, "accel": self.accel}
        if self.error:
            out["error"] = self.error
        if self.notes:
            out["notes"] = self.notes
        return out


# --- the grammar itself --------------------------------------------------

def key_id(token):
    """Grammar key token (one printable char or an accelerator.js name) to key id."""
    if len(token) == 1:
        if not 0x21 <= ord(token) <= 0x7E:
            return None
        return token.lower()
    low = token.lower()
    if low in PUNCT_BY_NAME:
        return PUNCT_BY_NAME[low]
    if low in GRAMMAR_NAMES:
        return low
    return None


def keysym_name(key):
    """Key id to its keysym name, as GDK spells it."""
    if len(key) == 1:
        if key.isalnum():
            return key
        return PUNCT[key]
    return GRAMMAR_NAMES[key]


def format_key(key):
    if len(key) == 1:
        if key.isalpha():
            return key.upper()
        if key.isdigit():
            return key
        return PUNCT[key]
    return GRAMMAR_NAMES[key]


def format_chord(chord):
    mods, key = chord
    return "".join(MOD_TOKEN[m] for m in MOD_ORDER if m in mods) + format_key(key)


def format_seq(seq):
    return " ".join(format_chord(c) for c in seq)


_GRAMMAR_MODS = {"ctrl": "ctrl", "control": "ctrl", "primary": "ctrl",
                 "shift": "shift", "alt": "alt", "super": "super"}


def parse_grammar(text):
    """Mirror of accelerator.js parseAccelerator(): a sequence, or None."""
    if not isinstance(text, str) or text == "":
        return None
    seq = []
    for part in text.split(" "):
        if part == "":
            return None
        mods = set()
        rest = part
        while (m := re.match(r"^<([^<>]+)>", rest)):
            mod = _GRAMMAR_MODS.get(m.group(1).lower())
            if mod is None:
                return None
            mods.add(mod)
            rest = rest[m.end():]
        key = key_id(rest) if rest else None
        if key is None:
            return None
        seq.append((frozenset(mods), key))
    return tuple(seq)


def same(a, b):
    return a is not None and b is not None and tuple(a) == tuple(b)


def _chord(mods, key):
    return (frozenset(mods), key)


def _require(key, raw, what="key"):
    if key is None:
        raise AccelError(f"{what} {raw!r} is not in the mapping grammar")
    return key


# --- key name tables per dialect -----------------------------------------

# GDK keysym names that are not grammar names but mean a grammar key.
# ISO_Left_Tab is what Shift+Tab produces; GTK apps bind it with <Shift>.
GTK_ALIASES = {"prior": "page_up", "next": "page_down", "iso_left_tab": "tab",
               "kp_space": None}

GTK_MODS = {"control": "ctrl", "ctrl": "ctrl", "ctl": "ctrl", "primary": "ctrl",
            "shift": "shift", "shft": "shift", "alt": "alt", "mod1": "alt",
            "super": "super"}
GTK_REJECTED_MODS = {"meta", "hyper", "release", "mod2", "mod3", "mod4", "mod5",
                     "lock", "caps", "button1", "button2", "button3"}


def _gtk_key(token):
    if len(token) == 1:
        return key_id(token)
    low = token.lower()
    if low in GTK_ALIASES:
        return GTK_ALIASES[low]
    return key_id(token)


def parse_gtk_chord(text):
    mods = set()
    rest = text.strip()
    while (m := re.match(r"^<([^<>]+)>", rest)):
        name = m.group(1).lower()
        if name in GTK_MODS:
            mods.add(GTK_MODS[name])
        elif name in GTK_REJECTED_MODS:
            raise AccelError(f"modifier <{m.group(1)}> is not in the mapping grammar")
        else:
            raise AccelError(f"unknown modifier <{m.group(1)}>")
        rest = rest[m.end():]
    if not rest:
        raise AccelError("no key after the modifiers")
    key = _require(_gtk_key(rest), rest)
    if rest.lower() == "iso_left_tab":
        mods.add("shift")
    return _chord(mods, key)


def parse_gtk(text):
    text = text.strip()
    if not text:
        raise AccelError("empty accelerator")
    return (parse_gtk_chord(text),)


# GDK keysym constants and modifier masks, as GTK code writes a binding:
# gtk_widget_class_add_binding_action (klass, GDK_KEY_s, GDK_CONTROL_MASK, ...)
GDK_KEY_RE = re.compile(r"(?:GDK_KEY_|Gdk\.KEY_|Gdk\.Key\.|gdk::Key::|gdk::keys::constants::)(\w+)")
GDK_MASKS = {"CONTROL_MASK": "ctrl", "SHIFT_MASK": "shift", "ALT_MASK": "alt", "MOD1_MASK": "alt",
             "SUPER_MASK": "super"}


def parse_gdk(text):
    m = GDK_KEY_RE.search(text)
    if not m:
        raise AccelError("no GDK keysym constant (GDK_KEY_x, Gdk.KEY_x, gdk::Key::x)")
    mods = set()
    for name in re.findall(r"([A-Z0-9_]+_MASK)\b", text[m.end():]):
        short = name[4:] if name.startswith("GDK_") else name
        if short not in GDK_MASKS:
            raise AccelError(f"modifier {name} is not in the mapping grammar")
        mods.add(GDK_MASKS[short])
    key = _require(_gtk_key(m.group(1)), m.group(1))
    if m.group(1).lower() == "iso_left_tab":
        mods.add("shift")
    return (_chord(mods, key),)


# Qt key names in portable text (QKeySequence keyname[] in qkeysequence.cpp)
QT_TEXT_KEYS = {
    "space": "space", "esc": "escape", "escape": "escape", "tab": "tab",
    "backtab": "tab", "backspace": "backspace", "return": "return", "enter": "kp_enter",
    "ins": "insert", "insert": "insert", "del": "delete", "delete": "delete",
    "print": "print", "print screen": "print", "home": "home", "end": "end",
    "left": "left", "up": "up", "right": "right", "down": "down",
    "pgup": "page_up", "page up": "page_up", "pageup": "page_up",
    "pgdown": "page_down", "page down": "page_down", "pagedown": "page_down",
    "menu": "menu",
    **{f"f{i}": f"f{i}" for i in range(1, 13)},
}

# Qt::Key enum names for printable keys (qnamespace.h values 0x20 to 0x7e).
# tests/test_tables.py checks this against qnamespace.h when it is cloned.
QT_ENUM_CHARS = {
    "Space": "space", "Exclam": "!", "QuoteDbl": '"', "NumberSign": "#", "Dollar": "$",
    "Percent": "%", "Ampersand": "&", "Apostrophe": "'", "ParenLeft": "(",
    "ParenRight": ")", "Asterisk": "*", "Plus": "+", "Comma": ",", "Minus": "-",
    "Period": ".", "Slash": "/", "Colon": ":", "Semicolon": ";", "Less": "<",
    "Equal": "=", "Greater": ">", "Question": "?", "At": "@", "BracketLeft": "[",
    "Backslash": "\\", "BracketRight": "]", "AsciiCircum": "^", "Underscore": "_",
    "QuoteLeft": "`", "BraceLeft": "{", "Bar": "|", "BraceRight": "}", "AsciiTilde": "~",
    **{str(d): str(d) for d in range(10)},
    **{c: c.lower() for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"},
}
QT_ENUM_SPECIAL = {
    "Escape": "escape", "Tab": "tab", "Backtab": "tab", "Backspace": "backspace",
    "Return": "return", "Enter": "kp_enter", "Insert": "insert", "Delete": "delete",
    "Print": "print", "Home": "home", "End": "end", "Left": "left", "Up": "up",
    "Right": "right", "Down": "down", "PageUp": "page_up", "PageDown": "page_down",
    "Menu": "menu",
    **{f"F{i}": f"f{i}" for i in range(1, 13)},
}
QT_MODS = {"ctrl": "ctrl", "control": "ctrl", "shift": "shift", "alt": "alt", "meta": "super"}
QT_ENUM_MODS = {
    "CTRL": "ctrl", "ControlModifier": "ctrl", "SHIFT": "shift", "ShiftModifier": "shift",
    "ALT": "alt", "AltModifier": "alt", "META": "super", "MetaModifier": "super",
    "KeypadModifier": "keypad", "KEYPAD": "keypad",
}
KEYPAD = {**{str(d): f"kp_{d}" for d in range(10)}, "+": "kp_add", "-": "kp_subtract",
          "*": "kp_multiply", "/": "kp_divide", ".": "kp_decimal", "kp_enter": "kp_enter",
          "return": "kp_enter"}


def _keypad(key, raw):
    if key not in KEYPAD:
        raise AccelError(f"keypad key {raw!r} is not in the mapping grammar")
    return KEYPAD[key]


def _split_plus(text):
    """Split "Ctrl+Shift++" into ["Ctrl", "Shift", "+"]: a trailing "+" is a key."""
    text = text.strip()
    if text == "+":
        return ["+"]
    if text.endswith("++"):
        return [t.strip() for t in text[:-2].split("+")] + ["+"]
    return [t.strip() for t in text.split("+")]


def parse_qt_text_chord(text):
    tokens = _split_plus(text)
    *mod_tokens, key_token = tokens
    mods, keypad = set(), False
    for tok in mod_tokens:
        low = tok.lower()
        if low == "num":
            keypad = True
        elif low in QT_MODS:
            mods.add(QT_MODS[low])
        else:
            raise AccelError(f"unknown Qt modifier {tok!r}")
    if not key_token:
        raise AccelError("no key after the modifiers")
    low = key_token.lower()
    if low == "backtab":
        mods.add("shift")
    if low in QT_TEXT_KEYS:
        key = QT_TEXT_KEYS[low]
    elif len(key_token) == 1:
        key = key_id(key_token)
    else:
        key = None
    key = _require(key, key_token)
    if keypad:
        key = _keypad(key, key_token)
    return _chord(mods, key)


def parse_qt_enum(text):
    """Qt::CTRL | Qt::Key_S, Qt::ControlModifier + Qt::Key_S, PyQt's Qt.Key.Key_S."""
    mods, keypad, key = set(), False, None
    for part in re.split(r"[|+]", text):
        part = part.strip().strip("()")
        if not part or part in ("QKeySequence", "QKeyCombination"):
            continue
        name = re.split(r"::|\.", part)[-1]
        if name.startswith("Key_"):
            k = name[4:]
            if k == "Backtab":
                mods.add("shift")
            if k in QT_ENUM_CHARS:
                key = QT_ENUM_CHARS[k]
            elif k in QT_ENUM_SPECIAL:
                key = QT_ENUM_SPECIAL[k]
            else:
                raise AccelError(f"Qt key {name} is not in the mapping grammar")
        elif name in QT_ENUM_MODS:
            if QT_ENUM_MODS[name] == "keypad":
                keypad = True
            else:
                mods.add(QT_ENUM_MODS[name])
        elif name in ("NoModifier", "0"):
            continue
        else:
            raise AccelError(f"unknown Qt enum {part!r}")
    if key is None:
        raise AccelError("no Qt::Key_ in the expression")
    if keypad:
        key = _keypad(key, text)
    return (_chord(mods, key),)


def parse_qt(text):
    text = text.strip()
    if not text:
        raise AccelError("empty accelerator")
    if re.search(r"\bKey_\w+", text):
        return parse_qt_enum(text)
    # Portable text: up to four chords separated by ", " (a "," right after
    # "+" is the comma key)
    parts = re.split(r"(?<!\+),\s+", text)
    return tuple(parse_qt_text_chord(p) for p in parts)


# Electron: shell/common/keyboard_util.cc KeyboardCodeFromStr() and
# shell/browser/ui/accelerator_util.cc. command, cmd, meta and super are all
# VKEY_COMMAND; CommandOrControl is Control off macOS.
ELECTRON_MODS = {"commandorcontrol": "ctrl", "cmdorctrl": "ctrl", "control": "ctrl",
                 "ctrl": "ctrl", "alt": "alt", "option": "alt", "shift": "shift",
                 "super": "super", "meta": "super", "command": "super", "cmd": "super"}
ELECTRON_KEYS = {
    "plus": "+", "space": "space", "tab": "tab", "backspace": "backspace",
    "delete": "delete", "insert": "insert", "return": "return", "enter": "return",
    "up": "up", "down": "down", "left": "left", "right": "right", "home": "home",
    "end": "end", "pageup": "page_up", "pagedown": "page_down", "escape": "escape",
    "esc": "escape", "printscreen": "print",
    **{f"num{d}": f"kp_{d}" for d in range(10)},
    "numdec": "kp_decimal", "numadd": "kp_add", "numsub": "kp_subtract",
    "nummult": "kp_multiply", "numdiv": "kp_divide",
    **{f"f{i}": f"f{i}" for i in range(1, 13)},
}


def parse_electron(text):
    text = text.strip()
    if not text:
        raise AccelError("empty accelerator")
    tokens = _split_plus(text)
    mods, key = set(), None
    for tok in tokens:
        low = tok.lower()
        if low in ELECTRON_MODS:
            mods.add(ELECTRON_MODS[low])
        elif low == "altgr":
            raise AccelError("AltGr is not in the mapping grammar")
        elif low in ELECTRON_KEYS:
            key = ELECTRON_KEYS[low]
        elif len(tok) == 1:
            key = _require(key_id(tok), tok)
        elif tok == "":
            raise AccelError("empty token")
        else:
            raise AccelError(f"Electron key {tok!r} is not in the mapping grammar")
    if key is None:
        raise AccelError("no key in the accelerator")
    return (_chord(mods, key),)


# Java: javax.swing.KeyStroke.getKeyStroke(String) and KeyEvent.VK_ names
JAVA_MODS = {"shift": "shift", "control": "ctrl", "ctrl": "ctrl", "meta": "super",
             "alt": "alt"}
JAVA_KEYS = {
    "enter": "return", "back_space": "backspace", "tab": "tab", "escape": "escape",
    "space": "space", "page_up": "page_up", "page_down": "page_down", "end": "end",
    "home": "home", "left": "left", "up": "up", "right": "right", "down": "down",
    "comma": ",", "minus": "-", "period": ".", "slash": "/", "semicolon": ";",
    "equals": "=", "open_bracket": "[", "back_slash": "\\", "close_bracket": "]",
    "multiply": "kp_multiply", "add": "kp_add", "subtract": "kp_subtract",
    "decimal": "kp_decimal", "divide": "kp_divide", "delete": "delete",
    "insert": "insert", "back_quote": "`", "quote": "'", "printscreen": "print",
    "context_menu": "menu", "ampersand": "&", "asterisk": "*", "quotedbl": '"',
    "less": "<", "greater": ">", "braceleft": "{", "braceright": "}", "at": "@",
    "colon": ":", "circumflex": "^", "dollar": "$", "exclamation_mark": "!",
    "left_parenthesis": "(", "right_parenthesis": ")", "number_sign": "#",
    "plus": "+", "underscore": "_",
    **{f"numpad{d}": f"kp_{d}" for d in range(10)},
    **{f"f{i}": f"f{i}" for i in range(1, 13)},
}
JAVA_MASKS = {
    "CTRL_DOWN_MASK": "ctrl", "CTRL_MASK": "ctrl", "SHIFT_DOWN_MASK": "shift",
    "SHIFT_MASK": "shift", "ALT_DOWN_MASK": "alt", "ALT_MASK": "alt",
    "META_DOWN_MASK": "super", "META_MASK": "super",
}


def _java_key(name):
    low = name.lower()
    if low in JAVA_KEYS:
        return JAVA_KEYS[low]
    if len(name) == 1:
        return key_id(name)
    raise AccelError(f"Java key {name!r} is not in the mapping grammar")


def parse_java(text):
    text = text.strip()
    if not text:
        raise AccelError("empty accelerator")
    if "VK_" in text:
        m = re.search(r"VK_(\w+)", text)
        key = _java_key(m.group(1))
        rest = text[m.end():]
        mods = set()
        for name in re.findall(r"\b([A-Z_]+_MASK)\b", rest):
            if name in JAVA_MASKS:
                mods.add(JAVA_MASKS[name])
            elif name.startswith("ALT_GRAPH"):
                raise AccelError("AltGraph is not in the mapping grammar")
            elif name.startswith("BUTTON"):
                raise AccelError("mouse buttons are not keys")
        if re.search(r"getMenuShortcutKeyMask(Ex)?\s*\(", rest):
            mods.add("ctrl")  # the menu shortcut key is Control off macOS
        return (_chord(mods, key),)
    tokens = text.split()
    mods = set()
    for i, tok in enumerate(tokens):
        low = tok.lower()
        if low in JAVA_MODS:
            mods.add(JAVA_MODS[low])
        elif low in ("pressed", "released"):
            continue
        elif low == "typed":
            if i + 1 >= len(tokens) or len(tokens[i + 1]) != 1:
                raise AccelError("typed needs one character")
            key = _require(key_id(tokens[i + 1]), tokens[i + 1])
            return (_chord(mods, key),)
        elif low == "altgraph":
            raise AccelError("AltGraph is not in the mapping grammar")
        elif low.startswith("button"):
            raise AccelError("mouse buttons are not keys")
        elif i == len(tokens) - 1:
            return (_chord(mods, _java_key(tok)),)
        else:
            raise AccelError(f"unknown Java modifier {tok!r}")
    raise AccelError("no key in the keystroke")


# VS Code: keybinding strings (keybindings.json, package.json contributes)
# and KeyMod/KeyCode expressions (src/vs/base/common/keyCodes.ts)
VSCODE_MODS = {"ctrl": "ctrl", "shift": "shift", "alt": "alt", "meta": "super",
               "win": "super", "cmd": "super", "super": "super"}
VSCODE_KEYS = {
    "enter": "return", "escape": "escape", "backspace": "backspace", "tab": "tab",
    "space": "space", "pageup": "page_up", "pagedown": "page_down", "end": "end",
    "home": "home", "left": "left", "up": "up", "right": "right", "down": "down",
    "insert": "insert", "delete": "delete", "del": "delete", "contextmenu": "menu",
    **{f"numpad{d}": f"kp_{d}" for d in range(10)},
    "numpad_add": "kp_add", "numpad_subtract": "kp_subtract",
    "numpad_multiply": "kp_multiply", "numpad_divide": "kp_divide",
    "numpad_decimal": "kp_decimal",
    **{f"f{i}": f"f{i}" for i in range(1, 13)},
}
VSCODE_KEYCODES = {
    **{f"Key{c}": c.lower() for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"},
    **{f"Digit{d}": str(d) for d in range(10)},
    "Enter": "return", "Escape": "escape", "Backspace": "backspace", "Tab": "tab",
    "Space": "space", "Minus": "-", "Equal": "=", "BracketLeft": "[",
    "BracketRight": "]", "Backslash": "\\", "Semicolon": ";", "Quote": "'",
    "Backquote": "`", "Comma": ",", "Period": ".", "Slash": "/", "Insert": "insert",
    "Home": "home", "PageUp": "page_up", "Delete": "delete", "End": "end",
    "PageDown": "page_down", "RightArrow": "right", "LeftArrow": "left",
    "DownArrow": "down", "UpArrow": "up", "ContextMenu": "menu",
    **{f"Numpad{d}": f"kp_{d}" for d in range(10)},
    "NumpadAdd": "kp_add", "NumpadSubtract": "kp_subtract",
    "NumpadMultiply": "kp_multiply", "NumpadDivide": "kp_divide",
    "NumpadDecimal": "kp_decimal",
    **{f"F{i}": f"f{i}" for i in range(1, 13)},
}
VSCODE_KEYMODS = {"CtrlCmd": "ctrl", "Shift": "shift", "Alt": "alt", "WinCtrl": "super"}


def _strip_parens(text):
    text = text.strip()
    while text.startswith("(") and text.endswith(")"):
        depth = 0
        for i, ch in enumerate(text):
            depth += ch == "("
            depth -= ch == ")"
            if depth == 0 and i < len(text) - 1:
                return text
        text = text[1:-1].strip()
    return text


def _vscode_expr_chord(text):
    """KeyMod.CtrlCmd | KeyCode.KeyS; VS Code sometimes joins them with + instead."""
    mods, key = set(), None
    for part in re.split(r"[|+]", _strip_parens(text)):
        part = part.strip().strip("()").strip()
        if not part or part == "0":
            continue
        m = re.fullmatch(r"(KeyMod|KeyCode)\.(\w+)", part)
        if not m:
            raise AccelError(f"cannot read {part!r}")
        if m.group(1) == "KeyMod":
            if m.group(2) not in VSCODE_KEYMODS:
                raise AccelError(f"unknown KeyMod {m.group(2)}")
            mods.add(VSCODE_KEYMODS[m.group(2)])
        else:
            if m.group(2) not in VSCODE_KEYCODES:
                raise AccelError(f"KeyCode.{m.group(2)} is not in the mapping grammar")
            key = VSCODE_KEYCODES[m.group(2)]
    if key is None:
        raise AccelError("no KeyCode in the expression")
    return _chord(mods, key)


def parse_vscode(text):
    text = text.strip()
    if not text:
        raise AccelError("empty accelerator")
    if "KeyCode." in text or "KeyMod." in text:
        text = _strip_parens(text)
        m = re.fullmatch(r"KeyChord\s*\((.*),(.*)\)", text, re.S)
        if m:
            return (_vscode_expr_chord(m.group(1)), _vscode_expr_chord(m.group(2)))
        return (_vscode_expr_chord(text),)
    seq = []
    for part in text.split():
        tokens = _split_plus(part)
        *mod_tokens, key_token = tokens
        mods = set()
        for tok in mod_tokens:
            if tok.lower() not in VSCODE_MODS:
                raise AccelError(f"unknown VS Code modifier {tok!r}")
            mods.add(VSCODE_MODS[tok.lower()])
        low = key_token.lower()
        if low in VSCODE_KEYS:
            key = VSCODE_KEYS[low]
        elif len(key_token) == 1:
            key = _require(key_id(key_token), key_token)
        else:
            raise AccelError(f"VS Code key {key_token!r} is not in the mapping grammar")
        seq.append(_chord(mods, key))
    return tuple(seq)


# Human text, as written in documentation
TEXT_MODS = {
    "ctrl": "ctrl", "control": "ctrl", "ctl": "ctrl", "primary": "ctrl", "strg": "ctrl",
    "cmd/ctrl": "ctrl", "ctrl/cmd": "ctrl", "cmdorctrl": "ctrl", "commandorcontrol": "ctrl",
    "shift": "shift", "alt": "alt", "option": "alt", "super": "super", "win": "super",
    "windows": "super", "meta": "super", "logo": "super",
}
TEXT_KEYS = {
    "enter": "return", "return": "return", "esc": "escape", "escape": "escape",
    "tab": "tab", "space": "space", "spacebar": "space", "backspace": "backspace",
    "del": "delete", "delete": "delete", "ins": "insert", "insert": "insert",
    "home": "home", "end": "end", "pgup": "page_up", "pageup": "page_up",
    "page up": "page_up", "pgdn": "page_down", "pgdown": "page_down",
    "pagedown": "page_down", "page down": "page_down", "up": "up", "down": "down",
    "left": "left", "right": "right", "up arrow": "up", "down arrow": "down",
    "left arrow": "left", "right arrow": "right", "↑": "up", "↓": "down",
    "←": "left", "→": "right", "plus": "+", "minus": "-", "comma": ",",
    "period": ".", "dot": ".", "slash": "/", "backslash": "\\", "semicolon": ";",
    "equal": "=", "equals": "=", "print": "print", "print screen": "print",
    "prtsc": "print", "menu": "menu", "grave": "`", "backtick": "`",
    "apostrophe": "'", "question": "?", "question mark": "?",
    **{f"f{i}": f"f{i}" for i in range(1, 13)},
    **{f"kp_{d}": f"kp_{d}" for d in range(10)},
    **{f"numpad {d}": f"kp_{d}" for d in range(10)},
    **{f"numpad{d}": f"kp_{d}" for d in range(10)},
}


def _clean_text(text):
    text = re.sub(r"</kbd>\s*<kbd>", "+", text)
    text = re.sub(r"</?kbd[^>]*>", "", text)
    return text.strip()


def parse_text_chord(text):
    text = text.strip()
    if not text:
        raise AccelError("empty chord")
    # "Ctrl-S": a dash joins tokens only when what precedes it is a modifier
    parts = []
    rest = text
    while True:
        m = re.match(r"^\s*([A-Za-z/]+)\s*([+-])\s*", rest)
        if m and m.group(1).lower() in TEXT_MODS and len(rest) > m.end():
            parts.append(m.group(1))
            rest = rest[m.end():]
            continue
        break
    mods = {TEXT_MODS[p.lower()] for p in parts}
    key_token = rest.strip()
    low = key_token.lower()
    if low in TEXT_KEYS:
        key = TEXT_KEYS[low]
    elif len(key_token) == 1:
        key = _require(key_id(key_token), key_token)
    else:
        raise AccelError(f"key {key_token!r} is not in the mapping grammar")
    return _chord(mods, key)


MULTIWORD_KEYS = [
    (r"page\s+up", "PageUp"), (r"page\s+down", "PageDown"), (r"print\s+screen", "PrtSc"),
    (r"(up|down|left|right)\s+arrow", r"\1"), (r"arrow\s+(up|down|left|right)", r"\1"),
    (r"question\s+mark", "?"), (r"num(?:pad)?\s+(\d)", r"KP_\1"),
]


def parse_text(text):
    text = _clean_text(text)
    if not text:
        raise AccelError("empty accelerator")
    if re.search(r"\.\.\.|…", text):
        raise AccelError("a range of shortcuts, not one shortcut")
    for pattern, repl in MULTIWORD_KEYS:
        text = re.sub(rf"(?i)\b{pattern}\b", repl, text)
    # "Ctrl + S" to "Ctrl+S"; the "+" of "Ctrl++" survives
    text = re.sub(r"\s*\+\s*(?=\S)", "+", text)
    # A sequence is chords separated by spaces: "Ctrl+K Ctrl+S"
    return tuple(parse_text_chord(t) for t in text.split())


PARSERS = {"gtk": parse_gtk, "gdk": parse_gdk, "qt": parse_qt, "electron": parse_electron,
           "java": parse_java, "vscode": parse_vscode, "text": parse_text}


def detect(text):
    t = text.strip()
    if "KeyMod." in t or "KeyCode." in t:
        return "vscode"
    if GDK_KEY_RE.search(t):
        return "gdk"
    if re.search(r"\bQt[:.]", t) or re.search(r"\bKey_\w", t):
        return "qt"
    if "VK_" in t:
        return "java"
    if re.search(r"<(primary|control|ctrl|ctl|shift|alt|super|meta|mod1)>", t, re.I):
        return "gtk"
    if re.search(r"cmdorctrl|commandorcontrol", t, re.I):
        return "electron"
    if re.fullmatch(r"((shift|control|ctrl|meta|alt|altGraph)\s+)+((typed|pressed|released)\s+)?[A-Z0-9_]+", t):
        return "java"
    return "text"


def split_alternatives(text, dialect):
    """One source string can list several alternative shortcuts."""
    if dialect == "gtk":
        return [p for p in text.split("|") if p.strip()]
    if dialect == "text":
        text = _clean_text(text)
        return [p for p in re.split(r"\s*(?:(?<!\+),\s+|\s+or\s+|\s+/\s+)\s*", text) if p.strip()]
    return [text]


def _one(text, dialect):
    result = Result(raw=text, dialect=dialect)
    try:
        seq = PARSERS[dialect](text)
    except AccelError as exc:
        result.error = str(exc)
        return result
    result.seq = seq
    result.accel = format_seq(seq)
    return result


def normalize_all(text, dialect="auto"):
    """Every alternative in `text`, each as a Result."""
    if not isinstance(text, str):
        return [Result(raw=repr(text), dialect=dialect, error="not a string")]
    if dialect in (None, "auto"):
        dialect = detect(text)
    if dialect not in PARSERS:
        raise ValueError(f"unknown dialect {dialect!r}")
    parts = split_alternatives(text, dialect) or [text]
    return [_one(p, dialect) for p in parts]


def normalize(text, dialect="auto"):
    """The first (primary) alternative in `text`."""
    return normalize_all(text, dialect)[0]
