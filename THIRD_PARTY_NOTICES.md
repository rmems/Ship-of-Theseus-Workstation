# Third-party notices

The repository's original scripts and documentation are licensed under the
[MIT License](LICENSE). No third-party source code, benchmark profile, or
binary is vendored in this repository.

The scripts invoke tools that operators install separately. Those tools remain
under their upstream licenses; invoking them does not incorporate their source
code into this repository.

| Tool | Role here | Upstream license/source |
| --- | --- | --- |
| [lshw](https://github.com/lyonel/lshw) | Optional hardware inventory | GNU General Public License, version 2; upstream [COPYING](https://github.com/lyonel/lshw/blob/master/COPYING) |
| [lm-sensors](https://github.com/lm-sensors/lm-sensors) | Optional sensor readings | GNU General Public License, version 2; upstream [COPYING](https://github.com/lm-sensors/lm-sensors/blob/master/COPYING) |
| [fio](https://github.com/axboe/fio) | Operator-selected storage benchmarking | GNU General Public License, version 2; upstream [COPYING](https://github.com/axboe/fio/blob/master/COPYING) |
| [stress-ng](https://github.com/ColinIanKing/stress-ng) | Operator-selected CPU/memory stress workloads | GNU General Public License, version 2; upstream [COPYING](https://github.com/ColinIanKing/stress-ng/blob/master/COPYING) |
| NVIDIA `nvidia-smi` and CUDA tooling | Optional GPU/runtime queries | Not redistributed here; governed by NVIDIA's applicable distribution terms |

If a future change copies or vendors upstream code, examples, benchmark
profiles, or assets, that pull request must identify the exact source revision,
license, required notices, and compatibility decision before merge.
