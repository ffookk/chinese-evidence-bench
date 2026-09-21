"""Regression coverage for value-free inspection of tracked text."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch


def load_guard(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().parents[1] / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


privacy = load_guard('privacy_check')
english = load_guard('check_english')


class GuardRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / 'repository'
        self.root.mkdir()
        self.git('init', '-q')
        self.git('config', 'user.name', 'Synthetic Test')
        self.git('config', 'user.email', 'guard@example.invalid')
        self.git('config', 'commit.gpgsign', 'false')

    def git(self, *args):
        return subprocess.run(['git', *args], cwd=self.root, check=True, capture_output=True)

    def stage(self, name, text):
        target = self.root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding='utf-8')
        self.git('add', '--', name)
        return target

    def encoded_email(self):
        value = 'synthetic' + '@' + 'mail.test'
        return ''.join('\\u%04x' % ord(character) for character in value)

    def assert_private_value_found(self, findings):
        self.assertTrue(any('non-example-email' in labels for _, labels in findings))
        self.assertNotIn('synthetic' + '@' + 'mail.test', repr(findings))

    def test_escaped_json_value_in_index_is_checked_after_worktree_cleanup(self):
        target = self.stage('sample.json', '{"value":"' + self.encoded_email() + '"}')
        target.write_text('{}', encoding='utf-8')
        self.assert_private_value_found(privacy.inspect(self.root))

    def test_escaped_json_worktree_value_is_checked(self):
        target = self.stage('sample.json', '{}')
        target.write_text('{"value":"' + self.encoded_email() + '"}', encoding='utf-8')
        self.assert_private_value_found(privacy.inspect(self.root))

    def test_escaped_json_key_and_jsonl_rows_are_checked(self):
        self.stage('sample.JSONL', '{}\n{"' + self.encoded_email() + '":"value"}\n')
        self.assert_private_value_found(privacy.inspect(self.root))

    def test_duplicate_json_members_cannot_hide_private_values(self):
        self.stage('sample.json', '{"value":"' + self.encoded_email() + '","value":"safe"}')
        self.assert_private_value_found(privacy.inspect(self.root))

    def test_historical_json_decode_is_not_skipped_by_shared_text_blob(self):
        content = '{"value":"' + self.encoded_email() + '"}'
        self.stage('a.txt', content)
        self.stage('z.json', content)
        self.git('commit', '-qm', 'Add fictional samples')
        self.git('rm', 'a.txt', 'z.json')
        self.git('commit', '-qm', 'Remove fictional samples')
        findings = privacy.inspect(self.root, history=True)
        self.assertTrue(any(location.startswith('historical-blob-') and 'non-example-email' in labels for location, labels in findings))
        self.assertNotIn('synthetic' + '@' + 'mail.test', repr(findings))

    def test_jsonl_unicode_line_separators_stay_inside_values(self):
        for point in (0x85, 0x2028, 0x2029):
            with self.subTest(point=point):
                self.stage('sample.jsonl', '{"line":"' + chr(point) + '","value":"' + self.encoded_email() + '"}\n')
                self.assert_private_value_found(privacy.inspect(self.root))
                encoded = json.dumps(chr(0x4e2d), ensure_ascii=True)
                self.stage('sample.jsonl', '{"line":"' + chr(point) + '","value":' + encoded + '}\n')
                self.assertIn((1, 'staged-cjk'), english.inspect(self.root))

    def test_jsonl_physical_line_endings_are_consistent(self):
        for separator in ('\n', '\r\n', '\r'):
            with self.subTest(separator=repr(separator)):
                target = self.stage('sample.jsonl', '{}' + separator + '{"value":"' + self.encoded_email() + '"}' + separator)
                target.write_text('{}', encoding='utf-8')
                self.assert_private_value_found(privacy.inspect(self.root))
                encoded = json.dumps(chr(0x4e2d), ensure_ascii=True)
                self.stage('sample.jsonl', '{}' + separator + '{"value":' + encoded + '}' + separator)
                self.assertIn((1, 'staged-cjk'), english.inspect(self.root))

    def test_decoded_windows_paths_are_scanned_without_reserialization(self):
        value = 'C:' + chr(92) + 'Users' + chr(92) + 'FictionalUser' + chr(92) + 'plan.json'
        for document in ({'path': value}, {value: 'example'}, [value]):
            with self.subTest(kind=type(document).__name__):
                target = self.stage('sample.json', json.dumps(document))
                target.write_text('{}', encoding='utf-8')
                findings = privacy.inspect(self.root)
                self.assertTrue(any('local-user-path' in labels for _, labels in findings))
                self.assertNotIn(value, repr(findings))

    def test_duplicate_json_members_cannot_hide_escaped_language(self):
        encoded = json.dumps(chr(0x4e2d), ensure_ascii=True)
        self.stage('sample.json', '{"value":' + encoded + ',"value":"English"}')
        self.assertIn((1, 'staged-cjk'), english.inspect(self.root))

    def linked_parent(self):
        self.stage('nested/sample.txt', 'English sample')
        outside = self.base / 'outside'
        outside.mkdir()
        (outside / 'sample.txt').write_text('Outside input', encoding='utf-8')
        shutil.rmtree(self.root / 'nested')
        (self.root / 'nested').symlink_to(outside, target_is_directory=True)

    def test_privacy_guard_never_reads_through_linked_parent(self):
        self.linked_parent()
        with patch.object(Path, 'read_text', side_effect=AssertionError('Unexpected worktree read')):
            findings = privacy.inspect(self.root)
        self.assertTrue(any('tracked-symlink' in labels for _, labels in findings))

    def test_language_guard_never_reads_through_linked_parent(self):
        self.linked_parent()
        with patch.object(Path, 'read_text', side_effect=AssertionError('Unexpected worktree read')):
            findings = english.inspect(self.root)
        self.assertIn((1, 'symlink-needs-review'), findings)

    @unittest.skipUnless(hasattr(os, 'mkfifo'), 'Named pipes require POSIX')
    def test_language_guard_never_opens_a_worktree_pipe(self):
        target = self.stage('sample.txt', 'English sample')
        target.unlink()
        os.mkfifo(target)
        with patch.object(Path, 'read_text', side_effect=AssertionError('Unexpected special-file read')):
            findings = english.inspect(self.root)
        self.assertIn((1, 'nonregular-needs-review'), findings)

    @unittest.skipUnless(hasattr(os, 'mkfifo'), 'Named pipes require POSIX')
    def test_privacy_guard_reports_nonregular_worktree_objects(self):
        target = self.stage('sample.txt', 'English sample')
        target.unlink()
        os.mkfifo(target)
        findings = privacy.inspect(self.root)
        self.assertTrue(any('nonregular-needs-manual-review' in labels for _, labels in findings))

    def test_normal_json_examples_and_staged_deletion_still_pass(self):
        target = self.stage('sample.json', json.dumps({'value': 'guard@example.invalid'}))
        self.assertEqual(privacy.inspect(self.root), [])
        self.assertEqual(english.inspect(self.root), [])
        target.unlink()
        self.assertEqual(privacy.inspect(self.root), [])
        self.assertEqual(english.inspect(self.root), [])


if __name__ == '__main__':
    unittest.main()
