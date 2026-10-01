"""Qt and KDE: C++ and Python code, QML, KXMLGUI .rc files, Designer .ui."""

import re

from . import accel, srctext, tables
from .srctext import clean_label

KSTD_ACTION = re.compile(r"\bKStandardActions?\s*::\s*(\w+)\s*\(")
KSTD_SHORTCUT = re.compile(r"\bKStandardShortcut\s*::\s*(\w+)\s*\(")
QKS_CALL = re.compile(r"\b(?:QKeySequence(?:\s*(?:::|\.)\s*fromString)?|QKeyCombination)\s*([({])")
STD_KEY_CXX = re.compile(r"\bQKeySequence\s*::\s*(?:StandardKey\s*::\s*)?(\w+)")
STD_KEY_PY = re.compile(r"\bQKeySequence\s*\.\s*(?:StandardKey\s*\.\s*)?(\w+)")
QT_NS = r"\bQt\s*(?:::|\.)\s*(?:(?:Modifier|KeyboardModifier|Key)\s*(?:::|\.)\s*)?"
ENUM_COMBO = re.compile(
    rf"(?:{QT_NS}(?:CTRL|SHIFT|ALT|META|ControlModifier|ShiftModifier|AltModifier|MetaModifier)"
    rf"\s*[|+]\s*)+{QT_NS}Key_\w+")
SHORTCUT_SETTERS = ("setShortcut", "setShortcuts", "setDefaultShortcut", "setDefaultShortcuts")
STRING_WRAPPERS = r"(?:QStringLiteral|QLatin1String|QString(?:::fromLatin1|::fromUtf8)?|u8|L)"
TRANSLATORS = r"(?:i18nc?|i18ncp?|i18np|ki18nc?|kli18nc?|tr|qsTr|QObject::tr|QCoreApplication::translate|translate|_)"


def _std_key_rows(name):
    entries = tables.qt_standard_key(name)
    return [e for e in entries or [] if e.get("accel")]


def _via(source, entry):
    return {"source": source, "file": entry["file"], "line": entry["line"]}


def _kstd_action_by_name(name):
    for ident, info in tables.load()["kstandard_actions"].items():
        if info["action_name"] == name:
            return tables.kstandard_action(ident)
    return None


def _string_arg(text, start, end, lang, want="any"):
    """The user-visible string of one argument, or None.

    want="label": only translated or plain strings (not icon names in
    QIcon::fromTheme). want="id": only QStringLiteral/QLatin1String/plain.
    """
    chunk = text[start:end].strip()
    if not chunk:
        return None
    translated = re.match(rf"{TRANSLATORS}\s*\(", chunk)
    wrapped = re.match(rf"{STRING_WRAPPERS}\s*\(", chunk) or re.match(r"u?\"", chunk) \
        or (lang == "python" and re.match(r"[\"']", chunk))
    if want == "label" and not (translated or wrapped):
        return None
    if want == "id" and not wrapped:
        return None
    if not (translated or wrapped):
        return None
    return srctext.translated(text, start, end, lang)


def _slot_name(text, args, lang):
    for a_start, a_end in reversed(args):
        chunk = text[a_start:a_end].strip()
        m = re.search(r"&\s*\w+(?:::\w+)*::(\w+)\s*$", chunk) or re.search(r"SLOT\s*\(\s*(\w+)\s*\(", chunk) \
            or (lang == "python" and re.fullmatch(r"self\.(\w+)", chunk))
        if m:
            return m.group(1)
    return None


