"""GTK: code in C, Vala, Python, Rust and JS; GtkBuilder .ui; Blueprint .blp."""

import re

from . import accel, blueprint, srctext
from .common import seq_or_error
from .srctext import clean_label

# --- shared pieces -------------------------------------------------------

# A GAction name with one group prefix: "app.quit", "win.zoom-in",
# "win.sort::name", "win.zoom(1)". Two dots or a file suffix is something else.
ACTION_RE = re.compile(r"^[A-Za-z][\w-]*\.[A-Za-z0-9_][\w-]*(?:::[\w.-]+|\([^)]*\))?$")
FILE_SUFFIX = re.compile(r"\.(?:ui|blp|png|svg|css|js|c|h|py|rs|json|xml|desktop|gresource|txt|md|so)$", re.I)

GTK_MOD_TAG = re.compile(
    r"^(?:<(?:primary|control|ctrl|ctl|shift|shft|alt|mod1|super|meta|hyper|release)>)+[^<>\s]+"
    r"(?:\|(?:<\w+>)*[^<>\s|]+)*$", re.I)

KEY_TOKEN = re.compile(
    r"(?:GDK_KEY_|Gdk\.KEY_|Gdk\.Key\.|gdk::Key::|gdk::keys::constants::|Gdk\.Key_)([A-Za-z0-9_]+)")
MASK_NAMES = {
    "CONTROL_MASK": "Control", "SHIFT_MASK": "Shift", "ALT_MASK": "Alt", "MOD1_MASK": "Alt",
    "SUPER_MASK": "Super", "META_MASK": "Meta", "HYPER_MASK": "Hyper",
}
NAMED_ACTION = re.compile(
    r"(?:gtk_named_action_new|NamedAction(?:\.new|::new)|gtk_signal_action_new|SignalAction(?:\.new|::new))"
    r"\s*\(\s*(?:\w+\s*=\s*)?([\"'])([^\"']+)\1"
    r"|new\s+Gtk\.(?:NamedAction|SignalAction)\s*\(\s*\{\s*(?:action_name|signal_name)\s*:\s*([\"'])([^\"']+)\3")


def is_action_name(value):
    return bool(ACTION_RE.match(value)) and not FILE_SUFFIX.search(value)


def mods_from_mask(mask_text):
    """GDK modifier names from a mask expression, or (None, error)."""
    text = mask_text.strip()
    if text in ("", "0", "None", "null", "NULL", "GdkModifierType(0)") or re.fullmatch(
            r"(?:gdk::)?ModifierType::(?:empty\(\)|NO_MODIFIER_MASK)|(?:Gdk\.)?ModifierType\.(?:NO_MODIFIER_MASK|0)|0\s*as\s*\w+", text):
        return [], None
    mods = []
    for name in re.findall(r"([A-Z0-9_]+_MASK)\b", text):
        short = re.sub(r"^GDK_", "", name)
        if short not in MASK_NAMES:
            return None, f"modifier {name} is not in the mapping grammar"
        if MASK_NAMES[short] not in mods:
            mods.append(MASK_NAMES[short])
    if not mods and text:
        return None, f"cannot read modifiers {text!r}"
    return mods, None


def gtk_from_key_mask(key, mask_text):
    """("<Control><Shift>s", None) from a keysym name and a mask, or (None, error)."""
    mods, error = mods_from_mask(mask_text)
    if error:
        return None, error
    return "".join(f"<{m}>" for m in mods) + key, None


def action_from_trigger_value(value):
    """GtkShortcut action strings: "action(app.quit)", "signal(activate)"."""
    if not value:
        return None
    m = re.fullmatch(r"\s*(?:action|signal)\((.+)\)\s*", value)
    return m.group(1).strip() if m else value.strip()


# --- GtkShortcutsShortcut / AdwShortcutsItem accelerator syntax ----------

