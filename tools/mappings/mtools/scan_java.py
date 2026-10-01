"""Java and Kotlin Swing code, and JetBrains keymap / plugin.xml files."""

import re

from . import srctext
from .common import seq_or_error

GET_KEYSTROKE = re.compile(r"\bKeyStroke\s*\.\s*getKeyStroke\s*\(")


def _label_of_var(text, var, pos, lang):
    if not var or not re.fullmatch(r"\w+", var):
        return None
    base = max(0, pos - 20000)
    last = None
    for m in re.finditer(rf"(?<![\w.]){re.escape(var)}\s*=(?!=)", text[base:pos]):
        last = m
    if last is None:
        return None
    start = base + last.end()
    end = text.find(";", start)
    m = re.search(r"\bnew\s+\w+\s*\(", text[start:end if end != -1 else pos])
    if not m:
        return None
    open_idx = start + m.end() - 1
    for s, _, value in srctext.iter_strings(text, lang, open_idx, srctext.matching(text, open_idx, lang)):
        return value
    return None


def scan_code(fs, lang):
    text = srctext.strip_comments(fs.text, lang)
    for m in GET_KEYSTROKE.finditer(text):
        args, close = srctext.split_args(text, m.end() - 1, lang)
        if close == -1 or not args:
            continue
        first = text[slice(*args[0])].strip()
        label = action = None
        for g_start, _ in srctext.enclosing_groups(text, m.start(), lang, limit=2):
            if text[g_start] != "(":
                continue
            receiver, name = srctext.callee_before(text, g_start)
            outer, _ = srctext.split_args(text, g_start, lang)
            strings = [v for a in outer for _, _, v in srctext.iter_strings(text, lang, *a)
                       if not (a[0] <= m.start() < a[1])]
            if name == "setAccelerator":
                label = _label_of_var(text, receiver, g_start, lang)
                break
            if name in ("put", "registerKeyboardAction") and strings:
                action = strings[0]
                break
        if first.startswith('"'):
            s, _, value = next(srctext.iter_strings(text, lang, *args[0]))
            fs.add(value, "java", fs.line(s), "java-keystroke", label=label, action=action, split=False)
        elif "VK_" in first:
            raw = re.sub(r"\s+", " ", ", ".join(text[slice(*a)].strip() for a in args))
            pos = text.find("VK_", args[0][0])
            fs.add(raw, "java", fs.line(pos), "java-keystroke", label=label, action=action, split=False)


def scan_keymap(fs, root):
    """<keyboard-shortcut first-keystroke="control S" second-keystroke="..."/> in a
    JetBrains keymap or a plugin.xml <action>."""
    keymap_name = None
    for el in root.children:
        if el.tag == "keymap":
            keymap_name = el.get("name")
    for ks in root.iter("keyboard-shortcut"):
        keymap = ks.get("keymap") or keymap_name or ""
        if re.search(r"mac", keymap, re.I) or ks.get("remove") == "true":
            continue
        first = ks.get("first-keystroke")
        if not first:
            continue
        action = label = None
        for anc in ks.ancestors():
            if anc.tag == "action":
                action = anc.get("id")
                label = anc.get("text")
                break
        parts = [first] + ([ks.get("second-keystroke")] if ks.get("second-keystroke") else [])
        raw = ", ".join(parts)
        seq, error = [], None
        for part in parts:
            chord, error = seq_or_error(part, "java")
            if error:
                break
            seq.extend(chord)
        context = keymap if ks.get("keymap") else None
        if error:
            fs.add_error(raw, error, ks.line, "jetbrains-keymap", label, action, context)
        else:
            fs.add_seq(raw, tuple(seq), ks.line, "jetbrains-keymap", label, action, context)
