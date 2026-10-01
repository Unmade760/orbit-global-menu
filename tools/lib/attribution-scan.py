#!/usr/bin/env python3
"""Fail on any mention of an AI assistant, model or agent in the repo.

Usage: attribution-scan.py   (run from the repo root)

Scans:
  - every tracked file, plus untracked files git does not ignore (so a new
    file fails before it is committed)
  - every commit reachable from HEAD: message, author and committer

Exempt: this scanner and tools/checks/attribution.sh, which have to spell
the names, and the "label" strings of shortcuts/apps/*.json, which quote an
application's own menu text (an editor can have a "Toggle Assistant" item).

Prints one line per hit and a "summary: " line. Exit 1 on any hit.
"""

import json
import re
import subprocess
import sys

PATTERN = re.compile(
    r'\b(?:claude|anthropic|openai|chatgpt|gpt-?\d|gemini|antigravity|copilot'
    r'|codex|llms?|subagents?|large language models?|language models?'
    r'|ai[- ]generated|ai[- ]assisted|generated (?:with|by) (?:an? )?ai'
    r'|ai (?:assistant|agent|model)s?)\b'
    r'|noreply@anthropic',
    re.IGNORECASE,
)
SELF = {'tools/lib/attribution-scan.py', 'tools/checks/attribution.sh'}
MAPPING_DIR = 'global-menu@unmade.space/shortcuts/apps/'


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
    hits = []
    files = set(git('ls-files', '-z').decode().split('\0'))
    files |= set(git('ls-files', '-z', '--others', '--exclude-standard').decode().split('\0'))
    files.discard('')
    scanned = 0
    for path in sorted(files - SELF):
        text = file_text(path)
        if text is None:
            continue
        scanned += 1
        for n, line in enumerate(text.splitlines(), 1):
            m = PATTERN.search(line)
            if m:
                hits.append(f'{path}:{n}: {m.group(0)!r}: {line.strip()[:160]}')

    log = git('log', '-z', '--format=%H%n%an <%ae>%n%cn <%ce>%n%B').decode()
    commits = [c for c in log.split('\0') if c.strip()]
    for entry in commits:
        sha, _, rest = entry.strip('\n').partition('\n')
        for line in rest.splitlines():
            m = PATTERN.search(line)
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