def var_context(text, var, pos, lang):
    """(label, action) of a QAction variable, read back from where it was made."""
    if not var or not re.fullmatch(r"\w+", var):
        return None, None
    base = max(0, pos - 20000)
    last = None
    for m in re.finditer(rf"(?<![\w]){re.escape(var)}\s*=(?!=)", text[base:pos]):
        last = m
    if last is None:
        return None, None
    a_start = base + last.end()
    if lang == "python":
        stmt_end = text.find("\n", a_start)
        opener = re.search(r"[({\[]", text[a_start:stmt_end if stmt_end != -1 else len(text)])
        if opener:
            close = srctext.matching(text, a_start + opener.start(), lang)
            stmt_end = max(stmt_end, close)
    else:
        stmt_end = text.find(";", a_start)
    stmt_end = pos if stmt_end == -1 or stmt_end > pos else stmt_end
    label = action = None
    stmt = text[a_start:stmt_end]
    m = KSTD_ACTION.search(stmt)
    if m:
        info = tables.kstandard_action(m.group(1))
        if info:
            label, action = info["label"], info["action_name"]
    m = re.search(r"\baddAction\s*\(", stmt)
    if m and action is None:
        open_idx = a_start + m.end() - 1
        args, _ = srctext.split_args(text, open_idx, lang)
        if args:
            action = _string_arg(text, *args[0], lang, want="id")
            if action is None:
                label = _string_arg(text, *args[0], lang, want="label")
    m = re.search(r"\b\w*Action\s*\(", stmt)
    if m and label is None and not re.match(r"addAction", m.group(0)):
        args, _ = srctext.split_args(text, a_start + m.end() - 1, lang)
        for a in args:
            label = _string_arg(text, *a, lang, want="label")
            if label:
                break
    between = text[a_start:pos]
    for m in re.finditer(rf"\b{re.escape(var)}\s*(?:->|\.)\s*setText\s*\(", between):
        args, _ = srctext.split_args(text, a_start + m.end() - 1, lang)
        if args:
            label = _string_arg(text, *args[0], lang, want="label") or label
    if action is None:
        m = re.search(rf"\baddAction\s*\(\s*([^,()]*\(\s*)?[\"']([^\"']+)[\"']\s*\)?\s*,\s*{re.escape(var)}\s*\)",
                      between)
        if m:
            action = m.group(2)
    if action is None:
        m = re.search(rf"\b{re.escape(var)}\s*(?:->|\.)\s*setObjectName\s*\(\s*(?:\w+\s*\(\s*)?[\"']([^\"']+)",
                      between)
        if m:
            action = m.group(1)
    return (clean_label(label, "qt") if label else None), action


def qt_context(text, pos, lang):
    """(label, action) for a shortcut at `pos`, from the call it is an argument of."""
    for g_start, g_end in srctext.enclosing_groups(text, pos, lang, limit=3):
        if text[g_start] != "(":
            continue
        receiver, name = srctext.callee_before(text, g_start)
        if name is None:
            continue
        args, _ = srctext.split_args(text, g_start, lang)
        if name in ("setShortcut", "setShortcuts"):
            return var_context(text, receiver, g_start, lang)
        if name in ("setDefaultShortcut", "setDefaultShortcuts"):
            var = text[slice(*args[0])].strip() if args else None
            return var_context(text, var, g_start, lang)
        if name == "addAction":
            label = None
            for a in args[:2]:
                label = _string_arg(text, *a, lang, want="label")
                if label:
                    break
            return (clean_label(label, "qt") if label else None), _slot_name(text, args, lang)
        if name == "QShortcut":
            return None, _slot_name(text, args[1:], lang)
        if name.endswith("Action"):
            label = None
            for a in args:
                label = _string_arg(text, *a, lang, want="label")
                if label:
                    break
            return (clean_label(label, "qt") if label else None), None
    return None, None


def _inside(ranges, pos):
    return any(s <= pos < e for s, e in ranges)


