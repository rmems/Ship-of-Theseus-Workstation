#!/usr/bin/env python3
"""Run-scoped, read-only workstation telemetry collector."""
import argparse
import ctypes
import ctypes.wintypes
import csv
import datetime as dt
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path


FIELDS = ["timestamp_utc", "elapsed_seconds", "run_id", "gpu_temperature_c",
          "gpu_power_w", "gpu_utilization_pct", "gpu_memory_utilization_pct",
          "gpu_memory_used_mib", "gpu_clock_mhz", "cpu_utilization_pct",
          "memory_total_bytes", "memory_available_bytes", "cpu_temperature_c",
          "cpu_temperature_sensor", "gpu_collection_status", "cpu_temperature_status"]


def command(args, timeout=5):
    try:
        result = subprocess.run(args, text=True, capture_output=True, timeout=timeout, check=True)
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def sample_cpu():
    if platform.system() == "Windows":
        idle, kernel, user = ctypes.wintypes.FILETIME(), ctypes.wintypes.FILETIME(), ctypes.wintypes.FILETIME()
        if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
            return None
        def ticks(value):
            return (value.dwHighDateTime << 32) | value.dwLowDateTime
        idle_ticks, kernel_ticks, user_ticks = ticks(idle), ticks(kernel), ticks(user)
        # Windows kernel time includes idle time.
        return kernel_ticks + user_ticks, idle_ticks
    try:
        values = [int(x) for x in Path("/proc/stat").read_text().splitlines()[0].split()[1:]]
        idle = values[3] + values[4]
        return sum(values), idle
    except (OSError, ValueError, IndexError):
        return None


