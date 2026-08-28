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
  lshw_tmp="$out/lshw.json.tmp"
  if [[ $EUID -eq 0 ]]; then
    lshw -json > "$lshw_tmp" 2>/dev/null && mv "$lshw_tmp" "$out/lshw.json" || rm -f "$lshw_tmp"
  elif sudo -n lshw -json > "$lshw_tmp" 2>/dev/null; then
    mv "$lshw_tmp" "$out/lshw.json"
  else
    rm -f "$lshw_tmp" "$out/lshw.json"
    printf 'Skipping lshw inventory: passwordless privileged access is unavailable.\n' >&2
  fi
fi

if command -v nvidia-smi >/dev/null 2>&1; then
  nvidia_tmp="$out/nvidia-smi.csv.tmp"
  if nvidia-smi --query-gpu=name,driver_version,memory.total,compute_cap --format=csv > "$nvidia_tmp" 2>/dev/null; then
    mv "$nvidia_tmp" "$out/nvidia-smi.csv"
  else
    rm -f "$nvidia_tmp" "$out/nvidia-smi.csv"
  fi
  nvidia_query_tmp="$out/nvidia-smi-query.txt.tmp"
  if nvidia-smi -q > "$nvidia_query_tmp" 2>/dev/null; then
    mv "$nvidia_query_tmp" "$out/nvidia-smi-query.txt"
  else
    rm -f "$nvidia_query_tmp" "$out/nvidia-smi-query.txt"
  fi
fi

if command -v nvcc >/dev/null 2>&1; then nvcc --version > "$out/nvcc.txt"; fi
if command -v sensors >/dev/null 2>&1; then sensors > "$out/sensors.txt" || true; fi

printf 'Inventory written to %s\n' "$out"
