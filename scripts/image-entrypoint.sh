#!/usr/bin/env bash
set -euo pipefail
set +x
# PASSWORD arrives through --env-secret, never a Docker ARG/ENV literal.
if [[ -z ${PASSWORD:-} ]]; then
  echo 'startup: failed (PASSWORD must come from a runtime secret)' >&2; exit 1
fi
# Optional after completing one manual run. Credentials remain in private files.
if [[ ${POC_AUTO_SETUP:-0} == 1 ]]; then
  bash /opt/devlab-bootstrap/scripts/run.sh --config "$HOME/.config/devlab-poc/config.json" setup
fi
# Disable user entrypoint.d hooks; keep upstream fixuid, signals, and password auth.
export ENTRYPOINTD=/opt/devlab-bootstrap/no-hooks
exec /usr/bin/entrypoint.sh "$@"
