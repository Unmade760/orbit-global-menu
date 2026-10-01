"""extract-shortcuts: a deterministic scan of a source tree for shortcut
declarations and menu definitions.

Every row names the file and line it came from, so a mapping can cite it
and verify-mapping can check the citation. Nothing is guessed: a row exists
only where the source spells out a shortcut, or names a standard one
(QKeySequence::Copy, KStandardAction::save, an Electron role) whose default
is read from mtools/data/standard_keys.json, which records its own source.
"""

import argparse
import os
import re
import subprocess
from pathlib import Path

from . import scan_docs, scan_gtk, scan_java, scan_js, scan_qt, xmltree
from .cli import emit, fail
from .common import FileScan

SKIP_DIRS = {
    "test", "tests", "testing", "__tests__", "spec", "specs", "testdata", "test-data", "testsuite",
    "node_modules", "bower_components", "vendor", "third_party", "thirdparty", "third-party",
    "3rdparty", "external", "extern", "subprojects", "deps", "build", "_build", "dist", "out",
    "target", "po", "locale", "locales", "l10n", "i18n", "translations", ".flatpak-builder",
    "benchmark", "benchmarks", "examples", "example", "fixtures",
}
MAX_BYTES = 1_500_000

GTK_HINT = re.compile(r"accel|KEY_|Key::|Key\.|binding|<primary>|<control>|<ctrl>|<shift>|<alt>|<super>|"
                      r"trigger", re.I)
QT_HINT = re.compile(r"QKeySequence|KStandard|Qt::Key|Qt\.Key|Key_|setShortcut|setDefaultShortcut|shortcut|addAction",
                     re.I)
JAVA_HINT = re.compile(r"KeyStroke")


PLATFORM_TOKEN = re.compile(r"(?:^|[-_. ()])(darwin|macos|mac|osx|cocoa|win32|windows|linux)(?=[-_. ()]|$)", re.I)
PLATFORM_NAMES = {"darwin": "mac", "macos": "mac", "mac": "mac", "osx": "mac", "cocoa": "mac",
                  "win32": "windows", "windows": "windows", "linux": "linux"}


def platform_of(rel):
    """"mac", "windows" or "linux" when the file name (else its nearest
    directory) names one platform: menu.darwin.ts, Default (Windows).sublime-keymap."""
    parts = Path(rel).parts
    for part in [Path(rel).name] + list(reversed(parts[:-1])):
        m = PLATFORM_TOKEN.search(part)
        if m:
            return PLATFORM_NAMES[m.group(1).lower()]
    return None


def skip_dir(name):
    return name.lower() in SKIP_DIRS or name.startswith(".")


def iter_files(root, include_all=False):
    root = Path(root)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d != ".git" and (include_all or not skip_dir(d)))
        for name in sorted(filenames):
            path = Path(dirpath) / name
            if include_all or not re.search(r"(?:\.min\.js|\.map|[-_.]test\.\w+|_spec\.\w+)$", name):
                yield path


def _read(path):
    try:
        if path.stat().st_size > MAX_BYTES:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    if b"\0" in data[:4096]:
        return None
    return data.decode("utf-8", errors="replace")


def _parse_xml(text):
    root = xmltree.parse(text)
    if root is None:
        # DocBook chapters are often fragments with several top-level elements
        body = re.sub(r"^\s*<\?xml[^>]*\?>", lambda m: " " * len(m.group(0)), text)
        body = re.sub(r"<!DOCTYPE[^>\[]*(\[.*?\])?\s*>", lambda m: re.sub(r"[^\n]", " ", m.group(0)), body,
                      flags=re.S)
        root = xmltree.parse("<__fragment__>" + body + "</__fragment__>")
    return root


def _xml_root_tag(root):
    for child in root.children:
        if child.tag == "__fragment__":
            return _xml_root_tag(child) if child.children else "__fragment__"
        return child.tag
    return None


def scan_xml(fs, path):
    text = fs.text
    root = _parse_xml(text)
    if root is None:
        return
    tag = _xml_root_tag(root)
    suffix = path.suffix.lower()
    if tag == "interface":
        scan_gtk.scan_builder(fs, root)
    elif tag == "ui" and suffix == ".ui":
        scan_qt.scan_designer(fs, root)
    elif tag in ("gui", "kpartgui"):
        scan_qt.scan_kxmlgui(fs, root)
    elif tag == "page" or suffix == ".page":
        scan_docs.scan_mallard(fs, root)
    elif "keyboard-shortcut" in text:
        scan_java.scan_keymap(fs, root)
    elif suffix == ".docbook" or re.search(r"<(?:menuchoice|keycombo)\b", text):
        scan_docs.scan_docbook(fs, root)


