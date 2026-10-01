"""desktop-ids: what a running app is called, read from its source tree.

Global Menu matches a mapping's identifiers against the focused window's
desktop file id, WM class and app name. This reads the .desktop files the
tree installs (resolving meson output names and @VAR@ placeholders), CMake
install rules, AppStream metainfo, Flatpak manifests and Electron packaging
fields, and suggests identifiers from them.
"""

import argparse
import json
import re
from pathlib import Path

from . import xmltree
from .cli import emit, fail
from .extract import git_info, iter_files

DESKTOP_NAME = re.compile(r"^(?P<stem>.+?\.desktop)(?:\.in)*(?:\.cmake|\.template)?(?:\.in)*$")
METAINFO_NAME = re.compile(r"\.(?:metainfo|appdata)\.xml(?:\.in)*$")
DEVEL = re.compile(r"(?:\.(?:Devel|Nightly|Debug|Canary|Development)|[-_](?:dev|devel|nightly|canary|debug))"
                   r"(?:\.desktop)?$", re.I)


def _line_of(text, offset):
    return text.count("\n", 0, offset) + 1


# --- meson ---------------------------------------------------------------

def _meson_file(text):
    """Assignments, .set() calls and .desktop outputs of one meson.build."""
    top, cond, concats, sets, outputs = {}, {}, [], [], []
    depth = 0
    for line in text.split("\n"):
        stripped = line.split("#", 1)[0].strip()
        if re.match(r"^(if|foreach)\b", stripped):
            depth += 1
        elif re.match(r"^(endif|endforeach)\b", stripped):
            depth = max(0, depth - 1)
        m = re.match(r"^(\w+)\s*=\s*'([^']*)'\s*$", stripped)
        if m:
            if depth == 0:
                top.setdefault(m.group(1), m.group(2))
            else:
                cond.setdefault(m.group(1), []).append(m.group(2))
        m = re.match(r"^(\w+)\s*=\s*'([^']*)'\s*\+\s*(\w+)\s*$", stripped)
        if m and depth == 0:
            concats.append((m.group(1), m.group(2), m.group(3)))
        for s in re.finditer(r"\.set(?:_quoted)?\(\s*'(\w+)'\s*,\s*([^,)]+)", stripped):
            sets.append((s.group(1), s.group(2).strip()))
    for m in re.finditer(r"output\s*:\s*('[^']*\.desktop'(?:\s*\.format\([^)]*\))?|\w+\s*\+\s*'\.desktop')", text):
        outputs.append((m.group(1), _line_of(text, m.start()), text[max(0, m.start() - 600):m.end()]))
    return top, cond, concats, sets, outputs


def _is_under(child, parent):
    return parent == Path(".") or child == parent or parent in child.parents


def meson_scan(files):
    """Variables, @VAR@ values and .desktop outputs from every meson.build.

    A meson.build sees the variables of the meson.build files above it (a
    subdir() inherits its parent's scope). A variable assigned only inside
    `if` blocks takes its first non-Devel value, so a development profile
    does not win over the release id.

    Returns (variables {name: (value, file)}, placeholders {NAME: value},
    outputs [(installed name, file, line, text of the call around it)]).
    """
    parsed = {rel: _meson_file(path.read_text(errors="replace")) for path, rel in files}

    def visible(rel):
        here = Path(rel).parent
        chain = sorted((r for r in parsed if _is_under(here, Path(r).parent)),
                       key=lambda r: len(Path(r).parent.parts))
        scope = {}
        for r in chain:
            top, cond, concats, _, _ = parsed[r]
            for name, values in cond.items():
                if name not in top:
                    scope[name] = (next((v for v in values if not DEVEL.search(v)), values[0]), r)
            scope.update({name: (value, r) for name, value in top.items()})
            for name, prefix, var in concats:
                if var in scope:
                    scope[name] = (prefix + scope[var][0], r)
        return scope

    variables, placeholders, outputs = {}, {}, []
    for rel in sorted(parsed, key=lambda r: (len(Path(r).parts), r)):
        scope = visible(rel)
        for name, value in scope.items():
            variables.setdefault(name, value)
        _, _, _, sets, outs = parsed[rel]
        for name, expr in sets:
            value = meson_value(expr, scope)
            if value is not None:
                placeholders.setdefault(name, value)
        for expr, line, context in outs:
            value = meson_value(expr, scope)
            if value:
                outputs.append((value, rel, line, context))
    return variables, placeholders, outputs