def shortcut_label_alternatives(text):
    """Parse the GtkShortcutLabel accelerator syntax.

    gtk/deprecated/gtkshortcutsshortcut.c: alternatives are separated by a
    space, "..." gives a range, "+" or "&" joins a sequence ("&" means keys
    pressed together, which a menu cannot send). Yields (raw, seq, error).
    """
    for alt in text.split():
        if "..." in alt:
            first, last = alt.split("...", 1)
            a, err_a = seq_or_error(first, "gtk")
            b, err_b = seq_or_error(last, "gtk")
            if err_a or err_b:
                yield alt, None, err_a or err_b
                continue
            (mods_a, key_a), (mods_b, key_b) = a[0], b[0]
            if mods_a != mods_b or len(key_a) != 1 or len(key_b) != 1 or \
                    key_a.isdigit() != key_b.isdigit() or key_a > key_b:
                yield alt, None, "range endpoints are not two keys of one kind"
                continue
            for code in range(ord(key_a), ord(key_b) + 1):
                yield alt, ((mods_a, chr(code)),), None
            continue
        if "&" in alt:
            yield alt, None, "keys pressed together are not in the mapping grammar"
            continue
        parts = [p for p in alt.split("+") if p]
        seq, error = [], None
        for part in parts:
            chord, error = seq_or_error(part, "gtk")
            if error:
                break
            seq.extend(chord)
        yield alt, (tuple(seq) if not error else None), error


def add_shortcut_label(fs, text, line, kind, label, action, context):
    for raw, seq, error in shortcut_label_alternatives(text):
        if error:
            fs.add_error(raw if raw != text else text, error, line, kind, label, action, context)
        else:
            fs.add_seq(text, seq, line, kind, label, action, context)


# --- code: C, Vala, Python, Rust, JS -------------------------------------

LANG_BY_SUFFIX = {
    ".c": "c", ".h": "c", ".cc": "cpp", ".cpp": "cpp", ".cxx": "cpp", ".hpp": "cpp", ".hh": "cpp",
    ".vala": "vala", ".py": "python", ".rs": "rust", ".js": "js", ".mjs": "js", ".cjs": "js",
    ".ts": "js", ".tsx": "js", ".jsx": "js",
}

SET_ACCELS = re.compile(
    r"\b(?:gtk_application_set_accels_for_action|set_accels_for_action|set_accelerators_for_action)"
    r"\s*(?:::<\s*([\w:]+)\s*>)?\s*\(")
CREATE_ACTION = re.compile(r"\bcreate_action\s*\(")
BINDING_CALL = re.compile(
    r"\b(gtk_widget_class_add_binding(?:_action|_signal)?|add_binding(?:_action|_signal)?"
    r"|gtk_widget_add_accelerator|add_accelerator|gtk_accel_map_add_entry|gtk_keyval_trigger_new"
    r"|KeyvalTrigger(?:\.new|::new)?)\s*\(")
TRIGGER_PARSE = re.compile(
    r"\b(?:gtk_shortcut_trigger_parse_string|ShortcutTrigger(?:\.parse_string|::parse_string))\s*\(")
PAIR_AFTER = re.compile(
    r"\s*[,:]\s*(?:\(\s*const\s+g?char\s*\*\s*\[\s*\]\s*\)\s*|&\s*|vec!\s*|new\s+string\s*\[\s*\]\s*)?([\[{(])")
TABLE_FILLER = re.compile(r"^[\s,]*(?:(?:NULL|nullptr|None|null)[\s,]*)*$")


def _strings_in(text, start, end, lang):
    return [(s, e, v) for s, e, v in srctext.iter_strings(text, lang, start, end)]


def _strong(seq):
    """A chord with a modifier or a named key: clearly a shortcut, not a letter."""
    return any(mods or len(key) > 1 for mods, key in seq)


