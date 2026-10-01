"""JavaScript and TypeScript (Electron menus, VS Code keybindings, CodeMirror,
key strings) and JSON keymaps (VS Code, Zed, Sublime Text)."""

import json
import re
from pathlib import Path

from . import jsobj, srctext, tables
from .srctext import clean_label

MAC_COND = re.compile(r"mac|darwin|osx|apple|\bios\b", re.I)
WIN_COND = re.compile(r"win32|windows|isWin\b|isWindows", re.I)
LINUX_COND = re.compile(r"linux", re.I)
# The Linux desktop build is not a browser build: isWeb and friends are false there
FALSE_COND = re.compile(r"\b(?:isWeb|isFirefox|isSafari|isChrome|isEdge|isIOS|isMobile|isWebKit|isAndroid)\b")
TRUE_COND = re.compile(r"\b(?:isNative|isElectron|isDesktop)\b")
CONST_STR = re.compile(r"\b(?:export\s+)?const\s+([A-Za-z_$][\w$]*)\s*(?::\s*[\w.<>\[\]| ]+)?=\s*(['\"`])([^'\"`\n]+)\2")
STATIC_STR = re.compile(r"\bstatic\s+(?:readonly\s+)?(\w+)\s*(?::\s*\w+)?\s*=\s*(['\"`])([^'\"`\n]+)\2")
CLASS_NAME = re.compile(r"\bclass\s+(\w+)")
LOCALIZE_LAST = {"localize", "localize2", "localizeWithPath", "nls", "i18nc", "pgettext", "C_"}

JS_KEY_LITERAL = re.compile(
    r"^(?:(?:\$?mod|ctrl|control|cmd|command|cmdorctrl|commandorcontrol|alt|option|shift|meta|super)\s*\+\s*)+"
    r"(?:[A-Za-z0-9]|F\d{1,2}|Key[A-Z]|Digit\d|[^\sA-Za-z0-9]|enter|return|escape|esc|tab|space|backspace"
    r"|delete|del|up|down|left|right|home|end|pageup|pagedown|insert|plus|minus"
    r"|arrow(?:up|down|left|right))$", re.I)
ELECTRON_HINT = re.compile(r"cmdorctrl|commandorcontrol", re.I)
MAC_ONLY_MOD = re.compile(r"(?:^|\+)\s*(?:cmd|command|option)\s*\+", re.I)

CM_KEYS = {"arrowup": "Up", "arrowdown": "Down", "arrowleft": "Left", "arrowright": "Right",
           " ": "Space", "space": "Space", "esc": "Escape"}


# --- JS structure helpers ------------------------------------------------

class Link:
    __slots__ = ("node", "key", "parent")

    def __init__(self, node, key, parent):
        self.node = node
        self.key = key
        self.parent = parent


def _split_top_commas(items):
    parts, cur = [], []
    for it in items:
        if isinstance(it, jsobj.Tok) and it.type == "punct" and it.value == ",":
            parts.append(cur)
            cur = []
        else:
            cur.append(it)
    parts.append(cur)
    return parts


def resolve(items, text):
    """Pick the Linux branch of `cond ? a : b` at the top level of `items`."""
    q = None
    for i, it in enumerate(items):
        if isinstance(it, jsobj.Tok) and it.type == "punct" and it.value == "?":
            q = i
            break
    if q is None or q == 0:
        return items
    depth, c = 0, None
    for j in range(q + 1, len(items)):
        it = items[j]
        if isinstance(it, jsobj.Tok) and it.type == "punct":
            if it.value == "?":
                depth += 1
            elif it.value == ":":
                if depth == 0:
                    c = j
                    break
                depth -= 1
    if c is None:
        return items
    cond = text[items[0].start:items[q - 1].end]
    negated = cond.strip().startswith("!") or "!=" in cond
    then_items, else_items = items[q + 1:c], items[c + 1:]
    if MAC_COND.search(cond) or WIN_COND.search(cond) or FALSE_COND.search(cond):
        chosen = then_items if negated else else_items
    elif LINUX_COND.search(cond) or TRUE_COND.search(cond):
        chosen = else_items if negated else then_items
    else:
        chosen = then_items
    return resolve(chosen, text)


