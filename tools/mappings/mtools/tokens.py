"""Find every accelerator-looking token in a piece of text, in any dialect.

verify-mapping uses this on the lines around a cited source line, and on a
quote from a web page, to decide whether they contain the chord a mapping
claims. It reads what is written there, nothing more: "Ctrl+S" in a comment
counts, "Ctrl" on one line and "S" on the next does not.
"""

import html
import re

from . import accel, tables

MODS = r"(?:ctrl|control|ctl|strg|shift|alt|option|super|meta|win|cmd|command|cmdorctrl|commandorcontrol|mod|\$mod|primary)"
PLUS_JOINED = re.compile(rf"(?<![\w$])(?:{MODS}\s*[+-]\s*)+(?:[A-Za-z][A-Za-z0-9_]*|\d|[^\sA-Za-z0-9])", re.I)
GTK_TAGS = re.compile(r"(?:<[A-Za-z0-9_]+>)+(?:[A-Za-z0-9_]+|[^\s\w<>\"'])")
QT_ENUM = re.compile(r"(?:\bQt\s*(?:::|\.)\s*(?:\w+\s*(?:::|\.)\s*)?\w+\s*[|+]\s*)*"
                     r"\bQt\s*(?:::|\.)\s*(?:Key\s*(?:::|\.)\s*)?Key_\w+")
GDK_KEY = re.compile(r"(?:GDK_KEY_|Gdk\.KEY_|Gdk\.Key\.|gdk::Key::|gdk::keys::constants::)(\w+)")
JAVA_VK = re.compile(r"VK_\w+[^;\n]*")
JAVA_TEXT = re.compile(r"[\"']((?:(?:shift|control|ctrl|meta|alt)\s+)+(?:(?:typed|pressed|released)\s+)?\w+)[\"']")
VSCODE_EXPR = re.compile(r"KeyChord\s*\([^()]*\)|(?:KeyMod\.\w+\s*\|\s*)*KeyCode\.\w+")
STD_QT = re.compile(r"\b(?:QKeySequence\s*(?:::|\.)\s*(?:StandardKey\s*(?:::|\.)\s*)?|StandardKey\s*\.\s*)(\w+)")
STD_KACTION = re.compile(r"\bKStandardActions?\s*::\s*(\w+)")
STD_KSHORTCUT = re.compile(r"\bKStandardShortcut\s*::\s*(\w+)")
ELECTRON_ROLE = re.compile(r"\brole\s*:\s*[\"'`](\w+)[\"'`]")
KXMLGUI_ACTION = re.compile(r"<Action\s+[^>]*name=\"(\w+)\"")
MALLARD_KEYS = re.compile(r"(?:<key\b[^>]*>[^<]+</key>\s*\+?\s*)+")
DOCBOOK_COMBO = re.compile(r"(?:&\w+;\s*)*<keycap>[^<]+</keycap>(?:\s*<keycap>[^<]+</keycap>)*")
KBD_GROUP = re.compile(r"(?:<kbd>[^<]+</kbd>\s*[+\-]?\s*)+", re.I)
NAMED_KEY = re.compile(r"(?<![\w<])(F(?:1[0-2]|[1-9])|Escape|Esc|Delete|Insert|Home|End|Page_?Up|Page_?Down|"
                       r"PgUp|PgDn|Return|Enter|Tab|BackSpace|Backspace|Print|Menu|Up|Down|Left|Right)(?![\w>])")
# LibreOffice Accelerators.xcu: <node oor:name="S_SHIFT_MOD1"> is Ctrl+Shift+S.
# MOD1 is Ctrl, MOD2 is Alt; MOD3 is the Mac Control key and has no Linux chord.
LO_KEY_NODE = re.compile(r'<node\s+oor:name="([A-Z0-9]+(?:_(?:SHIFT|MOD[123]))*)"')
LO_MODS = {"SHIFT": "Shift", "MOD1": "Ctrl", "MOD2": "Alt"}
LO_KEYS = {"POINT": "period", "COMMA": "comma", "SEMICOLON": "semicolon", "ADD": "KP_Add",
           "SUBTRACT": "KP_Subtract", "MULTIPLY": "KP_Multiply", "DIVIDE": "KP_Divide", "RETURN": "Return",
           "ESCAPE": "Escape", "TAB": "Tab", "SPACE": "space", "BACKSPACE": "BackSpace", "DELETE": "Delete",
           "INSERT": "Insert", "UP": "Up", "DOWN": "Down", "LEFT": "Left", "RIGHT": "Right", "HOME": "Home",
           "END": "End", "PAGEUP": "Page_Up", "PAGEDOWN": "Page_Down", "BRACKETLEFT": "bracketleft",
           "BRACKETRIGHT": "bracketright", "QUOTELEFT": "grave", "QUOTERIGHT": "apostrophe",
           "NUMBERSIGN": "numbersign", "COLON": "colon"}