def _named_array(text, name, before, lang):
    """String literals of the array literal last assigned to `name` before `before`."""
    name = re.sub(r"^(?:&|\(\s*const\s+g?char\s*\*\*?\s*\)\s*)", "", name).strip()
    if not re.fullmatch(r"[A-Za-z_]\w*", name):
        return []
    base = max(0, before - 20000)
    last = None
    for m in re.finditer(rf"\b{name}\s*(?:\[\s*\w*\s*\])*\s*(?::\s*[^=;\n]+)?=\s*(?:vec!\s*|&\s*)?([\[{{(])",
                         text[base:before]):
        last = m
    if last is None:
        return []
    open_idx = base + last.start(1)
    close = srctext.matching(text, open_idx, lang)
    return _strings_in(text, open_idx, close, lang) if close != -1 else []


def nearby_named_action(text, start, end, fs):
    """Action of a trigger: a NamedAction/SignalAction in the enclosing call,
    else on the next few lines, else on the two lines before."""
    for g_start, g_end in srctext.enclosing_groups(text, start, limit=3):
        m = NAMED_ACTION.search(text, g_start, g_end)
        if m:
            return m.group(2) or m.group(4)
    line_end = end
    for _ in range(5):
        nxt = text.find("\n", line_end + 1)
        line_end = len(text) if nxt == -1 else nxt
    m = NAMED_ACTION.search(text, end, line_end)
    if m:
        return m.group(2) or m.group(4)
    line_start = start
    for _ in range(3):
        prev = text.rfind("\n", 0, line_start - 1)
        line_start = 0 if prev == -1 else prev
    found = None
    for m in NAMED_ACTION.finditer(text, line_start, start):
        found = m.group(2) or m.group(4)
    return found


