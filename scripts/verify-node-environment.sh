#!/usr/bin/env bash
set -uo pipefail

out=${1:-benchmarks/verification-$(date -u +%Y%m%dT%H%M%SZ).txt}
mkdir -p "$(dirname "$out")"

failures=0
check() {
  local label=$1; shift
  if "$@" >/dev/null 2>&1; then printf 'PASS  %s\n' "$label"; else printf 'FAIL  %s\n' "$label"; failures=$((failures + 1)); fi
}
check_fedora() {
  local ID=
  # shellcheck disable=SC1091
  source /etc/os-release
  [[ $ID == fedora ]]
}
run_verification() {
  printf 'collected_at_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf 'command_family=node-environment-verification\n\n'
  check "Fedora release metadata" check_fedora
  check "Python 3" python3 --version
  check "NVIDIA GPU visibility" nvidia-smi
  check "CUDA compiler" nvcc --version
  check "block-device inventory" lsblk -J
  if (( failures )); then printf '%s verification check(s) failed.\n' "$failures" >&2; return 1; fi
  printf 'All node environment checks passed.\n'
}

run_verification 2>&1 | tee "$out"
statuses=("${PIPESTATUS[@]}")
(( statuses[0] == 0 && statuses[1] == 0 ))
