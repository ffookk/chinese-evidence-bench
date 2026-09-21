#!/usr/bin/env python3
"""Best-effort privacy guard for tracked text, reachable history and metadata.

Reports rule names only, never the matching values. This is a heuristic, not
a guarantee that arbitrary personal information or every credential is found.
"""
import argparse
import json
import re
import subprocess
from pathlib import Path

RULES = {
    'local-user-path': re.compile(r'/(?:Users|home)/[^/\s]+|[A-Za-z]:\\Users\\[^\\\s]+'),
    'private-chat-link': re.compile(r'https?://(?:chatgpt\.com|chat\.openai\.com)/c/'),
    'private-key': re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----'),
    'github-token': re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})\b'),
    'provider-token': re.compile(r'\bsk-(?:proj-|ant-)?[A-Za-z0-9_-]{24,}\b'),
    'aws-access-key': re.compile(r'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b'),
    'slack-token': re.compile(r'\bxox[baprs]-[A-Za-z0-9-]{20,}\b'),
    'url-credential': re.compile(r'https?://[^\s/:@]+:[^\s/@]+@'),
}
EMAIL = re.compile(r'(?<![\w.+-])[A-Za-z0-9_.+%-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})(?![\w.-])')
EXAMPLE_DOMAINS = {'example.com', 'example.org', 'example.net', 'example.invalid'}


def scan_text(text):
    found = {name for name, rule in RULES.items() if rule.search(text)}
    for match in EMAIL.finditer(text):
        domain = match.group(1).lower()
        if domain not in EXAMPLE_DOMAINS and not domain.endswith('.invalid') and domain != 'users.noreply.github.com' and match.group(0).lower() != 'noreply@github.com':
            found.add('non-example-email')
    return found


def scan_content(text, suffix=''):
    found = scan_text(text)
    if suffix.lower() not in {'.json', '.jsonl'}:
        return found
    documents = re.split(r'\r\n|\r|\n', text) if suffix.lower() == '.jsonl' else [text]
    for document in documents:
        try:
            decoded = json.loads(document, object_pairs_hook=list)
        except (ValueError, RecursionError):
            continue  # Format validation handles malformed JSON separately.
        pending = [decoded]
        while pending:
            value = pending.pop()
            if isinstance(value, str):
                found.update(scan_text(value))
            elif isinstance(value, (list, tuple)):
                pending.extend(value)
    return found


def linked_worktree_path(root, name):
    path = root
    for part in Path(name).parts:
        path = path / part
        if path.is_symlink():
            return True
    return False


def unsafe_filename(name):
    path = Path(name)
    return (path.name == '.env' or path.name.startswith('.env.') and path.name not in {'.env.example', '.env.sample'}
            or path.name in {'id_rsa', 'id_ed25519', 'credentials.json'}
            or any(part in {'private-input', 'private-output', 'local-data'} for part in path.parts))


def git(root, *args):
    result = subprocess.run(['git', *args], cwd=root, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError('Git inspection failed; inspect repository state locally.')
    return result.stdout


def inspect(root, history=False):
    findings = []
    entries = git(root, 'ls-files', '--stage', '-z').split(b'\0')
    for index, entry in enumerate(filter(None, entries), 1):
        meta, raw_name = entry.split(b'\t', 1)
        mode, oid, stage = meta.split(b' ')
        if stage != b'0':
            raise RuntimeError('Resolve index conflicts before inspecting content.')
        name = raw_name.decode('utf-8')
        labels = scan_text(name)
        if unsafe_filename(name):
            labels.add('sensitive-filename')
        # A later working-tree edit must not hide an earlier staged value.
        staged = git(root, 'cat-file', 'blob', oid.decode('ascii'))
        try:
            staged_labels = scan_content(staged.decode('utf-8'), Path(name).suffix)
        except UnicodeDecodeError:
            staged_labels = {'binary-needs-manual-review'}
        if mode == b'120000':
            staged_labels.add('tracked-symlink')
        if staged_labels:
            findings.append((f'index-file-{index}', sorted(staged_labels)))
        path = root / name
        if linked_worktree_path(root, name):
            labels.add('tracked-symlink')
        elif path.is_file():
            try:
                labels.update(scan_content(path.read_text(encoding='utf-8'), path.suffix))
            except UnicodeDecodeError:
                labels.add('binary-needs-manual-review')
        elif path.exists():
            labels.add('nonregular-needs-manual-review')
        if labels:
            findings.append((f'tracked-file-{index}', sorted(labels)))
    if history:
        metadata = git(root, 'log', '--all', '--format=%B%n%an <%ae>%n%cn <%ce>').decode('utf-8')
        labels = scan_text(metadata)
        if labels:
            findings.append(('commit-metadata', sorted(labels)))
        seen = set()
        commits = git(root, 'rev-list', '--all').decode('ascii').splitlines()
        for commit in commits:
            entries = git(root, 'ls-tree', '-r', '-z', commit).split(b'\0')
            for entry in filter(None, entries):
                meta, raw_name = entry.split(b'\t', 1)
                mode, kind, oid = meta.split(b' ')
                name = raw_name.decode('utf-8')
                name_labels = scan_text(name)
                if name_labels:
                    findings.append(('historical-filename', sorted(name_labels)))
                if unsafe_filename(name):
                    findings.append(('historical-filename', ['sensitive-filename']))
                if mode == b'120000':
                    findings.append(('historical-symlink', ['tracked-symlink']))
                content_key = (oid, Path(name).suffix.lower())
                if kind != b'blob' or content_key in seen:
                    continue
                seen.add(content_key)
                raw = git(root, 'cat-file', 'blob', oid.decode('ascii'))
                try:
                    labels = scan_content(raw.decode('utf-8'), Path(name).suffix)
                except UnicodeDecodeError:
                    labels = {'binary-needs-manual-review'}
                if labels:
                    findings.append((f'historical-blob-{len(seen)}', sorted(labels)))
    return findings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--history', action='store_true', help='Also inspect all reachable commits and metadata')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    try:
        findings = inspect(root, args.history)
    except (RuntimeError, OSError, UnicodeError):
        print('Privacy inspection could not finish; no sensitive values were printed.')
        return 2
    for location, labels in findings:
        print(f'{location}: {", ".join(labels)}')
    if findings:
        print('Privacy check failed. Review the flagged content locally; do not paste it into an issue or log.')
        return 1
    print('Privacy checks passed for the inspected tracked text' + (' and reachable history.' if args.history else '.'))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
