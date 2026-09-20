import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('privacy_check', Path(__file__).resolve().parents[1] / 'scripts' / 'privacy_check.py')
privacy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(privacy)


class PrivacyGuardTests(unittest.TestCase):
    def test_example_and_noreply_addresses_are_allowed(self):
        self.assertEqual(privacy.scan_text('person@example.invalid account@users.noreply.github.com'), set())

    def test_personal_address_is_flagged_without_returning_value(self):
        sample = 'synthetic' + '@' + 'mail.test'
        self.assertEqual(privacy.scan_text(sample), {'non-example-email'})

    def test_private_path_and_chat_link_are_flagged(self):
        sample = '/' + 'Users' + '/synthetic' + ' https://chatgpt.com/' + 'c/' + 'synthetic'
        self.assertEqual(privacy.scan_text(sample), {'local-user-path', 'private-chat-link'})

    def test_token_and_private_key_patterns(self):
        sample = 'ghp' + '_' + 'x' * 40
        key = '-----BEGIN ' + 'PRIVATE KEY-----'
        self.assertEqual(privacy.scan_text(sample + '\n' + key), {'github-token', 'private-key'})

    def test_sensitive_filenames(self):
        self.assertTrue(privacy.unsafe_filename('.env'))
        self.assertTrue(privacy.unsafe_filename('private-output/plan.html'))
        self.assertFalse(privacy.unsafe_filename('.env.example'))

    def test_index_is_checked_even_if_worktree_was_cleaned(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
            sample = 'synthetic' + '@' + 'mail.test'
            (root / 'sample.txt').write_text(sample)
            subprocess.run(['git', 'add', 'sample.txt'], cwd=root, check=True)
            (root / 'sample.txt').write_text('safe example')
            findings = privacy.inspect(root)
            self.assertTrue(any(location.startswith('index-file-') and 'non-example-email' in labels for location, labels in findings))
            self.assertNotIn(sample, str(findings))

    def test_deleted_historical_filename_is_checked(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            def run(*args):
                subprocess.run(['git', *args], cwd=root, check=True, capture_output=True)
            run('init', '-q')
            run('config', 'user.name', 'Synthetic Test')
            run('config', 'user.email', 'guard@example.invalid')
            run('config', 'commit.gpgsign', 'false')
            name = 'synthetic' + '@' + 'mail.test'
            (root / name).write_text('safe example')
            run('add', '--', name)
            run('commit', '-qm', 'synthetic history')
            run('rm', '--', name)
            run('commit', '-qm', 'remove example')
            findings = privacy.inspect(root, history=True)
            self.assertIn(('historical-filename', ['non-example-email']), findings)
            self.assertNotIn(name, str(findings))


if __name__ == '__main__':
    unittest.main()
