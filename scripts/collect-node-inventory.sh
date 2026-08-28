#!/usr/bin/env bash
set -euo pipefail

out=${1:-benchmarks/inventory-$(date -u +%Y%m%dT%H%M%SZ)}
mkdir -p "$out"

date -u +%Y-%m-%dT%H:%M:%SZ > "$out/collected_at_utc.txt"
hostnamectl 2>/dev/null > "$out/hostnamectl.txt" || hostname > "$out/hostname.txt"
cat /etc/os-release > "$out/os-release.txt"
uname -a > "$out/uname.txt"
lscpu > "$out/lscpu.txt"
free -h > "$out/memory.txt"
python3 --version > "$out/python-version.txt"
lsblk -J -o NAME,MODEL,SIZE,TYPE,FSTYPE,MOUNTPOINTS > "$out/lsblk.json"

if command -v lshw >/dev/null 2>&1; then
  if lshw -json > "$out/lshw.json" 2>/dev/null; then :; else
    sudo -n lshw -json > "$out/lshw.json" 2>/dev/null || true
  fi
fi

if command -v nvidia-smi >/dev/null 2>&1; then
  nvidia-smi --query-gpu=name,driver_version,memory.total,compute_cap --format=csv > "$out/nvidia-smi.csv" 2>/dev/null || true
  nvidia-smi -q > "$out/nvidia-smi-query.txt" 2>/dev/null || true
fi

if command -v nvcc >/dev/null 2>&1; then nvcc --version > "$out/nvcc.txt"; fi
if command -v sensors >/dev/null 2>&1; then sensors > "$out/sensors.txt" || true; fi

printf 'Inventory written to %s\n' "$out"
