#!/usr/bin/env python3
"""Fail on any word from the private deny list kept outside the repo.

Usage: attribution-scan.py   (run from the repo root)

The list is a text file of regular expressions, one per line; blank lines
and lines starting with # are ignored. It is read from $GM_ATTRIBUTION_WORDS,
or from /home/ravi/fildem-work/attribution-words.txt when that is unset. A
list that is missing, empty or does not compile is a failure, never a pass.

Scans:
  - every tracked file, this scanner and its wrapper included, plus
    untracked files git does not ignore (so a new file fails before it is
    committed)
  - every commit reachable from HEAD: message, author and committer

Exempt: the "label" strings of shortcuts/apps/*.json, which quote an
application's own menu text.

Prints one line per hit and a "summary: " line. Exit 1 on any hit.
"""

import json
import os
import re
import subprocess
import sys

WORDS_ENV = 'GM_ATTRIBUTION_WORDS'
WORDS_DEFAULT = '/home/ravi/fildem-work/attribution-words.txt'
MAPPING_DIR = 'global-menu@unmade.space/shortcuts/apps/'


def fail(reason):
    print(f'summary: {reason}')
    sys.exit(1)


def load_pattern():
    path = os.environ.get(WORDS_ENV) or WORDS_DEFAULT
    try:
        with open(path, encoding='utf-8') as f:
            lines = f.read().splitlines()
    except OSError as e:
        fail(f'deny list not readable at {path}: {e.strerror} (set {WORDS_ENV} to move it)')
    words = [w.strip() for w in lines if w.strip() and not w.lstrip().startswith('#')]
    if not words:
        fail(f'deny list at {path} has no entries')
    try:
        return re.compile('|'.join(f'(?:{w})' for w in words), re.IGNORECASE)
    except re.error as e:
        fail(f'deny list at {path} does not compile: {e}')


def git(*args):
    return subprocess.run(['git', *args], check=True, capture_output=True).stdout


def strip_labels(node):
    if isinstance(node, dict):
        return {k: (None if k == 'label' else strip_labels(v)) for k, v in node.items()}
    if isinstance(node, list):
        return [strip_labels(v) for v in node]
    return node


def file_text(path):
    try:
        with open(path, 'rb') as f:
            data = f.read()
    except (FileNotFoundError, IsADirectoryError):
        return None
    if b'\0' in data[:8192]:
        return None
    text = data.decode('utf-8', errors='replace')
    if path.startswith(MAPPING_DIR) and path.endswith('.json'):
        try:
            text = json.dumps(strip_labels(json.loads(text)), ensure_ascii=False, indent=0)
        except ValueError:
            pass
    return text


def main():
    pattern = load_pattern()
    hits = []
    files = set(git('ls-files', '-z').decode().split('\0'))
    files |= set(git('ls-files', '-z', '--others', '--exclude-standard').decode().split('\0'))
    files.discard('')
    scanned = 0
    for path in sorted(files):
        text = file_text(path)
        if text is None:
            continue
        scanned += 1
        for n, line in enumerate(text.splitlines(), 1):
            m = pattern.search(line)
            if m:
                hits.append(f'{path}:{n}: {m.group(0)!r}: {line.strip()[:160]}')

    log = git('log', '-z', '--format=%H%n%an <%ae>%n%cn <%ce>%n%B').decode()
    commits = [c for c in log.split('\0') if c.strip()]
    for entry in commits:
        sha, _, rest = entry.strip('\n').partition('\n')
        for line in rest.splitlines():
            m = pattern.search(line)
            if m:
                hits.append(f'commit {sha[:10]}: {m.group(0)!r}: {line.strip()[:160]}')

    for h in hits:
        print(h)
    print(f'files scanned: {scanned}, commits scanned: {len(commits)}')
    if hits:
        print(f'summary: {len(hits)} mention(s), first: {hits[0][:200]}')
        return 1
    print(f'summary: no mention in {scanned} files and {len(commits)} commits')
    return 0


if __name__ == '__main__':
    sys.exit(main())
