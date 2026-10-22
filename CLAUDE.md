# CLAUDE.md

Claude-specific notes only. There is no `AGENTS.md` in this repo; project overview, engineering principles, and the CI
tiers are in `README.md`, and runbooks are in `docs/` (`node-baseline.md`, `self-hosted-runner.md`, `backup-recovery.md`,
`system-report.md`), so they are not repeated here.

## Commands

Run from the repo root. "Verified" means it ran successfully in a fresh checkout on Python 3.13.16 and ShellCheck 0.11.0
(Linux, CPU only, no GPU, no Fedora). The repo has no `.gitignore`, so set `PYTHONDONTWRITEBYTECODE=1` to keep the tree clean.

| Command | Status |
|---|---|
| `python3 -m pip install -r requirements.txt` (`jsonschema[format]>=4.23,<5`) | not run (`jsonschema` was already installed; CI runs it) |
| `python3 -m unittest -v tests/test_theseus_report.py` | verified (17 tests) |
| `scripts/theseus-report --help` | verified |
| `shellcheck scripts/*.sh` | ran, exit 1: four SC2329 info notices in `runner-health.sh` (functions called indirectly via `check`) |
| `scripts/theseus-report collect`, `validate` | not run (`collect` reads the live host and writes under `benchmarks/`; `validate` needs a collected report) |
| `scripts/verify-node-environment.sh`, `collect-node-inventory.sh`, `benchmark-node.sh`, `capture-telemetry.sh` | not run (probe the host and need its GPU/Fedora tools; written to `benchmarks/`) |
| `scripts/runner-health.sh` | not run (checks the self-hosted runner and service on the host) |
| `bash .cursor/install.sh` | not run (changes the host: apt, `/usr/local/bin`, `/etc/profile.d`) |

CI: `system-report.yml` runs the unittest and `--help` rows above on Python 3.13 on hosted runners. `portable-ci.yml` is meant to
run pinned ShellCheck 0.11.0 on `scripts/*.sh`, but its recent runs all end in `failure` with 0 jobs (GitHub reports a possible
workflow-file issue), so ShellCheck is not enforced in CI today. No hardware-gate workflow exists yet.

## Architecture map

- `scripts/theseus-report`: the only Python tool (`collect` and `validate`). It emits a sanitized `system-report.json` checked against `schemas/system-report.schema.json`.
- `scripts/*.sh`: Bash collectors (inventory, verification, benchmark, telemetry, runner health). Each refuses to reuse an existing output path and writes to `benchmarks/` by default.
- `tests/test_theseus_report.py` + `tests/fixtures/system-report/`: unit tests over canned `lscpu`, `lsblk`, `free`, `nvidia-smi`, `nvcc`, and `os-release` output.
- `configs/node-provenance.toml`: node description; the `[software]` fields are filled only from collected inventory.
- `docs/`: runbooks and records. `docs/change-log.md` is a curated infrastructure log, not a mirror of `git log`.
- `.codacy.yml`: Codacy `exclude_paths` (currently just `CLAUDE.md`).
- `.cursor/`: Cursor Cloud Agent bootstrap, not a project build step. `assets/`, `THIRD_PARTY_NOTICES.md`: images (excluded from the MIT license) and tool attribution.

## Invariants and non-goals

- Do not run provisioning, node-cleanup, or runner scripts from an agent session; read them. Mark them "not run (changes the host)".
- The system report is an allowlist: no hostname, username, IP/MAC, serial, UUID, disk name, mountpoint, private path, env var, package list, process command line, token, credential, or raw command output (`docs/system-report.md`). Do not widen it without bumping the schema.
- Fail honestly: unavailable collectors record `unavailable` or `failed`; never fabricate versions or results (`configs/node-provenance.toml` says "do not guess versions").
- Keep the repo narrow: node-level infrastructure only. Application code belongs in its own repository.
- Collectors invoke external tools but do not vendor them; keep `THIRD_PARTY_NOTICES.md` current.
- Third-party Actions are pinned to commit SHAs with `persist-credentials: false`; ShellCheck is pinned by version and SHA-256. Keep that pattern.
- Source files carry no SPDX headers; do not add them. `LICENSE` (MIT) applies to original scripts and documentation, not visual assets; see `assets/LICENSE.md`. There is no publish `exclude`/`include` list. `.codacy.yml` excludes `CLAUDE.md` from Codacy analysis only.

## Gotchas

- `benchmarks/` is referenced as the output directory but does not exist and is not gitignored; never commit generated output.
- `.claude/` and `.venv/` are not gitignored (`.cursor/install.sh` only adds `.venv` to `.git/info/exclude`); do not commit local agent state.
- `scripts/theseus-report` has a `#!/usr/bin/env python3` shebang and needs `jsonschema` importable there.
- A local `shellcheck scripts/*.sh` exits 1 on the info-level SC2329 notices, so it would fail `portable-ci.yml` once that workflow actually runs, even though nothing is broken.
- Never run `cargo`/registry/publish-style commands; nothing here is published.
- Edit only what the task needs.