def scan_code(fs, lang):
    text = srctext.strip_comments(fs.text, lang)
    taken = []  # (start, end) spans already reported
    data = tables.load()

    for m in KSTD_ACTION.finditer(text):
        fn = m.group(1)
        if fn in ("create", "_k_createInternal"):
            args, close = srctext.split_args(text, m.end() - 1, lang)
            em = re.search(r"KStandardActions?\s*::\s*(\w+)", text[slice(*args[0])]) if args else None
            info = tables.kstandard_action(em.group(1)) if em else None
        elif fn in data["kstandard_action_functions"]:
            info = tables.kstandard_action(fn)
        else:
            info = None
        if not info:
            continue
        taken.append((m.start(), m.end()))
        line = fs.line(m.start())
        raw = re.sub(r"\s+", "", text[m.start():m.end() - 1])
        for sc in info["shortcuts"]:
            if sc.get("accel"):
                fs.add_accel(raw, sc["accel"], line, "kstandardaction", label=info["label"],
                             action=info["action_name"], via=_via("kconfig", sc))

    for m in KSTD_SHORTCUT.finditer(text):
        fn = m.group(1)
        if fn == "shortcut":
            args, _ = srctext.split_args(text, m.end() - 1, lang)
            em = re.search(r"KStandardShortcut\s*::\s*(\w+)", text[slice(*args[0])]) if args else None
            enum = em.group(1) if em else None
        else:
            enum = tables.kstandard_shortcut_function(fn)
        entries = tables.kstandard_shortcut(enum) if enum else None
        if not entries:
            continue
        taken.append((m.start(), m.end()))
        label, action = qt_context(text, m.start(), lang)
        raw = re.sub(r"\s+", "", text[m.start():m.end() - 1])
        for sc in entries:
            if sc.get("accel"):
                fs.add_accel(raw, sc["accel"], fs.line(m.start()), "kstandardshortcut",
                             label=label, action=action, via=_via("kconfig", sc))

    for m in QKS_CALL.finditer(text):
        open_idx = m.start(1)
        close = srctext.matching(text, open_idx, lang)
        if close == -1 or _inside(taken, m.start()):
            continue
        inner = text[open_idx + 1:close].strip()
        if not inner:
            continue
        label, action = qt_context(text, m.start(), lang)
        if re.match(rf"(?:{TRANSLATORS}|{STRING_WRAPPERS})\s*\(|u?[\"']", inner):
            value = srctext.translated(text, open_idx + 1, close, lang)
            if value is None:
                continue
            first = next(srctext.iter_strings(text, lang, open_idx + 1, close))
            taken.append((m.start(), close + 1))
            fs.add(value, "qt", fs.line(first[0]), "qt-shortcut", label=label, action=action)
        elif "Key_" in inner:
            args, _ = srctext.split_args(text, open_idx, lang)
            seq, error, raws = [], None, []
            for a_start, a_end in args:
                chunk = text[a_start:a_end].strip()
                raws.append(chunk)
                result = accel._one(chunk, "qt")
                if result.error:
                    error = result.error
                    break
                seq.extend(result.seq)
            taken.append((m.start(), close + 1))
            raw = re.sub(r"\s+", " ", ", ".join(raws))
            key_pos = text.find("Key_", open_idx)
            if error:
                fs.add_error(raw, error, fs.line(key_pos), "qt-shortcut", label, action)
            else:
                fs.add_seq(raw, tuple(seq), fs.line(key_pos), "qt-shortcut", label, action)

    std_re = STD_KEY_PY if lang == "python" else STD_KEY_CXX
    for m in std_re.finditer(text):
        if _inside(taken, m.start()) or m.group(1) not in data["qt_standard_keys"]:
            continue
        taken.append((m.start(), m.end()))
        label, action = qt_context(text, m.start(), lang)
        raw = re.sub(r"\s+", "", m.group(0))
        for entry in _std_key_rows(m.group(1)):
            fs.add_accel(raw, entry["accel"], fs.line(m.start()), "qt-standard-key",
                         label=label, action=action, via=_via("qtbase", entry))

    for m in ENUM_COMBO.finditer(text):
        if _inside(taken, m.start()):
            continue
        taken.append((m.start(), m.end()))
        label, action = qt_context(text, m.start(), lang)
        fs.add(re.sub(r"\s+", " ", m.group(0)), "qt", fs.line(m.start()), "qt-shortcut",
               label=label, action=action, split=False)

    # Actions registered by name, shortcut or not: their labels name menu items
    # that KXMLGUI .rc files list by action name only
    for m in re.finditer(r"\baddAction\s*\(", text):
        args, close = srctext.split_args(text, m.end() - 1, lang)
        if close == -1 or not args:
            continue
        name = _string_arg(text, *args[0], lang, want="id")
        if not name or not re.fullmatch(r"[\w.-]+", name):
            continue
        var = None
        if len(args) >= 2 and re.fullmatch(r"\w+", text[slice(*args[1])].strip()):
            var = text[slice(*args[1])].strip()
        if var is None:
            am = re.search(r"(\w+)\s*=\s*[^;={}]*$", text[max(0, m.start() - 200):m.start()])
            var = am.group(1) if am else None
        if var is None:
            continue
        nxt = re.compile(rf"(?<![\w]){re.escape(var)}\s*=(?!=)").search(text, close)
        label, action = var_context(text, var, nxt.start() if nxt else min(len(text), close + 3000), lang)
        if action == name and label:
            fs.add_action(name, label, fs.line(m.start()), "qt-action")

    # Plain strings handed to a shortcut setter: setShortcut(QStringLiteral("Ctrl+S"))
    for m in re.finditer(rf"\b({'|'.join(SHORTCUT_SETTERS)})\s*\(|\bshortcut\s*=\s*(?=[\"'])", text):
        if m.group(1):
            args, close = srctext.split_args(text, m.end() - 1, lang)
            if close == -1:
                continue
            args = args[1:] if m.group(1).startswith("setDefault") else args
        else:
            end = srctext.skip_string(text, m.end(), lang)
            args = [(m.end(), end)]
        for a_start, a_end in args:
            if _inside(taken, a_start + 1) or _inside(taken, a_end - 1):
                continue
            chunk = text[a_start:a_end].strip()
            if not re.match(rf"(?:{TRANSLATORS}|{STRING_WRAPPERS})\s*\(|u?[\"']", chunk):
                continue
            value = srctext.translated(text, a_start, a_end, lang)
            if not value:
                continue
            taken.append((a_start, a_end))
            label, action = qt_context(text, a_start, lang)
            fs.add(value, "qt", fs.line(a_start + (len(text[a_start:a_end]) - len(text[a_start:a_end].lstrip()))),
                   "qt-shortcut", label=label, action=action, keep_errors=False)