def scan_code(fs, lang):
    text = srctext.strip_comments(fs.text, lang)
    strings = list(srctext.iter_strings(text, lang))

    # set_accels_for_action (and relm4's set_accelerators_for_action::<T>)
    for m in SET_ACCELS.finditer(text):
        open_idx = m.end() - 1
        args, close = srctext.split_args(text, open_idx, lang)
        if close == -1:
            continue
        found = _strings_in(text, open_idx, close, lang)
        action = m.group(1)
        accel_strings = found
        if action is None:
            if not found:
                continue
            action = found[0][2]
            accel_strings = found[1:]
        if not accel_strings and args:
            # set_accels_for_action (app, "app.help", help_accels): read the array
            accel_strings = _named_array(text, text[slice(*args[-1])].strip(), m.start(), lang)
        for s, e, value in accel_strings:
            fs.consumed.add(s)
            fs.add(value, "gtk", fs.line(s), "gtk-set-accels", action=action)
        for s, _, _ in found:
            fs.consumed.add(s)

    # create_action("quit", callback, ["<primary>q"]), the GNOME Builder template
    if lang == "python":
        for m in CREATE_ACTION.finditer(text):
            args, close = srctext.split_args(text, m.end() - 1, lang)
            if close == -1 or not args:
                continue
            name = _strings_in(text, *args[0], lang)
            if not name:
                continue
            action = name[0][2]
            if "." not in action:
                action = f"app.{action}"
            for a_start, a_end in args[1:]:
                chunk = text[a_start:a_end].strip()
                chunk = re.sub(r"^shortcuts\s*=\s*", "", chunk)
                if not chunk.startswith("["):
                    continue
                for s, e, value in _strings_in(text, a_start, a_end, lang):
                    fs.consumed.add(s)
                    fs.add(value, "gtk", fs.line(s), "gtk-set-accels", action=action)

    # Bindings and keyval triggers built from a keysym and a modifier mask
    for m in BINDING_CALL.finditer(text):
        name = m.group(1)
        open_idx = m.end() - 1
        args, close = srctext.split_args(text, open_idx, lang)
        if close == -1:
            continue
        key_idx = None
        for i, (a_start, a_end) in enumerate(args):
            if KEY_TOKEN.match(text[a_start:a_end].strip()):
                key_idx = i
                break
        if key_idx is None:
            # new Gtk.KeyvalTrigger({keyval: Gdk.KEY_q, modifiers: ...})
            km = KEY_TOKEN.search(text, open_idx, close)
            mm = re.search(r"modifiers\s*:\s*([^,}]+)", text[open_idx:close])
            if not km:
                continue
            key_start, key = km.start(), km.group(1)
            mask_text = mm.group(1) if mm else "0"
            rest_args = []
        else:
            a_start, a_end = args[key_idx]
            km = KEY_TOKEN.search(text, a_start, a_end)
            key_start, key = km.start(), km.group(1)
            mask_text = text[slice(*args[key_idx + 1])] if key_idx + 1 < len(args) else "0"
            rest_args = args[key_idx + 2:]
        raw = re.sub(r"\s+", " ", f"{text[km.start():km.end()]}, {mask_text.strip()}")
        action = None
        kind = "gtk-binding"
        if name.endswith(("_action", "_signal")) or name in ("gtk_accel_map_add_entry",):
            found = _strings_in(text, open_idx, close, lang)
            action = found[0][2] if found else None
        elif name.endswith("add_binding") or name == "add_binding":
            if rest_args:
                cb = text[slice(*rest_args[0])].strip()
                cb = re.sub(r"^(?:G_CALLBACK|Some)\s*\(\s*(.*?)\s*\)$", r"\1", cb)
                action = cb or None
        elif "Trigger" in name or "trigger" in name:
            kind = "gtk-shortcut"
            action = nearby_named_action(text, m.start(), close, fs)
        elif "accelerator" in name:
            found = _strings_in(text, open_idx, close, lang)
            action = found[0][2] if found else None
        gtk_str, error = gtk_from_key_mask(key, mask_text)
        line = fs.line(key_start)
        if error:
            fs.add_error(raw, error, line, kind, action=action)
        else:
            row = fs.add(gtk_str, "gtk", line, kind, action=action, split=False)
            for r in row:
                r["accel_raw"] = raw
        for s, _, _ in _strings_in(text, open_idx, close, lang):
            fs.consumed.add(s)

    # Gtk.ShortcutTrigger.parse_string("<Control>q|<Control>w")
    for m in TRIGGER_PARSE.finditer(text):
        open_idx = m.end() - 1
        close = srctext.matching(text, open_idx, lang)
        if close == -1:
            continue
        found = _strings_in(text, open_idx, close, lang)
        if not found:
            continue
        s, e, value = found[0]
        fs.consumed.add(s)
        action = nearby_named_action(text, m.start(), close, fs)
        fs.add(value, "gtk", fs.line(s), "gtk-shortcut", action=action)

    # Tables of (action, accels): { "win.new-tab", { "<Primary>t", NULL } }
    for s, e, value in strings:
        if s in fs.consumed or not is_action_name(value):
            continue
        pm = PAIR_AFTER.match(text, e)
        if not pm:
            continue
        open_idx = pm.start(1)
        close = srctext.matching(text, open_idx, lang)
        if close == -1:
            continue
        inner = _strings_in(text, open_idx + 1, close, lang)
        if not inner:
            continue
        rest = text[open_idx + 1:close]
        for i_s, i_e, _ in reversed(inner):
            rest = rest[:i_s - open_idx - 1] + rest[i_e - open_idx - 1:]
        if not TABLE_FILLER.match(rest):
            continue
        parsed = [accel.normalize_all(v, "gtk") for _, _, v in inner]
        if any(r.error for results in parsed for r in results):
            continue
        if not any(_strong(r.seq) for results in parsed for r in results):
            continue
        if any(i_s in fs.consumed for i_s, _, _ in inner):
            continue
        for i_s, i_e, v in inner:
            fs.consumed.add(i_s)
            fs.add(v, "gtk", fs.line(i_s), "gtk-accel-table", action=value)
        fs.consumed.add(s)

    # Any other "<Primary>x" literal: report it with the nearest action name
    for s, e, value in strings:
        if s in fs.consumed or not GTK_MOD_TAG.match(value):
            continue
        fs.consumed.add(s)
        action = None
        for g_start, g_end in srctext.enclosing_groups(text, s, lang, limit=1):
            names = [(abs(ns - s), v) for ns, _, v in srctext.iter_strings(text, lang, g_start, g_end)
                     if ns != s and is_action_name(v)]
            if names:
                action = min(names)[1]
        fs.add(value, "gtk", fs.line(s), "gtk-accel-literal", action=action)


