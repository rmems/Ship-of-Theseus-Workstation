# Sanitized system report

`scripts/theseus-report` creates a machine-readable description of the Ship of
Theseus execution environment. It is intentionally narrower than the raw
inventory directory produced by `scripts/collect-node-inventory.sh`.

## Usage

```bash
scripts/theseus-report collect --output benchmarks/system-report-example
scripts/theseus-report validate benchmarks/system-report-example/system-report.json
python3 -m unittest tests/test_theseus_report.py
```

`collect` refuses an existing output directory. The default output is a new,
timestamped, PID-suffixed directory under `benchmarks/`.

## Contract

The public artifact is `system-report.json`, defined by
[`schemas/system-report.schema.json`](../schemas/system-report.schema.json).
Schema version `1.0.0` separates stable `identity` fields from volatile runtime
values such as available memory and uptime. Optional NVIDIA and CUDA collectors
record `available`, `unavailable`, or `failed` status rather than fabricating
values or aborting an otherwise valid report.

The collector persists only allowlisted parsed data. It does not write raw
command output and omits hostname, username, IP/MAC address, serial number,
UUID, disk name, mountpoint, private path, environment variable, installed
package list, process command line, token, or credential. Review generated
reports before publishing them; machine model names and version information can
still be operationally sensitive.

## Field guide

| Section | Meaning |
| --- | --- |
| `identity` | Stable platform description: architecture, Fedora release, kernel, CPU topology, total memory, GPU model/VRAM/driver/capability, CUDA toolkit version, and block-device model/size/transport. |
| `volatile` | Point-in-time values that must not be mistaken for platform identity. |
| `collection_status` | Per-source availability/failure evidence with non-sensitive reason classes. |

No root access is required. `lshw`, `dmidecode`, `hostnamectl`, `ip`, and raw
`nvidia-smi -q` output are deliberately outside the canonical report because
they can expose identifiers or raw host details.
