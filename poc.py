#!/usr/bin/env python3
"""Repeatable setup for a trusted, single-user internal DevLab PoC."""
import argparse
import datetime
import getpass
import fcntl
import json
import os
from pathlib import Path
import re
import resource
import shutil
import stat
import subprocess
import sys
import tempfile
import uuid
from urllib.parse import urlsplit
import urllib.request

ROOT = Path(__file__).resolve().parent
PINS = dict(line.split('=', 1) for line in (ROOT / 'versions.env').read_text().splitlines() if line and not line.startswith('#'))
TOOLS = Path(os.environ.get('POC_TOOLS_DIR', str(Path.home() / '.local/share/devlab-poc/toolchain')))
STATE = Path(os.environ.get('POC_STATE_DIR', str(Path.home() / '.local/share/devlab-poc/state')))
SECRETS = Path.home() / '.config/devlab-poc/secrets.json'
STEPS = ('preflight', 'codex', 'repository', 'providers', 'ssh', 'ready')
SECRET_KEYS = {'github_token', 'codex_api_key', 'application_api_key', 'slurm_private_key'}


def check(ok):
    if not ok:
        raise ValueError('Validation failed')


def private_dir(path):
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    s = path.lstat()
    check(stat.S_ISDIR(s.st_mode) and s.st_uid == os.getuid() and s.st_mode & 0o077 == 0)


def save(path, text):
    # Atomic replacement creates a fresh 0600 file; does not follow target symlinks.
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as out:
        temp = Path(out.name)
        try:
            os.chmod(temp, 0o600)
            out.write(text)
            out.flush()
            os.fsync(out.fileno())
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)


def read_secrets(path):
    private_dir(path.parent)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd) as src:
        s = os.fstat(src.fileno())
        check(stat.S_ISREG(s.st_mode) and s.st_uid == os.getuid() and s.st_nlink == 1)
        check(s.st_mode & 0o077 == 0 and s.st_size < 100000)
        data = json.load(src)
    check(set(data) == SECRET_KEYS)
    for name, value in data.items():
        check(isinstance(value, str) and bool(value.strip()) and '\x00' not in value)
        if name != 'slurm_private_key':
            check(not any(ch.isspace() for ch in value))
    return data


def init_secrets(path):
    check(sys.stdin.isatty())
    check(not path.exists() and not path.is_symlink())
    private_dir(path.parent)
    values = {name: getpass.getpass(label) for name, label in (
        ('github_token', 'GitHub read token (hidden): '),
        ('codex_api_key', 'Codex provider key (hidden): '),
        ('application_api_key', 'Token Factory/application provider key (hidden): '))}
    key = Path(input('Path to dedicated Slurm private key: ').strip()).expanduser()
    check(key.is_file() and not key.is_symlink() and key.stat().st_mode & 0o077 == 0)
    values['slurm_private_key'] = key.read_text()
    check(all(values.values()))
    save(path, json.dumps(values))
    print('Credentials saved privately outside the repository.')


def config(path):
    c = json.loads(path.read_text())
    check(set(c) == {'repo_url', 'repo_commit', 'repo_dir', 'codex', 'application', 'slurm'})
    check('REPLACE' not in json.dumps(c))
    check(re.fullmatch(r'https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\.git', c['repo_url']))
    check(re.fullmatch(r'[0-9a-f]{40}', c['repo_commit']))
    check(Path(c['repo_dir']).is_absolute() and c['repo_dir'] != '/')
    for name in ('codex', 'application'):
        p = c[name]
        check(set(p) == {'base_url', 'model'})
        u = urlsplit(p['base_url'])
        check(u.scheme == 'https' and u.hostname and not u.username and not u.password)
        check(not u.query and not u.fragment and not any(x.isspace() for x in p['base_url']))
        check(re.fullmatch(r'[A-Za-z0-9_./:-]+', p['model']))
    s = c['slurm']
    check(set(s) == {'host', 'port', 'user', 'known_hosts_file'})
    check(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]*', s['host']))
    check(re.fullmatch(r'[A-Za-z_][A-Za-z0-9_-]*', s['user']))
    check(type(s['port']) is int and 1 <= s['port'] <= 65535)
    # Make relative host-file paths relative to the configuration, not the shell.
    hosts = Path(s['known_hosts_file']).expanduser()
    s['known_hosts_file'] = str((path.parent / hosts).resolve())
    return c