def meson_value(expr, variables):
    expr = expr.strip()
    m = re.fullmatch(r"'([^']*)'", expr)
    if m:
        return m.group(1)
    if re.fullmatch(r"\w+", expr) and expr in variables:
        return variables[expr][0]
    m = re.fullmatch(r"'([^']*)'\s*\.format\(\s*([^)]*)\)", expr)
    if m:
        args = [meson_value(a, variables) for a in m.group(2).split(",")]
        if any(a is None for a in args):
            return None
        out = m.group(1)
        for i, a in enumerate(args):
            out = out.replace(f"@{i}@", a)
        return out
    m = re.fullmatch(r"(\w+)\s*\+\s*'([^']*)'", expr)
    if m and m.group(1) in variables:
        return variables[m.group(1)][0] + m.group(2)
    return None


def fill(value, placeholders):
    if value is None:
        return None
    return re.sub(r"@(\w+)@", lambda m: placeholders.get(m.group(1), m.group(0)), value)


# --- .desktop files ----------------------------------------------------------

def read_desktop(text):
    """Keys of the [Desktop Entry] group (untranslated, intltool _Key too)."""
    keys, group = {}, None
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("[") and line.endswith("]"):
            group = line[1:-1]
            continue
        if group != "Desktop Entry" or "=" not in line or line.startswith("#"):
            continue
        key, value = line.split("=", 1)
        key = key.strip().lstrip("_")
        if "[" in key:
            continue
        keys.setdefault(key, value.strip())
    return keys


def exec_name(value):
    if not value:
        return None
    words = [w for w in value.split() if not re.match(r"^(env|\w+=\S*)$", w)]
    if not words:
        return None
    if words[0] == "flatpak":
        return None
    return Path(words[0].strip("\"'")).name or None


# --- scan --------------------------------------------------------------------

def scan(root, include_all=False):
    root = Path(root)
    files = [(p, p.relative_to(root).as_posix()) for p in iter_files(root, include_all)]
    meson_files = [(p, r) for p, r in files if p.name == "meson.build"]
    variables, placeholders, outputs = meson_scan(meson_files)
    placeholder_values = dict(placeholders)
    for name, (value, _) in variables.items():
        placeholder_values.setdefault(name.upper(), value)

    cmake_installs = {}
    for path, rel in files:
        if path.name != "CMakeLists.txt" and not path.name.endswith(".cmake"):
            continue
        text = path.read_text(errors="replace")
        for m in re.finditer(r"([\w.${}/-]*?([\w.-]+\.desktop))\b", text):
            before = text[max(0, m.start() - 200):m.start()]
            if re.search(r"install\s*\((?:[^()]|\([^()]*\))*$", before, re.S) or \
                    re.search(r"configure_file\s*\([^()]*$", before, re.S):
                cmake_installs.setdefault(m.group(2), {"file": rel, "line": _line_of(text, m.start())})

    desktop_files, build, metainfo = [], [], []
    meson_outputs = outputs

    for path, rel in files:
        m = DESKTOP_NAME.match(path.name)
        if not m:
            continue
        text = path.read_text(errors="replace")
        keys = read_desktop(text)
        if "Name" not in keys and "Exec" not in keys:
            continue
        desktop_id = m.group("stem")
        templated = "@" in desktop_id or path.name != desktop_id
        installed_by = None
        if desktop_id in cmake_installs:
            installed_by = cmake_installs[desktop_id]
        # A template is installed under the name its meson.build gives it: the
        # output whose call names this file, else the only output in its tree
        if templated:
            in_tree = [o for o in meson_outputs
                       if rel.startswith(Path(o[1]).parent.as_posix().rstrip(".") + "/")
                       or Path(o[1]).parent.as_posix() == "."]
            named = [o for o in in_tree if path.name in o[3] or path.name.rsplit(".in", 1)[0] in o[3]]
            pick = named[0] if named else (in_tree[0] if len(in_tree) == 1 else None)
            if pick:
                desktop_id = pick[0]
                installed_by = {"file": pick[1], "line": pick[2]}
        if "@" in desktop_id:
            desktop_id = fill(desktop_id, placeholder_values)
        entry = {
            "file": rel,
            "line": 1,
            "desktop_id": desktop_id,
            "name": fill(keys.get("Name"), placeholder_values),
            "startup_wm_class": fill(keys.get("StartupWMClass"), placeholder_values),
            "exec": exec_name(fill(keys.get("Exec"), placeholder_values)),
            "icon": fill(keys.get("Icon"), placeholder_values),
            "no_display": keys.get("NoDisplay", "").lower() == "true",
        }
        if installed_by:
            entry["installed_by"] = installed_by
        desktop_files.append(entry)

    for path, rel in files:
        if not METAINFO_NAME.search(path.name):
            continue
        tree = xmltree.parse(path.read_text(errors="replace"))
        if tree is None:
            continue
        comp = next((c for c in tree.children if c.tag == "component"), None)
        if comp is None:
            continue
        ids = comp.find_children("id")
        names = [n for n in comp.find_children("name") if "xml:lang" not in n.attrs]
        launch = [lc for lc in comp.find_children("launchable") if lc.get("type") == "desktop-id"]
        metainfo.append({
            "file": rel,
            "id": fill(ids[0].text, placeholder_values) if ids else None,
            "name": names[0].text if names else None,
            "launchable": fill(launch[0].text, placeholder_values) if launch else None,
        })

    for path, rel in files:
        if path.suffix not in (".json", ".yml", ".yaml") or path.stat().st_size > 500_000:
            continue
        text = path.read_text(errors="replace")
        if path.name == "package.json":
            try:
                data = json.loads(text)
            except ValueError:
                continue
            for field in ("name", "productName", "desktopName"):
                if isinstance(data.get(field), str):
                    build.append({"file": rel, "kind": "package.json", "field": field, "value": data[field]})
            b = data.get("build") if isinstance(data.get("build"), dict) else {}
            linux = b.get("linux") if isinstance(b.get("linux"), dict) else {}
            desk = linux.get("desktop") if isinstance(linux.get("desktop"), dict) else {}
            desk = desk.get("entry", desk) if isinstance(desk.get("entry", desk), dict) else desk
            for field, value in (("build.appId", b.get("appId")), ("build.productName", b.get("productName")),
                                 ("build.linux.executableName", linux.get("executableName")),
                                 ("build.linux.desktop.StartupWMClass", desk.get("StartupWMClass")),
                                 ("build.linux.desktop.Name", desk.get("Name"))):
                if isinstance(value, str):
                    build.append({"file": rel, "kind": "electron-builder", "field": field, "value": value})
            continue
        if path.name.startswith("electron-builder") and path.suffix in (".yml", ".yaml"):
            for m in re.finditer(r"^\s*(appId|productName|executableName|StartupWMClass)\s*:\s*['\"]?([^'\"\n#]+)",
                                 text, re.M):
                build.append({"file": rel, "kind": "electron-builder", "field": m.group(1),
                              "value": m.group(2).strip()})
            continue
        if path.suffix == ".json" and '"runtime"' in text:
            try:
                data = json.loads(text)
            except ValueError:
                continue
            app_id = data.get("id") or data.get("app-id") if isinstance(data, dict) else None
            if isinstance(app_id, str):
                build.append({"file": rel, "kind": "flatpak", "field": "id", "value": app_id})
        elif path.suffix in (".yml", ".yaml") and re.search(r"^runtime\s*:", text, re.M):
            m = re.search(r"^(?:app-id|id)\s*:\s*['\"]?([\w.-]+)", text, re.M)
            if m:
                build.append({"file": rel, "kind": "flatpak", "field": "id", "value": m.group(1)})

    for name, installed in sorted(cmake_installs.items()):
        if not any(e["desktop_id"] == name for e in desktop_files):
            build.append({"file": installed["file"], "line": installed["line"], "kind": "cmake",
                          "field": "install", "value": name})

    return {"desktop_files": desktop_files, "metainfo": metainfo, "build": build,
            "identifiers": suggest(desktop_files, metainfo, build)}


