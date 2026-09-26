# Self-hosted GitHub Actions runner runbook

The workstation can provide a Fedora/Linux runner for GPU, CUDA, FPGA/RTL, and long-running engineering validation that is unsuitable for ordinary hosted runners.

## Operating rules

1. Use a dedicated runner identity and least-privilege repository access.
2. Apply labels that describe verified capabilities, not aspirational hardware: for example `self-hosted`, `linux`, `x64`, and add `cuda` only after environment verification passes.
3. Keep runner work directories separate from research datasets and model checkpoints.
4. Do not place long-lived credentials in workflow files or repository logs.
5. Record runner OS, kernel, driver, CUDA, and relevant toolchain versions in the job artifact.
6. Stop or drain the runner before driver, kernel, firmware, or storage maintenance.
7. Run one job at a time per runner identity; this node is not configured for parallel job execution, so concurrent workflow triggers queue rather than run simultaneously.
8. Treat the runner's `_work` directory as disposable once the runner is stopped or drained per rule 6 above — never while a job may still be running. Jobs should not depend on artifacts surviving between runs, and during a declared maintenance window operators may clear it without coordinating with separate research work on the node.

## Required toolchains

At minimum: `git`, `bash`, and `python3`. Individual workflows add project-specific toolchains (CUDA, Rust, SystemVerilog simulators) as job-level dependencies rather than baking them into the runner image, so a workflow's own setup steps remain the source of truth for what it needs.

## Validation

`scripts/runner-health.sh [output-path]` checks the runner-relevant subset of node health: required executables, free storage under a configurable work directory, GPU visibility, and — only when explicitly opted into via environment variables — whether a runner installation is registered and whether its service is active. It never reads runner credential or registration file contents, only their presence, and it refuses to overwrite an existing output path. Opt-in checks are skipped (not failed) when left unconfigured, since not every runner needs a GPU or runs as a system service.

Exit codes are:

- `0`: all checks passed
- `1`: one or more checks failed (report written)
- `2`: configuration or output-path failure (no report written)

By default, reports are written to `benchmarks/runner-health-<UTC timestamp>-<pid>.txt`. The path is claimed only after basic validation succeeds, and rerunning with the same output path after a config/setup failure is supported because the path is never reserved first.

| Variable | Default | Effect |
| --- | --- | --- |
| `RUNNER_HEALTH_MIN_FREE_GIB` | `20` | Minimum free space required under the work directory |
| `RUNNER_HEALTH_WORK_DIR` | `.` | Directory whose filesystem is checked for free space |
| `RUNNER_HEALTH_RUNNER_DIR` | unset | If set, verify a runner is registered at this path (checks for a `.runner` file) |
| `RUNNER_HEALTH_SERVICE_NAME` | unset | If set, verify this systemd service is active |

The script documents the current state as written at each run and never alters `PATH` or other process-wide environment state.

Run it after driver, kernel, or runner-version updates, and as part of the recovery procedure below.

## Recovery

If a runner becomes unhealthy, remove it from service, preserve the job URL and baseline report, and inspect disk, temperature, and GPU health. Then use this approved bootstrap procedure:

1. In the target repository, open **Settings > Actions > Runners**. If the local installation is accessible, stop and uninstall its service. Before entering GitHub's generated removal command with its short-lived token, open a protected Bash subshell:

   ```bash
   env HISTFILE=/dev/null bash --noprofile --norc
   set +o history
   set +o xtrace
   ```

   Paste and run the generated `./config.sh remove --token ...` command only in that subshell, then run `exit`. If the installation is inaccessible, force-remove the stale registration in GitHub.
2. Select **New self-hosted runner**, choose Linux and `x64`, and run the displayed download, integrity-check, and extraction commands exactly as generated. Open the same protected Bash subshell before entering the generated `./config.sh --token ...` registration command; paste and run it only there, then run `exit` to restore the operator shell with its history and tracing settings unchanged. Registration tokens are short-lived; never save either token in this repository or in shell history.
3. Assign only verified labels from the operating rules above. After registration, follow GitHub's Linux service instructions to install and start the runner service.
4. Confirm that GitHub reports the runner as idle, run an approved smoke workflow, and preserve its job URL plus a fresh `scripts/runner-health.sh` report.

GitHub's maintained procedures are [Adding self-hosted runners](https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/add-runners), [Removing self-hosted runners](https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/remove-runners), and [Configuring the self-hosted runner application as a service](https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/configure-the-application). A green job is evidence for that job, not proof that the node is permanently healthy.