def env(state):
    return {'PATH': os.environ.get('PATH', os.defpath), 'HOME': str(state / 'process-home'),
            'LANG': 'C.UTF-8', 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null',
            'GIT_TERMINAL_PROMPT': '0', 'GIT_LFS_SKIP_SMUDGE': '1',
            'UV_PYTHON_INSTALL_DIR': str(TOOLS / 'python'), 'UV_PYTHON_DOWNLOADS': 'never',
            'UV_CACHE_DIR': str(state / 'application-uv-cache')}


def run(argv, state, cwd=None, extra=None, timeout=300):
    child_env = env(state)
    child_env.update(extra or {})
    result = subprocess.run(argv, env=child_env, cwd=cwd, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=timeout)
    check(result.returncode == 0)
    return result.stdout.decode().strip()


def git():
    return ['git', '-c', 'credential.helper=', '-c', 'core.hooksPath=/dev/null',
            '-c', 'http.followRedirects=false', '-c', 'protocol.allow=never',
            '-c', 'protocol.https.allow=always', '-c', 'submodule.recurse=false']


def install_codex(state):
    # Installation is credential-free and separate: make tools / Docker build.
    # Codex CLI is intentionally unpinned; only confirm the binary runs.
    check(run([str(TOOLS / 'codex/node_modules/.bin/codex'), '--version'], state).startswith('codex-cli '))
    check(run(['node', '--version'], state) == 'v' + PINS['NODE_VERSION'])


def repository(c, state, secrets):
    dest = Path(c['repo_dir'])
    if dest.exists() or dest.is_symlink():
        check(not dest.is_symlink() and (dest / '.git').is_dir() and not (dest / '.git').is_symlink())
        check(run(git() + ['remote', 'get-url', 'origin'], state, dest) == c['repo_url'])
        check(run(git() + ['rev-parse', 'HEAD'], state, dest) == c['repo_commit'])
        return  # Keep user edits. Do not pull or reset automatically.
    dest.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.poc-checkout-', dir=dest.parent))
    try:
        with tempfile.TemporaryDirectory(dir=state) as temp:
            helper = Path(temp) / 'askpass'
            # Only a path is in Git's environment; the helper reads the token.
            source = ('#!' + sys.executable + '\nimport json, os, sys\n'
                      'p = sys.argv[1]\n'
                      'if p.startswith("Username for ") and "\'https://github.com\'" in p:\n'
                      ' print("x-access-token")\n'
                      'elif p.startswith("Password for ") and "\'https://x-access-token@github.com\'" in p:\n'
                      ' with open(os.environ["POC_SECRETS_FILE"]) as f: print(json.load(f)["github_token"])\n'
                      'else: sys.exit(1)\n')
            save(helper, source)
            helper.chmod(0o700)
            extra = {'GIT_ASKPASS': str(helper), 'POC_SECRETS_FILE': str(secrets.resolve())}
            run(git() + ['init', str(stage)], state)
            run(git() + ['remote', 'add', 'origin', c['repo_url']], state, stage)
            run(git() + ['fetch', '--depth=1', 'origin', c['repo_commit']], state, stage, extra)
            run(git() + ['checkout', '--detach', 'FETCH_HEAD'], state, stage)
            check(run(git() + ['rev-parse', 'HEAD'], state, stage) == c['repo_commit'])
            stage.rename(dest)
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def providers(c, state):
    private_dir(state / 'codex')
    p = c['codex']
    save(state / 'codex/config.toml', '\n'.join([
        'model = ' + json.dumps(p['model']), 'model_provider = "poc"',
        'approval_policy = "on-request"', 'sandbox_mode = "workspace-write"',
        '[shell_environment_policy]', 'inherit = "core"',
        'exclude = ["*KEY*", "*TOKEN*", "*SECRET*"]',
        '[model_providers.poc]', 'name = "PoC provider"',
        'base_url = ' + json.dumps(p['base_url']),
        'env_key = "POC_CODEX_KEY"', 'wire_api = "responses"', 'requires_openai_auth = false', '']))