def scan_file(path, rel):
    text = _read(path)
    if text is None:
        return None
    return scan_text(rel, text, path)


def scan_text(rel, text, path=None):
    """Scan one file's text; `rel` decides the scanner by its suffix."""
    path = Path(path) if path is not None else Path(rel)
    fs = FileScan(rel, text)
    name = path.name.lower()
    suffix = path.suffix.lower()
    stem_suffixes = [s.lower() for s in path.suffixes]
    if suffix == ".in" and len(stem_suffixes) > 1:
        suffix = next((s for s in reversed(stem_suffixes) if s != ".in"), suffix)
    if suffix in (".ui", ".rc", ".page", ".docbook", ".xml", ".kxmlgui"):
        if "<" in text:
            scan_xml(fs, path)
    elif suffix == ".blp":
        scan_gtk.scan_blueprint(fs)
    elif suffix in scan_gtk.LANG_BY_SUFFIX:
        lang = scan_gtk.LANG_BY_SUFFIX[suffix]
        if GTK_HINT.search(text):
            scan_gtk.scan_code(fs, lang)
        if lang in ("c", "cpp", "python") and QT_HINT.search(text):
            scan_qt.scan_code(fs, lang)
        if lang == "js":
            scan_js.scan_js(fs)
    elif suffix == ".qml":
        scan_qt.scan_qml(fs)
    elif suffix in (".java", ".kt"):
        if JAVA_HINT.search(text):
            scan_java.scan_code(fs, "java" if suffix == ".java" else "kotlin")
    elif suffix in (".json", ".jsonc", ".sublime-keymap") or name.endswith(".code-workspace"):
        scan_js.scan_json(fs, path)
    elif suffix in (".md", ".markdown"):
        scan_docs.scan_markdown(fs)
    elif suffix in (".yml", ".yaml"):
        scan_docs.scan_yaml(fs)
    return fs


# --- cross-file enrichment -------------------------------------------------

def _detailed(action, target=None):
    if action is None:
        return None
    if target is not None:
        return f"{action}::{target}"
    return action


def _walk_items(items):
    for item in items:
        if item.get("separator"):
            continue
        yield item
        yield from _walk_items(item.get("items", []))


def enrich(rows, menus, actions):
    """Fill missing labels from the app's own menus and shortcut windows, and
    missing menu accelerators from the rows. Each filled value names where it
    came from (label_source, accel_source)."""
    labels = {}

    def offer(action, label, file, line, rank):
        if not action or not label:
            return
        key = action
        prev = labels.get(key)
        if prev is None or (rank, file, line) < prev[0]:
            labels[key] = ((rank, file, line), label)

    for menu in menus:
        for item in _walk_items(menu.get("items", [])):
            offer(_detailed(item.get("action"), item.get("target")), item.get("label"),
                  menu["file"], item.get("line", menu.get("line", 0)), 0)
    for row in rows:
        if row["kind"] in ("gtk-shortcuts-window", "adw-shortcuts-dialog"):
            offer(row.get("action"), row.get("label"), row["file"], row["line"], 1)
    for entry in actions:
        offer(entry.get("action"), entry.get("label"), entry["file"], entry["line"], 1)
    for row in rows:
        offer(row.get("action"), row.get("label"), row["file"], row["line"], 2)

    for row in rows:
        if row.get("label") is None and row.get("action") in labels:
            (_, file, line), label = labels[row["action"]]
            row["label"] = label
            row["label_source"] = {"file": file, "line": line}

    for menu in menus:
        for item in _walk_items(menu.get("items", [])):
            key = _detailed(item.get("action"), item.get("target"))
            if item.get("label") is None and key in labels:
                (_, file, line), label = labels[key]
                item["label"] = label
                item["label_source"] = {"file": file, "line": line}

    accels = {}
    for row in rows:
        if row.get("accel") and row.get("action"):
            key = row["action"]
            cand = ((row["file"], row["line"]), row["accel"])
            if key not in accels or cand[0] < accels[key][0]:
                accels[key] = cand
    for menu in menus:
        for item in _walk_items(menu.get("items", [])):
            if item.get("accel") or not item.get("action"):
                continue
            key = _detailed(item.get("action"), item.get("target"))
            hit = accels.get(key) or (accels.get(item["action"]) if item.get("target") is None else None)
            if hit:
                (file, line), accel_str = hit
                item["accel"] = accel_str
                item["accel_source"] = {"file": file, "line": line}