# --- GtkBuilder XML ------------------------------------------------------

def _attrs(el):
    return {a.get("name"): a for a in el.find_children("attribute")}


def _props(el):
    return {p.get("name", "").replace("_", "-"): p for p in el.find_children("property")}


def gmenu_items(fs, el):
    out = []
    after_section = False
    for child in el.children:
        if child.tag == "section":
            items = gmenu_items(fs, child)
            label = _attrs(child).get("label")
            if items or label is not None:
                if out and not out[-1].get("separator"):
                    sep = {"separator": True}
                    if label is not None:
                        sep["label"] = label.text
                    out.append(sep)
                out.extend(items)
                after_section = True
            continue
        if child.tag not in ("submenu", "item"):
            continue
        if after_section and out and not out[-1].get("separator"):
            out.append({"separator": True})
        after_section = False
        attrs = _attrs(child)
        label = clean_label(attrs["label"].text, "gtk") if "label" in attrs else None
        if child.tag == "submenu":
            out.append({"label": label, "line": child.line, "items": gmenu_items(fs, child)})
            continue
        links = {lk.get("name"): lk for lk in child.find_children("link")}
        item = {"label": label, "line": child.line}
        for key in ("action", "target", "hidden-when"):
            if key in attrs:
                item[key.replace("-", "_")] = attrs[key].text
        if "submenu" in links:
            item["items"] = gmenu_items(fs, links["submenu"])
        if "accel" in attrs:
            node = attrs["accel"]
            rows = fs.add(node.text, "gtk", node.line, "gmenu-accel", label=label,
                          action=item.get("action"))
            item["accel"] = rows[0]["accel"] if rows else None
            item["accel_line"] = node.line
        elif item.get("action"):
            fs.add_action(item["action"], label, child.line, "gmenu")
        out.append(item)
    return out


SHORTCUT_ITEM_CLASSES = {"GtkShortcutsShortcut": "gtk-shortcuts-window",
                         "AdwShortcutsItem": "adw-shortcuts-dialog"}
SHORTCUT_GROUP_CLASSES = ("GtkShortcutsGroup", "AdwShortcutsSection", "GtkShortcutsSection")


def _context_of(el):
    for anc in el.ancestors():
        if anc.tag == "object" and anc.get("class") in SHORTCUT_GROUP_CLASSES:
            props = _props(anc)
            for key in ("title", "section-name"):
                if key in props and props[key].text:
                    return props[key].text
    return None


def scan_builder(fs, root):
    for menu in root.iter("menu"):
        fs.add_menu({"line": menu.line, "kind": "gmenu", "id": menu.get("id"),
                     "items": gmenu_items(fs, menu)})
    for obj in root.iter("object"):
        cls = obj.get("class")
        props = _props(obj)
        if cls in SHORTCUT_ITEM_CLASSES:
            kind = SHORTCUT_ITEM_CLASSES[cls]
            title = props["title"].text if "title" in props else None
            action = props["action-name"].text if "action-name" in props else None
            context = _context_of(obj)
            if "accelerator" in props and props["accelerator"].text:
                node = props["accelerator"]
                add_shortcut_label(fs, node.text, node.line, kind, title, action, context)
            elif action:
                fs.add_action(action, title, obj.line, kind, context)
        elif cls == "GtkShortcut" and "trigger" in props:
            node = props["trigger"]
            action = action_from_trigger_value(props["action"].text) if "action" in props else None
            fs.add(node.text, "gtk", node.line, "gtk-shortcut", action=action)
        for acc in obj.find_children("accelerator"):
            key = acc.get("key")
            if not key:
                continue
            mask = acc.get("modifiers", "0")
            raw = f"key={key} modifiers={mask}" if acc.get("modifiers") else f"key={key}"
            label = clean_label(props["label"].text, "gtk") if "label" in props else None
            action = props["action-name"].text if "action-name" in props else acc.get("signal")
            gtk_str, error = gtk_from_key_mask(key, mask.replace("|", " | "))
            if error:
                fs.add_error(raw, error, acc.line, "gtk-builder-accelerator", label, action)
            else:
                for row in fs.add(gtk_str, "gtk", acc.line, "gtk-builder-accelerator",
                                  label=label, action=action, split=False):
                    row["accel_raw"] = raw


