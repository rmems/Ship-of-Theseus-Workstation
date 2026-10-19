# Experiment environment provenance manifest

`scripts/theseus-provenance` writes a small JSON record of the environment
that produced a telemetry capture, benchmark, or experiment result (#8). It
points to the full sanitized system report (`scripts/theseus-report`, #3)
and to run artifacts by ID and SHA-256. It does not copy the full inventory.

Contract: [`schemas/provenance-manifest.schema.json`](../schemas/provenance-manifest.schema.json),
JSON Schema Draft 2020-12, **`schema_version` `1.0.0`**, redaction
`policy_version` `1.0.0`.

## Usage

```bash
python3 -m pip install -r requirements.txt

# Probe the host and write benchmarks/<manifest_id>.json (never overwrites)
scripts/theseus-provenance collect \
  --host-role telemetry-capture \
  --run-id telemetry-2026-10-19-001 --run-kind telemetry \
  --repo rmems/gaming-telemetry=../gaming-telemetry \
  --telemetry-contract 2.1.0 --telemetry-collector gaming-telemetry=0.6.0 \
  --system-report benchmarks/system-report-.../system-report.json \
  --artifact telemetry=benchmarks/telemetry-....csv \
  --meta workload_class=gpu-ml \
  --require environment.gpu.devices --require environment.cuda.driver_cuda_version

scripts/theseus-provenance validate benchmarks/prov-....json
python3 -m unittest -v tests/test_theseus_provenance.py
```

`--output -` writes to stdout. Exit codes: `0` valid, `2` collection,
validation, or redaction failure, `3` schema-version or redaction-policy
mismatch.

## Field status semantics

Each probed value is a field object:

```json
{"source": "nvidia_smi", "status": "available", "value": "580.95.05"}
{"source": "nvidia_smi", "status": "unavailable", "reason": "command_not_found"}
```

- A field is never left out. The schema requires every field, so a probe
  that fails produces `status: unavailable` with a `reason`.
- A value is never guessed. A failed probe has no `value`. Values such as
  `[N/A]` and `[Not Supported]` are recorded as `not_supported_by_device`.
  They are never turned into `0`.
- `status: omitted` is used only when the operator chose to leave a value
  out (`--no-host-fingerprint` gives `operator_opt_out`).
- Reasons: `command_not_found`, `command_failed`, `command_timeout`,
  `permission_denied`, `source_unavailable`, `unparseable_output`,
  `not_supported_by_device`, `module_not_installed`, `cpu_only_build`,
  `not_a_git_repository`, `not_provided`, `operator_opt_out`.
- `--require FIELD` (dotted path, for example `environment.gpu.devices.0.vbios_version`)
  makes collection or validation fail when that field is not available.
  Canonical #5 and #6 runs should use it so a run without a GPU cannot pass
  as a GPU run.

The collector only reads. It never installs anything, changes clocks or
power limits, or needs root.

## Fields and redaction decisions

The redaction decision for every field is listed below. "Keep" means the
value is a public product or version string, not a host identifier.

| Field | Source | Decision |
| --- | --- | --- |
| `schema_version`, `manifest_id`, `created_at_utc` | collector | Keep. `manifest_id` is `prov-<UTC stamp>-<8 random hex>` and is not derived from the host. |
| `collector.{name,version,source_commit}` | git (this repo) | Keep the commit SHA. The checkout path and remote URL are never stored. |
| `node.label` | constant | Keep. It is always `ship-of-theseus`. The real hostname is never read for output. |
| `node.host_role` | operator | Keep. Must be one of a fixed set of values. |
| `node.host_fingerprint` | `/etc/machine-id` | **Hash.** `HMAC-SHA256(machine-id, key="ship-of-theseus-provenance/v1")`. It stays the same across runs on one OS install, so runs can be compared. Because the hash is keyed, it is not the same value as a plain hash of machine-id that other tools might publish. The raw ID is never stored. The fingerprint changes if the OS is reinstalled. Use `--no-host-fingerprint` to leave it out. |
| `environment.os.{id,version_id}` | `/etc/os-release` | Keep. `PRETTY_NAME`, URLs, and variant fields are not read. |
| `environment.kernel_release` | `/proc/sys/kernel/osrelease` | Keep. |
| `environment.architecture` | `platform.machine()` | Keep. |
| `environment.firmware.{bios_vendor,bios_version,bios_date,board_vendor,board_name}` | `/sys/class/dmi/id/*` | Keep. **Only these five attributes are opened.** `product_serial`, `board_serial`, `chassis_serial`, `product_uuid`, and `*asset_tag` are never read. A test checks this. |
| `environment.cpu.model` | `/proc/cpuinfo` | Keep. CPU flags and microcode are not stored. |
| `environment.cpu.scaling_governors`, `energy_performance_preferences` | cpufreq sysfs | Keep the sorted unique set across CPUs. If governors differ between CPUs, every distinct value is recorded. |
| `environment.cpu.amd_pstate_mode`, `boost_enabled` | amd_pstate / cpufreq sysfs | Keep. |
| `environment.gpu.kernel_module_version` | `/proc/driver/nvidia/version` | Keep the version number only. The file also contains the NVIDIA build host and builder username, which are discarded. |
| `environment.gpu.devices[]` (`index`, `name`, `driver_version`, `vbios_version`, `compute_capability`, `memory_total_mib`, `power_limit_w`, `power_default_limit_w`, `power_enforced_limit_w`, `power_max_limit_w`, `clocks_max_graphics_mhz`, `clocks_max_memory_mhz`, `persistence_mode`, `pcie_link_gen_max`, `pcie_link_width_max`) | `nvidia-smi --query-gpu` | Keep. The query never asks for `uuid`, `serial`, `pci.bus_id`, or board or device IDs. A test checks this. |
| `environment.cuda.driver_cuda_version` | `nvidia-smi` banner | Keep the `CUDA Version:` number only. The rest of the banner (bus IDs, process names, process paths) is discarded. |
| `environment.cuda.toolkit_version` | `nvcc --version` | Keep. |
| `environment.toolchains.{python,rustc,cargo,gcc,julia}` | `--version` | Keep the version only. Install paths are not stored. |
| `environment.frameworks.{pytorch,pytorch_cuda_build,pytorch_cudnn}` | `python -c` import in the workload's own environment (user site and `PYTHONPATH` kept; only the current directory is dropped from `sys.path`) | Keep. No device query or allocation runs. That smoke test belongs to #4. |
| `repositories[].{name,commit,dirty}` | operator name + git | Keep the name given by the operator, the HEAD SHA, and the dirty flag. **The local checkout path and remote URL are not stored.** Untracked files do not count as dirty. |
| `telemetry.{contract_version,collector_name,collector_version}` | operator | Keep. If not given, recorded as `not_provided`. |
| `links.run_id`, `links.run_kind` | operator | Keep. Must match a restricted pattern or enum. |
| `links.system_report` | operator file | Keep `report_id` and the SHA-256 of the file. The report path is not stored. |
| `links.artifacts[].{kind,sha256,size_bytes}` | operator files | Keep the digest and size only. **File paths are not stored.** |
| `workload_metadata` | operator `--meta` | Keep, up to 32 string pairs. Every value is scanned for redaction. |
| `redaction.{policy_version,host_fingerprint_method}` | constant | Keep. These let a consumer check which policy was applied. |

The schema does not allow any other fields (`additionalProperties: false`
at every level). Both collection and validation also scan the whole document
and **fail** (they do not strip the data and continue) if:

- any key contains `hostname`, `username`, `serial`, `uuid`, `mac_address`,
  `ip_address`, `path`, `home`, `email`, `token`, `secret`, `password`,
  `credential`, `remote_url`, or `bus_id`;
- any string value looks like a home, absolute or `./`/`../` relative path,
  IPv4, IPv6 (including compressed forms such as `2001:db8::1`), MAC, UUID,
  email, any URL (so `https://` git remotes too), or `git@host:` remote;
- any operator-supplied or free-form string contains the running host's
  hostname or username. Collection checks this automatically. For
  `validate`, pass the terms with `--forbid TERM`. Values the schema pins to
  a fixed set (`source`, `status`, `reason`, `node.label`, `collector.name`,
  the `ship-of-theseus-` prefix of `report_id`), the os-release ID, vendor
  model strings (GPU name, CPU model, firmware vendor/board) and the owner in
  `owner/repo` cannot carry host data, so this check skips them.

## How #4, #5, and #6 attach a manifest

All three link outward by ID and digest. None of them copies the manifest
contents into its own output.

- **#4 runtime verification.** Run `collect --run-kind verification --run-id <verification-id>`
  next to the verifier, then `--artifact verification=<report>`. A verifier
  pass should require `environment.gpu.devices`,
  `environment.cuda.driver_cuda_version`, and, when the profile needs them,
  `environment.cuda.toolkit_version` and `environment.frameworks.pytorch`.
- **#5 benchmarks.** Collect a manifest *before* the isolated run with
  `--host-role benchmark --run-kind benchmark --run-id <benchmark-run-id> --system-report <report>`.
  Store it as `benchmarks/results/YYYY-MM-DD/<run-id>/provenance.json` next
  to the raw tool output. The normalized summary records `manifest_id` and
  the manifest's SHA-256. Compare two runs only if they agree on the fields
  that matter for the benchmark (kernel, driver, governors, GPU power limit,
  and so on).
- **#6 telemetry.** Collect with `--host-role telemetry-capture --run-kind telemetry`,
  plus `--telemetry-contract` and `--telemetry-collector` for the producer
  in use (gaming-telemetry, Theseus-Quarry, vahtisiru). Collect before
  capture starts, and pass the finished trace as `--artifact telemetry=<file>`.
  If the artifact digest has to come after capture, write a second manifest
  that has the digest. Never edit the first manifest.

A downstream experiment repository stores the manifest file, or its
`manifest_id` and SHA-256, next to its result.

## Known limits

- The environment is recorded *at collection time*. Values such as
  governors or power limits can change during a run. Use #6 telemetry for
  changes during the run.
- `nvidia-smi`, NVML, DMI, and cpufreq are not available in hosted CI or in
  containers. There, those fields are recorded as `unavailable`. That is the
  expected result, not a pass. Use `--require` on the real host.
- On the workstation, check that the `nvidia-smi` query works (the
  `enforced.power.limit` and `pcie.link.*.max` columns depend on the driver
  version) and that DMI attributes can be read without root. If they cannot,
  the fields are recorded as `permission_denied`.