def resolved_children(node, text):
    """(key, item) pairs under a node, ternaries resolved for Linux."""
    if isinstance(node, jsobj.Obj):
        for key, value, _ in node.props:
            for it in resolve(value.items, text):
                yield key, it
    elif isinstance(node, jsobj.Arr):
        for value in node.elements:
            for it in resolve(value.items, text):
                yield None, it
    elif isinstance(node, jsobj.Group):
        for part in _split_top_commas(node.items):
            for it in resolve(part, text):
                yield None, it
    elif isinstance(node, jsobj.Block):
        for it in node.items:
            yield None, it


def walk(items, text):
    """(node, Link to parent) for every node, depth first, in source order."""
    stack = [(it, None) for it in reversed(items)]
    while stack:
        item, link = stack.pop()
        if not isinstance(item, jsobj.Node):
            continue
        yield item, link
        children = list(resolved_children(item, text))
        for key, child in reversed(children):
            stack.append((child, Link(item, key, link)))


def value_items(obj, key, text):
    value = obj.get(key)
    return resolve(value.items, text) if value is not None else []


def single(items):
    return items[0] if len(items) == 1 else None


def str_value(obj, key, text):
    it = single(value_items(obj, key, text))
    return it.value if isinstance(it, jsobj.Tok) and it.type == "str" else None


def str_tok(obj, key, text):
    it = single(value_items(obj, key, text))
    return it if isinstance(it, jsobj.Tok) and it.type == "str" else None


def js_label(items, text):
    """User-visible text of a label expression: 'Save', t('Save'), localize('k', 'Save')."""
    callee = None
    strs = []
    for it in items:
        if isinstance(it, jsobj.Tok) and it.type == "str":
            strs.append(it.value)
        elif isinstance(it, jsobj.Tok) and it.type == "id":
            callee = it.value
        elif isinstance(it, jsobj.Group):
            strs.extend(t.value for t in jsobj.strings(jsobj.Value(it.items)))
        elif isinstance(it, jsobj.Obj) and it.get("original") is not None:
            return js_label(it.get("original").items, text)
        elif isinstance(it, jsobj.Obj) and it.get("value") is not None:
            return js_label(it.get("value").items, text)
    if not strs:
        return None
    value = strs[-1] if callee in LOCALIZE_LAST and len(strs) > 1 else strs[0]
    style = "vscode" if "&&" in value else "electron"
    return clean_label(value, style)


def tokens_in(node):
    """Every token start offset inside a node."""
    out = []
    stack = [node]
    while stack:
        n = stack.pop()
        if isinstance(n, jsobj.Tok):
            out.append(n.start)
        elif isinstance(n, jsobj.Node):
            stack.extend(jsobj.children(n))
    return out


# --- Electron menus ------------------------------------------------------

SUBMENU_ROLES = {"appmenu", "filemenu", "editmenu", "viewmenu", "windowmenu", "sharemenu"}


def _role_items(role, line):
    items = []
    for r in tables.electron_submenu(role) or []:
        if r is None:
            items.append({"separator": True})
            continue
        info = tables.electron_role(r) or {}
        if not info.get("linux", True):
            continue
        item = {"label": info.get("label"), "role": r, "line": line}
        if info.get("accel"):
            item["accel"] = info["accel"]
            item["accel_line"] = line
        items.append(item)
    return items


def _item_action(obj, text):
    for key in ("id", "command"):
        value = str_value(obj, key, text)
        if value:
            return value
    it = single(value_items(obj, "click", text))
    if isinstance(it, jsobj.Tok) and it.type == "id":
        return it.value
    return None


def _is_menu_item(obj, text):
    keys = set(obj.keys())
    if "accelerator" in keys:
        return True
    role = str_value(obj, "role", text)
    return bool(role and tables.electron_role(role) is not None)


