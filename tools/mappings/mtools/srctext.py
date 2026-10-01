"""Source text helpers: comment blanking, string literals, brackets, lines.

Comments are replaced by spaces rather than removed, so every offset and
line number in the blanked text matches the original file.
"""

import bisect
import re

C_LIKE = {"c", "cpp", "vala", "rust", "java", "js", "qml", "go", "cs", "kotlin", "swift"}
QUOTE_CHARS = {"c": "\"'", "cpp": "\"'", "vala": "\"'", "rust": "\"'", "java": "\"'",
               "js": "\"'`", "qml": "\"'`", "python": "\"'", "go": "\"'`", "cs": "\"'",
               "kotlin": "\"'", "swift": "\"'"}
# Languages where ' opens a one-character literal (or a Rust lifetime), not a string
CHAR_LITERAL_LANGS = {"c", "cpp", "vala", "rust", "java", "go", "cs", "kotlin", "swift"}
CHAR_LITERAL = re.compile(r"'(?:\\.[^'\n]{0,8}|[^\\'\n])'")


class LineIndex:
    def __init__(self, text):
        self._starts = [0] + [m.end() for m in re.finditer("\n", text)]

    def line(self, offset):
        return bisect.bisect_right(self._starts, offset)


def _blank(chars, start, end):
    for i in range(start, end):
        if chars[i] != "\n":
            chars[i] = " "


def strip_comments(text, lang):
    """Blank comments; strings are kept. lang: c-like name, "python" or "shell"."""
    chars = list(text)
    n = len(text)
    i = 0
    quotes = QUOTE_CHARS.get(lang, "\"'")
    hash_comments = lang in ("python", "shell", "yaml")
    slash_comments = lang in C_LIKE
    while i < n:
        ch = text[i]
        if slash_comments and ch == "/" and i + 1 < n:
            nxt = text[i + 1]
            if nxt == "/":
                end = text.find("\n", i)
                end = n if end == -1 else end
                _blank(chars, i, end)
                i = end
                continue
            if nxt == "*":
                end = text.find("*/", i + 2)
                end = n if end == -1 else end + 2
                _blank(chars, i, end)
                i = end
                continue
        if hash_comments and ch == "#":
            end = text.find("\n", i)
            end = n if end == -1 else end
            _blank(chars, i, end)
            i = end
            continue
        if ch in quotes:
            if ch == "'" and lang in CHAR_LITERAL_LANGS:
                m = CHAR_LITERAL.match(text, i)
                i = m.end() if m else i + 1
                continue
            i = skip_string(text, i, lang)
            continue
        i += 1
    return "".join(chars)


def skip_string(text, i, lang=None):
    """Index right after the string literal that starts at text[i]."""
    q = text[i]
    n = len(text)
    if lang == "python" and text.startswith(q * 3, i):
        end = text.find(q * 3, i + 3)
        return n if end == -1 else end + 3
    j = i + 1
    while j < n:
        c = text[j]
        if c == "\\":
            j += 2
            continue
        if c == q:
            return j + 1
        if c == "\n" and q != "`":
            return j  # unterminated on this line
        j += 1
    return n


_ESCAPES = {"n": "\n", "t": "\t", '"': '"', "'": "'", "\\": "\\", "`": "`"}


def unescape(body):
    return re.sub(r"\\(.)", lambda m: _ESCAPES.get(m.group(1), m.group(1)), body)


STRING_RE = re.compile(r"""(?P<q>["'`])(?P<body>(?:\\.|(?!(?P=q)).)*?)(?P=q)""", re.S)


def iter_strings(text, lang="c", start=0, end=None):
    """(start, end, value) for each string literal in text[start:end].

    text should be comment-blanked already. C-family ' literals are skipped.
    """
    end = len(text) if end is None else end
    quotes = QUOTE_CHARS.get(lang, "\"'")
    i = start
    while i < end:
        ch = text[i]
        if ch in quotes:
            if ch == "'" and lang in CHAR_LITERAL_LANGS:
                m = CHAR_LITERAL.match(text, i)
                i = m.end() if m else i + 1
                continue
            j = skip_string(text, i, lang)
            if lang == "python" and text.startswith(ch * 3, i):
                yield i, j, text[i + 3:j - 3]
            else:
                yield i, j, unescape(text[i + 1:j - 1])
            i = j
            continue
        i += 1


OPEN = {"(": ")", "[": "]", "{": "}"}
CLOSE = {v: k for k, v in OPEN.items()}