def ssh(c, state, values):
    private_dir(state / 'ssh')
    key = state / 'ssh/slurm_key'
    save(key, values['slurm_private_key'])
    run(['ssh-keygen', '-y', '-P', '', '-f', str(key)], state)
    s = c['slurm']
    known = state / 'ssh/known_hosts'
    save(known, Path(s['known_hosts_file']).read_text())
    host = s['host'] if s['port'] == 22 else '[{}]:{}'.format(s['host'], s['port'])
    run(['ssh-keygen', '-F', host, '-f', str(known)], state)
    # Quote filesystem paths for OpenSSH, including possible spaces in the home.
    quote = lambda p: json.dumps(str(p))
    save(state / 'ssh/config', '\n'.join([
        'Host slurm', '  HostName ' + s['host'], '  User ' + s['user'], '  Port ' + str(s['port']),
        '  IdentityFile ' + quote(key), '  UserKnownHostsFile ' + quote(known),
        '  GlobalKnownHostsFile /dev/null', '  StrictHostKeyChecking yes',
        '  IdentitiesOnly yes', '  IdentityAgent none', '  ForwardAgent no',
        '  BatchMode yes', '  PasswordAuthentication no', '  KbdInteractiveAuthentication no',
        '  ConnectTimeout 15', '']))


def event(state, run_id, step, status):
    check(step in STEPS and status in ('started', 'complete', 'failed'))
    row = {'time': datetime.datetime.now(datetime.timezone.utc).isoformat(),
           'run_id': run_id, 'step': step, 'status': status}
    fd = os.open(state / 'events.jsonl', os.O_CREAT | os.O_APPEND | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'a') as log:
        s = os.fstat(log.fileno())
        check(stat.S_ISREG(s.st_mode) and s.st_uid == os.getuid() and s.st_nlink == 1 and s.st_mode & 0o077 == 0)
        log.write(json.dumps(row) + '\n')
    print('{}: {}'.format(step, status), flush=True)


def setup(settings, state, secrets):
    private_dir(state)
    private_dir(state / 'process-home')
    step, run_id = 'preflight', str(uuid.uuid4())
    try:
        event(state, run_id, step, 'started')
        c = config(settings)
        repo = Path(c['repo_dir']).resolve()
        check(not state.resolve().is_relative_to(repo) and not secrets.resolve().is_relative_to(repo))
        check(all(shutil.which(tool) for tool in ('git', 'node', 'npm', 'ssh', 'ssh-keygen')))
        values = read_secrets(secrets)
        event(state, run_id, step, 'complete')
        for step, task in (
            ('codex', lambda: install_codex(state)),
            ('repository', lambda: repository(c, state, secrets)),
            ('providers', lambda: providers(c, state)),
            ('ssh', lambda: ssh(c, state, values))):
            event(state, run_id, step, 'started')
            task()
            event(state, run_id, step, 'complete')
        save(state / 'settings.json', json.dumps(c))
        event(state, run_id, 'ready', 'complete')
        return 0
    except Exception:
        event(state, run_id, step, 'failed')
        return 1


def latest(state):
    rows = [json.loads(line) for line in (state / 'events.jsonl').read_text().splitlines()]
    return {r['step']: r['status'] for r in rows if r['run_id'] == rows[-1]['run_id']}


