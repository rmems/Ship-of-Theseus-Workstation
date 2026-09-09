#!/usr/bin/env bash
set -uo pipefail

out=${1:-benchmarks/runner-health-$(date -u +%Y%m%dT%H%M%SZ)-$$.txt}
min_free_gib=${RUNNER_HEALTH_MIN_FREE_GIB:-20}
work_dir=${RUNNER_HEALTH_WORK_DIR:-.}
runner_dir=${RUNNER_HEALTH_RUNNER_DIR:-}
service_name=${RUNNER_HEALTH_SERVICE_NAME:-}

if [[ ! $min_free_gib =~ ^[0-9]+$ ]]; then
  printf 'RUNNER_HEALTH_MIN_FREE_GIB must be a non-negative integer: %s\n' "$min_free_gib" >&2
  exit 2
fi

# Keep this bound strict enough to prevent integer-range wrap in shell arithmetic.
if (( min_free_gib > 1048576 )); then
  printf 'RUNNER_HEALTH_MIN_FREE_GIB is too large: %s GiB\n' "$min_free_gib" >&2
  exit 2
fi

if ! mkdir -p "$(dirname "$out")"; then
  printf 'Cannot create runner-health output directory: %s\n' "$(dirname "$out")" >&2
  exit 2
fi

if [[ -e $out ]]; then
  printf 'Refusing to reuse runner-health output path: %s\n' "$out" >&2
  exit 2
fi

if ! exec 3> "$out"; then
  printf 'Cannot create runner-health output path: %s\n' "$out" >&2
  exit 2
fi

log() {
  printf '%s\n' "$1"
  printf '%s\n' "$1" >&3
}

check() {
  local label=$1
  local status_file
  shift

  status_file=$(mktemp)
  if "$@" >"$status_file" 2>&1; then
    log "PASS  $label"
    rm -f "$status_file"
    return 0
  fi
  local status=$?
  log "FAIL  $label"
  while IFS= read -r line; do
    log "  $line"
  done <"$status_file"
  rm -f "$status_file"
  failures=$((failures + 1))
  return "$status"
}

skip() {
  log "SKIP  $1"
}

check_executable() {
  command -v "$1" >/dev/null 2>&1
}

check_free_space() {
  local available_kib
  local status=1

  available_kib=$(df -Pk "$work_dir" 2>/dev/null | awk 'NR==2 {print $4}')
  if [[ -n $available_kib ]] && (( available_kib / 1024 / 1024 >= 10#$min_free_gib )); then
    status=0
  fi
  return "$status"
}

check_runner_registered() {
  [[ -d "$runner_dir" && -f "$runner_dir/.runner" ]]
}

check_service_active() {
  systemctl is-active --quiet "$service_name"
}

failures=0
run_health_check() {
  log "collected_at_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  log "command_family=runner-health"
  log ""

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
    log "$failures runner-health check(s) failed."
    return 1
  fi
  log "All runner-health checks passed."
  return 0
}

run_health_check
status=$?
exec 3>&-
exit "$status"