# --- QML -----------------------------------------------------------------

QML_PROP = re.compile(r"\b(sequence|sequences|shortcut|shortcuts)\s*:\s*")


def _depth(text, start, pos):
    depth = 0
    i = start
    while i < pos:
        ch = text[i]
        if ch in "\"'`":
            i = srctext.skip_string(text, i, "qml")
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        i += 1
    return depth


def _qml_prop(text, block, name):
    b_start, b_end = block
    for m in re.finditer(rf"(?<![\w.]){name}\s*:\s*", text[b_start + 1:b_end]):
        pos = b_start + 1 + m.start()
        if _depth(text, b_start + 1, pos) == 0:
            v_start = b_start + 1 + m.end()
            v_end = text.find("\n", v_start)
            return v_start, (b_end if v_end == -1 or v_end > b_end else v_end)
    return None


def scan_qml(fs):
    text = srctext.strip_comments(fs.text, "qml")
    for m in QML_PROP.finditer(text):
        if re.search(r"[\w.]$", text[:m.start()]):
            continue
        v_start = m.end()
        if text[v_start:v_start + 1] == "[":
            args, _ = srctext.split_args(text, v_start, "qml")
        else:
            line_end = text.find("\n", v_start)
            line_end = len(text) if line_end == -1 else line_end
            semi = text.find(";", v_start, line_end)
            args = [(v_start, semi if semi != -1 else line_end)]
        block = None
        for g in srctext.enclosing_groups(text, m.start(), "qml", limit=3):
            if text[g[0]] == "{":
                block = g
                break
        label = action = None
        if block:
            span = _qml_prop(text, block, "text")
            if span:
                label = srctext.translated(text, span[0], span[1], "qml")
                label = clean_label(label, "qt") if label else None
            span = _qml_prop(text, block, "id")
            if span:
                action = text[span[0]:span[1]].strip() or None
        for a_start, a_end in args:
            chunk = text[a_start:a_end].strip()
            if not chunk:
                continue
            sm = re.fullmatch(r"(?:StandardKey|Qt\.StandardKey|QKeySequence)\s*\.\s*(\w+)", chunk)
            if sm:
                for entry in _std_key_rows(sm.group(1)):
                    fs.add_accel(chunk, entry["accel"], fs.line(a_start), "qml-shortcut",
                                 label=label, action=action, via=_via("qtbase", entry))
                continue
            value = srctext.translated(text, a_start, a_end, "qml")
            if value is None:
                continue
            first = next(srctext.iter_strings(text, "qml", a_start, a_end))
            fs.add(value, "qt", fs.line(first[0]), "qml-shortcut", label=label, action=action)


# --- KXMLGUI .rc ----------------------------------------------------------

def _text_child(el):
    for child in el.find_children("text"):
        return clean_label(child.text, "qt")
    for child in el.find_children("title"):
        return clean_label(child.text, "qt")
    return None


