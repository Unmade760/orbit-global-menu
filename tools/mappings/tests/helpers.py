"""Shared test helpers: tool paths, a throwaway git repository, CLI runner."""

import json
import os
import subprocess
import tempfile
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent
BIN = TOOLS / "bin"
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def run_cli(name, *args, check=False, env=None):
    """Run bin/<name> and return (exit code, parsed JSON stdout or None, stderr)."""
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    proc = subprocess.run(
        [str(BIN / name), *map(str, args)],
        capture_output=True, text=True, env=full_env, timeout=300,
    )
    try:
        data = json.loads(proc.stdout) if proc.stdout.strip() else None
    except json.JSONDecodeError:
        data = None
    if check and proc.returncode != 0:
        raise AssertionError(f"{name} exited {proc.returncode}: {proc.stderr}\n{proc.stdout}")
    return proc.returncode, data, proc.stderr


def git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True, capture_output=True, text=True,
    ).stdout.strip()


def make_repo(files):
    """A git repository with one commit holding `files` ({path: text}).

    Configured so shallow, blobless and by-hash fetches over file:// work
    the way they do against GitHub and GitLab. Returns (TemporaryDirectory,
    repo path, commit hash).
    """
    tmp = tempfile.TemporaryDirectory()
    repo = Path(tmp.name) / "upstream"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "uploadpack.allowFilter", "true")
    git(repo, "config", "uploadpack.allowAnySHA1InWant", "true")
    for rel, text in files.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "fixture")
    return tmp, repo, git(repo, "rev-parse", "HEAD")
