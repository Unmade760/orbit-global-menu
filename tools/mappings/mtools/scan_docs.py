"""Documentation: Markdown tables and lists, Mallard pages, DocBook, YAML keymaps.

Prose is never read as a shortcut: a key name counts only inside markup that
marks it as a key (a <kbd> group, a code span, bold text, a Mallard <key>,
a DocBook <keycombo>), in a table column about keys, or when it carries a
modifier.
"""

import re

from . import accel

KEY_HEADER = re.compile(r"key|shortcut|binding|hotkey|accelerator|combination|keystroke|chord", re.I)
KBD_GROUP = re.compile(r"<kbd>[^<]*</kbd>(?:\s*[+\-]?\s*<kbd>[^<]*</kbd>)*", re.I)
CODE_SPAN = re.compile(r"`([^`\n]+)`")
BOLD_SPAN = re.compile(r"\*\*([^*\n]+)\*\*|__([^_\n]+)__")
LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.*)$")
# A list item "Ctrl+S: Save" or "Ctrl+S \u2013 Save" (en or em dash between spaces)
PLAIN_LEAD = re.compile("^(?P<keys>[^:\u2013\u2014]+?)\\s*(?::|\\s[\u2013\u2014-]\\s)\\s*(?P<label>\\S.*)$")


def _strip_md(text):
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"[`*_]", "", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def _parse(text):
    """Every alternative of `text` if all normalize, else None."""
    results = accel.normalize_all(text, "text")
    if not results or any(r.error for r in results):
        return None
    return results


def _has_modifier(results):
    return any(mods for r in results for mods, _ in r.seq)


def _named(results):
    return all(any(len(key) > 1 for _, key in r.seq) for r in results)


def _clean_label(text):
    text = _strip_md(text).strip(" :\u2013\u2014-.,;[]()")
    return text if re.search(r"\w", text) else None


def _split_row(line):
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|"):
        body = body[:-1]
    cells, cur, in_code = [], "", False
    i = 0
    while i < len(body):
        ch = body[i]
        if ch == "\\" and i + 1 < len(body) and body[i + 1] == "|":
            cur += "|"
            i += 2
            continue
        if ch == "`":
            in_code = not in_code
        if ch == "|" and not in_code:
            cells.append(cur)
            cur = ""
        else:
            cur += ch
        i += 1
    cells.append(cur)
    return [c.strip() for c in cells]


def _cell_shortcuts(cell, key_column):
    formatted = bool(KBD_GROUP.search(cell) or CODE_SPAN.fullmatch(cell.strip())
                     or BOLD_SPAN.fullmatch(cell.strip()))
    text = cell.strip()
    if CODE_SPAN.fullmatch(text) or BOLD_SPAN.fullmatch(text):
        text = text.strip("`*_")
    results = _parse(text)
    if results is None:
        return None
    if formatted or key_column or _has_modifier(results):
        return results
    return None


def _inline_candidates(line):
    """(start, end, text, formatted_as_kbd) for key markup in a line."""
    out = []
    for m in KBD_GROUP.finditer(line):
        out.append((m.start(), m.end(), m.group(0), True))
    for m in CODE_SPAN.finditer(line):
        out.append((m.start(), m.end(), m.group(1), False))
    for m in BOLD_SPAN.finditer(line):
        out.append((m.start(), m.end(), m.group(1) or m.group(2), False))
    return sorted(out)