def _dedupe(rows):
    seen, out = set(), []
    for row in rows:
        key = (row["file"], row["line"], row["kind"], row["accel"], row["accel_raw"], row.get("action"),
               row.get("label"))
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def _sort_key(row):
    return (row["file"], row["line"], row["kind"], row["accel"] or "", row.get("action") or "",
            row.get("label") or "", row["accel_raw"])


def scan(root, include_all=False):
    root = Path(root)
    rows, menus, actions = [], [], []
    constants = {}
    files = with_rows = 0
    for path in iter_files(root, include_all):
        rel = path.relative_to(root).as_posix()
        platform = platform_of(rel)
        if platform == "mac" and not include_all:
            continue
        fs = scan_file(path, rel)
        if fs is None:
            continue
        if platform:
            for row in fs.rows:
                row["platform"] = platform
        files += 1
        if fs.rows or fs.menus:
            with_rows += 1
        rows += fs.rows
        menus += fs.menus
        actions += fs.actions
        for name, value in fs.constants.items():
            constants.setdefault(name, set()).add((value, rel))
    # Command ids named by a constant defined in another file, when the name is unique
    for row in rows:
        ref = row.get("action_ref")
        if row.get("action") is None and ref:
            values = constants.get(ref) or constants.get(ref.split(".")[-1] if "." not in ref else ref)
            if values and len({v for v, _ in values}) == 1:
                value, rel = sorted(values)[0]
                row["action"] = value
                row["action_source"] = rel
    rows = _dedupe(rows)
    menus.sort(key=lambda m: (m["file"], m.get("line", 0)))
    actions.sort(key=lambda a: (a["file"], a["line"], a["action"] or ""))
    enrich(rows, menus, actions)
    rows.sort(key=_sort_key)
    by_kind = {}
    for row in rows:
        by_kind[row["kind"]] = by_kind.get(row["kind"], 0) + 1
    stats = {
        "files_scanned": files,
        "files_with_results": with_rows,
        "rows": len(rows),
        "rows_with_accel": sum(1 for r in rows if r["accel"]),
        "rows_with_error": sum(1 for r in rows if r["accel"] is None),
        "distinct_accels": len({r["accel"] for r in rows if r["accel"]}),
        "menus": len(menus),
        "by_kind": dict(sorted(by_kind.items())),
    }
    return {"stats": stats, "shortcuts": rows, "menus": menus, "actions": actions}


def git_info(root):
    def run(*args):
        proc = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
        return proc.stdout.strip() if proc.returncode == 0 else None
    return run("rev-parse", "HEAD"), run("remote", "get-url", "origin")


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="extract-shortcuts",
        description="Scan a source tree for shortcut declarations and menu definitions. Prints JSON: "
                    "{root, commit, url, stats, shortcuts: [{accel_raw, accel, label, action, file, line, "
                    "kind, context?, error?, via?, platform?, label_source?}], menus, actions}. Test, "
                    "vendored and translation directories, and macOS-only files, are skipped unless --all "
                    "is given.")
    parser.add_argument("dir", help="source tree, usually a clone made by fetch-source")
    parser.add_argument("--all", action="store_true", help="also scan tests, vendored code and build output")
    parser.add_argument("--kind", action="append", default=[], help="keep only rows of this kind (repeatable)")
    parser.add_argument("--path", action="append", default=[],
                        help="keep only rows and menus whose file starts with this prefix (repeatable)")
    parser.add_argument("--no-errors", action="store_true", help="drop rows whose shortcut has no mapping form")
    parser.add_argument("--summary", action="store_true", help="print stats and per-file counts only")
    args = parser.parse_args(argv)

    root = Path(args.dir).expanduser()
    if not root.is_dir():
        fail(f"not a directory: {root}")
    result = scan(root, include_all=args.all)
    rows = result["shortcuts"]
    if args.kind:
        rows = [r for r in rows if r["kind"] in args.kind]
    if args.path:
        rows = [r for r in rows if any(r["file"].startswith(p) for p in args.path)]
        result["menus"] = [m for m in result["menus"] if any(m["file"].startswith(p) for p in args.path)]
    if args.no_errors:
        rows = [r for r in rows if r["accel"]]
    commit, url = git_info(root)
    out = {"root": str(root.resolve()), "commit": commit, "url": url, "stats": result["stats"]}
    if args.summary:
        per_file = {}
        for r in rows:
            per_file[r["file"]] = per_file.get(r["file"], 0) + 1
        out["files"] = dict(sorted(per_file.items(), key=lambda kv: (-kv[1], kv[0])))
    else:
        out["shortcuts"] = rows
        out["menus"] = result["menus"]
        out["actions"] = result["actions"]
    emit(out)
    return 0