def memory():
    if platform.system() == "Windows":
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.wintypes.DWORD), ("dwMemoryLoad", ctypes.wintypes.DWORD),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        status = MEMORYSTATUSEX()
        status.dwLength = ctypes.sizeof(status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return {"MemTotal": status.ullTotalPhys, "MemAvailable": status.ullAvailPhys}
        return {}
    found = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, value = line.split(":", 1)
            if key in ("MemTotal", "MemAvailable"):
                found[key] = int(value.strip().split()[0]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return found


def cpu_model():
    if platform.system() == "Windows":
        return os.environ.get("PROCESSOR_IDENTIFIER")
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.lower().startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return None


def cpu_temp():
    # Prefer AMD Tctl; hwmon labels are optional and sensor support varies by host.
    for path in sorted(Path("/sys/class/hwmon").glob("hwmon*/temp*_input")):
        label_path = path.with_name(path.name.replace("_input", "_label"))
        try:
            label = label_path.read_text().strip() if label_path.exists() else ""
            if "tctl" not in label.lower() and "cpu" not in label.lower() and "package" not in label.lower():
                continue
            return int(path.read_text().strip()) / 1000, "sysfs_hwmon"
        except (OSError, ValueError):
            continue
    # lm_sensors is a safe optional fallback; never infer a value from another component.
    output = command(["sensors", "-j"])
    if output:
        try:
            def find_temp(value):
                if isinstance(value, dict):
                    for key, item in value.items():
                        if "tctl" in key.lower() or "package id 0" in key.lower():
                            if isinstance(item, dict):
                                for subkey, temp in item.items():
                                    if subkey.endswith("_input") and isinstance(temp, (int, float)):
                                        return float(temp)
                        got = find_temp(item)
                        if got is not None:
                            return got
                elif isinstance(value, list):
                    for item in value:
                        got = find_temp(item)
                        if got is not None:
                            return got
                return None
            value = find_temp(json.loads(output))
            if value is not None:
                return value, "lm_sensors"
        except (ValueError, TypeError):
            pass
    return None, "unavailable"


def sample_lhm_temperature(helper):
    if helper is None or helper.poll() is not None:
        return None, None, "unavailable"
    try:
        helper.stdin.write("sample\n")
        helper.stdin.flush()
        response = json.loads(helper.stdout.readline())
        return response.get("value_c"), response.get("sensor"), response.get("status", "unavailable")
    except (OSError, ValueError, AttributeError):
        return None, None, "read_error"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True, help="Workload or benchmark identifier")
    parser.add_argument("--interval-seconds", type=float, default=5)
    parser.add_argument("--output", required=True, help="New directory for CSV and manifest")
    parser.add_argument("--cpu-temp-helper", help="path to the LibreHardwareMonitor helper executable or DLL; Windows only")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="Workload command after --")
    args = parser.parse_args()
    if args.interval_seconds <= 0:
        parser.error("--interval-seconds must be positive")
    workload = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not workload:
        parser.error("provide the sustained workload command after --")
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=False)
    csv_path = out / "telemetry.csv"
    start_wall = dt.datetime.now(dt.timezone.utc)
    start_mono = time.monotonic()
    gpu_query = ["nvidia-smi", "--query-gpu=temperature.gpu,power.draw,utilization.gpu,utilization.memory,memory.used,clocks.gr",
                 "--format=csv,noheader,nounits"]
    gpu_available = shutil.which("nvidia-smi") is not None
    temperature_helper = None
    if args.cpu_temp_helper:
        if platform.system() != "Windows":
            parser.error("--cpu-temp-helper is currently supported only on Windows")
        helper_command = [args.cpu_temp_helper]
        if args.cpu_temp_helper.lower().endswith(".dll"):
            helper_command.insert(0, "dotnet")
        temperature_helper = subprocess.Popen(helper_command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                              stderr=None, text=True, bufsize=1)
    cpu0 = sample_cpu()
    process = subprocess.Popen(workload)
    rows = 0
    try:
        with csv_path.open("x", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS)
            writer.writeheader()
            while True:
                now = time.monotonic()
                gpu_text = command(gpu_query) if gpu_available else None
                gpu_values = (gpu_text.split(",") if gpu_text else [])
                gpu_values = [v.strip() for v in gpu_values[:6]]
                gpu_values = ["" if v.lower() in ("n/a", "na", "[not supported]") else v for v in gpu_values]
                gpu_values += [""] * (6 - len(gpu_values))
                cpu1 = sample_cpu()
                utilization = None
                if cpu0 and cpu1 and cpu1[0] > cpu0[0]:
                    utilization = round(100 * (1 - (cpu1[1] - cpu0[1]) / (cpu1[0] - cpu0[0])), 2)
                cpu0 = cpu1
                mem = memory()
                if temperature_helper:
                    temperature, temperature_sensor, temp_source = sample_lhm_temperature(temperature_helper)
                else:
                    temperature, temp_source = cpu_temp()
                    temperature_sensor = None
                elapsed = now - start_mono
                values = [
                    dt.datetime.now(dt.timezone.utc).isoformat(), round(elapsed, 3), args.run_id,
                    *gpu_values, utilization, mem.get("MemTotal"), mem.get("MemAvailable"), temperature,
                    temperature_sensor,
                    "ok" if gpu_text else ("unavailable" if not gpu_available else "query_failed"), temp_source]
                writer.writerow({key: ("null" if value is None or value == "" else value)
                                 for key, value in zip(FIELDS, values)})
                stream.flush()
                rows += 1
                status = process.poll()
                if status is not None:
                    break
                cpu0 = cpu1
                time.sleep(max(0, args.interval_seconds - (time.monotonic() - now)))
        exit_code = process.wait()
    except KeyboardInterrupt:
        process.terminate()
        exit_code = process.wait()
    finally:
        if temperature_helper and temperature_helper.poll() is None:
            temperature_helper.stdin.close()
            temperature_helper.wait(timeout=5)
    ended = dt.datetime.now(dt.timezone.utc)
    revision = command(["git", "rev-parse", "HEAD"])
    gpu_name = command(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"]) if gpu_available else None
    driver = command(["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"]) if gpu_available else None
    manifest = {
        "schema_version": 1, "run_id": args.run_id, "started_at_utc": start_wall.isoformat(),
        "ended_at_utc": ended.isoformat(), "elapsed_seconds": round(time.monotonic() - start_mono, 3),
        "sample_interval_seconds": args.interval_seconds, "sample_count": rows,
        "workload_argv": workload, "workload_exit_code": exit_code,
        "host": {"hostname": platform.node(), "platform": platform.platform(), "python": platform.python_version(),
                 "cpu_model": cpu_model(), "gpu_model": gpu_name, "gpu_driver": driver, "repository_revision": revision},
        "sources": {"gpu": "nvidia-smi" if gpu_available else "unavailable",
                    "cpu_temperature": "LibreHardwareMonitor helper" if args.cpu_temp_helper else "optional hwmon/lm_sensors; null when unsupported",
                    "cpu_utilization": "GetSystemTimes" if platform.system() == "Windows" else "/proc/stat",
                    "memory": "GlobalMemoryStatusEx" if platform.system() == "Windows" else "/proc/meminfo"},
        "telemetry_file": "telemetry.csv"
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(out)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
