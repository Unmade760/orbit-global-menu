"""Generate mtools/data/standard_keys.json from upstream source.

Shortcuts that code names instead of spelling out (QKeySequence::Copy,
KStandardAction::save, an Electron role) take their keys from these tables.
Every entry records the file and line it came from, and the file records the
commit of each source, so a mapping can cite the table the same way it cites
app code.

Run: python3 -m mtools.gen_tables [--sources DIR]
The sources are sparse clones made with bin/fetch-source (see README.md).
"""

import argparse
import json
import re
import subprocess
from pathlib import Path

from . import accel

SOURCES_ROOT = "/home/ravi/fildem-work/sources"
OUT = Path(__file__).resolve().parent / "data" / "standard_keys.json"

FILES = {
    "qtbase": ["src/gui/kernel/qplatformtheme.cpp"],
    "kconfig": ["src/gui/kstandardshortcut.cpp", "src/gui/kstandardactions_p.h",
                "src/gui/kstandardactions.h"],
    "kconfigwidgets": ["src/kstandardaction_p.h", "src/kstandardaction.cpp"],
    "electron": ["shell/browser/api/electron_api_menu_roles.cc"],
}

LINUX_DEFINES = {"Q_OS_LINUX": True, "Q_OS_UNIX": True}
LINUX_BUILDFLAGS = {"IS_LINUX": True, "IS_POSIX": True}


def line_of(text, offset):
    return text.count("\n", 0, offset) + 1


def preprocess(text):
    """Blank the lines a Linux build drops, keeping line numbers.

    Handles #if / #ifdef / #ifndef / #elif / #else / #endif over
    defined(Q_OS_*) with !, && and ||; any other macro counts as undefined.
    """
    out, stack = [], []  # stack of (branch_taken, currently_active)

    def evaluate(expr):
        expr = re.sub(r"BUILDFLAG\s*\(\s*(\w+)\s*\)", lambda m: str(LINUX_BUILDFLAGS.get(m.group(1), False)), expr)
        expr = re.sub(r"defined\s*\(\s*(\w+)\s*\)", lambda m: str(LINUX_DEFINES.get(m.group(1), False)), expr)
        expr = re.sub(r"defined\s+(\w+)", lambda m: str(LINUX_DEFINES.get(m.group(1), False)), expr)
        expr = re.sub(r"\b(?!True\b|False\b)\w+\s*\([^()]*\)", "False", expr)
        expr = expr.replace("&&", " and ").replace("||", " or ")
        expr = re.sub(r"!(?!=)", " not ", expr)
        expr = re.sub(r"\b(?!True\b|False\b|and\b|or\b|not\b)[A-Za-z_]\w*\b", "False", expr)
        if not re.fullmatch(r"[\sA-Za-z()]*", expr):
            return False
        return bool(eval(expr, {"__builtins__": {}}))  # noqa: S307, only True/False/and/or/not

    def active():
        return all(a for _, a in stack)

    for line in text.split("\n"):
        stripped = line.strip()
        m = re.match(r"#\s*(if|ifdef|ifndef|elif|else|endif)\b(.*)", stripped)
        if m:
            kind, rest = m.group(1), m.group(2).strip()
            if kind == "if":
                value = evaluate(rest)
                stack.append((value, value))
            elif kind == "ifdef":
                value = LINUX_DEFINES.get(rest, False)
                stack.append((value, value))
            elif kind == "ifndef":
                value = not LINUX_DEFINES.get(rest, False)
                stack.append((value, value))
            elif kind == "elif" and stack:
                taken, _ = stack[-1]
                value = not taken and evaluate(rest)
                stack[-1] = (taken or value, value)
            elif kind == "else" and stack:
                taken, _ = stack[-1]
                stack[-1] = (True, not taken)
            elif kind == "endif" and stack:
                stack.pop()
            out.append("")
            continue
        out.append(line if active() else "")
    return "\n".join(out)


