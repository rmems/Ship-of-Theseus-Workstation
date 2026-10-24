# AGENTS.md

Guidance for coding agents (Amp, Codex, Cursor, Claude Code, and others) working in this repository.

## Purpose

This repository documents **Ship of Theseus**, a single-node AI/HPC research workstation, as
infrastructure: hardware, software stack, workloads, reproducibility practices, and how the node
has changed over time (see `README.md`). The goal is an environment that is inspectable,
reproducible and benchmarkable. The code is a small set of shell collectors and a Python
sanitized-report tool.

## Layout

| Path | Contents |
|------|----------|
| `scripts/*.sh` | Node inventory, telemetry capture, benchmarking, environment checks, runner health |
| `scripts/theseus-report` | Sanitized system-report CLI (`collect`, `validate`) |
| `schemas/system-report.schema.json` | Schema for `system-report.json` (v1.0.0) |
| `tests/test_theseus_report.py` (+ `tests/fixtures/`) | unittest suite for the report tool |
| `configs/node-provenance.toml` | Node provenance config |
| `docs/` | Node baseline, workload catalog, system report, self-hosted runner, backup/recovery, change log |

## Toolchain

- Python **3.13** in CI (`system-report.yml`); dependency `jsonschema` from `requirements.txt`.
- ShellCheck **0.11.0** exactly (`portable-ci.yml` installs the pinned release tarball and checks
  `shellcheck --version` equals 0.11.0).
- No GPU needed for the tests. Optional NVIDIA/CUDA collectors record `available`/`unavailable`/`failed`.

## Commands (from `.github/workflows/`)

```bash
shellcheck scripts/*.sh                              # portable-ci.yml
python -m pip install --requirement requirements.txt  # system-report.yml
python -m unittest -v tests/test_theseus_report.py
scripts/theseus-report --help
```

## Conventions visible in the repo

- Keep the system report sanitized. Per `docs/system-report.md`, that collector persists only
  allowlisted parsed data and omits hostname, username, IP/MAC, serials, UUIDs, disk names,
  mountpoints, private paths, environment variables, package lists, process command lines, tokens
  and credentials. Other collectors (for example the node inventory) record more by design, so check
  each script's own docs before changing what it writes.
- Don't widen what the system report writes without updating `docs/system-report.md` and its
  allowlist. Failure handling differs per collector (`collect-node-inventory.sh` removes partial
  output, while `runner-health.sh` keeps a report on failure), so read the script before changing it.
- `docs/change-log.md` is a curated, dated record of meaningful infrastructure changes, not a
  mirror of `git log`.
- Commit subjects follow Conventional Commits (`feat:`, `fix:`, `docs:`) with the PR number.