# DOM KeyboardEvent.code spellings inside quotes: 'ControlLeft+ShiftLeft+KeyZ', 'ArrowUp', 'Space'.
# LosslessCut writes its default key bindings this way. Left and Right modifier variants are the same
# modifier; Meta variants are the Mac duplicates and have no Linux chord in the mapping grammar.
CODE_KEY = (r"Key[A-Z]|Digit[0-9]|F(?:1[0-2]|[1-9])|Space|Enter|Backspace|Tab|Escape|Delete|Insert|Home|End|"
            r"PageUp|PageDown|Arrow(?:Up|Down|Left|Right)|Comma|Period|Slash|Backslash|Semicolon|Quote|Backquote|"
            r"Minus|Equal|BracketLeft|BracketRight")
CODE_COMBO = re.compile(rf"(?<=[\'\"`])((?:(?:Control|Shift|Alt|Meta)(?:Left|Right)\+)*)({CODE_KEY})(?=[\'\"`])")
CODE_KEY_SYMS = {"Space": "space", "Enter": "Return", "Backspace": "BackSpace", "Tab": "Tab", "Escape": "Escape",
                 "Delete": "Delete", "Insert": "Insert", "Home": "Home", "End": "End", "PageUp": "Page_Up",
                 "PageDown": "Page_Down", "ArrowUp": "Up", "ArrowDown": "Down", "ArrowLeft": "Left",
                 "ArrowRight": "Right", "Comma": "comma", "Period": "period", "Slash": "slash",
                 "Backslash": "backslash", "Semicolon": "semicolon", "Quote": "apostrophe", "Backquote": "grave",
                 "Minus": "minus", "Equal": "equal", "BracketLeft": "bracketleft", "BracketRight": "bracketright"}
# A string literal that is one letter or digit ("S", 'j'): a bare key binding such as
# {QStringLiteral("split"), QStringLiteral("S")}. Only the lines around a cited line are read,
# so this proves that the key is written there and nothing about what it does.
QUOTED_KEY = re.compile(r"(?<![\w\"'])([\"'])([A-Za-z0-9])\1(?![\w\"'])")
# Chromium accelerator tables: {ui::VKEY_F5, ui::EF_CONTROL_DOWN | ui::EF_SHIFT_DOWN, IDC_...}.
# EF_PLATFORM_ACCELERATOR is Control off macOS. AltGr and Command modifiers have no chord in the
# mapping grammar, and VKEY_BROWSER_* media keys have no keysym name here, so those entries give nothing.
VKEY_ENTRY = re.compile(r"\bui::VKEY_(\w+)\s*,\s*((?:ui::EF_\w+\s*\|?\s*)+)")
VKEY_MODS = {"CONTROL_DOWN": "Control", "PLATFORM_ACCELERATOR": "Control", "SHIFT_DOWN": "Shift", "ALT_DOWN": "Alt"}
VKEY_KEYS = {"NEXT": "Page_Down", "PRIOR": "Page_Up", "OEM_MINUS": "minus", "OEM_PLUS": "plus",
             "SUBTRACT": "KP_Subtract", "ADD": "KP_Add", "OEM_2": "slash", "ESCAPE": "Escape", "TAB": "Tab",
             "LEFT": "Left", "RIGHT": "Right", "UP": "Up", "DOWN": "Down", "HOME": "Home", "END": "End",
             "DELETE": "Delete", "BACK": "BackSpace", "RETURN": "Return", "SPACE": "space", "INSERT": "Insert"}
