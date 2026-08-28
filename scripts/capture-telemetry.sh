#!/usr/bin/env bash
set -euo pipefail
interval=${1:-5}
duration=${2:-60}
out=${3:-benchmarks/telemetry-$(date -u +%Y%m%dT%H%M%SZ).csv}
if [[ ! $interval =~ ^[1-9][0-9]*$ ]]; then
  printf 'interval must be a positive integer: %s\n' "$interval" >&2
  exit 2
fi
if [[ ! $duration =~ ^(0|[1-9][0-9]*)$ ]]; then
  printf 'duration must be a non-negative integer: %s\n' "$duration" >&2
  exit 2
fi
mkdir -p "$(dirname "$out")"
printf 'timestamp_utc,gpu_temperature_c,gpu_power_w,gpu_utilization_pct,gpu_memory_used_mib,cpu_temperature_c\n' > "$out"
end=$((SECONDS + duration))
while (( SECONDS < end )); do
  timestamp=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  if ! gpu=$(nvidia-smi --query-gpu=temperature.gpu,power.draw,utilization.gpu,memory.used --format=csv,noheader,nounits 2>/dev/null) || [[ -z $gpu ]]; then
    gpu=',,,'
  fi
  cpu=$(sensors 2>/dev/null | awk '/Tctl:|Package id 0:/{gsub(/[+°C]/,"",$2); print $2; exit}' || true)
  while IFS= read -r gpu_row; do
    printf '%s,%s,%s\n' "$timestamp" "$gpu_row" "${cpu:-}" >> "$out"
  done <<< "$gpu"
  sleep "$interval"
done
printf '%s\n' "$out"
