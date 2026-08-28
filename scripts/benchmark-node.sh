#!/usr/bin/env bash
set -uo pipefail
out=${1:-benchmarks/benchmark-$(date -u +%Y%m%dT%H%M%SZ).txt}
mkdir -p "$(dirname "$out")" || exit 1

failures=0
run_and_record() {
  local label=$1
  local command_status
  shift
  if "$@"; then
    printf 'status=passed command=%s\n' "$label"
  else
    command_status=$?
    printf 'status=failed command=%s exit_code=%s\n' "$label" "$command_status"
    failures=$((failures + 1))
  fi
}

{
  printf 'collected_at_utc=%s\n\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo '## CPU'; run_and_record lscpu lscpu
  echo '## Memory'; run_and_record free free -h
  echo '## GPU'; run_and_record nvidia-smi nvidia-smi
  echo '## Storage'; run_and_record lsblk lsblk -o NAME,MODEL,SIZE,TYPE,FSTYPE,MOUNTPOINTS
  echo '## Temporary filesystem write smoke test'
  if tmp=$(mktemp); then
    trap 'rm -f "$tmp"' EXIT
    run_and_record dd dd if=/dev/zero of="$tmp" bs=1M count=1024 conv=fdatasync status=progress 2>&1
  else
    printf 'status=failed command=mktemp exit_code=%s\n' "$?"
    failures=$((failures + 1))
  fi
  (( failures == 0 ))
} | tee "$out"
statuses=("${PIPESTATUS[@]}")
(( statuses[0] == 0 && statuses[1] == 0 ))
