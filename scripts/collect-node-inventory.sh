#!/usr/bin/env bash
set -euo pipefail

out=${1:-benchmarks/inventory-$(date -u +%Y%m%dT%H%M%SZ)}
if [[ -e $out ]]; then
  printf 'Refusing to reuse inventory output path: %s\n' "$out" >&2
  exit 2
fi
mkdir -p "$(dirname "$out")"
mkdir "$out"
out_inode=""
collection_complete=0
cleanup_on_failure() {
  local status=$?
  (( status == 0 )) && return
  (( collection_complete )) && return
  python3 - "$out" "$out_inode" <<'PY'
import os
import sys

path, inode = sys.argv[1], sys.argv[2]
parent = os.path.dirname(os.path.abspath(path)) or "/"
name = os.path.basename(path)


def rmtree_relative(dir_fd, entry_name):
    fd = os.open(entry_name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=dir_fd)
    try:
        for entry in os.scandir(fd):
            if entry.is_dir(follow_symlinks=False):
                rmtree_relative(fd, entry.name)
            else:
                os.unlink(entry.name, dir_fd=fd)
    finally:
        os.close(fd)
    os.rmdir(entry_name, dir_fd=dir_fd)


try:
    parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
except OSError:
    sys.exit(0)
try:
    try:
        fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
    except OSError:
        sys.exit(0)
    try:
        if inode and os.fstat(fd).st_ino != int(inode):
            sys.exit(0)
    finally:
        os.close(fd)
    rmtree_relative(parent_fd, name)
finally:
    os.close(parent_fd)
PY
}
trap cleanup_on_failure EXIT
out_inode=$(stat -c %i "$out")

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
    if lshw -json > "$lshw_tmp" 2>/dev/null; then
      if ! mv "$lshw_tmp" "$out/lshw.json"; then
        rm -f "$lshw_tmp"
        exit 1
      fi
    else
      rm -f "$lshw_tmp"
    fi
  else
    rm -f "$lshw_tmp" "$out/lshw.json"
    printf 'Skipping lshw inventory: run the collector as root to capture this optional report.\n' >&2
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

if command -v nvcc >/dev/null 2>&1; then
  nvcc_tmp="$out/nvcc.txt.tmp"
  if nvcc --version > "$nvcc_tmp" 2>/dev/null; then
    mv "$nvcc_tmp" "$out/nvcc.txt"
  else
    rm -f "$nvcc_tmp" "$out/nvcc.txt"
    printf 'Skipping nvcc inventory: CUDA compiler query failed.\n' >&2
  fi
fi
if command -v sensors >/dev/null 2>&1; then
  sensors_tmp="$out/sensors.txt.tmp"
  if sensors > "$sensors_tmp" 2>/dev/null; then
    mv "$sensors_tmp" "$out/sensors.txt"
  else
    rm -f "$sensors_tmp" "$out/sensors.txt"
  fi
fi

collection_complete=1
printf 'Inventory written to %s\n' "$out"
