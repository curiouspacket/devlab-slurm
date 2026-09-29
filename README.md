# Repeatable VSCode DevLab PoC

A small, credential-free ZIP plus a matching Dockerfile. Make exposes commands; Bash installs the pinned tools; Python configures GitHub access, Codex/provider endpoints and Slurm SSH. **uv** manages the exact Python runtime and the locked virtual environment. Intended for one trusted internal user per DevLab.

## Pinned release set

| Component | Pin |
| --- | --- |
| NVM | **v0.40.3** |
| Node.js | 22.23.3; bundled npm 10.9.9 |
| uv | 0.12.20 |
| CPython | 3.12.14 |
| Codex CLI | 0.159.0, npm lockfile with package integrity hashes |
| code-server base | 4.117.0, multi-architecture image digest in Dockerfile |
| Debian package repository | Snapshot 20260928T000000Z, trixie + trixie-security |

`versions.env` records the pins and SHA-256 values for NVM, Node and uv archives. The installer verifies those archives before extraction; uv uses its bundled managed-Python download metadata. `pyproject.toml`, `.python-version` and **uv.lock** pin Python. The bootstrap itself uses only Python's standard library, so its Python dependency list is intentionally empty; there is no second requirements.txt to drift. The application must carry its **own** dependency lockfile. Pin its 40-character Git commit in config.json.

Supported target: Debian 13 code-server, Linux x86_64 or aarch64, UID 1000/coder by default. For a GPU DevLab, build the image for the node's architecture, normally linux/amd64. This image is a development/control environment, not a CUDA training runtime; the application jobs run on Soperator.

## 1. Test the ZIP inside an existing DevLab

Upload `devlab-vscode.zip` through the VSCode UI or inject it at creation. Verify its SHA-256 against the accompanying `devlab-vscode.zip.sha256` delivered separately. Do not put credentials in the ZIP.

In the VSCode terminal, set `ZIP` to the uploaded path or the injected mount:

```bash
ZIP=/opt/injected/devlab-vscode.zip
# For a manual upload, replace ZIP with the actual uploaded path.
# The stock image has curl and tar, but may lack unzip and make.
sudo apt-get update && sudo apt-get install -y --no-install-recommends unzip
mkdir -p "$HOME/bootstrap"
unzip -q "$ZIP" -d "$HOME/bootstrap"
cd "$HOME/bootstrap/devlab-vscode"
bash scripts/install-system.sh
bash scripts/bootstrap-tools.sh
```

Extract into a new directory when updating a release; don't merge releases with `unzip -o`. The initial `unzip` package is only an extraction prerequisite. Subsequent OS packages use the dated snapshot. On an existing/custom image with a different OS, install `bash curl ca-certificates git make openssh-client tar xz-utils unzip` through that OS's package manager; the bundled `install-system.sh` intentionally requires Debian 13.

The installer clears inherited environment variables before downloading/installing tools. It keeps NVM separate from an existing `~/.nvm`, does not edit shell profiles, and installs verified Node binaries into that dedicated NVM tree. **No credentials are needed for this step.** Repeat the same command to reuse matching tools. Do not run two installers at once; after a killed install, remove `toolchain/.install-lock` only after confirming no installer is running. To switch release sets, use a fresh `POC_TOOLS_DIR` and keep the old one until validation succeeds.

## 2. Configure and supply runtime credentials

Keep config and secrets outside both the bundle and application repository:

```bash
umask 077
mkdir -p "$HOME/.config/devlab-poc"
chmod 700 "$HOME/.config/devlab-poc"
cp config.example.json "$HOME/.config/devlab-poc/config.json"
# Edit that file in VSCode: repo URL, full commit SHA, target path,
# provider base URLs/models, and Soperator login host/user/port.
```

Use Codex with OpenAI or another provider that actually supports the **Responses API** and Codex's tool behavior. Token Factory can independently be the application's endpoint. An OpenAI-compatible Chat Completions endpoint alone is not sufficient for Codex. The example leaves model IDs for you to choose from your account; setup rejects unfilled `REPLACE` fields.

Obtain the cluster's SSH host key through a trusted administrator/control-plane channel. Save its OpenSSH `known_hosts` line as `$HOME/.config/devlab-poc/slurm_known_hosts` (the relative path in the example resolves beside config.json). For port 22 the entry names the hostname; otherwise use `[hostname]:port`. Do not trust an unverified `ssh-keyscan` result. Authorize your dedicated **public** key for the Slurm user on the cluster.

Upload the matching private key to a location outside the repository and set it to mode 600. `make secrets` asks for its path and prompts invisibly for the three API tokens:

```bash
chmod 600 /path/to/dedicated_slurm_key
make secrets
make setup
make status
make validate
```

The four secrets are saved to `~/.config/devlab-poc/secrets.json`, mode **600**, in a mode **700** directory. The private Slurm key must work unattended (no passphrase); use a dedicated, least-privilege PoC key. After import, remove the uploaded duplicate if it is no longer needed. Keep the original in your approved secret store. GitHub needs only read access to the selected private repository. `make secrets` refuses to overwrite an existing credentials file; replace it deliberately via your approved private-file workflow when rotating credentials.

Automation can provision the same JSON file through your approved secret retrieval/mount workflow, then call `make setup`. Required fields: `github_token`, `codex_api_key`, `application_api_key`, `slurm_private_key` (complete multiline OpenSSH key). The file must be a regular file owned by the DevLab user, mode 600, with a private parent directory; symlinks are rejected. **Do not use `--inject-file` for that JSON**: injected files are read-only and not private credential files. The included PoC uses prompts/private files rather than implementing a new secret-manager client.