def scan_markdown(fs):
    heading = None
    in_fence = False
    header_cells = None
    lines = fs.text.split("\n")
    for number, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        h = re.match(r"^#{1,6}\s+(.*)", line)
        if h:
            heading = _strip_md(h.group(1))
            header_cells = None
            continue
        if stripped.startswith("|") and stripped.count("|") >= 2:
            cells = _split_row(line)
            if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                continue
            nxt = lines[number] if number < len(lines) else ""
            if re.fullmatch(r"\s*\|?\s*:?-{2,}:?\s*(?:\|\s*:?-{2,}:?\s*)*\|?\s*", nxt):
                header_cells = cells
                continue
            found, label = [], None
            for i, cell in enumerate(cells):
                key_column = bool(header_cells and i < len(header_cells) and KEY_HEADER.search(header_cells[i]))
                results = _cell_shortcuts(cell, key_column)
                if results:
                    found.append((cell, results))
                elif label is None and _strip_md(cell):
                    label = _clean_label(cell)
            for cell, results in found:
                for r in results:
                    fs.add_accel(_strip_md(cell) if len(results) == 1 else r.raw, r.accel, number,
                                 "doc-text", label=label, context=heading)
            continue
        header_cells = None
        item = LIST_ITEM.match(line)
        body = item.group(1) if item else line
        candidates = _inline_candidates(body)
        emitted = False
        for start, end, text, is_kbd in candidates:
            results = _parse(text)
            if results is None:
                continue
            if not (is_kbd or _has_modifier(results) or _named(results)):
                continue
            label = _clean_label(body[:start] + " " + body[end:])
            for r in results:
                fs.add_accel(_strip_md(text) if len(results) == 1 else r.raw, r.accel, number, "doc-text",
                             label=label, context=heading)
            emitted = True
        if not emitted and item:
            pm = PLAIN_LEAD.match(_strip_md(body))
            if pm:
                results = _parse(pm.group("keys"))
                if results and _has_modifier(results):
                    for r in results:
                        fs.add_accel(pm.group("keys"), r.accel, number, "doc-text",
                                     label=_clean_label(pm.group("label")), context=heading)


# --- Mallard ---------------------------------------------------------------

def _keyseq_text(el):
    keys = [k.all_text() for k in el.iter("key")]
    if el.tag == "key" or not keys:
        return el.all_text()
    joiner = " " if el.get("type") == "sequence" else "+"
    return joiner.join(keys)


def _mallard_label(el):
    for anc in el.ancestors():
        if anc.tag == "tr":
            for td in anc.find_children("td"):
                if not any(True for _ in td.iter("key")):
                    text = td.all_text()
                    if text:
                        return text, None
            return None, None
        if anc.tag == "item" and anc.parent is not None and anc.parent.tag == "terms":
            for p in anc.find_children("p"):
                if p.all_text():
                    return p.all_text(), None
        if anc.tag == "p":
            guis = [g.all_text() for g in anc.iter("gui")]
            if guis:
                return guis[-1], (" > ".join(guis[:-1]) or None)
    return None, None


def scan_mallard(fs, root):
    for el in root.iter():
        if el.tag not in ("keyseq", "key"):
            continue
        if any(a.tag == "keyseq" for a in el.ancestors()):
            continue
        text = _keyseq_text(el)
        results = _parse(text)
        if results is None:
            continue
        label, context = _mallard_label(el)
        for r in results:
            fs.add_accel(text, r.accel, el.line, "mallard", label=label, context=context)


# --- DocBook -----------------------------------------------------------------

ENTITY_KEYS = {"ctrl": "Ctrl", "shift": "Shift", "alt": "Alt", "meta": "Super", "super": "Super",
               "enter": "Enter", "esc": "Esc", "del": "Del", "backspace": "Backspace", "tab": "Tab",
               "space": "Space", "up": "Up", "down": "Down", "left": "Left", "right": "Right",
               "home": "Home", "end": "End", "pgup": "PgUp", "pgdn": "PgDn", "ins": "Ins",
               "insert": "Ins", "delete": "Del", "return": "Enter", "cmd": None}


def _keycombo_text(combo):
    parts = []
    for ent in re.findall(r"&(\w+);", "".join(combo.text_parts)):
        name = ENTITY_KEYS.get(ent.lower(), ent)
        if name is None:
            return None
        parts.append(name)
    for child in combo.children:
        if child.tag in ("keycap", "keysym", "keycode"):
            text = child.all_text()
            for ent in re.findall(r"&(\w+);", text):
                text = text.replace(f"&{ent};", ENTITY_KEYS.get(ent.lower()) or ent)
            parts.append(text)
    return "+".join(p for p in parts if p) or None