def entry(raw, dialect, file, line):
    result = accel.normalize(raw, dialect)
    item = {"raw": raw, "accel": result.accel, "file": file, "line": line}
    if result.error:
        item["error"] = result.error
    return item


def strip_mnemonic(label):
    return re.sub(r"&(?!&)", "", label).replace("&&", "&")


# --- Qt: QPlatformThemePrivate::keyBindings[] ----------------------------

SCHEMES = {"gnome": {"KB_Gnome", "KB_X11", "KB_All"}, "kde": {"KB_KDE", "KB_X11", "KB_All"}}


def qt_standard_keys(src):
    file = FILES["qtbase"][0]
    text = (src / "qtbase" / file).read_text()
    rows = re.finditer(
        r"\{QKeySequence::(\w+),\s*(\d+),\s*([^,]+?),\s*([^}]+?)\}", text)
    out = {}
    for m in rows:
        key, priority, seq, platforms = m.group(1), int(m.group(2)), m.group(3).strip(), m.group(4)
        flags = {p.strip() for p in platforms.split("|")}
        line = line_of(text, m.start())
        for scheme, accepted in SCHEMES.items():
            lst = out.setdefault(key, {}).setdefault(scheme, [])
            if flags & accepted:
                item = entry(seq, "qt", file, line)
                # QPlatformTheme::keyBindings(): priority > 0 goes first
                if priority > 0:
                    lst.insert(0, item)
                else:
                    lst.append(item)
    return out


# --- KDE: KStandardShortcut, KStandardAction ------------------------------

def _balanced(text, start):
    """Index right after the brace block that opens at text[start] == '{'."""
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return i + 1
    raise ValueError("unbalanced braces")


def kstandard_shortcuts(src):
    file = FILES["kconfig"][0]
    raw_text = (src / "kconfig" / file).read_text()
    text = preprocess(raw_text)
    macros = {}
    for m in re.finditer(r"#define\s+(\w+)\(x\)\s+QKeySequence\(QKeyCombination\(([^)]*)\)\)", raw_text):
        macros[m.group(1)] = m.group(2)  # "Qt::CTRL | Qt::Key_##x"
    out = {}
    for m in re.finditer(
            r"\{\s*(\w+),\s*\"([^\"]*)\",\s*QT_TRANSLATE_NOOP3\(\"KStandardShortcut\",\s*\"([^\"]*)\",\s*\"[^\"]*\"\),\s*QList<QKeySequence>\s*\{",
            text):
        start = m.end() - 1
        body = text[start + 1:_balanced(text, start) - 1]
        line = line_of(text, m.start())
        shortcuts = []
        for call in re.finditer(r"\b(\w+)\((\w+)\)|((?:Qt::\w+\s*\|\s*)*Qt::Key_\w+)", body):
            if call.group(1) in macros:
                raw = f"{call.group(1)}({call.group(2)})"
                expr = macros[call.group(1)].replace("##x", call.group(2))
            elif call.group(3):
                raw = expr = call.group(3)
            else:
                continue
            item = entry(expr, "qt", file, line_of(text, start + 1 + call.start()))
            item["raw"] = raw
            shortcuts.append(item)
        out[m.group(1)] = {"name": m.group(2), "label": m.group(3), "shortcuts": shortcuts,
                           "file": file, "line": line}
    return out


def kstandard_shortcut_functions(src):
    """Accessor name to enum name: `const QList<QKeySequence> &openNew()
    { return shortcut(New); }` in kstandardshortcut.cpp."""
    text = (src / "kconfig" / FILES["kconfig"][0]).read_text()
    out = {}
    for m in re.finditer(
            r"const\s+QList<QKeySequence>\s*&(\w+)\(\)\s*\{\s*return\s+shortcut\((\w+)\);\s*\}", text):
        out[m.group(1)] = m.group(2)
    return dict(sorted(out.items()))