# --- Blueprint -----------------------------------------------------------

def _blp_type(node):
    return (node.type or "").split(".")[-1]


def blp_menu_items(fs, node, lines):
    out = []
    after_section = False
    for child in node.children:
        ctype = child.type if isinstance(child, blueprint.ShortItem) else _blp_type(child)
        if ctype == "section":
            items = blp_menu_items(fs, child, lines)
            if items:
                if out and not out[-1].get("separator"):
                    sep = {"separator": True}
                    if child.prop_string("label"):
                        sep["label"] = child.prop_string("label")
                    out.append(sep)
                out.extend(items)
                after_section = True
            continue
        if ctype not in ("submenu", "item", "item-short"):
            continue
        if after_section and out and not out[-1].get("separator"):
            out.append({"separator": True})
        after_section = False
        line = lines.line(child.pos)
        if ctype == "item-short":
            args = [t.value for t in child.args]
            item = {"label": clean_label(args[0], "gtk") if args else None, "line": line}
            if len(args) > 1:
                item["action"] = args[1]
                fs.add_action(args[1], item["label"], line, "gmenu")
            out.append(item)
            continue
        label = child.prop_string("label")
        label = clean_label(label, "gtk") if label else None
        if ctype == "submenu":
            out.append({"label": label, "line": line, "items": blp_menu_items(fs, child, lines)})
            continue
        item = {"label": label, "line": line}
        for key in ("action", "target", "hidden-when"):
            value = child.prop_string(key)
            if value is not None:
                item[key.replace("-", "_")] = value
        if child.prop_string("accel"):
            rows = fs.add(child.prop_string("accel"), "gtk", lines.line(child.prop_pos("accel")),
                          "gmenu-accel", label=label, action=item.get("action"))
            item["accel"] = rows[0]["accel"] if rows else None
            item["accel_line"] = lines.line(child.prop_pos("accel"))
        elif item.get("action"):
            fs.add_action(item["action"], label, line, "gmenu")
        out.append(item)
    return out


def _blp_context(node):
    for anc in node.ancestors():
        if _blp_type(anc) in ("ShortcutsGroup", "ShortcutsSection") and anc.prop_string("title"):
            return anc.prop_string("title")
    return None


def scan_blueprint(fs):
    root, lines = blueprint.parse(fs.text)
    for node in blueprint.walk(root):
        if isinstance(node, blueprint.ShortItem) or node is root:
            continue
        ntype = _blp_type(node)
        if ntype == "menu":
            fs.add_menu({"line": lines.line(node.pos), "kind": "gmenu", "id": node.ident,
                         "items": blp_menu_items(fs, node, lines)})
        elif ntype in ("ShortcutsItem", "ShortcutsShortcut"):
            kind = "adw-shortcuts-dialog" if ntype == "ShortcutsItem" else "gtk-shortcuts-window"
            title = node.prop_string("title")
            action = node.prop_string("action-name")
            context = _blp_context(node)
            accel_text = node.prop_string("accelerator")
            if accel_text:
                add_shortcut_label(fs, accel_text, lines.line(node.prop_pos("accelerator")),
                                   kind, title, action, context)
            elif action:
                fs.add_action(action, title, lines.line(node.pos), kind, context)
        elif ntype == "Shortcut" and node.prop_string("trigger"):
            fs.add(node.prop_string("trigger"), "gtk", lines.line(node.prop_pos("trigger")),
                   "gtk-shortcut", action=action_from_trigger_value(node.prop_string("action")))
