SHELL := /bin/bash
.DEFAULT_GOAL := help
.PHONY: help system tools secrets setup status codex slurm-check validate test bundle
help:
	@printf '%s\n' 'make system   Debian 13 prerequisites' 'make tools    pinned uv/Python/NVM/Node; latest Codex & Nebius CLI' 'make secrets  hidden prompts; private local file' 'make setup    repeatable environment setup' 'make status   sanitized completion summary' 'make validate provider and Slurm connectivity probes' 'make test     local unit tests'
system:
	@bash scripts/install-system.sh
tools:
	@bash scripts/bootstrap-tools.sh
secrets:
	@bash scripts/run.sh secrets
setup:
	@bash scripts/run.sh setup
status:
	@bash scripts/run.sh status
codex:
	@bash scripts/run.sh codex
slurm-check:
	@bash scripts/run.sh slurm sinfo
validate:
	@bash scripts/run.sh validate
test:
	@bash scripts/run.sh test
bundle:
	@bash scripts/run.sh package
