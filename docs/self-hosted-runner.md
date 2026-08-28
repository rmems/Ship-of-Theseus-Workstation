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

1. In the target repository, open **Settings > Actions > Runners**. If the local installation is accessible, stop and uninstall its service. Before entering GitHub's generated removal command with its short-lived token, open a protected Bash subshell:

   ```bash
   env HISTFILE=/dev/null bash --noprofile --norc
   set +o history
   set +o xtrace
   ```

   Paste and run the generated `./config.sh remove --token ...` command only in that subshell, then run `exit`. If the installation is inaccessible, force-remove the stale registration in GitHub.
2. Select **New self-hosted runner**, choose Linux and `x64`, and run the displayed download, integrity-check, and extraction commands exactly as generated. Open the same protected Bash subshell before entering the generated `./config.sh --token ...` registration command; paste and run it only there, then run `exit` to restore the operator shell with its history and tracing settings unchanged. Registration tokens are short-lived; never save either token in this repository or in shell history.
3. Assign only verified labels from the operating rules above. After registration, follow GitHub's Linux service instructions to install and start the runner service.
4. Confirm that GitHub reports the runner as idle, run an approved smoke workflow, and preserve its job URL plus a fresh node verification report.

GitHub's maintained procedures are [Adding self-hosted runners](https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/add-runners), [Removing self-hosted runners](https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/remove-runners), and [Configuring the self-hosted runner application as a service](https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/configure-the-application). A green job is evidence for that job, not proof that the node is permanently healthy.
