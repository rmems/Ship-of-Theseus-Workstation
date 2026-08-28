#!/usr/bin/env bash
set -euo pipefail
out=${1:-benchmarks/benchmark-$(date -u +%Y%m%dT%H%M%SZ).txt}
mkdir -p "$(dirname "$out")"
{
  printf 'collected_at_utc=%s\n\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo '## CPU'; lscpu 2>/dev/null || true
  echo '## Memory'; free -h 2>/dev/null || true
  echo '## GPU'; nvidia-smi 2>/dev/null || true
  echo '## Storage'; lsblk -o NAME,MODEL,SIZE,TYPE,FSTYPE,MOUNTPOINTS 2>/dev/null || true
  echo '## Temporary filesystem write smoke test'
  tmp=$(mktemp); trap 'rm -f "$tmp"' EXIT
  dd if=/dev/zero of="$tmp" bs=1M count=1024 conv=fdatasync status=progress 2>&1 || true
} | tee "$out"