def _shortcut_text(container):
    combos = [c for c in container.iter("keycombo")]
    if not combos:
        keys = [k.all_text() for k in container.iter("keycap")]
        return "+".join(keys) if keys else None
    texts = [_keycombo_text(c) for c in combos]
    if any(t is None for t in texts):
        return None
    return " ".join(texts)


def scan_docbook(fs, root):
    in_menuchoice = set()
    for mc in root.iter("menuchoice"):
        for sc in mc.find_children("shortcut"):
            text = _shortcut_text(sc)
            for c in sc.iter("keycombo"):
                in_menuchoice.add(id(c))
            if not text:
                continue
            items = [g.all_text() for g in mc.iter("guimenuitem")]
            subs = [g.all_text() for g in mc.iter("guisubmenu")]
            menus = [g.all_text() for g in mc.iter("guimenu")]
            label = items[-1] if items else (subs[-1] if subs else None)
            path = menus + (subs if items else subs[:-1])
            results = _parse(text)
            if results is None:
                continue
            line = next(iter(sc.iter("keycombo")), sc).line
            for r in results:
                fs.add_accel(text, r.accel, line, "docbook-menuchoice", label=label,
                             context=" > ".join(path) or None)
    for combo in root.iter("keycombo"):
        if id(combo) in in_menuchoice or any(a.tag == "keycombo" for a in combo.ancestors()):
            continue
        text = _keycombo_text(combo)
        results = _parse(text) if text else None
        if results is None:
            continue
        label = None
        for anc in combo.ancestors():
            if anc.tag == "row":
                for entry in anc.find_children("entry"):
                    if not any(True for _ in entry.iter("keycombo")) and entry.all_text():
                        label = entry.all_text()
                        break
                break
            if anc.tag == "varlistentry":
                for li in anc.find_children("listitem"):
                    label = re.split(r"(?<=\.)\s", li.all_text())[0][:120] or None
                break
        for r in results:
            fs.add_accel(text, r.accel, combo.line, "docbook-keycombo", label=label)


# --- YAML --------------------------------------------------------------------

YAML_KEY_FIELDS = ("key", "keys", "shortcut", "shortcuts", "keybinding", "binding", "accelerator", "hotkey")
YAML_LABEL_FIELDS = ("name", "label", "title", "description", "desc")
YAML_ACTION_FIELDS = ("command", "action", "id")


def scan_yaml(fs):
    blocks, cur, cur_indent = [], None, None
    for number, line in enumerate(fs.text.split("\n"), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = re.match(r"^(\s*)-\s+([\w-]+)\s*:\s*(.*)$", line)
        if m:
            cur = {m.group(2).lower(): (m.group(3), number)}
            cur_indent = len(m.group(1)) + 2
            blocks.append(cur)
            continue
        m = re.match(r"^(\s*)([\w-]+)\s*:\s*(.*)$", line)
        if m and cur is not None and len(m.group(1)) >= cur_indent:
            cur[m.group(2).lower()] = (m.group(3), number)
        else:
            cur = None
    for block in blocks:
        field = next((f for f in YAML_KEY_FIELDS if f in block and block[f][0].strip()), None)
        if not field:
            continue
        value, line = block[field]
        value = value.strip().strip("'\"")
        alts = [v.strip().strip("'\"") for v in value.strip("[]").split(",")] if value.startswith("[") else [value]
        label = next((block[f][0].strip().strip("'\"") for f in YAML_LABEL_FIELDS if f in block), None)
        action = next((block[f][0].strip().strip("'\"") for f in YAML_ACTION_FIELDS if f in block), None)
        for alt in alts:
            results = _parse(alt)
            if results:
                for r in results:
                    fs.add_accel(alt, r.accel, line, "doc-yaml", label=label, action=action)