def electron_item(fs, obj, text, taken):
    """Rows for one menu item object; returns the item for the menu tree."""
    line = fs.line(obj.start)
    label_items = value_items(obj, "label", text)
    label = js_label(label_items, text) if label_items else None
    role = str_value(obj, "role", text)
    role_info = tables.electron_role(role) if role else None
    action = _item_action(obj, text)
    item = {"label": label or (role_info or {}).get("label"), "line": line}
    if role:
        item["role"] = role
    if action:
        item["action"] = action
    value = obj.get("accelerator")
    if value is not None:
        taken.append((value.start, value.end))
        chosen = resolve(value.items, text)
        tok = single(chosen)
        if isinstance(tok, jsobj.Tok) and tok.type == "str":
            rows = fs.add(tok.value, "electron", fs.line(tok.start), "electron-menu",
                          label=item["label"], action=action or role)
            item["accel"] = next((r["accel"] for r in rows if r["accel"]), None)
            if item["accel"]:
                item["accel_line"] = fs.line(tok.start)
        elif chosen and not (isinstance(tok, jsobj.Tok) and tok.value in ("undefined", "null")):
            raw = re.sub(r"\s+", " ", text[chosen[0].start:chosen[-1].end])
            fs.add_error(raw, "computed accelerator, not a literal in the source", fs.line(chosen[0].start),
                         "electron-menu", label=item["label"], action=action or role)
    elif role_info and role_info.get("accel") and role_info.get("linux"):
        fs.add_accel(f"role: {role}", role_info["accel"], line, "electron-role", label=item["label"],
                     action=role, via={"source": "electron", "file": role_info["file"],
                                       "line": role_info["line"]})
        item["accel"] = role_info["accel"]
        item["accel_line"] = line
    if role and role.lower() in SUBMENU_ROLES and obj.get("submenu") is None:
        item["items"] = _role_items(role, line)
        for sub in item["items"]:
            if sub.get("accel"):
                info = tables.electron_role(sub["role"])
                fs.add_accel(f"role: {role} > {sub['role']}", sub["accel"], line, "electron-role",
                             label=sub["label"], action=sub["role"],
                             via={"source": "electron", "file": info["file"], "line": info["line"]})
    return item


def electron_menu_items(fs, arr, text, items_by_obj):
    out = []
    for key, it in resolved_children(arr, text):
        if isinstance(it, jsobj.Tok) and it.value == "...":
            continue
        if isinstance(it, jsobj.Group):
            for _, inner in resolved_children(it, text):
                if isinstance(inner, jsobj.Arr):
                    out.extend(electron_menu_items(fs, inner, text, items_by_obj))
            continue
        if not isinstance(it, jsobj.Obj):
            continue
        if str_value(it, "type", text) == "separator":
            out.append({"separator": True})
            continue
        item = dict(items_by_obj.get(id(it)) or electron_item_plain(fs, it, text))
        sub = single(value_items(it, "submenu", text))
        if isinstance(sub, jsobj.Arr):
            item["items"] = electron_menu_items(fs, sub, text, items_by_obj)
        out.append(item)
    return out


def electron_item_plain(fs, obj, text):
    label_items = value_items(obj, "label", text)
    item = {"label": js_label(label_items, text) if label_items else None, "line": fs.line(obj.start)}
    action = _item_action(obj, text)
    if action:
        item["action"] = action
    return item


def _is_template(arr, link, text):
    if link is not None and link.key == "submenu":
        return False
    found = False
    for _, it in resolved_children(arr, text):
        if isinstance(it, jsobj.Obj):
            role = (str_value(it, "role", text) or "").lower()
            if it.get("submenu") is not None or role in SUBMENU_ROLES:
                found = True
            elif not ({"label", "role", "type", "click", "accelerator"} & set(it.keys())):
                return False
    return found


# --- VS Code keybinding registrations -------------------------------------

def _has_keymod(value, text):
    return value is not None and re.search(r"\bKey(?:Mod|Code|Chord)\b", text[value.start:value.end]) is not None


def _id_of(obj, text):
    """(command id, None) for id: 'x'; (None, "NAME") for id: NAME or Class.ID."""
    value = str_value(obj, "id", text)
    if value:
        return value, None
    items = value_items(obj, "id", text)
    if items and all(isinstance(t, jsobj.Tok) and (t.type == "id" or t.value == ".") for t in items):
        return None, "".join(t.value for t in items)
    return None, None


