#!/usr/bin/env bash
# Run with bash; injected/ZIP files need not be executable.
set -euo pipefail
set +x
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
if [[ ${POC_CLEAN_ENV:-} != 1 ]]; then
  exec env -i HOME="$HOME" PATH=/usr/local/bin:/usr/bin:/bin POC_CLEAN_ENV=1 bash "$0"
fi
source "$ROOT/versions.env"
source /etc/os-release
[[ "$ID" == debian && "$VERSION_ID" == 13 ]] || {
  echo 'Expected Debian 13. Install prerequisites manually; see README.' >&2; exit 1;
}
SUDO=()
if [[ $EUID != 0 ]]; then SUDO=(sudo); fi
sources=$(mktemp)
trap 'rm -f "$sources"' EXIT
cat > "$sources" <<EOF
deb [check-valid-until=no] https://snapshot.debian.org/archive/debian/$DEBIAN_SNAPSHOT/ trixie main
deb [check-valid-until=no] https://snapshot.debian.org/archive/debian-security/$DEBIAN_SNAPSHOT/ trixie-security main
EOF
# Scope the snapshot to these commands; retain normal signature checking.
opts=(-o "Dir::Etc::sourcelist=$sources" -o Dir::Etc::sourceparts=- -o Acquire::Check-Valid-Until=false)
echo 'system-packages: started'
if ! "${SUDO[@]}" apt-get "${opts[@]}" update >/dev/null 2>&1 ||
   ! "${SUDO[@]}" env DEBIAN_FRONTEND=noninteractive apt-get "${opts[@]}" install -y --no-install-recommends       ca-certificates curl git make openssh-client tar xz-utils unzip >/dev/null 2>&1; then
  echo 'system-packages: failed (check sudo, snapshot access and apt locks)' >&2; exit 1
fi
echo 'system-packages: complete'
