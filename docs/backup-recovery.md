# Backup, recovery, and change record

The node is an evolving research system. Changes to hardware, Fedora, kernel, NVIDIA driver, CUDA, storage layout, runner configuration, and experiment runtimes should leave an auditable record.

## Minimum recovery record

- current machine-readable inventory;
- current provenance manifest;
- runner registration/repository scope, without tokens;
- locations and restore instructions for research data and model artifacts;
- last known-good driver/runtime combination;
- date, reason, and result of major changes.

The 2 TB Crucial T700 is the primary high-throughput working device. The 2 TB Fanxiang PCIe 4.0 NVMe device is secondary/backup storage; a backup is a recovery asset only when its contents are independently copied and periodically restore-tested.

## Change procedure

1. Collect an inventory and environment verification report.
2. Record the intended change and affected workloads.
3. Apply the change during a maintenance window.
4. Re-run verification and the relevant benchmark/smoke test.
5. Record differences, failures, and rollback steps.
