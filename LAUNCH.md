# Launching a DevLab (run on your workstation)

This covers the two ways to start the DevLab described in this repo, using the
public [Nebius CLI](https://docs.nebius.com/cli/) (`nebius`) and the
[`nebius ai devlab create`](https://docs.nebius.com/cli/reference/ai/devlab/create)
command. Both paths use the same underlying bootstrap; they differ only in how
the tooling reaches the DevLab.

- **Path A — Base image + injected ZIP**: start from a stock code-server image
  and inject `devlab-vscode.zip` (see the root README) at creation time.
- **Path B — Custom container image**: build and push the Dockerfile in this
  repo, then launch from that image directly.

Neither command creates or modifies anything outside the DevLab itself
(no Soperator or cloud secrets are touched). Retrieve the cluster login
address, your public-key authorization, and the trusted SSH host-key entry
from your cluster administrator.

## Shared setup

Create a [SecretStash](https://docs.nebius.com/mysterybox/overview) secret
with a non-empty `PASSWORD` payload entry for editor login. Use a strong
random password, and reference it below by selector — never by value.
`SECRET_ID@VERSION_ID` makes the exact secret version explicit. Make sure
the DevLab service has IAM read access to that secret. For a private
registry, a separate SecretStash secret must hold `REGISTRY_USERNAME` and
`REGISTRY_PASSWORD` (pull-only credentials).

```bash
export PROJECT_ID='YOUR_PROJECT_ID'
export SUBNET_ID='YOUR_SUBNET_ID'
export PLATFORM='YOUR_PLATFORM'     # e.g. cpu-e2, if available in your region
export PRESET='YOUR_PRESET'         # a supported preset for that platform
export IDE_PASSWORD_SECRET='SECRET_ID@VERSION_ID'
```

Fill in the project/region/capacity variables explicitly — don't rely on the
default platform or preset if you need a specific, repeatable target.

## Path A: base image + injected ZIP

This uses a stock code-server image, pinned to a specific digest, with the
bootstrap ZIP injected read-only. It uses `--image`, not `--template`: the
bundled README and Makefile drive setup from inside the editor terminal
instead of a template's own startup hooks.

```bash
source versions.env
export BUNDLE_ZIP='/absolute/path/to/devlab-vscode.zip'
export DEVLAB_NAME='devlab-vscode-base'

nebius ai devlab create \
  --name "$DEVLAB_NAME" --parent-id "$PROJECT_ID" --subnet-id "$SUBNET_ID" \
  --platform "$PLATFORM" --preset "$PRESET" \
  --image "$BASE_IMAGE" --primary-route-port 8080 \
  --workspace-path /home/coder --disk-size 250Gi \
  --public=false --env-secret "PASSWORD=$IDE_PASSWORD_SECRET" \
  --inject-file "$BUNDLE_ZIP:/opt/injected/devlab-vscode.zip" \
  --async
```

The injected file is read-only, capped at 64 KiB, and does not auto-extract
or execute. Follow the root README inside the editor terminal to unzip and
run the bootstrap. `--public=false` skips the runtime VM's public IP — the
editor is reached through its managed HTTPS route, gated by the `PASSWORD`
secret.

## Path B: custom container image

Build and push the Dockerfile in this repo (see the root README), then use
the **registry digest returned after pushing** — an image ID from
`docker inspect` is not a registry manifest digest.

```bash
export CUSTOM_IMAGE='registry.example/team/devlab-poc@sha256:YOUR_64_HEX_DIGEST'
export DEVLAB_NAME='devlab-vscode-image'
export REGISTRY_SECRET='REGISTRY_SECRET_ID@VERSION_ID'  # private registry only

nebius ai devlab create \
  --name "$DEVLAB_NAME" --parent-id "$PROJECT_ID" --subnet-id "$SUBNET_ID" \
  --platform "$PLATFORM" --preset "$PRESET" \
  --image "$CUSTOM_IMAGE" --primary-route-port 8080 \
  --workspace-path /home/coder --disk-size 250Gi \
  --public=false --env-secret "PASSWORD=$IDE_PASSWORD_SECRET" \
  --registry-secret "$REGISTRY_SECRET" \
  --async
```

Omit `--registry-secret` for a public registry. Don't pass `--template` with
either command — both are image-based. `--ssh-key` (optional, a **public**
key) grants SSH access **to the DevLab**; it's unrelated to the private key
used **from the DevLab to Slurm**, which is configured inside the editor
per the root README.

For a validation-only request, replace `--async` with `--dry-run` — it
contacts Nebius to validate the request without provisioning anything.
`--async` returns a DevLab ID once creation is accepted, not once startup
completes. Check status with:

```bash
nebius ai devlab get --id "$DEVLAB_ID"
```

then open the returned HTTPS endpoint and confirm the editor login works.

## Included wrapper

With the same environment variables, this wrapper adds basic input/ZIP-size
checks and defaults to a dry run:

```bash
bash scripts/launch-devlab.sh base --dry-run
bash scripts/launch-devlab.sh base --create

bash scripts/launch-devlab.sh image --dry-run
bash scripts/launch-devlab.sh image --create
```

## Further reading

- [`nebius ai devlab create` reference](https://docs.nebius.com/cli/reference/ai/devlab/create)
- [Managing DevLabs](https://docs.nebius.com/serverless/devlabs/manage)
- [DevLab quickstart](https://docs.nebius.com/serverless/quickstart/devlabs)
- [SecretStash overview](https://docs.nebius.com/mysterybox/overview)