def collect_constants(fs):
    """String constants a command id can be named by: const X = '...', static ID = '...'."""
    for m in CONST_STR.finditer(fs.text):
        fs.constants.setdefault(m.group(1), m.group(3))
    classes = [(m.start(), m.group(1)) for m in CLASS_NAME.finditer(fs.text)]
    for m in STATIC_STR.finditer(fs.text):
        owner = [name for pos, name in classes if pos < m.start()]
        if owner:
            fs.constants.setdefault(f"{owner[-1]}.{m.group(1)}", m.group(3))


def vscode_keymod(fs, node, link, text, taken):
    if link is not None and link.key in ("linux", "mac", "win"):
        return
    target = node
    linux = single(value_items(node, "linux", text))
    if isinstance(linux, jsobj.Obj) and (linux.get("primary") is not None or linux.get("secondary") is not None):
        target = linux
    exprs = []
    primary = target.get("primary")
    if primary is not None:
        exprs.append(primary)
    secondary = target.get("secondary")
    if secondary is not None:
        arr = single(resolve(secondary.items, text))
        if isinstance(arr, jsobj.Arr):
            exprs.extend(arr.elements)
        else:
            exprs.append(secondary)
    action, ref = _id_of(node, text)
    label = None
    up = link
    while up is not None and action is None and ref is None:
        if isinstance(up.node, jsobj.Obj) and up.key in ("keybinding", "kbOpts"):
            action, ref = _id_of(up.node, text)
            title = value_items(up.node, "title", text) or value_items(up.node, "label", text)
            label = js_label(title, text) if title else None
            break
        up = up.parent
    if action is None and ref is not None:
        action = fs.constants.get(ref)
    when = str_value(node, "when", text)
    taken.append((node.start, node.end))
    for expr in exprs:
        items = resolve(expr.items, text)
        if not items:
            continue
        raw = re.sub(r"\s+", " ", text[items[0].start:items[-1].end]).strip()
        if raw in ("0", "undefined", "null") or not re.search(r"Key(?:Mod|Code|Chord)", raw):
            continue
        rows = fs.add(raw, "vscode", fs.line(items[0].start), "vscode-keymod", label=label, action=action,
                      context=when, split=False)
        if action is None and ref is not None:
            for row in rows:
                row["action_ref"] = ref


# --- CodeMirror, Zed and other dash-joined key specs -----------------------

def dash_to_text(spec, mod_is="ctrl"):
    """"Mod-Shift-z" or "ctrl-shift-p" to "Ctrl+Shift+z"; None for mac-only specs."""
    chords = []
    for chord in spec.split(" "):
        if not chord:
            continue
        parts = []
        rest = chord
        while True:
            m = re.match(r"^(shift|cmd|ctrl|control|alt|mod|meta|super|secondary|c|s|a|m|fn)-(?=.)", rest, re.I)
            if not m:
                break
            name = m.group(1).lower()
            if name in ("cmd", "fn") or (name in ("meta", "m") and mod_is == "ctrl"):
                return None
            parts.append({"mod": "Ctrl", "secondary": "Ctrl", "c": "Ctrl", "control": "Ctrl",
                          "s": "Shift", "a": "Alt", "meta": "Super", "m": "Super"}.get(name, name.capitalize()))
            rest = rest[m.end():]
        key = CM_KEYS.get(rest.lower(), rest)
        parts.append(key)
        chords.append("+".join(parts))
    return " ".join(chords) if chords else None


def _key_spec(value):
    """Text form of a "Ctrl-Shift-Tab" or "mod+k" key string, or None if it is not one."""
    if not value:
        return None
    value = value.strip()
    if re.match(r"^(?:(?:Shift|Ctrl|Control|Alt|Mod|Meta|Super)-)+\S", value, re.I):
        return dash_to_text(value)
    if JS_KEY_LITERAL.match(value) and not MAC_ONLY_MOD.search("+" + value):
        return literal_to_text(value)
    return None