def scan_kxmlgui(fs, gui):
    props = {}
    for ap in gui.iter("ActionProperties"):
        if ap.get("scheme", "Default") != "Default":
            continue
        for act in ap.find_children("Action"):
            name, shortcut = act.get("name"), act.get("shortcut")
            if not name or not shortcut or not shortcut.strip():
                continue
            rows = []
            for part in [p.strip() for p in shortcut.split(";") if p.strip()]:
                rows += fs.add(part, "qt", act.line, "kxmlgui", action=name)
            first = next((r["accel"] for r in rows if r["accel"]), None)
            if first:
                props.setdefault(name, (first, act.line))
    std_seen = set()

    def build(menu):
        items = []
        for child in menu.children:
            if child.tag == "Separator":
                items.append({"separator": True})
            elif child.tag == "Menu":
                items.append({"label": _text_child(child), "id": child.get("name"), "line": child.line,
                              "items": build(child)})
            elif child.tag == "Action" and child.get("name"):
                name = child.get("name")
                item = {"action": name, "line": child.line}
                std = _kstd_action_by_name(name)
                if std:
                    item["label"] = std["label"]
                    accels = [sc for sc in std["shortcuts"] if sc.get("accel")]
                    if accels:
                        item["accel"] = accels[0]["accel"]
                        item["accel_line"] = child.line
                    if name not in std_seen:
                        std_seen.add(name)
                        for sc in accels:
                            fs.add_accel(name, sc["accel"], child.line, "kxmlgui-standard-action",
                                         label=std["label"], action=name, via=_via("kconfig", sc))
                if props.get(name):
                    item["accel"], item["accel_line"] = props[name]
                items.append(item)
        return items

    for bar in gui.iter("MenuBar"):
        for menu in bar.find_children("Menu"):
            fs.add_menu({"line": menu.line, "kind": "kxmlgui", "id": menu.get("name"),
                         "label": _text_child(menu), "items": build(menu)})


# --- Qt Designer .ui -------------------------------------------------------

def _prop_string(el, name):
    for prop in el.find_children("property"):
        if prop.get("name") == name:
            for s in prop.find_children("string"):
                return s
    return None


def scan_designer(fs, ui):
    actions = {}
    for act in ui.iter("action"):
        name = act.get("name")
        text_el = _prop_string(act, "text")
        label = clean_label(text_el.text, "qt") if text_el is not None else None
        entry = {"label": label, "accel": None}
        sc = _prop_string(act, "shortcut")
        if sc is not None and sc.text:
            rows = fs.add(sc.text, "qt", sc.line, "qt-designer", label=label, action=name)
            entry["accel"] = next((r["accel"] for r in rows if r["accel"]), None)
            entry["accel_line"] = sc.line
        elif name:
            fs.add_action(name, label, act.line, "qt-designer")
        actions[name] = entry
    menus = {w.get("name"): w for w in ui.iter("widget") if w.get("class") == "QMenu"}

    def build(widget):
        items = []
        for add in widget.find_children("addaction"):
            name = add.get("name")
            if name == "separator":
                items.append({"separator": True})
            elif name in menus:
                sub = menus[name]
                title = _prop_string(sub, "title")
                items.append({"label": clean_label(title.text, "qt") if title is not None else None,
                              "id": name, "line": sub.line, "items": build(sub)})
            else:
                info = actions.get(name, {})
                item = {"label": info.get("label"), "action": name, "line": add.line}
                if info.get("accel"):
                    item["accel"] = info["accel"]
                    item["accel_line"] = info["accel_line"]
                items.append(item)
        return items

    bars = [w for w in ui.iter("widget") if w.get("class") == "QMenuBar"]
    top = []
    for bar in bars:
        top += [menus[a.get("name")] for a in bar.find_children("addaction") if a.get("name") in menus]
    if not bars:
        nested = {a.get("name") for m in menus.values() for a in m.find_children("addaction")}
        top = [m for n, m in menus.items() if n not in nested]
    for menu in top:
        title = _prop_string(menu, "title")
        fs.add_menu({"line": menu.line, "kind": "qt-designer", "id": menu.get("name"),
                     "label": clean_label(title.text, "qt") if title is not None else None,
                     "items": build(menu)})
