# Reproducible node baseline

Issue #2 establishes this repository as an evidence record for the Ship of Theseus workstation. Runtime values belong in timestamped files under `benchmarks/`; hardware identity and operating role remain in the README.

## Collect a baseline

From the repository root:

```bash
scripts/collect-node-inventory.sh
scripts/verify-node-environment.sh
scripts/benchmark-node.sh
scripts/capture-telemetry.sh 5 60
```

The collectors use established Linux tooling where available: [`lshw`](https://github.com/lyonel/lshw) for hardware inventory, [`lm-sensors`](https://github.com/lm-sensors/lm-sensors) for sensor readings, and NVIDIA's `nvidia-smi`/CUDA tooling for GPU state. Missing optional tools are represented by missing output files rather than fabricated values.

The inventory collector records storage topology through `lsblk`. The provenance manifest is a checked-in schema/template; update runtime fields only from a collected report.

## Verification contract

The verifier checks Fedora metadata, Python, NVIDIA visibility, CUDA compiler availability, and block-device inventory. A passing result means those commands returned successfully on that run; it does not claim that a training workload, benchmark, or hosted CI job is production-ready.

## Benchmark interpretation

For repeatable CPU and memory stress testing, use [`stress-ng`](https://github.com/ColinIanKing/stress-ng). For controlled storage tests, use [`fio`](https://github.com/axboe/fio) against an explicitly selected test directory or device. The included benchmark script is a safe inventory and temporary-filesystem smoke test, not a replacement for workload-specific benchmarks.

Baseline files must include their UTC collection time and command family. Compare like-for-like runs: power policy, driver/runtime versions, workload size, thermal state, and background processes can materially change results. Never replace a failed or surprising measurement with a specification-sheet value.

## Safety and redaction

Do not commit secrets, tokens, SSH material, private service URLs, or raw logs containing credentials. Review generated files before committing. Telemetry and benchmark outputs can reveal host details, so publish only the subset needed for reproducibility.