def launch(action, args, state, secrets):
    check(latest(state).get('ready') == 'complete')
    c = json.loads((state / 'settings.json').read_text())
    child_env = env(state)
    child_env['HOME'] = str(Path.home())
    if action == 'codex':
        child_env.update(CODEX_HOME=str(state / 'codex'), POC_CODEX_KEY=read_secrets(secrets)['codex_api_key'])
        argv = [str(TOOLS / 'codex/node_modules/.bin/codex')] + args
    elif action == 'application':
        check(bool(args))
        child_env.update(OPENAI_API_KEY=read_secrets(secrets)['application_api_key'],
                         NEBIUS_API_KEY=read_secrets(secrets)['application_api_key'],
                         OPENAI_BASE_URL=c['application']['base_url'], MODEL=c['application']['model'])
        argv = args
    else:
        argv = ['ssh', '-F', str(state / 'ssh/config'), 'slurm'] + args
    os.chdir(c['repo_dir'])
    os.execvpe(argv[0], argv, child_env)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError('Redirects disabled')


def probe_provider(provider, key):
    # A small authenticated read verifies connectivity, not inference quality.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    request = urllib.request.Request(provider['base_url'].rstrip('/') + '/models',
                                     headers={'Authorization': 'Bearer ' + key})
    with opener.open(request, timeout=20) as response:
        check(response.status == 200)
        data = json.loads(response.read(1024 * 1024))
        check(any(m.get('id') == provider['model'] for m in data.get('data', [])))


def validate(state, secrets):
    check(latest(state).get('ready') == 'complete')
    c = json.loads((state / 'settings.json').read_text())
    values = read_secrets(secrets)
    results = {}
    tasks = (
        ('codex_provider', lambda: probe_provider(c['codex'], values['codex_api_key'])),
        ('application_provider', lambda: probe_provider(c['application'], values['application_api_key'])),
        ('slurm_access', lambda: run(['ssh', '-F', str(state / 'ssh/config'), 'slurm', 'sinfo', '--noheader'], state, timeout=30)),
    )
    for step, task in tasks:
        try:
            task()
            results[step] = 'complete'
        except Exception:
            results[step] = 'failed'
        print(step + ': ' + results[step], flush=True)
    save(state / 'validation.json', json.dumps({'time': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'checks': results}))
    return int('failed' in results.values())


def main():
    os.umask(0o077)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    p = argparse.ArgumentParser()
    p.add_argument('--config', type=Path, default=(Path('config.json') if Path('config.json').exists() else Path.home() / '.config/devlab-poc/config.json'))
    p.add_argument('--state-dir', type=Path, default=STATE)
    p.add_argument('--secrets-file', type=Path, default=SECRETS)
    p.add_argument('action', choices=['secrets', 'setup', 'status', 'codex', 'application', 'slurm', 'validate'])
    p.add_argument('args', nargs=argparse.REMAINDER)
    a = p.parse_args()
    a.state_dir = a.state_dir.expanduser().resolve()
    a.secrets_file = a.secrets_file.expanduser().absolute()
    if a.action == 'secrets':
        init_secrets(a.secrets_file)
    elif a.action == 'setup':
        private_dir(a.state_dir)
        fd = os.open(a.state_dir / 'setup.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return setup(a.config, a.state_dir, a.secrets_file)
    elif a.action == 'validate':
        return validate(a.state_dir, a.secrets_file)
    elif a.action == 'status':
        summary = latest(a.state_dir)
        for step in STEPS:
            state = summary.get(step, 'pending')
            check(state in ('pending', 'started', 'complete', 'failed'))
            print('{}: {}'.format(step, state))
        return 0 if summary.get('ready') == 'complete' else 1
    else:
        launch(a.action, a.args, a.state_dir, a.secrets_file)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (Exception, KeyboardInterrupt):
        print('Failed. Check the configuration, file permissions, and last setup step; raw output is suppressed.', file=sys.stderr)
        sys.exit(1)