def literal_to_text(value):
    text = re.sub(r"\$mod", "Ctrl", value, flags=re.I)
    text = re.sub(r"(?i)\bmod\b", "Ctrl", text)
    text = re.sub(r"\bKey([A-Z])\b", r"\1", text)
    text = re.sub(r"\bDigit(\d)\b", r"\1", text)
    text = re.sub(r"(?i)\barrow(up|down|left|right)\b", r"\1", text)
    return text


# --- scanners ------------------------------------------------------------

JS_HINTS = re.compile(r"accelerator|role\s*:|KeyMod|KeyCode|keybinding|\bkey\s*:|\brun\s*:|Mousetrap|hotkeys|"
                      r"tinykeys|mod\+|Mod-|Ctrl-|extraKeys|ctrl\+|Ctrl\+|CmdOrCtrl|CommandOrControl", re.I)


def scan_js(fs):
    text = fs.text
    collect_constants(fs)
    if not JS_HINTS.search(text):
        return
    items = jsobj.parse(text)
    taken = []
    items_by_obj = {}
    arrays = []
    for node, link in walk(items, text):
        if isinstance(node, jsobj.Obj):
            keys = set(node.keys())
            if keys & {"primary", "secondary", "linux"} and (
                    _has_keymod(node.get("primary"), text) or _has_keymod(node.get("secondary"), text)
                    or isinstance(single(value_items(node, "linux", text)), jsobj.Obj)
                    and _has_keymod(node.get("linux"), text)):
                vscode_keymod(fs, node, link, text, taken)
            elif _is_menu_item(node, text):
                items_by_obj[id(node)] = electron_item(fs, node, text, taken)
            elif "key" in keys and "command" in keys:
                tok = str_tok(node, "linux", text) or str_tok(node, "key", text)
                if tok is not None:
                    taken.append((node.start, node.end))
                    fs.add(tok.value, "vscode", fs.line(tok.start), "vscode-keybinding",
                           action=str_value(node, "command", text), context=str_value(node, "when", text))
            elif "key" in keys and keys & {"run", "shift", "preventDefault", "scope"}:
                tok = str_tok(node, "linux", text) or str_tok(node, "key", text)
                spec = dash_to_text(tok.value) if tok is not None else None
                if spec:
                    taken.append((node.start, node.end))
                    run = single(value_items(node, "run", text))
                    action = run.value if isinstance(run, jsobj.Tok) and run.type == "id" else None
                    fs.add(spec, "text", fs.line(tok.start), "codemirror-keymap", action=action,
                           keep_errors=False)
            elif "key" in keys and _key_spec(str_value(node, "key", text)):
                # { key: 'Ctrl-Shift-Tab' } under a named property: Zettlr's default keybindings
                tok = str_tok(node, "key", text)
                spec = _key_spec(tok.value)
                taken.append((node.start, node.end))
                action = str_value(node, "command", text) or str_value(node, "id", text)
                if action is None and link is not None and isinstance(link.node, jsobj.Obj):
                    action = link.key
                fs.add(spec, "text", fs.line(tok.start), "js-keybinding", action=action, keep_errors=False)
            else:
                for key, value, key_tok in node.props:
                    if key_tok.type != "str" or not re.match(r"^(?:(?:Shift|Cmd|Ctrl|Alt|Mod|Meta)-)+.", key or ""):
                        continue
                    spec = dash_to_text(key)
                    if not spec:
                        taken.append((key_tok.start, key_tok.end))
                        continue
                    target = single(resolve(value.items, text))
                    action = target.value if isinstance(target, jsobj.Tok) and target.type in ("id", "str") else None
                    taken.append((key_tok.start, key_tok.end))
                    fs.add(spec, "text", fs.line(key_tok.start), "codemirror-keymap", action=action,
                           keep_errors=False)
        elif isinstance(node, jsobj.Arr):
            arrays.append((node, link))

    for arr, link in arrays:
        if _is_template(arr, link, text):
            for _, it in resolved_children(arr, text):
                if isinstance(it, jsobj.Obj):
                    item = dict(items_by_obj.get(id(it)) or electron_item_plain(fs, it, text))
                    sub = single(value_items(it, "submenu", text))
                    if isinstance(sub, jsobj.Arr):
                        item["items"] = electron_menu_items(fs, sub, text, items_by_obj)
                    if "items" in item:
                        item["kind"] = "electron"
                        fs.add_menu(item)

    blank = srctext.strip_comments(text, "js")
    for s, e, value in srctext.iter_strings(blank, "js"):
        if any(a <= s < b for a, b in taken) or s in fs.consumed:
            continue
        if not JS_KEY_LITERAL.match(value.strip()):
            continue
        value = value.strip()
        action = None
        for g_start, _ in srctext.enclosing_groups(blank, s, "js", limit=1):
            args, _ = srctext.split_args(blank, g_start, "js")
            for i, (a_s, a_e) in enumerate(args):
                if a_s <= s < a_e and i + 1 < len(args):
                    nxt = blank[args[i + 1][0]:args[i + 1][1]].strip()
                    if re.fullmatch(r"[A-Za-z_$][\w$.]*", nxt):
                        action = nxt
        if ELECTRON_HINT.search(value):
            fs.add(value, "electron", fs.line(s), "electron-accel-literal", action=action, keep_errors=False)
        elif MAC_ONLY_MOD.search("+" + value):
            continue
        else:
            fs.add(literal_to_text(value), "text", fs.line(s), "js-key-literal", action=action,
                   keep_errors=False)


