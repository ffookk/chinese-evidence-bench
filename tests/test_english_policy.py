import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('check_english', Path(__file__).resolve().parents[1] / 'scripts' / 'check_english.py')
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)


class EnglishPolicyTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True, capture_output=True)

    def stage(self, name, content):
        (self.root / name).write_text(content, encoding='utf-8')
        subprocess.run(['git', 'add', '--', name], cwd=self.root, check=True, capture_output=True)

    def test_staged_text_cannot_be_hidden_by_clean_working_text(self):
        self.stage('sample.md', chr(0x4e2d))
        (self.root / 'sample.md').write_text('English replacement', encoding='utf-8')
        self.assertIn((1, 'staged-cjk'), guard.inspect(self.root))

    def test_escaped_json_values_are_checked(self):
        self.stage('sample.json', json.dumps({'sample': chr(0x4e2d)}, ensure_ascii=True))
        self.assertIn((1, 'staged-cjk'), guard.inspect(self.root))

    def test_filename_is_checked_without_echoing_its_value(self):
        self.stage(chr(0x4e2d) + '.md', 'English content')
        self.assertIn((1, 'filename-cjk'), guard.inspect(self.root))
        self.assertNotIn(chr(0x4e2d), repr(guard.inspect(self.root)))

    def test_untracked_private_content_is_outside_scope(self):
        self.stage('sample.md', 'English text with an em dash ' + chr(0x2014) + ' and a scientific symbol ' + chr(0x3bc))
        (self.root / 'private-draft.json').write_text(chr(0x4e2d), encoding='utf-8')
        self.assertEqual(guard.inspect(self.root), [])


if __name__ == '__main__':
    unittest.main()