## 3. Use the environment

```bash
make codex
make slurm-check
# Runs in the checked-out application directory, supplying its provider key only:
bash scripts/run.sh application python app.py
# Or install/run the application's locked dependencies using its own uv.lock:
bash scripts/run.sh application uv sync --locked
bash scripts/run.sh application uv run --locked python app.py
```

Replace `app.py` with the application's entry point. Application dependencies/build steps are repository-specific and are not guessed by this bootstrap. Codex receives its own key; application processes receive `OPENAI_API_KEY`, `NEBIUS_API_KEY`, `OPENAI_BASE_URL` and `MODEL`. Git's temporary askpass helper reads the GitHub token from the private file; the remote URL never contains it. Git submodules and LFS downloads are not automatically initialized.

`make setup` preserves an existing checkout and its local edits when its origin and HEAD match the pinned settings. A different HEAD/origin fails without resetting files. Re-running setup rewrites provider and SSH configuration from the private inputs. It checks tool versions, clones the exact commit, configures providers and SSH, then reports `ready: complete`. This means **configuration completed**, not that application inference or a Slurm job has succeeded.

`make validate` checks authenticated `/models` access and that the configured model is advertised for both providers, then runs `sinfo --noheader` over pinned-host SSH. It records only fixed check names/statuses. Providers without `/models` may require a provider-specific probe. This does not submit a workload or prove Codex Responses API compatibility; follow TEST_PLAN.md for those checks.

## 4. Build the custom image

Build from this directory. `.dockerignore` uses an allowlist so local config, tokens, keys, checkouts and caches cannot enter the build context. The build installs exactly the same tools, without any credentials.

```bash
docker build --platform linux/amd64 -t YOUR_REGISTRY/team/devlab-poc:0.2.0 .
# Push using your normal registry login/workflow, then record the registry digest.
docker push YOUR_REGISTRY/team/devlab-poc:0.2.0
```

See **LAUNCH.md** for base and custom-image launch commands. Both receive the editor's `PASSWORD` through a SecretStash reference. The custom image requires that password before starting; no anonymous editor is exposed.

Inside the custom image, use:

```bash
cd /opt/devlab-bootstrap
# No tool download step required: tools live under /opt/devlab-tools.
# Follow section 2 to create private configuration and credentials, then:
make secrets
make setup
make status
make validate
```

Image files/tools live under `/opt` so mounting persistent `/home/coder` cannot hide them. Credentials, the checkout and runtime status remain under `/home/coder`. After a successful manual setup, optional `--env POC_AUTO_SETUP=1` repeats setup **before** editor startup on subsequent starts, using `$HOME/.config/devlab-poc/config.json`. It requires already-provisioned private credentials and host keys; if setup fails, startup fails. Leave it off for the first test so the editor is available to configure the workspace.

To reuse tools in an interactive Bash terminal without exposing keys:

```bash
source versions.env
export NVM_DIR="${POC_TOOLS_DIR:-$HOME/.local/share/devlab-poc/toolchain}/nvm"
source "$NVM_DIR/nvm.sh"
nvm use "$NODE_VERSION"
```

## Logs, scope and troubleshooting

- `make status`: latest setup run's fixed step/status values; nonzero exit unless ready.
- `~/.local/share/devlab-poc/state/events.jsonl`: UTC time, run UUID, fixed step and status only.
- `~/.local/share/devlab-poc/state/validation.json`: timestamp and fixed probe results.
- Toolchain `bootstrap-status.log`: fixed installer steps/status, no raw package output.
- Failed setup exits nonzero; raw subprocess output/exception text is suppressed. Check the failed stage, configuration, file permissions, endpoint/network access and SSH host-key trust. Do not enable `set -x`, print environment variables, or dump the credential JSON.

The logging guarantee covers these setup and validation commands. Interactive Codex, arbitrary application commands and their own logs are outside that guarantee. The authorized DevLab user/root can read the runtime credentials; this design does not isolate secrets from malicious code running as that same user. Use trusted code and dedicated limited PoC credentials. Persistent disk snapshots/backups can retain the credential file: decommission the workspace and revoke the PoC credentials at the end.

The ZIP pins application tools; a pre-existing DevLab may still have other OS packages/extensions installed. For consistent environments across people, distribute the **built image by digest**. The Docker build is pinned to a base digest and dated package repositories but is not claimed byte-for-byte reproducible. Keep approved security updates as explicit new tested release sets.

To rebuild the injectable archive after approved changes, run `make bundle` from the extracted writable bundle directory. The package script uses an explicit file allowlist, deterministic archive metadata, and a 65,536-byte size gate. It writes the ZIP and checksum beside the bundle directory.

## Verification and sources

No private repository, API account, Soperator cluster or live DevLab was accessed in preparing this release.

- [code-server Docker installation](https://coder.com/docs/code-server/install#docker)
- [Pinned code-server entrypoint](https://github.com/coder/code-server/blob/v4.117.0/ci/release-image/entrypoint.sh)
- [uv locked projects](https://docs.astral.sh/uv/guides/projects/)
- [NVM v0.40.3](https://github.com/nvm-sh/nvm/releases/tag/v0.40.3)
- [Node.js 22.23.3 checksums](https://nodejs.org/dist/v22.23.3/SHASUMS256.txt)
- [uv 0.12.20 release](https://github.com/astral-sh/uv/releases/tag/0.12.20)
- [Token Factory API reference](https://api.tokenfactory.nebius.com/docs)
- [Codex provider configuration](https://developers.openai.com/codex/config-reference)
