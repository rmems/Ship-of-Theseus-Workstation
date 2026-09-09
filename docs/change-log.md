# Change log

A curated, chronological record of meaningful Ship of Theseus infrastructure
changes — not a mirror of `git log`. It exists so a shift in benchmark or
experiment behavior can be correlated with a specific, dated infrastructure
change rather than treated as unexplained drift.

## What belongs here

- Hardware replacement or addition (CPU, GPU, storage, RAM, cooling, PSU)
- BIOS/firmware changes that materially affect workloads (EXPO/XMP profiles,
  PCIe lane allocation, power limits)
- Fedora major-version upgrades
- NVIDIA driver transitions
- CUDA/runtime transitions
- Self-hosted runner architecture or service changes

## What does not belong here

Routine package updates, dependency bumps, or any other churn with no
research or operational significance. If a change wouldn't plausibly explain
a shift in benchmark or experiment behavior, it doesn't belong in this file.

## Entry format

Each entry records:

- **Date** — ISO 8601 (`YYYY-MM-DD`)
- **Change** — what changed, concretely (old value → new value where applicable)
- **Reason** — why the change was made
- **Expected impact** — what should differ afterward, if anything
- **Validation performed** — how the change was confirmed to work (command
  run, report generated, workflow triggered)
- **Provenance links** — related baseline/manifest IDs, benchmark runs, or
  issue/PR references, when they exist

```markdown
### YYYY-MM-DD — Short title

- **Change:**
- **Reason:**
- **Expected impact:**
- **Validation performed:**
- **Provenance links:**
```

Newest entries first within a section. This file follows the curation
principle of [Keep a Changelog](https://keepachangelog.com/en/1.1.0/):
entries are selective and human-written, not auto-generated from commits.

## Unreleased

No entries yet.
