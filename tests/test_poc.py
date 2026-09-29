import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import poc


class PoCTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.state = self.root / 'state'
        poc.private_dir(self.state)
        poc.private_dir(self.state / 'process-home')
        self.secrets = self.root / 'credentials/secrets.json'
        poc.private_dir(self.secrets.parent)
        poc.save(self.secrets, json.dumps({k: 'CANARY_' + k for k in poc.SECRET_KEYS}))
        self.c = {
            'repo_url': 'https://github.com/example/private.git', 'repo_commit': 'a' * 40,
            'repo_dir': str(self.root / 'repo'),
            'codex': {'base_url': 'https://api.example.com/v1', 'model': 'test'},
            'application': {'base_url': 'https://api.example.com/v1', 'model': 'test'},
            'slurm': {'host': 'login.example.com', 'port': 22, 'user': 'researcher',
                      'known_hosts_file': str(self.root / 'known_hosts')}}
        self.settings = self.root / 'config.json'
        self.settings.write_text(json.dumps(self.c))

    def tearDown(self):
        self.temp.cleanup()

    def test_credentials_permissions_and_symlinks(self):
        self.assertEqual(poc.read_secrets(self.secrets)['github_token'], 'CANARY_github_token')
        self.assertEqual(self.secrets.stat().st_mode & 0o777, 0o600)
        self.secrets.chmod(0o644)
        with self.assertRaises(ValueError): poc.read_secrets(self.secrets)
        link = self.secrets.parent / 'link'
        link.symlink_to(self.secrets)
        with self.assertRaises(OSError): poc.read_secrets(link)

    def test_rejects_secrets_in_urls_and_ssh_injection(self):
        for kind in ('git', 'endpoint', 'ssh'):
            c = json.loads(json.dumps(self.c))
            if kind == 'git': c['repo_url'] = 'https://CANARY@github.com/example/private.git'
            if kind == 'endpoint': c['codex']['base_url'] += '?key=CANARY'
            if kind == 'ssh': c['slurm']['host'] += '\nProxyCommand bad'
            self.settings.write_text(json.dumps(c))
            with self.assertRaises(ValueError): poc.config(self.settings)

    def test_setup_failure_is_redacted_and_latest_status_fails(self):
        capture = io.StringIO()
        with patch('shutil.which', return_value='/tool'), patch.object(poc, 'install_codex', side_effect=RuntimeError('CANARY_FAILURE')):
            with contextlib.redirect_stdout(capture):
                result = poc.setup(self.settings, self.state, self.secrets)
        self.assertEqual(result, 1)
        text = (self.state / 'events.jsonl').read_text() + capture.getvalue()
        self.assertNotIn('CANARY', text)
        self.assertEqual(poc.latest(self.state)['codex'], 'failed')
        self.assertNotIn('ready', poc.latest(self.state))

    def test_existing_repo_is_reused_and_codex_binary_is_verified(self):
        (Path(self.c['repo_dir']) / '.git').mkdir(parents=True)
        edit = Path(self.c['repo_dir']) / 'user-edit'
        edit.write_text('keep this')
        with patch.object(poc, 'run', side_effect=[self.c['repo_url'], self.c['repo_commit']]) as runner:
            poc.repository(self.c, self.state, self.secrets)
        self.assertEqual(runner.call_count, 2)
        self.assertEqual(edit.read_text(), 'keep this')
        # Codex CLI is unpinned: any version the binary reports is accepted.
        with patch.object(poc, 'run', side_effect=['codex-cli 99.99.99', 'v' + poc.PINS['NODE_VERSION']]) as runner:
            poc.install_codex(self.state)
        self.assertEqual(runner.call_count, 2)

    def test_generated_git_helper_scopes_credentials_and_cleans_up(self):
        def fake_run(argv, state, cwd=None, extra=None, **kwargs):
            self.assertNotIn('CANARY', str(argv) + str(extra))
            if 'fetch' in argv:
                helper = extra['GIT_ASKPASS']
                for prompt, expected, code in (
                    ("Username for 'https://github.com':", 'x-access-token', 0),
                    ("Password for 'https://x-access-token@github.com':", 'CANARY_github_token', 0),
                    ("Password for 'https://evil.example':", '', 1)):
                    result = subprocess.run([helper, prompt], env={**os.environ, **extra}, capture_output=True, text=True)
                    self.assertEqual(result.returncode, code)
                    self.assertEqual(result.stdout.strip(), expected)
            return self.c['repo_commit'] if 'rev-parse' in argv else ''
        with patch.object(poc, 'run', side_effect=fake_run):
            poc.repository(self.c, self.state, self.secrets)
        self.assertTrue(Path(self.c['repo_dir']).is_dir())
        self.assertFalse(list(self.state.glob('tmp*')))

    def test_ssh_host_pinning_and_private_generated_files(self):
        key = self.root / 'temporary_test_key'
        poc.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(key)], self.state)
        public = Path(str(key) + '.pub').read_text().split()
        Path(self.c['slurm']['known_hosts_file']).write_text('login.example.com ' + ' '.join(public[:2]) + '\n')
        poc.ssh(self.c, self.state, {'slurm_private_key': key.read_text()})
        effective = poc.run(['ssh', '-G', '-F', str(self.state / 'ssh/config'), 'slurm'], self.state)
        self.assertIn('stricthostkeychecking true', effective)
        self.assertIn('forwardagent no', effective)
        self.assertEqual((self.state / 'ssh/slurm_key').stat().st_mode & 0o777, 0o600)

    def test_launch_passes_only_the_selected_provider_key(self):
        poc.event(self.state, 'run', 'ready', 'complete')
        poc.save(self.state / 'settings.json', json.dumps(self.c))
        for action, args in [('codex', []), ('application', ['python', 'app.py'])]:
            with patch.object(poc.os, 'chdir'), patch.object(poc.os, 'execvpe') as execute:
                poc.launch(action, args, self.state, self.secrets)
            child = execute.call_args.args[2]
            values = json.dumps(child)
            self.assertNotIn('CANARY_github_token', values)
            self.assertNotIn('CANARY_slurm_private_key', values)
            if action == 'codex':
                self.assertEqual(child['POC_CODEX_KEY'], 'CANARY_codex_api_key')
                self.assertNotIn('CANARY_application_api_key', values)
            else:
                self.assertEqual(child['OPENAI_API_KEY'], 'CANARY_application_api_key')
                self.assertNotIn('CANARY_codex_api_key', values)

    def test_validation_failure_redacted_and_setup_readiness_retained(self):
        poc.event(self.state, 'setup-run', 'ready', 'complete')
        poc.save(self.state / 'settings.json', json.dumps(self.c))
        captured = io.StringIO()
        with patch.object(poc, 'probe_provider', side_effect=ValueError('CANARY')), patch.object(poc, 'run', return_value='CANARY'):
            with contextlib.redirect_stdout(captured):
                self.assertEqual(poc.validate(self.state, self.secrets), 1)
        self.assertNotIn('CANARY', captured.getvalue() + (self.state / 'validation.json').read_text())
        self.assertEqual(poc.latest(self.state)['ready'], 'complete')

    def test_provider_config_and_child_env_do_not_contain_secrets(self):
        with patch.dict(os.environ, {'GITHUB_TOKEN': 'CANARY', 'GIT_TRACE': '1', 'OPENAI_API_KEY': 'CANARY'}):
            poc.providers(self.c, self.state)
            self.assertNotIn('CANARY', json.dumps(poc.env(self.state)))
            self.assertNotIn('GIT_TRACE', poc.env(self.state))
        text = (self.state / 'codex/config.toml').read_text()
        self.assertNotIn('CANARY', text)
        self.assertIn('env_key = "POC_CODEX_KEY"', text)


if __name__ == '__main__':
    unittest.main()
