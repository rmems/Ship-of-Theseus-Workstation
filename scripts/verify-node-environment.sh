#!/usr/bin/env bash
set -u
failures=0
check() {
  local label=$1; shift
  if "$@" >/dev/null 2>&1; then printf 'PASS  %s\n' "$label"; else printf 'FAIL  %s\n' "$label"; failures=$((failures + 1)); fi
}
check "Fedora release metadata" awk -F= '$1 == "ID" && $2 == "fedora" { found = 1 } END { exit !found }' /etc/os-release
check "Python 3" python3 --version
check "NVIDIA GPU visibility" nvidia-smi
check "CUDA compiler" nvcc --version
check "block-device inventory" lsblk -J
if (( failures )); then printf '%s verification check(s) failed.\n' "$failures" >&2; exit 1; fi
printf 'All node environment checks passed.\n'
