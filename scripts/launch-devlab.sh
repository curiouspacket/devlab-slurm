#!/usr/bin/env bash
# Run on your workstation with the Nebius CLI (`nebius`), NOT inside the DevLab.
set -euo pipefail
set +x
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
source "$ROOT/versions.env"
kind=${1:?Usage: bash scripts/launch-devlab.sh base|image [--dry-run|--create]}
mode=${2:---dry-run}
[[ $# -le 2 && ( "$mode" == --dry-run || "$mode" == --create ) ]] || exit 2
: "${PROJECT_ID:?Set PROJECT_ID}" "${SUBNET_ID:?Set SUBNET_ID}"
: "${PLATFORM:?Set PLATFORM}" "${PRESET:?Set PRESET}" "${DEVLAB_NAME:?Set DEVLAB_NAME}"
: "${IDE_PASSWORD_SECRET:?Set a SecretStash selector whose payload key is PASSWORD}"
args=(ai devlab create --name "$DEVLAB_NAME" --parent-id "$PROJECT_ID"
  --subnet-id "$SUBNET_ID" --platform "$PLATFORM" --preset "$PRESET"
  --primary-route-port 8080 --workspace-path /home/coder
  --disk-size 250Gi --public=false
  --env-secret "PASSWORD=$IDE_PASSWORD_SECRET")
if [[ -n ${NEBIUS_PROFILE:-} ]]; then args+=(--profile "$NEBIUS_PROFILE"); fi
case "$kind" in
  base)
    : "${BUNDLE_ZIP:?Set an absolute path to devlab-vscode.zip}"
    [[ "$BUNDLE_ZIP" == /* && -f "$BUNDLE_ZIP" && "$BUNDLE_ZIP" != *:* ]]
    size=$(wc -c < "$BUNDLE_ZIP")
    (( size > 0 && size <= 65536 )) || { echo 'ZIP must be 1..65536 bytes.' >&2; exit 1; }
    args+=(--image "$BASE_IMAGE" --inject-file "$BUNDLE_ZIP:/opt/injected/devlab-vscode.zip"
      --env ENTRYPOINTD=/opt/no-startup-hooks)
    ;;
  image)
    : "${CUSTOM_IMAGE:?Set your uploaded image using registry/path@sha256:digest}"
    [[ "$CUSTOM_IMAGE" =~ @sha256:[a-f0-9]{64}$ ]] || { echo 'Use an immutable image digest.' >&2; exit 1; }
    args+=(--image "$CUSTOM_IMAGE")
    if [[ -n ${REGISTRY_SECRET:-} ]]; then args+=(--registry-secret "$REGISTRY_SECRET"); fi
    ;;
  *) echo 'Choose base or image.' >&2; exit 2 ;;
esac
if [[ "$mode" == --dry-run ]]; then args+=(--dry-run); else args+=(--async); fi
# Only identifiers, image references, file paths and secret references are arguments.
exec nebius "${args[@]}"