# Blink editing key table: {'Z', kCtrlKey | kShiftKey, "Redo"}. Meta is the Mac Command key.
BLINK_ENTRY = re.compile(r"\{\s*'([A-Z0-9])'\s*,\s*((?:k(?:Ctrl|Shift|Alt|Meta)Key\s*\|?\s*)+)")
BLINK_MODS = {"Ctrl": "Control", "Shift": "Shift", "Alt": "Alt"}
# VLC's default hotkeys, `#define KEY_FASTER "+"`. Only keys with no modifier and no letter are read
# here ("+", "[", "Page Up", "Space"); chords with modifiers and letters already read as text. The
# value may be followed by a backslash-t and a media key alias ("Space\tMedia Play Pause").
LIBVLC_KEY_DEFINE = re.compile(r'^[ \t]*#[ \t]*define[ \t]+KEY_\w+[ \t]+"(Page (?:Up|Down)|Space|[^\sA-Za-z0-9"\\])(?=\\t|")', re.M)
# GIMP's action tables write unmodified punctuation and paging keys as GDK keysym names inside a
# NULL-terminated accelerator array: `{ "minus", "KP_Subtract", NULL }`. Only that shape is read.
GIMP_ACCEL_ARRAY = re.compile(r'\{(?:\s*"[^"\n]*"\s*,)+\s*NULL\s*\}')
GIMP_ACCEL_KEYSYMS = {"grave": "grave", "minus": "minus", "plus": "plus", "exclam": "exclam",
                      "slash": "slash", "Prior": "Page_Up", "Next": "Page_Down"}
# Inkscape's default.xml lists a comma separated key list per action, `<bind gaction="..." keys="plus,
# equal, KP_Add" />`, over several lines. Entries with no modifier tag are bare keysym names or digits.
INKSCAPE_BIND_KEYS = re.compile(r'<bind\s+gaction="[^"]*"\s+keys="([^"]*)"')
SEQUENCE_GAP = re.compile(r"^\s*(?:,|then)?\s*$", re.I)

ENTITY_KEYS = {"ctrl": "Ctrl", "shift": "Shift", "alt": "Alt", "meta": "Super", "super": "Super",
               "enter": "Enter", "esc": "Esc", "del": "Del", "backspace": "Backspace", "tab": "Tab",
               "space": "Space", "up": "Up", "down": "Down", "left": "Left", "right": "Right",
               "home": "Home", "end": "End", "pgup": "PgUp", "pgdn": "PgDn", "ins": "Ins"}


def _seqs(text, dialect):
    return [r.seq for r in accel.normalize_all(text, dialect) if r.seq]


def _lo_key_seqs(name):
    key, *mods = name.split("_")
    if any(m not in LO_MODS for m in mods):
        return []
    if re.fullmatch(r"F(?:1[0-2]|[1-9])|[0-9]", key):
        base = key
    elif re.fullmatch(r"[A-Z]", key):
        base = key if mods else key.lower()
    elif key in LO_KEYS:
        base = LO_KEYS[key]
    else:
        return []
    return _seqs("".join(f"<{LO_MODS[m]}>" for m in mods) + base, "gtk")


def _vkey_seqs(key, mods):
    flags = re.findall(r"EF_(\w+)", mods)
    if any(f not in VKEY_MODS and f != "NONE" for f in flags):
        return []
    if re.fullmatch(r"[A-Z]|[0-9]", key):
        base = key.lower() if key.isalpha() else key
    elif re.fullmatch(r"F(?:1[0-2]|[1-9])", key):
        base = key
    elif re.fullmatch(r"NUMPAD[0-9]", key):
        base = "KP_" + key[-1]
    elif key in VKEY_KEYS:
        base = VKEY_KEYS[key]
    else:
        return []
    names = [VKEY_MODS[f] for f in flags if f in VKEY_MODS]
    gtk = "".join(f"<{m}>" for m in dict.fromkeys(names))
    return _seqs(gtk + base, "gtk")


def _blink_seqs(key, mods):
    names = re.findall(r"k(Ctrl|Shift|Alt|Meta)Key", mods)
    if "Meta" in names:
        return []
    gtk = "".join(f"<{BLINK_MODS[n]}>" for n in names)
    return _seqs(gtk + (key.lower() if key.isalpha() else key), "gtk")


