"""draft-mapping: build a mapping, and the SOURCES.json that proves it, from
extract-shortcuts output.

Two ways to find the menus:

  menus     the app's own menubar: KXMLGUI .rc menus, Qt Designer menus,
            Electron menu templates. Menus with the same id (KXMLGUI) or label
            merge across files and repos, the way KXMLGUI merges plugin menus.
  sections  rows grouped by the menu path or section the source documents
            for them: DocBook <menuchoice> paths ("Edit > Go To"), GTK and
            libadwaita shortcut-window sections, Mallard <guiseq>.

auto uses menus when the source has a menubar with labelled items, else
sections. Every shortcut in the draft comes from a row or menu item that
names its file and line, and gets a record at that line, so the draft goes
straight to verify-mapping. An item with no label is dropped, never named
by guesswork. The draft still wants a read-through: menu names, order,
and which of the app's many actions belong in a menu bar.
"""

import argparse
import json
import os
from pathlib import Path

from . import accel
from .cli import emit, fail
from .draft import KIND_RANK
from .verify import DEFAULT_SOURCES

MENUBAR_KINDS = ("kxmlgui", "qt-designer", "electron")
SECTION_KINDS = ("docbook-menuchoice", "gtk-shortcuts-window", "adw-shortcuts-dialog", "mallard")


def repo_id(doc):
    return Path(doc.get("root") or "source").name


def _tidy(items):
    """Drop leading, trailing and doubled separators."""
    out = []
    for item in items:
        if item.get("separator"):
            if out and not out[-1].get("separator"):
                out.append({"separator": True})
        else:
            out.append(item)
    while out and out[-1].get("separator"):
        out.pop()
    return out


class Builder:
    def __init__(self):
        self.records = []
        self.dropped = []
        self.repos = {}

    def use_repo(self, doc):
        rid = repo_id(doc)
        if rid not in self.repos:
            info = {"url": doc.get("url"), "commit": doc.get("commit")}
            root = Path(doc["root"]) if doc.get("root") else None
            if root is not None and root != Path(DEFAULT_SOURCES) / rid:
                info["path"] = str(root)
            self.repos[rid] = info
        return rid

    def leaf(self, path, label, accel_str, proof, doc):
        item = {"label": label}
        seq = accel.parse_grammar(accel_str) if accel_str else None
        if seq is not None and proof is not None:
            shortcut = accel.format_seq(seq)
            item["shortcut"] = shortcut
            self.records.append({"path": path, "shortcut": shortcut, "repo": self.use_repo(doc),
                                 "file": proof[0], "line": proof[1], "commit": doc.get("commit")})
        elif accel_str:
            self.dropped.append({"path": path, "reason": f"shortcut {accel_str} has no source line; kept as a placeholder"})
        return item

    def convert(self, items, prefix, menu_file, doc):
        out = []
        seen = set()
        for item in items:
            if item.get("separator"):
                out.append({"separator": True})
                continue
            label = item.get("label")
            if "items" in item:
                if not label:
                    self.dropped.append({"path": prefix + [item.get("id") or "?"], "reason": "submenu has no label"})
                    continue
                sub = _tidy(self.convert(item["items"], prefix + [label], menu_file, doc))
                if not any(not s.get("separator") for s in sub):
                    self.dropped.append({"path": prefix + [label], "reason": "empty submenu"})
                    continue
                out.append({"label": label, "items": sub})
                continue
            if not label:
                self.dropped.append({"path": prefix + [item.get("action") or item.get("role") or "?"],
                                     "reason": "no label in the source"})
                continue
            key = (label, item.get("accel"))
            if key in seen:
                continue
            seen.add(key)
            proof = None
            if item.get("accel_source"):
                proof = (item["accel_source"]["file"], item["accel_source"]["line"])
            elif item.get("accel_line"):
                proof = (menu_file, item["accel_line"])
            out.append(self.leaf(prefix + [label], label, item.get("accel"), proof, doc))
        return out


def from_menus(docs, builder):
    menus = []
    for doc in docs:
        for m in doc.get("menus", []):
            if m.get("kind") in MENUBAR_KINDS:
                menus.append((doc, m))
    if not menus:
        return None
    per_file = {}
    for doc, m in menus:
        per_file[(repo_id(doc), m["file"])] = per_file.get((repo_id(doc), m["file"]), 0) + 1
    main = max(per_file, key=lambda k: (per_file[k], -list(per_file).index(k)))
    ordered = [x for x in menus if (repo_id(x[0]), x[1]["file"]) == main] + \
              [x for x in menus if (repo_id(x[0]), x[1]["file"]) != main]
    merged = {}
    for doc, m in ordered:
        key = (m.get("id") or "").lower() if m["kind"] == "kxmlgui" and m.get("id") else (m.get("label") or "").lower()
        entry = merged.setdefault(key, {"label": None, "items": []})
        entry["label"] = entry["label"] or m.get("label")
        label = entry["label"] or m.get("id") or "?"
        items = builder.convert(m.get("items", []), [label], m["file"], doc)
        existing = {(i.get("label"), i.get("shortcut")) for i in entry["items"] if not i.get("separator")}
        entry["items"].extend(i for i in items if i.get("separator") or (i.get("label"), i.get("shortcut")) not in existing)
    out = []
    for key, entry in merged.items():
        items = _tidy(entry["items"])
        if not entry["label"]:
            builder.dropped.append({"path": [key], "reason": "menu has no label"})
            continue
        if not any(not i.get("separator") for i in items):
            builder.dropped.append({"path": [entry["label"]], "reason": "empty menu"})
            continue
        out.append({"label": entry["label"], "items": items})
    return out