def suggest(desktop_files, metainfo, build):
    """Identifier candidates in the order a mapping usually lists them."""
    out, seen = [], set()

    def add(value):
        if not value or "@" in value or DEVEL.search(value):
            return
        if value.lower() in seen:
            return
        seen.add(value.lower())
        out.append(value)

    for e in desktop_files:
        if e["no_display"] or DEVEL.search(e["desktop_id"]):
            continue
        add(e["desktop_id"])
        add(e["desktop_id"][:-len(".desktop")] if e["desktop_id"].endswith(".desktop") else None)
        add(e["startup_wm_class"])
        add(e["exec"])
        add(e["name"])
    for m in metainfo:
        add(m["launchable"])
        add(m["id"])
        add(m["name"])
    for b in build:
        if b["kind"] in ("flatpak",):
            add(b["value"] + ".desktop")
            add(b["value"])
        elif b["kind"] in ("package.json", "electron-builder") and b["field"] != "build.linux.desktop.Name":
            add(b["value"])
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="desktop-ids",
        description="Read desktop ids, StartupWMClass and app names from a source tree: .desktop files "
                    "(also .desktop.in, meson output names, CMake install rules), AppStream metainfo, "
                    "Flatpak manifests and Electron packaging fields. Prints JSON {root, commit, "
                    "desktop_files, metainfo, build, identifiers}; `identifiers` is a suggested list for "
                    "a mapping, Devel builds left out.")
    parser.add_argument("dir")
    parser.add_argument("--all", action="store_true", help="also read test and vendored directories")
    args = parser.parse_args(argv)
    root = Path(args.dir).expanduser()
    if not root.is_dir():
        fail(f"not a directory: {root}")
    commit, url = git_info(root)
    emit({"root": str(root.resolve()), "commit": commit, "url": url, **scan(root, args.all)})
    return 0
