#!/usr/bin/env bash
set -euo pipefail
interval=${1:-5}
duration=${2:-60}
out=${3:-benchmarks/telemetry-$(date -u +%Y%m%dT%H%M%SZ)-$$.csv}
if [[ ! $interval =~ ^[1-9][0-9]*$ ]]; then
  printf 'interval must be a positive integer: %s\n' "$interval" >&2
  exit 2
fi
if [[ ! $duration =~ ^(0|[1-9][0-9]*)$ ]]; then
  printf 'duration must be a non-negative integer: %s\n' "$duration" >&2
  exit 2
fi
mkdir -p "$(dirname "$out")"
if ! (set -o noclobber; : > "$out") 2>/dev/null; then
  printf 'Refusing to reuse telemetry output path: %s\n' "$out" >&2
  exit 2
fi
printf 'timestamp_utc,gpu_temperature_c,gpu_power_w,gpu_utilization_pct,gpu_memory_used_mib,cpu_temperature_c\n' > "$out"
end=$(( $(date +%s) + duration ))
while (( $(date +%s) < end )); do
  timestamp=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  if ! gpu=$(nvidia-smi --query-gpu=temperature.gpu,power.draw,utilization.gpu,memory.used --format=csv,noheader,nounits 2>/dev/null) || [[ -z $gpu ]]; then
    gpu=',,,'
  fi
  cpu=$(sensors 2>/dev/null | awk '
    /Tctl:/ { value = $2 }
    /Package id 0:/ { value = $4 }
    value != "" {
      gsub(/[+°C]/, "", value)
      print value
      exit
    }
  ' || true)
  while IFS= read -r gpu_row; do
    printf '%s,%s,%s\n' "$timestamp" "$gpu_row" "${cpu:-}" >> "$out"
  done <<< "$gpu"
  remaining=$((end - $(date +%s)))
  (( remaining <= 0 )) && break
  sleep_for=$(( interval < remaining ? interval : remaining ))
  sleep "$sleep_for"
done
printf '%s\n' "$out"