def _table_seqs(entries):
    out = []
    for e in entries or []:
        seq = accel.parse_grammar(e["accel"]) if e.get("accel") else None
        if seq:
            out.append(seq)
    return out


def _mask_mods(text):
    names = {"CONTROL_MASK": "Control", "SHIFT_MASK": "Shift", "ALT_MASK": "Alt", "MOD1_MASK": "Alt",
             "SUPER_MASK": "Super"}
    mods = []
    for name in re.findall(r"([A-Z0-9_]+_MASK)\b", text):
        short = re.sub(r"^GDK_", "", name)
        if short in names and names[short] not in mods:
            mods.append(names[short])
    return mods


def find_chords(text):
    """[(start, end, raw, seq)] for every accelerator found in `text`."""
    text = html.unescape(text) if "&lt;" in text or "&amp;" in text or "&gt;" in text else text
    found = []

    def add(m_start, m_end, raw, seqs):
        for seq in seqs:
            found.append((m_start, m_end, raw, seq))

    for m in GTK_TAGS.finditer(text):
        add(m.start(), m.end(), m.group(0), _seqs(m.group(0), "gtk"))
    for m in PLUS_JOINED.finditer(text):
        raw = re.sub(r"(?i)\$?mod(?=\s*[+-])", "Ctrl", m.group(0))
        raw = re.sub(r"(?i)\bKey([A-Z])$", r"\1", raw)
        seqs = _seqs(raw, "text") or _seqs(raw, "electron")
        add(m.start(), m.end(), m.group(0), seqs)
    for m in QT_ENUM.finditer(text):
        add(m.start(), m.end(), m.group(0), _seqs(m.group(0), "qt"))
    for m in GDK_KEY.finditer(text):
        tail = text[m.end():m.end() + 160]
        tail = re.split(r"[;)\n]", tail, maxsplit=1)[0]
        gtk = "".join(f"<{mod}>" for mod in _mask_mods(tail)) + m.group(1)
        add(m.start(), m.end(), m.group(0), _seqs(gtk, "gtk"))
    for m in JAVA_VK.finditer(text):
        add(m.start(), m.end(), m.group(0), _seqs(m.group(0).rstrip(")"), "java"))
    for m in JAVA_TEXT.finditer(text):
        add(m.start(1), m.end(1), m.group(1), _seqs(m.group(1), "java"))
    for m in VSCODE_EXPR.finditer(text):
        add(m.start(), m.end(), m.group(0), _seqs(m.group(0), "vscode"))
    data = tables.load()
    for m in STD_QT.finditer(text):
        if m.group(1) in data["qt_standard_keys"]:
            add(m.start(), m.end(), m.group(0), _table_seqs(tables.qt_standard_key(m.group(1))))
    for m in STD_KACTION.finditer(text):
        info = tables.kstandard_action(m.group(1))
        if info and (m.group(1) in data["kstandard_action_functions"] or m.group(1) in data["kstandard_actions"]):
            add(m.start(), m.end(), m.group(0), _table_seqs(info["shortcuts"]))
    for m in STD_KSHORTCUT.finditer(text):
        enum = tables.kstandard_shortcut_function(m.group(1)) or m.group(1)
        add(m.start(), m.end(), m.group(0), _table_seqs(tables.kstandard_shortcut(enum)))
    for m in ELECTRON_ROLE.finditer(text):
        role = m.group(1)
        info = tables.electron_role(role)
        seqs = []
        if info and info.get("accel") and info.get("linux"):
            seqs.append(accel.parse_grammar(info["accel"]))
        for sub in tables.electron_submenu(role) or []:
            sub_info = tables.electron_role(sub) if sub else None
            if sub_info and sub_info.get("accel") and sub_info.get("linux"):
                seqs.append(accel.parse_grammar(sub_info["accel"]))
        add(m.start(), m.end(), m.group(0), seqs)
    for m in KXMLGUI_ACTION.finditer(text):
        for ident, info in data["kstandard_actions"].items():
            if info["action_name"] == m.group(1):
                add(m.start(), m.end(), m.group(0), _table_seqs(tables.kstandard_action(ident)["shortcuts"]))
    for m in MALLARD_KEYS.finditer(text):
        keys = re.findall(r"<key\b[^>]*>([^<]+)</key>", m.group(0))
        add(m.start(), m.end(), m.group(0), _seqs("+".join(keys), "text"))
    for m in DOCBOOK_COMBO.finditer(text):
        ents = [ENTITY_KEYS.get(e.lower(), e) for e in re.findall(r"&(\w+);", m.group(0))]
        caps = re.findall(r"<keycap>([^<]+)</keycap>", m.group(0))
        add(m.start(), m.end(), m.group(0), _seqs("+".join(ents + caps), "text"))
    for m in KBD_GROUP.finditer(text):
        add(m.start(), m.end(), m.group(0), _seqs(m.group(0), "text"))
    for m in QUOTED_KEY.finditer(text):
        add(m.start(), m.end(), m.group(0), _seqs(m.group(2).lower(), "gtk"))
    for m in CODE_COMBO.finditer(text):
        mods = re.findall(r"(Control|Shift|Alt|Meta)(?:Left|Right)", m.group(1))
        if "Meta" in mods:
            continue
        key = m.group(2)
        if re.fullmatch(r"Key[A-Z]", key):
            base = key[3:].lower()
        elif re.fullmatch(r"Digit[0-9]", key):
            base = key[5:]
        else:
            base = CODE_KEY_SYMS.get(key, key)
        add(m.start(), m.end(), m.group(0), _seqs("".join(f"<{x}>" for x in mods) + base, "gtk"))
    for m in NAMED_KEY.finditer(text):
        add(m.start(), m.end(), m.group(0), _seqs(m.group(1).replace("_", ""), "text"))

    for m in VKEY_ENTRY.finditer(text):
        add(m.start(), m.end(), m.group(0), _vkey_seqs(m.group(1), m.group(2)))

    for m in BLINK_ENTRY.finditer(text):
        add(m.start(), m.end(), m.group(0), _blink_seqs(m.group(1), m.group(2)))

    for m in LIBVLC_KEY_DEFINE.finditer(text):
        add(m.start(1), m.end(1), m.group(1), _seqs(m.group(1).replace(" ", "_"), "gtk"))

    for m in GIMP_ACCEL_ARRAY.finditer(text):
        for q in re.finditer(r'"([A-Za-z]+)"', m.group(0)):
            if q.group(1) in GIMP_ACCEL_KEYSYMS:
                add(m.start() + q.start(), m.start() + q.end(), q.group(1),
                    _seqs(GIMP_ACCEL_KEYSYMS[q.group(1)], "gtk"))

    for m in INKSCAPE_BIND_KEYS.finditer(text):
        for k in re.finditer(r"[^,\s]+", m.group(1)):
            if "<" not in k.group(0):
                add(m.start(1) + k.start(), m.start(1) + k.end(), k.group(0), _seqs(k.group(0), "gtk"))

    for m in LO_KEY_NODE.finditer(text):
        add(m.start(), m.end(), m.group(0), _lo_key_seqs(m.group(1)))

    found.sort(key=lambda f: (f[0], f[1]))
    return found


def contains(text, target):
    """(True, raw token) if `text` holds a token for the chord sequence `target`.

    A multi-chord target also matches consecutive single-chord tokens that
    are separated only by whitespace, a comma or "then" ("Ctrl+K Ctrl+S").
    """
    found = find_chords(text)
    for start, end, raw, seq in found:
        if accel.same(seq, target):
            return True, raw
    if len(target) > 1:
        singles = [(s, e, raw, seq) for s, e, raw, seq in found if len(seq) == 1]
        for i, (s, e, raw, seq) in enumerate(singles):
            if seq[0] != target[0]:
                continue
            chain, end, raws = [seq[0]], e, [raw]
            for s2, e2, raw2, seq2 in singles[i + 1:]:
                if len(chain) == len(target):
                    break
                if s2 < end:
                    continue
                if not SEQUENCE_GAP.match(text[end:s2]):
                    break
                if seq2[0] != target[len(chain)]:
                    break
                chain.append(seq2[0])
                raws.append(raw2)
                end = e2
            if tuple(chain) == tuple(target):
                return True, " ".join(raws)
    return False, None