def from_sections(docs, builder):
    rows = []
    for doc in docs:
        for row in doc.get("shortcuts", []):
            if row.get("kind") in SECTION_KINDS and row.get("accel") and row.get("label") and row.get("context"):
                rows.append((doc, row))
    rows.sort(key=lambda dr: (-KIND_RANK.get(dr[1]["kind"], 0), dr[1]["file"], dr[1]["line"]))
    tree = {}
    order = []
    for doc, row in rows:
        path = [p.strip() for p in row["context"].split(">") if p.strip()]
        node = tree
        for depth, part in enumerate(path):
            if part not in node:
                node[part] = {}
                if depth == 0:
                    order.append(part)
            node = node[part]
        items = node.setdefault("\0items", [])
        if any(i["label"] == row["label"] for i in items):
            continue
        items.append({"label": row["label"], "accel": row["accel"], "row": row, "doc": doc})

    def build(node, prefix):
        out = []
        for key, child in node.items():
            if key == "\0items":
                continue
            sub = build(child, prefix + [key])
            if sub:
                out.append({"label": key, "items": sub})
        for item in node.get("\0items", []):
            row = item["row"]
            out.append(builder.leaf(prefix + [item["label"]], item["label"], item["accel"],
                                    (row["file"], row["line"]), item["doc"]))
        return out

    return [{"label": top, "items": build(tree[top], [top])} for top in order if build(tree[top], [top])]


def _count(items):
    shortcuts = placeholders = 0
    for item in items:
        if item.get("separator"):
            continue
        if "items" in item:
            s, p = _count(item["items"])
            shortcuts, placeholders = shortcuts + s, placeholders + p
        elif "shortcut" in item:
            shortcuts += 1
        else:
            placeholders += 1
    return shortcuts, placeholders


def draft_mapping(docs, app, name=None, identifiers=None, strategy="auto"):
    builder = Builder()
    menus = None
    used = strategy
    if strategy in ("auto", "menus"):
        menus = from_menus(docs, builder)
        used = "menus"
        if strategy == "auto" and not menus:
            builder = Builder()
            menus = None
    if menus is None and strategy in ("auto", "sections"):
        menus = from_sections(docs, builder)
        used = "sections"
    menus = menus or []
    mapping = {"format": 1, "app": app, "name": name or app,
               "identifiers": identifiers or [app], "menus": menus}
    shortcuts = placeholders = 0
    for m in menus:
        s, p = _count(m["items"])
        shortcuts, placeholders = shortcuts + s, placeholders + p
    # One record per item that made it into the mapping: merging drops
    # duplicates after their records were written
    wanted = set()

    def leaves(items, prefix):
        for i in items:
            if "items" in i:
                leaves(i["items"], prefix + [i["label"]])
            elif "shortcut" in i:
                wanted.add(json.dumps(prefix + [i["label"]]))
    for m in menus:
        leaves(m["items"], [m["label"]])
    records, seen = [], set()
    for rec in builder.records:
        key = json.dumps(rec["path"])
        if key in wanted and key not in seen:
            seen.add(key)
            records.append(rec)
    repos = {r: info for r, info in builder.repos.items() if any(rec["repo"] == r for rec in records)}
    return {
        "strategy": used,
        "mapping": mapping,
        "sources": {"format": 1, "app": app, "repos": repos, "items": records},
        "report": {"menus": len(menus), "with_shortcut": shortcuts, "placeholders": placeholders,
                   "dropped": builder.dropped},
    }


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="draft-mapping",
        description="Draft a Global Menu mapping and its SOURCES.json from extract-shortcuts output (one "
                    "JSON file per repo, merged). Strategy menus uses the app's menubar (KXMLGUI, Qt "
                    "Designer, Electron templates); sections groups documented shortcuts by menu path or "
                    "section; auto picks menus when there is a menubar. Prints {strategy, mapping, sources, "
                    "report}, or writes APP.json and APP.sources.json with --out-dir.")
    parser.add_argument("extract", nargs="+", help="extract-shortcuts output files")
    parser.add_argument("--app", required=True, help="mapping id (the file name stem)")
    parser.add_argument("--name", help="display name (default: the app id)")
    parser.add_argument("--identifier", action="append", default=[], help="identifier (repeatable)")
    parser.add_argument("--desktop", help="desktop-ids output; its `identifiers` are used")
    parser.add_argument("--strategy", choices=("auto", "menus", "sections"), default="auto")
    parser.add_argument("--out-dir", help="write APP.json and APP.sources.json here")
    args = parser.parse_args(argv)
    docs = []
    for path in args.extract:
        try:
            docs.append(json.loads(Path(path).read_text()))
        except (OSError, ValueError) as exc:
            fail(f"cannot read {path}: {exc}")
    identifiers = list(args.identifier)
    if args.desktop:
        try:
            identifiers += json.loads(Path(args.desktop).read_text()).get("identifiers", [])
        except (OSError, ValueError) as exc:
            fail(f"cannot read {args.desktop}: {exc}")
    out = draft_mapping(docs, args.app, args.name, identifiers or None, args.strategy)
    if args.out_dir:
        out_dir = Path(args.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        mapping_file = out_dir / f"{args.app}.json"
        sources_file = out_dir / f"{args.app}.sources.json"
        mapping_file.write_text(json.dumps(out["mapping"], indent=2, ensure_ascii=False) + "\n")
        sources_file.write_text(json.dumps(out["sources"], indent=2, ensure_ascii=False) + "\n")
        emit({"strategy": out["strategy"], "mapping_file": str(mapping_file), "sources_file": str(sources_file),
              "report": out["report"]})
    else:
        emit(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(os.sys.argv[1:]))
