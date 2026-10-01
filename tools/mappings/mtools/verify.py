"""verify-mapping: the gate that stops invented shortcuts.

Every mapping item with a shortcut needs a provenance record in the
SOURCES.json file next to it, and the record has to hold up:

  {file, line, commit[, repo]}  the file at that commit, lines line-3 to
                                line+3, contains a token for the same chord.
                                The extractor's rows for that file are tried
                                first, then a plain token scan of the lines.
  {url, quote}                  `rloop verify --quote QUOTE --url URL` exits 0
                                and the quote itself contains the chord.

SOURCES.json:
  {"format": 1, "app": "<mapping app id>",
   "repos": {"<id>": {"url": "...", "commit": "...", "path": "optional clone dir"}},
   "items": [{"path": ["File", "Save"], "shortcut": "<Ctrl>S" (optional),
              "repo": "<id>", "file": "src/x.c", "line": 12, "commit": "<sha>"},
             {"path": ["Edit", "Emoji"], "url": "https://...", "quote": "..."}]}

`path` is the chain of labels from the top-level menu to the item. An item
passes when any one of its records passes.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from . import accel, tokens
from .cli import emit, fail
from .extract import scan_text

WINDOW = 3
DEFAULT_SOURCES = "/home/ravi/fildem-work/sources"


# --- mapping walk ----------------------------------------------------------

def mapping_items(mapping):
    """(path, item) for every item, depth first, in menu order."""
    out = []

    def walk(items, prefix):
        for item in items:
            if not isinstance(item, dict) or item.get("separator"):
                continue
            path = prefix + [item.get("label")]
            if isinstance(item.get("items"), list):
                walk(item["items"], path)
            else:
                out.append((path, item))

    for menu in mapping.get("menus", []):
        walk(menu.get("items", []), [menu.get("label")])
    return out


# --- source checks ---------------------------------------------------------

class Sources:
    """Reads files at a commit from local clones, with caches."""

    def __init__(self, src, repos, root):
        self.src = Path(src) if src else None
        self.repos = repos or {}
        self.root = Path(root)
        self._files = {}
        self._rows = {}

    def clone_dir(self, record):
        repo = record.get("repo")
        if repo:
            info = self.repos.get(repo, {})
            return Path(info["path"]) if info.get("path") else self.root / repo
        if self.src:
            return self.src
        if len(self.repos) == 1:
            (repo, info), = self.repos.items()
            return Path(info["path"]) if info.get("path") else self.root / repo
        return None

    def read(self, clone, commit, file):
        key = (str(clone), commit, file)
        if key not in self._files:
            if not (clone / ".git").exists():
                self._files[key] = (None, f"no clone at {clone}; run fetch-source first")
            else:
                proc = subprocess.run(["git", "-C", str(clone), "cat-file", "-e", f"{commit}^{{commit}}"],
                                      capture_output=True, text=True)
                if proc.returncode != 0:
                    self._files[key] = (None, f"commit {commit} is not in the clone at {clone}; "
                                              f"run fetch-source with --ref {commit}")
                else:
                    proc = subprocess.run(["git", "-C", str(clone), "show", f"{commit}:{file}"],
                                          capture_output=True)
                    if proc.returncode != 0:
                        self._files[key] = (None, f"{file} does not exist at commit {commit[:12]}")
                    else:
                        self._files[key] = (proc.stdout.decode("utf-8", errors="replace"), None)
        return self._files[key]

    def rows(self, clone, commit, file, text):
        key = (str(clone), commit, file)
        if key not in self._rows:
            try:
                fs = scan_text(file, text)
                self._rows[key] = fs.rows if fs else []
            except Exception as exc:  # a scanner bug must not hide the token check
                self._rows[key] = []
                print(f"extractor failed on {file}: {exc}", file=sys.stderr)
        return self._rows[key]


def check_file_record(record, target, sources):
    for key in ("file", "line", "commit"):
        if record.get(key) in (None, ""):
            return False, f"record has no {key}", None
    clone = sources.clone_dir(record)
    if clone is None:
        return False, "record names no repo and no --src was given", None
    text, error = sources.read(clone, str(record["commit"]), record["file"])
    if error:
        return False, error, None
    lines = text.split("\n")
    line = int(record["line"])
    if not 1 <= line <= len(lines):
        return False, f"line {line} is outside {record['file']} ({len(lines)} lines)", None
    lo, hi = max(1, line - WINDOW), min(len(lines), line + WINDOW)
    base = {"file": record["file"], "commit": record["commit"], "cited_line": line}
    for row in sources.rows(clone, str(record["commit"]), record["file"], text):
        if lo <= row["line"] <= hi and row.get("accel") and accel.same(accel.parse_grammar(row["accel"]), target):
            return True, None, {**base, "via": "extractor", "kind": row["kind"], "line": row["line"],
                                "token": row["accel_raw"]}
    window = "\n".join(lines[lo - 1:hi])
    ok, raw = tokens.contains(window, target)
    if ok:
        return True, None, {**base, "via": "token", "token": raw, "lines": [lo, hi]}
    near = sorted({row["accel"] for row in sources.rows(clone, str(record["commit"]), record["file"], text)
                   if lo <= row["line"] <= hi and row.get("accel")})
    found = sorted({accel.format_seq(seq) for _, _, _, seq in tokens.find_chords(window)} | set(near))
    msg = f"lines {lo}-{hi} of {record['file']} hold no token for {accel.format_seq(target)}"
    if found:
        msg += f"; they hold {', '.join(found)}"
    return False, msg, None


def _cache_path():
    root = Path(os.environ.get("MAPPING_TOOLS_CACHE", Path.home() / ".cache" / "mapping-tools"))
    return root / "rloop-verify.json"


def _cache_load():
    try:
        return json.loads(_cache_path().read_text())
    except (OSError, ValueError):
        return {}


def _cache_save(cache):
    path = _cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cache, indent=1, sort_keys=True))
    except OSError:
        pass


def check_url_record(record, target, cache, no_cache=False):
    url, quote = record.get("url"), record.get("quote")
    if not url or not quote:
        return False, "record needs both url and quote", None
    ok, raw = tokens.contains(quote, target)
    if not ok:
        return False, f"the quote contains no token for {accel.format_seq(target)}", None
    key = hashlib.sha256(f"{url}\n{quote}".encode()).hexdigest()
    if not no_cache and cache.get(key, {}).get("exit") == 0:
        return True, None, {"via": "url", "url": url, "token": raw, "cached": True}
    rloop = os.environ.get("RLOOP", "rloop")
    try:
        proc = subprocess.run([rloop, "verify", "--quote", quote, "--url", url],
                              capture_output=True, text=True, timeout=180)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"rloop verify could not run: {exc}", None
    if proc.returncode != 0:
        detail = (proc.stdout.strip() or proc.stderr.strip()).splitlines()
        return False, f"rloop verify exited {proc.returncode}" + (f": {detail[-1]}" if detail else ""), None
    cache[key] = {"exit": 0, "url": url}
    return True, None, {"via": "url", "url": url, "token": raw}


# --- main --------------------------------------------------------------------

def verify(mapping, sources_doc, src=None, root=None, no_cache=False):
    sources = Sources(src, sources_doc.get("repos"), root or os.environ.get("MAPPING_SOURCES", DEFAULT_SOURCES))
    records = [r for r in sources_doc.get("items", []) if isinstance(r, dict)]
    by_path = {}
    for rec in records:
        by_path.setdefault(json.dumps(rec.get("path")), []).append(rec)
    cache = _cache_load()
    results, used = [], set()
    for path, item in mapping_items(mapping):
        result = {"path": path}
        shortcut = item.get("shortcut")
        if shortcut is None:
            result["status"] = "skip"
            result["reason"] = "placeholder, no shortcut"
            results.append(result)
            used.add(json.dumps(path))
            continue
        result["shortcut"] = shortcut
        target = accel.parse_grammar(shortcut)
        if target is None:
            result.update(status="fail", reason=f"{shortcut!r} is not in the mapping grammar")
            results.append(result)
            continue
        recs = by_path.get(json.dumps(path), [])
        if recs:
            used.add(json.dumps(path))
        if not recs:
            result.update(status="fail", reason="no provenance record for this item")
            results.append(result)
            continue
        reasons = []
        for rec in recs:
            if rec.get("shortcut") is not None:
                claimed = accel.parse_grammar(rec["shortcut"])
                if not accel.same(claimed, target):
                    reasons.append(f"the record is for {rec['shortcut']}, the mapping says {shortcut}")
                    continue
            if rec.get("url") or rec.get("quote"):
                ok, reason, evidence = check_url_record(rec, target, cache, no_cache)
            else:
                ok, reason, evidence = check_file_record(rec, target, sources)
            if ok:
                result.update(status="pass", evidence=evidence)
                break
            reasons.append(reason)
        else:
            result.update(status="fail", reason="; ".join(reasons))
        results.append(result)
    _cache_save(cache)
    orphans = [{"path": r.get("path")} for r in records if json.dumps(r.get("path")) not in used]
    summary = {
        "items": len(results),
        "with_shortcut": sum(1 for r in results if r["status"] != "skip"),
        "passed": sum(1 for r in results if r["status"] == "pass"),
        "failed": sum(1 for r in results if r["status"] == "fail"),
        "placeholders": sum(1 for r in results if r["status"] == "skip"),
        "orphan_records": len(orphans),
    }
    return {"summary": summary, "items": results, "orphans": orphans}


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="verify-mapping",
        description="Check that every shortcut in a mapping is backed by its cited source. Each item "
                    "with a shortcut needs a record in SOURCES.json: {file, line, commit[, repo]} whose "
                    "lines line-3..line+3 at that commit contain a token for the same chord, or "
                    "{url, quote} that `rloop verify` confirms and that contains the chord. Prints "
                    "per-item pass/fail JSON; exits 1 if any item fails. See mtools/verify.py for the "
                    "SOURCES.json format.")
    parser.add_argument("mapping", help="the mapping JSON (shortcuts/apps/<app>.json)")
    parser.add_argument("sources", help="its provenance file (SOURCES.json)")
    parser.add_argument("--src", help="clone directory for records that name no repo")
    parser.add_argument("--sources-root", help=f"where repo ids resolve (default $MAPPING_SOURCES or {DEFAULT_SOURCES})")
    parser.add_argument("--no-cache", action="store_true", help="re-run rloop verify even for cached passes")
    parser.add_argument("--failures", action="store_true", help="print only failing items")
    args = parser.parse_args(argv)
    try:
        mapping = json.loads(Path(args.mapping).read_text())
        sources_doc = json.loads(Path(args.sources).read_text())
    except (OSError, ValueError) as exc:
        fail(f"cannot read input: {exc}")
    out = verify(mapping, sources_doc, src=args.src, root=args.sources_root, no_cache=args.no_cache)
    out = {"mapping": str(args.mapping), "sources": str(args.sources), "app": mapping.get("app"), **out}
    if sources_doc.get("app") not in (None, mapping.get("app")):
        out["warning"] = f"SOURCES.json is for {sources_doc.get('app')!r}, the mapping is {mapping.get('app')!r}"
    if args.failures:
        out["items"] = [i for i in out["items"] if i["status"] == "fail"]
    emit(out)
    return 1 if out["summary"]["failed"] else 0
