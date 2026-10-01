"""fetch-source: a shallow, blobless clone of an app's source, one per id.

The clone is fetched by ref with `git fetch --depth 1 --filter=blob:none`,
which takes a branch, a tag or a commit hash alike (GitHub and GitLab both
serve a reachable commit by hash). Blobs are fetched on checkout, so only the
files of that one commit come down, and --path narrows the checkout further
for very large trees.
"""

import argparse
import os
import re
import subprocess
from pathlib import Path

from .cli import emit, fail

DEFAULT_ROOT = os.environ.get("MAPPING_SOURCES", "/home/ravi/fildem-work/sources")
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class GitError(RuntimeError):
    pass


def git(repo, *args, timeout=900):
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, timeout=timeout,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )
    if proc.returncode != 0:
        raise GitError(f"git {' '.join(args)}: {proc.stderr.strip()}")
    return proc.stdout.strip()


def fetch_ref(dest, ref, timeout):
    git(dest, "fetch", "--quiet", "--depth", "1", "--filter=blob:none",
        "origin", ref or "HEAD", timeout=timeout)
    git(dest, "checkout", "--quiet", "--force", "--detach", "FETCH_HEAD", timeout=timeout)


def clone(dest, url, ref, paths, timeout):
    dest.mkdir(parents=True)
    git(dest, "init", "--quiet")
    git(dest, "remote", "add", "origin", url)
    # Makes later fetches blobless too, and lets git fetch missing blobs lazily
    git(dest, "config", "remote.origin.promisor", "true")
    git(dest, "config", "remote.origin.partialclonefilter", "blob:none")
    if paths:
        git(dest, "sparse-checkout", "set", "--no-cone", *paths)
    fetch_ref(dest, ref, timeout)


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="fetch-source",
        description="Shallow, blobless clone of an app's source into ROOT/ID. "
                    "Prints JSON with the checked-out commit. An existing clone "
                    "of the same URL is reused, and moved to --ref when one is given.",
    )
    parser.add_argument("id", help="directory name for the clone, e.g. gnome-text-editor")
    parser.add_argument("url", help="git URL")
    parser.add_argument("--ref", help="branch, tag or commit hash (default: the remote HEAD)")
    parser.add_argument("--path", action="append", default=[],
                        help="check out only this path (repeatable), for very large repositories")
    parser.add_argument("--root", default=DEFAULT_ROOT,
                        help=f"where clones live (default {DEFAULT_ROOT}, or $MAPPING_SOURCES)")
    parser.add_argument("--update", action="store_true",
                        help="refetch the ref even when an existing clone is reused")
    parser.add_argument("--timeout", type=int, default=900, help="seconds per git step (default 900)")
    args = parser.parse_args(argv)

    if not ID_RE.match(args.id):
        fail(f"bad id {args.id!r}: use letters, digits, dot, dash and underscore")

    dest = Path(args.root).expanduser() / args.id
    reused = False
    try:
        if (dest / ".git").exists():
            existing = git(dest, "remote", "get-url", "origin")
            if existing != args.url:
                fail(f"{dest} is a clone of a different URL ({existing})", url=args.url)
            reused = True
            if args.path:
                git(dest, "sparse-checkout", "set", "--no-cone", *args.path)
            if args.ref or args.update:
                current = git(dest, "rev-parse", "HEAD")
                if args.update or not (args.ref and current.startswith(args.ref)):
                    fetch_ref(dest, args.ref, args.timeout)
        elif dest.exists() and any(dest.iterdir()):
            fail(f"{dest} exists and is not a git clone")
        else:
            if dest.exists():
                dest.rmdir()
            clone(dest, args.url, args.ref, args.path, args.timeout)
        commit = git(dest, "rev-parse", "HEAD")
    except GitError as exc:
        fail(str(exc), url=args.url)
    except subprocess.TimeoutExpired:
        fail(f"git timed out after {args.timeout} s", url=args.url)

    emit({
        "id": args.id,
        "url": args.url,
        "ref": args.ref,
        "commit": commit,
        "path": str(dest),
        "reused": reused,
        "sparse": args.path,
    })
    return 0
