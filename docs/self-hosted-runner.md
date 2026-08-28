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

If a runner becomes unhealthy, remove it from service, preserve the job URL and baseline report, and inspect disk, temperature, and GPU health. Then use this approved bootstrap procedure:

1. In the target repository, open **Settings > Actions > Runners**. If the local installation is accessible, stop and uninstall its service, then run GitHub's displayed removal command with a newly generated removal token. If the installation is inaccessible, force-remove the stale registration in GitHub.
2. Select **New self-hosted runner**, choose Linux and `x64`, and run the displayed download, integrity-check, extraction, and registration commands exactly as generated. Registration tokens are short-lived; never save one in this repository or in shell history.
3. Assign only verified labels from the operating rules above. After registration, follow GitHub's Linux service instructions to install and start the runner service.
4. Confirm that GitHub reports the runner as idle, run an approved smoke workflow, and preserve its job URL plus a fresh node verification report.

GitHub's maintained procedures are [Adding self-hosted runners](https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/add-runners), [Removing self-hosted runners](https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/remove-runners), and [Configuring the self-hosted runner application as a service](https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/configure-the-application). A green job is evidence for that job, not proof that the node is permanently healthy.
