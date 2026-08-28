# Workload catalog

| Workload class | Repository reference | Node dependency | Evidence to record |
| :--- | :--- | :--- | :--- |
| Local model experimentation and evaluation | [`rmems/agoge-forger`](https://github.com/rmems/agoge-forger) | RTX 5080, NVIDIA driver, CUDA/runtime, fast primary storage | model/runtime versions, GPU query, benchmark/telemetry report |
| Synthetic-data generation and agent trajectories | [`rmems/synthetic-factory`](https://github.com/rmems/synthetic-factory), [`rmems/operation-prometheus`](https://github.com/rmems/operation-prometheus) | CPU parallelism, memory, storage throughput, repository tooling | commit SHA, dataset/config version, inventory/provenance manifest |
| CUDA / Blackwell systems work | [`rmems/blackwell-kernel-lab`](https://github.com/rmems/blackwell-kernel-lab) | RTX 5080, driver/toolkit, compiler and profiling tools | compiler/tool versions, workload parameters, measured result |
| Neuromorphic computing | [`rmems/corinth-canal`](https://github.com/rmems/corinth-canal) | CPU parallelism, memory, reproducible simulation environment | source SHA, simulator/runtime versions, seed/config |
| FPGA / RTL validation | [`rmems/silicon-hdl`](https://github.com/rmems/silicon-hdl) | Fedora toolchain, local simulators, self-hosted CI | tool versions, workflow run, artifact digest |
| Self-hosted GitHub Actions | [`rmems/Ship-of-Theseus-Workstation`](https://github.com/rmems/Ship-of-Theseus-Workstation) | Fedora host, runner service, labels, disk and thermal headroom | runner/job URL, host baseline, maintenance record |

The catalog describes dependency classes, not ownership. Application-specific documentation and research artifacts remain in their canonical repositories.