def matching(text, i, lang="c"):
    """Index of the bracket that closes text[i], skipping strings; -1 if none."""
    stack = []
    n = len(text)
    quotes = QUOTE_CHARS.get(lang, "\"'")
    while i < n:
        ch = text[i]
        if ch in quotes:
            if ch == "'" and lang in CHAR_LITERAL_LANGS:
                m = CHAR_LITERAL.match(text, i)
                i = m.end() if m else i + 1
                continue
            i = skip_string(text, i, lang)
            continue
        if ch in OPEN:
            stack.append(OPEN[ch])
        elif ch in CLOSE:
            if not stack or stack[-1] != ch:
                return -1
            stack.pop()
            if not stack:
                return i
        i += 1
    return -1


def split_args(text, open_idx, lang="c"):
    """Top-level comma-separated arguments of the group opening at text[open_idx].

    Returns ([(start, end), ...], index of the closing bracket), or ([], -1)
    when the group does not close.
    """
    close = matching(text, open_idx, lang)
    if close == -1:
        return [], -1
    quotes = QUOTE_CHARS.get(lang, "\"'")
    args, depth = [], 0
    i = start = open_idx + 1
    while i < close:
        ch = text[i]
        if ch in quotes:
            if ch == "'" and lang in CHAR_LITERAL_LANGS:
                m = CHAR_LITERAL.match(text, i)
                i = m.end() if m else i + 1
                continue
            i = skip_string(text, i, lang)
            continue
        if ch in OPEN:
            depth += 1
        elif ch in CLOSE:
            depth -= 1
        elif ch == "," and depth == 0:
            args.append((start, i))
            start = i + 1
        i += 1
    if text[start:close].strip():
        args.append((start, close))
    return args, close


def callee_before(text, open_idx):
    """The dotted name right before an opening bracket: "a->setShortcut" gives
    ("a", "setShortcut"); "QKeySequence" gives (None, "QKeySequence")."""
    m = re.search(r"((?:[A-Za-z_][\w]*(?:\(\))?\s*(?:->|\.|::)\s*)*)([A-Za-z_]\w*)\s*(?:::<[^>]*>)?\s*$",
                  text[max(0, open_idx - 200):open_idx])
    if not m:
        return None, None
    chain = re.split(r"\s*(?:->|\.|::)\s*", m.group(1).strip())
    chain = [c for c in chain if c]
    receiver = chain[-1] if chain else None
    return receiver, m.group(2)


def enclosing_groups(text, offset, lang="c", limit=3, window=2000):
    """Up to `limit` (start, end) bracket groups enclosing `offset`, innermost first."""
    groups = []
    lo = max(0, offset - window)
    i = offset - 1
    depth = {")": 0, "]": 0, "}": 0}
    while i >= lo and len(groups) < limit:
        ch = text[i]
        if ch in CLOSE:
            depth[ch] += 1
        elif ch in OPEN:
            close = OPEN[ch]
            if depth[close] > 0:
                depth[close] -= 1
            else:
                end = matching(text, i, lang)
                if end != -1 and end >= offset:
                    groups.append((i, end))
        i -= 1
    return groups


def clean_label(label, style="gtk"):
    """Drop mnemonic markers: GTK "_", Qt, KDE and Electron "&", VS Code "&&"."""
    if label is None:
        return None
    text = label.strip()
    if style == "gtk":
        text = re.sub(r"_(?!_)", "", text).replace("__", "_")
    elif style in ("qt", "electron", "vscode"):
        text = text.replace("&&", "\0")
        if style == "vscode":
            text = text.replace("\0", "")
        text = re.sub(r"&(?=\S)", "", text).replace("\0", "&")
    return text.strip() or None


I18N_CALL = re.compile(
    r"\b(?:i18nc?|i18ncp?|i18np|ki18nc?|kli18nc?|tr|qsTr|qsTrId|QObject::tr|_|C_|N_|NC_|gettext|pgettext|"
    r"localize2?|nls\.localize2?|t|i18n\.t|__|translate|QStringLiteral|QLatin1String|QString|"
    r"QStringLiteral|u8|L)\s*\(")


def translated(text, start=0, end=None, lang="c"):
    """The user-visible string of a label expression, e.g. i18nc("ctx", "Save")."""
    strings = [v for _, _, v in iter_strings(text, lang, start, end)]
    if not strings:
        return None
    head = text[start:end]
    if re.match(r"\s*(?:i18nc|i18ncp|ki18nc|kli18nc|C_|NC_|pgettext|localize2?|nls\.localize2?)\s*\(", head):
        return strings[-1] if len(strings) > 1 else strings[0]
    return strings[0]
