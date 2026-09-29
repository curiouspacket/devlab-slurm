#!/usr/bin/env bash
set -Eeuo pipefail
set +x
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
TOOLS=${POC_TOOLS_DIR:-$HOME/.local/share/devlab-poc/toolchain}
if [[ ${POC_CLEAN_ENV:-} != 1 ]]; then
  exec env -i HOME="$HOME" PATH=/usr/local/bin:/usr/bin:/bin POC_CLEAN_ENV=1     POC_TOOLS_DIR="$TOOLS" bash "$0"
fi
source "$ROOT/versions.env"
[[ $(uname -s) == Linux ]] || { echo 'Tool bootstrap supports Linux only.' >&2; exit 1; }
case $(uname -m) in
  x86_64) arch=x64; target=x86_64-unknown-linux-gnu; uv_sha=$UV_X64_SHA256; node_sha=$NODE_X64_SHA256 ;;
  aarch64|arm64) arch=arm64; target=aarch64-unknown-linux-gnu; uv_sha=$UV_ARM64_SHA256; node_sha=$NODE_ARM64_SHA256 ;;
  *) echo 'Unsupported architecture.' >&2; exit 1 ;;
esac
for cmd in curl tar xz sha256sum git make ssh ssh-keygen; do
  command -v "$cmd" >/dev/null || { echo "Missing prerequisite: $cmd. Run bash scripts/install-system.sh." >&2; exit 1; }
done
umask 077
mkdir -p "$TOOLS"
[[ ! -L "$TOOLS" && -O "$TOOLS" ]] || { echo 'Tool directory must be owned by this user, not a symlink.' >&2; exit 1; }
# One writer: no partially installed runtime may be reused by another setup.
mkdir "$TOOLS/.install-lock" 2>/dev/null || { echo 'Tool installation locked; check for another installer.' >&2; exit 1; }
tmp=$(mktemp -d "$TOOLS/.download.XXXXXX")
step=preflight
cleanup() { rm -rf "$tmp"; rmdir "$TOOLS/.install-lock"; }
trap cleanup EXIT
report() { printf '%s: %s\n' "$1" "$2" | tee -a "$TOOLS/bootstrap-status.log"; }
trap 'report "$step" failed; exit 1' ERR
fetch() {
  curl --disable --fail --silent --show-error --location --proto '=https' --proto-redir '=https' "$1" -o "$2" 2>/dev/null
  printf '%s  %s\n' "$3" "$2" | sha256sum -c - >/dev/null
}
step=nvm; report "$step" started
export NVM_DIR="$TOOLS/nvm"
if [[ ! -f "$NVM_DIR/nvm.sh" ]]; then
  fetch "https://codeload.github.com/nvm-sh/nvm/tar.gz/refs/tags/$NVM_VERSION" "$tmp/nvm.tgz" "$NVM_SHA256"
  mkdir -p "$NVM_DIR"
  tar -xzf "$tmp/nvm.tgz" -C "$NVM_DIR" --strip-components=1
fi
# nvm is a shell function, not an executable. Do not alter the user's shell files.
set +u
source "$NVM_DIR/nvm.sh" --no-use
[[ "v$(nvm --version)" == "$NVM_VERSION" ]]
set -u
report "$step" complete
step=node; report "$step" started
node_dir="$NVM_DIR/versions/node/v$NODE_VERSION"
if [[ ! -x "$node_dir/bin/node" ]]; then
  fetch "https://nodejs.org/dist/v$NODE_VERSION/node-v$NODE_VERSION-linux-$arch.tar.xz" "$tmp/node.tar.xz" "$node_sha"
  mkdir -p "$node_dir"
  tar -xJf "$tmp/node.tar.xz" -C "$node_dir" --strip-components=1
fi
export PATH="$node_dir/bin:$PATH"
[[ $(node --version) == "v$NODE_VERSION" ]]
[[ $(npm --version) == "$NPM_VERSION" ]]
set +u
nvm alias default "$NODE_VERSION" >/dev/null
nvm use "$NODE_VERSION" >/dev/null
set -u
report "$step" complete
step=uv; report "$step" started
if [[ ! -x "$TOOLS/uv/uv" ]]; then
  fetch "https://github.com/astral-sh/uv/releases/download/$UV_VERSION/uv-$target.tar.gz" "$tmp/uv.tgz" "$uv_sha"
  mkdir -p "$TOOLS/uv"
  tar -xzf "$tmp/uv.tgz" -C "$TOOLS/uv" --strip-components=1
fi
[[ $("$TOOLS/uv/uv" --version) == "uv $UV_VERSION"* ]]
export UV_PYTHON_INSTALL_DIR="$TOOLS/python" UV_CACHE_DIR="$tmp/uv-cache"
export UV_PYTHON_BIN_DIR="$TOOLS/python-bin" UV_NO_PROGRESS=1
report "$step" complete
step=python; report "$step" started
"$TOOLS/uv/uv" python install "$PYTHON_VERSION" >/dev/null 2>&1
"$TOOLS/uv/uv" python find --managed-python "$PYTHON_VERSION" >/dev/null 2>&1
report "$step" complete
step=codex; report "$step" started
mkdir -p "$TOOLS/codex"
if ! cmp -s "$ROOT/codex/package-lock.json" "$TOOLS/codex/package-lock.json" ||
   [[ $("$TOOLS/codex/node_modules/.bin/codex" --version 2>/dev/null || true) != "codex-cli $CODEX_VERSION" ]]; then
  cp "$ROOT/codex/package.json" "$ROOT/codex/package-lock.json" "$TOOLS/codex/"
  # No lifecycle scripts or inherited credentials; integrity comes from npm's lockfile.
  touch "$tmp/npm-global-config"
  npm ci --prefix "$TOOLS/codex" --ignore-scripts --no-audit --no-fund     --cache "$tmp/npm-cache" --userconfig /dev/null --globalconfig "$tmp/npm-global-config" >/dev/null 2>&1
fi
[[ $("$TOOLS/codex/node_modules/.bin/codex" --version 2>/dev/null) == "codex-cli $CODEX_VERSION" ]]
report "$step" complete
report toolchain complete
