# Self-hosted GitHub Actions runner runbook

The workstation can provide a Fedora/Linux runner for GPU, CUDA, FPGA/RTL, and long-running engineering validation that is unsuitable for ordinary hosted runners.

## Operating rules

1. Use a dedicated runner identity and least-privilege repository access.
2. Apply labels that describe verified capabilities, not aspirational hardware: for example `self-hosted`, `linux`, `x64`, and add `cuda` only after environment verification passes.
3. Keep runner work directories separate from research datasets and model checkpoints.
4. Do not place long-lived credentials in workflow files or repository logs.
5. Record runner OS, kernel, driver, CUDA, and relevant toolchain versions in the job artifact.
6. Stop or drain the runner before driver, kernel, firmware, or storage maintenance.

## Recovery

If a runner becomes unhealthy, remove it from service, preserve the job URL and baseline report, inspect disk/temperature/GPU health, and reinstall or re-register it from the approved bootstrap procedure. A green job is evidence for that job, not proof that the node is permanently healthy.

## Planned follow-up

Add a pinned bootstrap script, systemd service policy, runner labels, update cadence, and a smoke workflow after the first baseline collection is reviewed.
