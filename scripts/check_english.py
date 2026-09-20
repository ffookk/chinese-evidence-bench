#!/usr/bin/env python3
"""Check the English contribution policy for current tracked text.

This guard detects CJK scripts, including decoded JSON values. It is not a
general language classifier: English wording still needs human review.
Historical revisions and GitHub collaboration text are outside this check.
Diagnostics contain only file indices and rule names, never input values.
"""
import json
import re
import subprocess
from pathlib import Path

CJK = re.compile(r'[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af\uf900-\ufaff\U00020000-\U000323af]')


def has_cjk(text, suffix=''):
    if CJK.search(text):
        return True
    documents = text.splitlines() if suffix.lower() == '.jsonl' else [text]
    if suffix.lower() in {'.json', '.jsonl'}:
        for document in documents:
            try:
                decoded = json.loads(document)
            except (ValueError, RecursionError):
                continue  # The project's format checks report invalid JSON.
            if CJK.search(json.dumps(decoded, ensure_ascii=False)):
                return True
    return False


def git(root, *args):
    result = subprocess.run(['git', *args], cwd=root, capture_output=True)
    if result.returncode:
        raise RuntimeError('Git inspection failed.')
    return result.stdout


def inspect(root):
    findings = []
    entries = git(root, 'ls-files', '--stage', '-z').split(b'\0')
    for index, entry in enumerate(filter(None, entries), 1):
        metadata, raw_name = entry.split(b'\t', 1)
        mode, oid, stage = metadata.split(b' ')
        if stage != b'0':
            raise RuntimeError('Resolve index conflicts before checking language.')
        name = raw_name.decode('utf-8')
        if has_cjk(name):
            findings.append((index, 'filename-cjk'))
        if mode == b'120000':
            findings.append((index, 'symlink-needs-review'))
            continue
        path = root / name
        staged = git(root, 'cat-file', 'blob', oid.decode('ascii'))
        try:
            if has_cjk(staged.decode('utf-8'), path.suffix):
                findings.append((index, 'staged-cjk'))
            if path.is_symlink():
                findings.append((index, 'symlink-needs-review'))
            elif path.exists() and has_cjk(path.read_text(encoding='utf-8'), path.suffix):
                findings.append((index, 'working-tree-cjk'))
        except UnicodeError:
            findings.append((index, 'binary-needs-review'))
    return findings


def main():
    try:
        findings = inspect(Path(__file__).resolve().parents[1])
    except (RuntimeError, OSError, UnicodeError):
        print('English policy inspection could not finish; no input values were printed.')
        return 2
    for index, rule in findings:
        print(f'tracked-file-{index}: {rule}')
    if findings:
        print('English policy check failed. Review the current tracked content locally.')
        return 1
    print('English policy check passed for current tracked text; manual language review is still required.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
