# Workload catalog

| Workload class | Node dependency | Evidence to record |
| :--- | :--- | :--- |
| Local model experimentation and evaluation | RTX 5080, NVIDIA driver, CUDA/runtime, fast primary storage | model/runtime versions, GPU query, benchmark/telemetry report |
| Synthetic-data generation and agent trajectories | CPU parallelism, memory, storage throughput, repository tooling | commit SHA, dataset/config version, inventory/provenance manifest |
| CUDA / Blackwell systems work | RTX 5080, driver/toolkit, compiler and profiling tools | compiler/tool versions, workload parameters, measured result |
| Neuromorphic computing | CPU parallelism, memory, reproducible simulation environment | source SHA, simulator/runtime versions, seed/config |
| FPGA / RTL validation | Fedora toolchain, local simulators, self-hosted CI | tool versions, workflow run, artifact digest |
| Self-hosted GitHub Actions | Fedora host, runner service, labels, disk and thermal headroom | runner/job URL, host baseline, maintenance record |

The catalog describes dependency classes, not ownership. Application-specific documentation and research artifacts remain in their canonical repositories.
