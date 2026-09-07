#!/usr/bin/env bash
set -uo pipefail

out=${1:-benchmarks/runner-health-$(date -u +%Y%m%dT%H%M%SZ)-$$.txt}
mkdir -p "$(dirname "$out")"
set -o noclobber
if ! { exec 3> "$out"; } 2>/dev/null; then
  set +o noclobber
  printf 'Refusing to reuse runner-health output path: %s\n' "$out" >&2
  exit 2
fi
set +o noclobber

min_free_gib=${RUNNER_HEALTH_MIN_FREE_GIB:-20}
if [[ ! $min_free_gib =~ ^[0-9]+$ ]]; then
  printf 'RUNNER_HEALTH_MIN_FREE_GIB must be a non-negative integer: %s\n' "$min_free_gib" >&2
  exit 2
fi
work_dir=${RUNNER_HEALTH_WORK_DIR:-.}
runner_dir=${RUNNER_HEALTH_RUNNER_DIR:-}
service_name=${RUNNER_HEALTH_SERVICE_NAME:-}

failures=0
check() {
  local label=$1; shift
  if "$@" >/dev/null 2>&1; then printf 'PASS  %s\n' "$label"; else printf 'FAIL  %s\n' "$label"; failures=$((failures + 1)); fi
}
skip() {
  printf 'SKIP  %s\n' "$1"
}
check_executable() {
  command -v "$1" >/dev/null 2>&1
}
check_free_space() {
  local available_kib
  available_kib=$(df -Pk "$work_dir" 2>/dev/null | awk 'NR==2 {print $4}')
  [[ -n $available_kib ]] && (( available_kib / 1024 / 1024 >= 10#$min_free_gib ))
}
check_runner_registered() {
  [[ -d "$runner_dir" && -f "$runner_dir/.runner" ]]
}
check_service_active() {
  systemctl is-active --quiet "$service_name"
}

run_health_check() {
  printf 'collected_at_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf 'command_family=runner-health\n\n'

  for exe in git bash python3; do
    check "required executable: $exe" check_executable "$exe"
  done

  check "storage: at least ${min_free_gib} GiB free under ${work_dir}" check_free_space

  if command -v nvidia-smi >/dev/null 2>&1; then
    check "GPU visibility (nvidia-smi)" nvidia-smi
  else
    skip "GPU visibility (nvidia-smi not installed; treat as non-GPU runner)"
  fi

  if [[ -n $runner_dir ]]; then
    check "runner registration present (RUNNER_HEALTH_RUNNER_DIR)" check_runner_registered
  else
    skip "runner registration (set RUNNER_HEALTH_RUNNER_DIR to check)"
  fi

  if [[ -n $service_name ]]; then
    check "runner service active (RUNNER_HEALTH_SERVICE_NAME)" check_service_active
  else
    skip "runner service state (set RUNNER_HEALTH_SERVICE_NAME to check)"
  fi

  if (( failures )); then
    printf '%s runner-health check(s) failed.\n' "$failures" >&2
    return 1
  fi
  printf 'All runner-health checks passed.\n'
}

run_health_check 2>&1 | tee /dev/fd/3
statuses=("${PIPESTATUS[@]}")
(( statuses[0] == 0 && statuses[1] == 0 ))