def _nls(path):
    nls = Path(path).with_name("package.nls.json")
    try:
        return json.loads(nls.read_text())
    except (OSError, ValueError):
        return {}


def scan_json(fs, path):
    text = fs.text
    if not re.search(r"\"(?:key|keys|bindings)\"\s*:", text):
        return
    items = jsobj.parse(text)
    titles = {}
    nls = None
    for node, _ in walk(items, text):
        if isinstance(node, jsobj.Obj) and "command" in node.keys() and "title" in node.keys():
            cmd, title = str_value(node, "command", text), str_value(node, "title", text)
            if cmd and title:
                titles.setdefault(cmd, title)
    for node, link in walk(items, text):
        if not isinstance(node, jsobj.Obj):
            continue
        keys = set(node.keys())
        if "command" in keys and ("key" in keys or "linux" in keys) and "keys" not in keys:
            tok = str_tok(node, "linux", text) or str_tok(node, "key", text)
            if tok is None:
                continue
            cmd = str_value(node, "command", text)
            title = titles.get(cmd)
            if title and title.startswith("%") and title.endswith("%"):
                nls = _nls(path) if nls is None else nls
                entry = nls.get(title.strip("%"))
                title = entry.get("message") if isinstance(entry, dict) else entry
            fs.add(tok.value, "vscode", fs.line(tok.start), "vscode-keybinding", label=title,
                   action=cmd, context=str_value(node, "when", text))
        elif "keys" in keys and "command" in keys:
            arr = single(value_items(node, "keys", text))
            if not isinstance(arr, jsobj.Arr):
                continue
            toks = [single(v.items) for v in arr.elements]
            if not toks or not all(isinstance(t, jsobj.Tok) and t.type == "str" for t in toks):
                continue
            raw = " ".join(t.value for t in toks)
            fs.add(raw, "vscode", fs.line(toks[0].start), "sublime-keymap",
                   action=str_value(node, "command", text), split=False)
        elif "bindings" in keys:
            bindings = single(value_items(node, "bindings", text))
            if not isinstance(bindings, jsobj.Obj):
                continue
            context = str_value(node, "context", text)
            for key, value, key_tok in bindings.props:
                if key_tok.type != "str":
                    continue
                spec = dash_to_text(key, mod_is="zed")
                target = resolve(value.items, text)
                action = None
                first = target[0] if target else None
                if isinstance(first, jsobj.Tok) and first.type == "str":
                    action = first.value
                elif isinstance(first, jsobj.Arr) and first.elements:
                    head = single(first.elements[0].items)
                    action = head.value if isinstance(head, jsobj.Tok) and head.type == "str" else None
                if not spec:
                    continue
                fs.add(spec, "text", fs.line(key_tok.start), "zed-keymap", action=action,
                       context=context, split=False)
