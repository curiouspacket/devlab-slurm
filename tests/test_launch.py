import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class LaunchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)
        # A local stub records arguments; these tests cannot call Nebius.
        stub = self.path / 'nebius'
        stub.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
        stub.chmod(0o700)
        self.zip = self.path / 'bundle.zip'
        self.zip.write_bytes(b'zip-test')
        self.env = {**os.environ, 'PATH': str(self.path) + os.pathsep + os.environ['PATH'],
                    'PROJECT_ID': 'project-test', 'SUBNET_ID': 'subnet-test',
                    'PLATFORM': 'cpu-e2', 'PRESET': 'test-preset', 'DEVLAB_NAME': 'test',
                    'IDE_PASSWORD_SECRET': 'secret-id@version-id', 'BUNDLE_ZIP': str(self.zip)}

    def tearDown(self):
        self.tmp.cleanup()

    def launch(self, *args):
        return subprocess.run(['bash', str(ROOT / 'scripts/launch-devlab.sh'), *args],
                              env=self.env, capture_output=True, text=True)

    def test_base_uses_secret_reference_digest_and_dry_run(self):
        result = self.launch('base')
        self.assertEqual(result.returncode, 0, result.stderr)
        args = result.stdout.splitlines()
        self.assertEqual(args[:3], ['ai', 'devlab', 'create'])
        self.assertIn('--dry-run', args)
        self.assertNotIn('--async', args)
        self.assertNotIn('--input', args)
        self.assertIn('PASSWORD=secret-id@version-id', args)
        self.assertIn('@sha256:', args[args.index('--image') + 1])
        self.assertIn(str(self.zip) + ':/opt/injected/devlab-vscode.zip', args)

    def test_image_requires_digest_and_supports_registry_reference(self):
        self.env['CUSTOM_IMAGE'] = 'registry.example/image:mutable'
        self.assertNotEqual(self.launch('image').returncode, 0)
        self.env['CUSTOM_IMAGE'] = 'registry.example/image@sha256:' + 'a' * 64
        self.env['REGISTRY_SECRET'] = 'registry-secret@version'
        result = self.launch('image', '--create')
        self.assertEqual(result.returncode, 0, result.stderr)
        args = result.stdout.splitlines()
        self.assertIn('--async', args)
        self.assertIn('registry-secret@version', args)
        self.assertNotIn('--inject-file', args)

    def test_oversized_zip_refused_without_calling_nebius(self):
        self.zip.write_bytes(b'x' * 65537)
        result = self.launch('base', '--create')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '')


if __name__ == '__main__':
    unittest.main()