def kstandard_actions(src):
    """KStandardAction ids, their action names, labels and shortcut ids.

    KF6 has two copies of the table: KStandardAction (kconfigwidgets) and
    KStandardActions (kconfig). Both are read; they must agree.
    """
    actions, functions = {}, {}
    for repo, file in (("kconfigwidgets", "src/kstandardaction_p.h"),
                       ("kconfig", "src/gui/kstandardactions_p.h")):
        text = (src / repo / file).read_text()
        for m in re.finditer(
                r"\{\s*(\w+),\s*KStandardShortcut::(\w+),\s*u\"([^\"]*)\",\s*(?:kli18n|QT_TRANSLATE_NOOP)\((?:\"KStandardActions\",\s*)?\"([^\"]*)\"",
                text):
            record = {"shortcut": m.group(2), "action_name": m.group(3),
                      "label": strip_mnemonic(m.group(4)), "file": file,
                      "line": line_of(text, m.start()), "source": repo}
            if m.group(1) in actions:
                prev = actions[m.group(1)]
                if (prev["shortcut"], prev["action_name"]) != (record["shortcut"], record["action_name"]):
                    raise ValueError(f"KStandardAction tables disagree on {m.group(1)}")
                continue
            actions[m.group(1)] = record
    for repo, file in (("kconfigwidgets", "src/kstandardaction.cpp"),
                       ("kconfig", "src/gui/kstandardactions.h")):
        text = (src / repo / file).read_text()
        for m in re.finditer(r"\b(\w+)\s*\([^;{)]*\)\s*\{", text):
            body_end = _balanced(text, m.end() - 1)
            body = text[m.end():body_end]
            c = re.search(r"(?:\bcreate|_k_createInternal)\(\s*(\w+)\s*,|buildAutomaticAction\(\s*\w+\s*,\s*(\w+)", body)
            if not c:
                continue
            ident = c.group(1) or c.group(2)
            if ident in actions and m.group(1) not in ("create", "_k_createInternal", "buildAutomaticAction"):
                functions.setdefault(m.group(1), ident)
    return actions, functions


# --- Electron: kRoles[] ---------------------------------------------------

ELECTRON_FLAGS = {"kIsMac": False, "kIsWin": False, "kIsLinux": True}


def resolve_cxx_ternary(expr):
    """Evaluate `cond ? "a" : "b"` for Linux; plain literals pass through."""
    expr = expr.strip()
    m = re.fullmatch(r"(.+?)\?\s*(\S.*?)\s*:\s*(\S.*)", expr, re.S)
    if m:
        cond = m.group(1)
        for name, value in ELECTRON_FLAGS.items():
            cond = cond.replace(name, str(value))
        cond = cond.replace("||", " or ").replace("&&", " and ").replace("!", " not ")
        if not re.fullmatch(r"[\sA-Za-z()]*", cond):
            raise ValueError(f"cannot evaluate {m.group(1)!r}")
        chosen = m.group(2) if eval(cond, {"__builtins__": {}}) else m.group(3)  # noqa: S307
        return resolve_cxx_ternary(chosen)
    lit = re.fullmatch(r'u?"([^"]*)"', expr)
    if lit:
        return lit.group(1)
    if expr == "nullptr":
        return None
    return expr


def _split_top(body):
    parts, depth, cur, in_str = [], 0, "", False
    for ch in body:
        if ch == '"':
            in_str = not in_str
        if not in_str:
            if ch in "({[":
                depth += 1
            elif ch in ")}]":
                depth -= 1
            elif ch == "," and depth == 0:
                parts.append(cur)
                cur = ""
                continue
        cur += ch
    if cur.strip():
        parts.append(cur)
    return [p.strip() for p in parts]


