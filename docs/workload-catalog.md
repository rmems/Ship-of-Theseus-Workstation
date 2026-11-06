# Workload catalog

| Workload class | Repository reference | Node dependency | Execution mode | Provenance hook | Evidence to record |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Local model experimentation and evaluation | [`rmems/agoge-forger`](https://github.com/rmems/agoge-forger) | RTX 5080, NVIDIA driver, CUDA/runtime, fast primary storage | Interactive / batch; hosted CI covers code quality (`pr_quality_gate.yml`) and Python smoke/inference validation (`python_smoke_test.yml`), not this specific GPU workload itself | Planned: `theseus-report` baseline (#3) | model/runtime versions, GPU query, benchmark/telemetry report |
| Synthetic-data generation and agent trajectories | [`rmems/synthetic-factory`](https://github.com/rmems/synthetic-factory), [`rmems/operation-prometheus`](https://github.com/rmems/operation-prometheus) | CPU parallelism, memory, storage throughput, repository tooling | Batch (local); hosted CI ([`synthetic-factory/.github/workflows/python.yml`](https://github.com/rmems/synthetic-factory/blob/main/.github/workflows/python.yml), [`operation-prometheus/.github/workflows/ci.yml`](https://github.com/rmems/operation-prometheus/blob/main/.github/workflows/ci.yml)) covers validation, not dataset generation itself | Planned: `theseus-report` baseline (#3) | commit SHA, dataset/config version, inventory/provenance manifest |
| CUDA / Blackwell systems work | [`rmems/blackwell-kernel-lab`](https://github.com/rmems/blackwell-kernel-lab) | RTX 5080, driver/toolkit, compiler and profiling tools | Interactive development plus CI (`ci-gpu.yml`; runner type inferred from workflow `runs-on`) | Planned: `theseus-report` baseline (#3) | compiler/tool versions, workload parameters, measured result |
| Neuromorphic computing | [`rmems/corinth-canal`](https://github.com/rmems/corinth-canal) | CPU parallelism, memory, reproducible simulation environment | Interactive development plus CI (`gpu-tests.yml`; runner type inferred from workflow `runs-on`) | Planned: `theseus-report` baseline (#3) | source SHA, simulator/runtime versions, seed/config |
| FPGA / RTL validation | [`rmems/silicon-hdl`](https://github.com/rmems/silicon-hdl) | Fedora toolchain, local simulators | CI (`vivado-ci.yml`, `sim.yml`; runner type inferred from workflow `runs-on`) plus interactive development | Planned: `theseus-report` baseline (#3) | tool versions, workflow run, artifact digest |
| Workstation GitHub Actions | [`rmems/Ship-of-Theseus-Workstation`](https://github.com/rmems/Ship-of-Theseus-Workstation) | Fedora host, runner service, labels, disk and thermal headroom | Hosted CI (`system-report.yml`, runs on `ubuntu-latest`) validates report schema, fixtures, and unit-test checks; no self-hosted runner-gated workload workflow is present yet | Planned: `scripts/runner-health.sh` report (#14) | runner/job URL, host baseline, maintenance record |

The catalog describes dependency classes, not ownership. Application-specific documentation and research artifacts remain in their canonical repositories.

## Sustained workload telemetry profile

Use `scripts/capture-telemetry.sh` to sample during a real workload. The collector launches the workload after opening the output directory, samples at a measured monotonic interval, and writes a bounded `telemetry.csv` plus `manifest.json`. The manifest records the run ID, command, host/platform, start/end UTC, sample count, and exit status. Linux uses `/proc` and labeled CPU/Tctl hwmon sensors; Windows uses `GetSystemTimes` and `GlobalMemoryStatusEx` for CPU and memory. Missing sensor readings are written as `null`; collection status columns distinguish a missing NVIDIA tool from a failed query. CPU temperature is collected from labeled CPU/Tctl hwmon sensors or `lm_sensors` on Linux. On Windows, build the optional LibreHardwareMonitor helper:

```powershell
dotnet publish scripts/windows-cpu-temperature/windows-cpu-temperature.csproj `
  --configuration Release --runtime win-x64 --self-contained false
```

Then pass its published executable to the collector with `--cpu-temp-helper`, for example:

```powershell
python scripts/capture_telemetry.py `
  --run-id local-model-eval-2026-11-02 `
  --interval-seconds 5 `
  --output benchmarks/telemetry/local-model-eval-2026-11-02 `
  --cpu-temp-helper scripts/windows-cpu-temperature/bin/Release/net8.0/win-x64/publish/windows-cpu-temperature.exe `
  -- python -m your_project.evaluate --config configs/eval.yaml
```

The helper records the chosen CPU sensor label in each CSV row and prefers Tctl/Tdie, then a CPU package sensor. The helper uses LibreHardwareMonitorLib 0.9.6; some sensors may require running the shell elevated. If no eligible CPU sensor is exposed, the value stays `null`. The tool observes hardware and does not control power, fans, or workload behavior.

Example profile for a sustained project training/evaluation command:

```bash
scripts/capture-telemetry.sh \
  --run-id agoge-forger-eval-2026-11-02 \
  --interval-seconds 5 \
  --output benchmarks/telemetry/agoge-forger-eval-2026-11-02 \
  -- python -m your_project.evaluate --config configs/eval.yaml
```

Replace the command with the actual, versioned workload invocation being studied. For CPU-heavy compilation, use the project's normal clean build command; for a mixed profile, use its ordinary CPU preprocessing plus GPU execution pipeline. Record the source commit and workload configuration with the run. These are workload profiles, not synthetic temperature-maximization tests. Output directories are unique and raw traces are ignored by Git by default; review and publish a compact, provenance-linked summary separately.

CI-workflow references in the Execution mode column are verified against each repository's actual public workflow files, not the workload's internal implementation; a repository having CI does not imply its workload itself runs inside that CI. Hosted/self-hosted classifications are inferred from each referenced workflow's declared `runs-on` value where that field is present; if `runs-on` is absent, that classification is not asserted. The "interactive" / "batch" local-execution labels are inferred from each repository's stated purpose, not from complete runtime-path verification. Treat them as a best-effort estimate until a workload owner confirms or corrects them.

Provenance hooks and CI references marked "Planned" name an artifact that does not exist on `main` yet. `scripts/theseus-report` is already available from #13; this catalog currently treats only `scripts/runner-health.sh` as the remaining missing artifact.
