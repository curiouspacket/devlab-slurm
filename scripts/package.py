#!/usr/bin/env python3
"""Build a deterministic, credential-free ZIP using an explicit file allowlist."""
import hashlib
import io
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FILES = (
    '.dockerignore', '.gitignore', '.python-version', 'Dockerfile', 'Makefile',
    'README.md', 'LAUNCH.md',
    'versions.env', 'pyproject.toml', 'uv.lock', 'poc.py', 'config.example.json',
    'scripts/install-system.sh', 'scripts/bootstrap-tools.sh', 'scripts/run.sh',
    'scripts/image-entrypoint.sh', 'scripts/launch-devlab.sh', 'scripts/package.py',
    'tests/test_poc.py', 'tests/test_launch.py',
)


def build():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in sorted(FILES):
            path = ROOT / name
            if not path.is_file() or path.is_symlink():
                raise ValueError('Missing file or symlink in package allowlist')
            entry = zipfile.ZipInfo('devlab-vscode/' + name, date_time=(2026, 9, 29, 0, 0, 0))
            entry.create_system = 3
            entry.external_attr = 0o100644 << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, path.read_bytes(), compresslevel=9)
    data = buffer.getvalue()
    if not 0 < len(data) <= 65536:
        raise ValueError('ZIP exceeds the 64 KiB injection limit')
    target_dir = ROOT / 'package'
    target_dir.mkdir(exist_ok=True)
    target = target_dir / 'devlab-vscode.zip'
    target.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    target.with_suffix('.zip.sha256').write_text(digest + '  ' + target.name + '\n')
    print('ZIP: {} bytes; SHA-256: {}'.format(len(data), digest))


if __name__ == '__main__':
    build()
