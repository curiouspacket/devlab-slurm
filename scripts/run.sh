#!/usr/bin/env bash
set -euo pipefail
set +x
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
source "$ROOT/versions.env"
TOOLS=${POC_TOOLS_DIR:-$HOME/.local/share/devlab-poc/toolchain}
STATE=${POC_STATE_DIR:-$HOME/.local/share/devlab-poc/state}
[[ -x "$TOOLS/uv/uv" ]] || { echo 'Run bash scripts/bootstrap-tools.sh first.' >&2; exit 1; }
export POC_TOOLS_DIR="$TOOLS" POC_STATE_DIR="$STATE"
export PATH="$TOOLS/uv:$TOOLS/nvm/versions/node/v$NODE_VERSION/bin:$TOOLS/codex/node_modules/.bin:$TOOLS/nebius:/usr/local/bin:/usr/bin:/bin"
export UV_PYTHON_INSTALL_DIR="$TOOLS/python" UV_PYTHON_DOWNLOADS=never
export UV_PROJECT_ENVIRONMENT="$STATE/venv" UV_CACHE_DIR="$STATE/uv-cache"
export UV_NO_PROGRESS=1 UV_NO_CONFIG=1
umask 077
mkdir -p "$STATE"
cd "$ROOT"
# Rebuild only the small stdlib-only virtual environment; downloads are prohibited here.
if [[ ${1:-} == package ]]; then
  exec "$TOOLS/uv/uv" run --locked --python "$PYTHON_VERSION" --project "$ROOT" python scripts/package.py
fi
if [[ ${1:-} == test ]]; then
  exec "$TOOLS/uv/uv" run --locked --python "$PYTHON_VERSION" --project "$ROOT" python -m unittest discover -s tests -v
fi
exec "$TOOLS/uv/uv" run --locked --python "$PYTHON_VERSION" --project "$ROOT" python "$ROOT/poc.py" "$@"