def electron_roles(src):
    file = FILES["electron"][0]
    text = (src / "electron" / file).read_text()
    table_start = text.index("kRoles[] = {")
    table_end = _balanced(text, text.index("{", table_start))
    roles = {}
    for m in re.finditer(r"\{\s*\"(\w+)\",", text[table_start:table_end]):
        start = table_start + m.start()
        body = text[start + 1:_balanced(text, start) - 1]
        fields = _split_top(body)
        role_id = resolve_cxx_ternary(fields[0])
        label = resolve_cxx_ternary(fields[1])
        accel_raw = resolve_cxx_ternary(fields[2])
        action = resolve_cxx_ternary(fields[3]) if len(fields) > 3 else "Action::kNone"
        line = line_of(text, start)
        item = {"label": label, "accel_raw": accel_raw or None, "accel": None,
                "linux": action != "Action::kNone", "file": file, "line": line}
        if accel_raw:
            result = accel.normalize(accel_raw, "electron")
            item["accel"] = result.accel
            if result.error:
                item["error"] = result.error
        roles[role_id] = item
    # Labels computed in Role::Label() when the table has nullptr
    label_fn = text[text.index("Role::Label() const"):]
    label_fn = label_fn[:_balanced(label_fn, label_fn.index("{"))]
    for role_id, item in roles.items():
        if item["label"] is not None:
            continue
        block = re.search(rf'role == "{role_id}"\)(.*?)(?=if \(role ==|return \{{\}};)', label_fn, re.S)
        if not block:
            continue
        for ret in re.finditer(r"return\s+([^;]+);", block.group(1)):
            value = resolve_cxx_ternary(ret.group(1))
            if value is not None and not value.startswith("base::"):
                item["label"] = value
                break
    return roles


def electron_submenus(src):
    """Role lists of DefaultSubmenu() for Linux: None marks a separator."""
    file = FILES["electron"][0]
    text = preprocess((src / "electron" / file).read_text())
    fn = text[text.index("DefaultSubmenu("):]
    fn = fn[:_balanced(fn, fn.index("{"))]
    out = {}
    for m in re.finditer(r'if \(id == "(\w+)"\)\s*(\{?)', fn):
        start = m.end()
        if m.group(2):
            block = fn[start - 1:_balanced(fn, start - 1)]
        else:
            block = fn[start:fn.index(";", start) + 1]
        # Drop the macOS branches: `if (kIsMac) X; else Y;` and `if (kIsMac) {..} else {..}`
        block = re.sub(r"if \(kIsMac\)\s*\{.*?\}\s*else\s*\{(.*?)\}", r"\1", block, flags=re.S)
        block = re.sub(r"if \(kIsMac\)\s*[^;]*;\s*else\s*([^;]*;)", r"\1", block, flags=re.S)
        block = re.sub(r"if \(kIsMac\)\s*[^;{]*;", "", block, flags=re.S)
        items = []
        for call in re.finditer(r'\.(Role|Separator)\(([^)]*)\)', block):
            if call.group(1) == "Separator":
                items.append(None)
            else:
                items.append(resolve_cxx_ternary(call.group(2)))
        out[m.group(1)] = {"roles": items, "file": file, "line": line_of(text, text.index("DefaultSubmenu(")) + fn.count("\n", 0, m.start())}
    return out


def commit_of(repo):
    return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()


def url_of(repo):
    return subprocess.run(["git", "-C", str(repo), "remote", "get-url", "origin"],
                          capture_output=True, text=True, check=True).stdout.strip()


def generate(sources_root, out_path):
    src = Path(sources_root)
    actions, functions = kstandard_actions(src)
    data = {
        "format": 1,
        "generated_by": "python3 -m mtools.gen_tables",
        "sources": {name: {"url": url_of(src / name), "commit": commit_of(src / name),
                           "files": files} for name, files in FILES.items()},
        "qt_standard_keys": qt_standard_keys(src),
        "kstandard_shortcuts": kstandard_shortcuts(src),
        "kstandard_shortcut_functions": kstandard_shortcut_functions(src),
        "kstandard_actions": actions,
        "kstandard_action_functions": dict(sorted(functions.items())),
        "electron_roles": electron_roles(src),
        "electron_submenus": electron_submenus(src),
    }
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
    return data


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sources", default=SOURCES_ROOT)
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args(argv)
    data = generate(args.sources, args.out)
    print(json.dumps({key: len(value) for key, value in data.items() if isinstance(value, dict)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
