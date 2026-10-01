"""draft-sources: propose a SOURCES.json for a mapping from extracted rows.

For each mapping item with a shortcut it picks the extracted row with the
same chord whose label is closest to the item's label, preferring menu and
shortcut-window declarations over code, and code over documentation.
Changelogs rank last: they say what a shortcut was, not what it is. Each
pick carries a confidence: "label" (the source's label matches), "action"
(its action name does, e.g. next-tab for Next Tab) or "chord-only" (the
source has that chord, maybe for another action, so it needs a look before
it is trusted). Items with no row for their chord are listed under "unmatched".
The output goes to verify-mapping unchanged.
"""

import argparse
import json
import re
from pathlib import Path

from . import accel
from .cli import emit, fail
from .extract import git_info, scan
from .verify import DEFAULT_SOURCES, mapping_items

STOP = {"the", "a", "an", "to", "of", "and", "or", "in", "on", "for", "with", "by", "at", "from"}
KIND_RANK = {
    "gmenu-accel": 3, "gtk-shortcuts-window": 3, "adw-shortcuts-dialog": 3, "electron-menu": 3,
    "electron-role": 3, "qt-designer": 3, "kxmlgui": 3, "kxmlgui-standard-action": 3,
    "docbook-menuchoice": 2, "gtk-set-accels": 2, "gtk-binding": 2, "gtk-shortcut": 2,
    "gtk-accel-table": 2, "gtk-builder-accelerator": 2, "kstandardaction": 2, "kstandardshortcut": 2,
    "qt-shortcut": 2, "qt-standard-key": 2, "qml-shortcut": 2, "vscode-keybinding": 2,
    "vscode-keymod": 2, "java-keystroke": 2, "jetbrains-keymap": 2, "codemirror-keymap": 2,
    "zed-keymap": 2, "sublime-keymap": 2,
    "mallard": 1, "docbook-keycombo": 1, "doc-text": 1, "doc-yaml": 1,
}
LABEL_MATCH = 0.5      # share of the mapping label's words found in the source label
LABEL_JACCARD = 0.2    # and not one shared word lost in a long sentence
ACTION_JACCARD = 0.5   # an action name is short, so it has to match more closely
HISTORICAL = re.compile(r"(?:^|/)(?:changelog|changes|news|history|release[-_ ]?notes)[^/]*$", re.I)


def words(text):
    if not text:
        return set()
    text = re.sub(r"[_&]", "", text) if "_" in text and " " in text else text.replace("&", "")
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    out = set()
    for w in re.split(r"[^a-z0-9]+", text.lower()):
        if w and w not in STOP:
            out.add(w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w)
    return out


def first_word(text):
    """The first significant word of a label, usually its verb."""
    for w in sorted(words(text), key=lambda w: (text or "").lower().find(w)):
        return w
    return None


def jaccard(a, b):
    return len(a & b) / len(a | b) if a and b else 0.0


def coverage(want, have):
    """Share of the mapping label's words that the source label also has."""
    return len(want & have) / len(want) if want and have else 0.0


def draft(mapping, extract_doc, repo, path=None):
    rows = [r for r in extract_doc.get("shortcuts", []) if r.get("accel")]
    by_chord = {}
    for row in rows:
        seq = accel.parse_grammar(row["accel"])
        if seq is not None:
            by_chord.setdefault(accel.format_seq(seq), []).append(row)
    commit = extract_doc.get("commit")
    records, unmatched = [], []
    counts = {"label": 0, "action": 0, "chord-only": 0}
    with_shortcut = 0
    for item_path, item in mapping_items(mapping):
        shortcut = item.get("shortcut")
        if shortcut is None:
            continue
        with_shortcut += 1
        seq = accel.parse_grammar(shortcut)
        candidates = by_chord.get(accel.format_seq(seq), []) if seq else []
        if not candidates:
            unmatched.append({"path": item_path, "shortcut": shortcut})
            continue
        want = words(item_path[-1])
        first = first_word(item_path[-1])
        context = words(" ".join(p for p in item_path[:-1] if p))

        def score(row):
            # A changelog says what a shortcut was once, not what it is now
            historical = bool(HISTORICAL.search(row["file"]))
            have = words(row.get("label"))
            label_score = jaccard(want, have)
            action_words = words(re.sub(r"[._:-]", " ", row.get("action") or ""))
            action_score = jaccard(want, action_words)
            if historical:
                tier = 0
            elif (coverage(want, have) >= (1.0 if len(want) == 2 else LABEL_MATCH)
                  and label_score >= LABEL_JACCARD and first in have):
                tier = 2
            elif coverage(want, action_words) >= LABEL_MATCH and action_score >= ACTION_JACCARD:
                tier = 1
            else:
                tier = 0
            ctx_score = jaccard(context, words(row.get("context")))
            rank = -1 if historical else KIND_RANK.get(row["kind"], 0)
            return (tier, rank if tier == 0 else 0, round(label_score, 3), round(action_score, 3),
                    rank, round(ctx_score, 3), -row["line"])

        best = max(sorted(candidates, key=lambda r: (r["file"], r["line"])), key=score)
        s = score(best)
        confidence = {2: "label", 1: "action", 0: "chord-only"}[s[0]]
        counts[confidence] += 1
        records.append({
            "path": item_path, "shortcut": shortcut, "repo": repo, "file": best["file"],
            "line": best["line"], "commit": commit,
            "match": {"confidence": confidence, "kind": best["kind"], "source_label": best.get("label"),
                      "source_action": best.get("action"), "label_score": s[2], "candidates": len(candidates)},
        })
    repo_info = {"url": extract_doc.get("url"), "commit": commit}
    if path is not None:
        repo_info["path"] = str(path)
    return {
        "format": 1, "app": mapping.get("app"), "repos": {repo: repo_info}, "items": records,
        "unmatched": unmatched,
        "summary": {"with_shortcut": with_shortcut, "label_match": counts["label"],
                    "action_match": counts["action"], "chord_only": counts["chord-only"],
                    "unmatched": len(unmatched)},
    }


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="draft-sources",
        description="Propose provenance records (a SOURCES.json for verify-mapping) by matching each "
                    "mapping item to an extracted row with the same chord. Give either the JSON "
                    "extract-shortcuts printed, or --src to extract now. Picks marked chord-only need "
                    "a check that the source's action is the item's action.")
    parser.add_argument("mapping")
    parser.add_argument("extract", nargs="?", help="extract-shortcuts output (JSON file)")
    parser.add_argument("--src", help="scan this clone instead of reading an extract file")
    parser.add_argument("--repo", help="repo id for the records (default: the clone's directory name)")
    args = parser.parse_args(argv)
    try:
        mapping = json.loads(Path(args.mapping).read_text())
    except (OSError, ValueError) as exc:
        fail(f"cannot read mapping: {exc}")
    if args.src:
        root = Path(args.src).expanduser().resolve()
        if not root.is_dir():
            fail(f"not a directory: {root}")
        commit, url = git_info(root)
        extract_doc = {"root": str(root), "commit": commit, "url": url, **scan(root)}
    elif args.extract:
        try:
            extract_doc = json.loads(Path(args.extract).read_text())
        except (OSError, ValueError) as exc:
            fail(f"cannot read extract output: {exc}")
        root = Path(extract_doc.get("root", "."))
    else:
        fail("give an extract-shortcuts JSON file or --src DIR")
    repo = args.repo or root.name
    standard = Path(DEFAULT_SOURCES) / repo
    path = None if root == standard else root
    emit(draft(mapping, extract_doc, repo, path))
    return 0
