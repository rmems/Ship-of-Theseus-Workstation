# ⚙️ Ship of Theseus | AI/HPC Research Node

<p align="center">
  <img src="assets/ship_of_theseus.png" width="800" alt="Ship of Theseus research workstation">
</p>

**Ship of Theseus** is my single-node AI/HPC research workstation and self-hosted engineering environment. This repository documents the machine as infrastructure: the hardware, software stack, workloads, reproducibility practices, and evolution of the node that supports my independent AI/ML systems research.

Rather than treating a high-end workstation as a project by itself, the goal is to make the environment **inspectable, reproducible, benchmarkable, and useful as engineering infrastructure**.

## 🎯 What this node is for

Ship of Theseus is used as a local execution and validation platform for work spanning:

- **AI/ML systems engineering** — local model experimentation, fine-tuning workflows, inference, evaluation, and synthetic-data pipelines.
- **GPU computing** — CUDA/CUDA-adjacent experimentation, profiling, kernel validation, and Blackwell-specific performance work.
- **Neuromorphic computing** — spiking-neural-network simulation, hybrid ANN/SNN experiments, telemetry-driven research, and model conversion workflows.
- **FPGA / RTL development** — SystemVerilog simulation and self-hosted validation for hardware-oriented projects.
- **Agentic software engineering** — local coding-agent workflows, repository-scale experiments, automated testing, and dataset generation from engineering trajectories.
- **Self-hosted CI** — GitHub Actions workloads that benefit from access to the workstation's GPU, Linux environment, or locally installed engineering toolchains.

## 🖥️ Node architecture

| Component | Specification | Primary role |
| :--- | :--- | :--- |
| **CPU** | AMD Ryzen 9 9950X (16 cores) | Compilation, simulation, data processing, multi-process agent workloads |
| **GPU** | ASUS ProArt GeForce RTX 5080 OC, 16 GB VRAM | Local ML, CUDA experimentation, GPU-accelerated research |
| **Memory** | 64 GB DDR5-6000 | Dataset processing, parallel development workloads, simulation |
| **Primary storage** | 2 TB Crucial T700 PCIe 5.0 NVMe | High-throughput working storage, models, build artifacts, experiment data |
| **Operating system** | Fedora Linux | Primary research, development, automation, and self-hosted CI environment |

The machine is intentionally treated as an evolving research node rather than a fixed build. Hardware, drivers, runtimes, and research workloads may change over time—the name **Ship of Theseus** reflects that continuous replacement and refinement.

## 🔬 Research ecosystem

This node supports multiple repositories and experimental pipelines across my GitHub and Hugging Face work. Representative workload classes include:

### Synthetic-data and model-training infrastructure

Repository-scale agent trajectories, validation artifacts, synthetic software-engineering data, and downstream local training/evaluation workflows.

### Neuromorphic and hybrid AI systems

Spiking neural networks, MoE-to-SNN experimentation, quantization, neural telemetry, sparse computation, and hardware/software co-design.

### GPU and systems work

Rust/Linux systems programming, CUDA-focused experimentation, profiling, reproducibility testing, and performance-sensitive infrastructure.

### RTL and FPGA validation

SystemVerilog simulation and hardware-oriented CI workloads, including workflows that are impractical or impossible on ordinary hosted runners because they depend on local engineering toolchains.

## 🧪 Repository direction

This repository is the **infrastructure record** for the node. As the environment matures, the highest-value additions are:

- reproducible Fedora/bootstrap documentation;
- NVIDIA driver, CUDA, and ML-runtime verification;
- system inventory and health-report scripts;
- GPU/CPU/storage benchmark snapshots;
- self-hosted GitHub Actions runner documentation;
- systemd/service configuration used by research workloads;
- experiment-environment provenance and reproducibility notes;
- documented failure modes, upgrades, and migration history.

The repository should stay narrow: application-specific code belongs in its own project. Ship-of-Theseus-HPC documents the **platform those projects run on**.

## 📐 Engineering principles

1. **Reproducibility over screenshots.** Record enough configuration to explain and recreate an environment.
2. **Measured performance over component marketing.** Benchmarks and workload behavior matter more than hardware specifications alone.
3. **Infrastructure as an engineering artifact.** CI, drivers, runtimes, services, and observability deserve versioned documentation.
4. **Project isolation.** Research code remains in its canonical repository; this repo owns node-level concerns.
5. **Evolution is expected.** Changes to the machine should leave an auditable trail instead of silently replacing the previous state.

## 🗺️ Planned structure

```text
Ship-of-Theseus-HPC/
├── README.md
├── assets/
├── docs/          # architecture, GPU stack, CI, reproducibility
├── scripts/       # bootstrap, verification, inventory, benchmarks
├── configs/       # node-level service/tool configuration
└── benchmarks/    # reproducible performance snapshots and results
```

These directories represent the intended infrastructure layout and will be added as their contents become useful and reproducible.

## 🤖 AI collaboration attribution

The August 2026 repositioning of this repository—from a general workstation/portfolio page into a focused AI/HPC infrastructure record—was developed collaboratively with **GPT-5.6 Sol by OpenAI**. GPT-5.6 Sol contributed repository-scope analysis, information architecture, and README drafting/refinement; final project direction and repository ownership remain with **rmems**.

AI-assisted contributions are attributed explicitly when they materially shape repository documentation or engineering decisions.

---

**Status:** Active research infrastructure. Documentation will evolve alongside the node and the workloads it supports.
