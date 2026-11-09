#!/usr/bin/env python3
"""Run-scoped, read-only workstation telemetry collector.

This local CLI intentionally executes the operator's workload and optional helper.
All child commands use argument lists without a shell, not remote/request input.
"""
import argparse
import csv
import datetime as dt
import json
import math
import platform
import queue
import shutil
# Required by this local workload runner.
import subprocess  # nosec B404
import sys
import threading
import time
from pathlib import Path

from telemetry_sensors import cpu_model, cpu_temp, memory, sample_cpu


FIELDS = ["timestamp_utc", "elapsed_seconds", "run_id", "gpu_temperature_c",
          "gpu_power_w", "gpu_utilization_pct", "gpu_memory_utilization_pct",
          "gpu_memory_used_mib", "gpu_clock_mhz", "cpu_utilization_pct",
          "memory_total_bytes", "memory_available_bytes", "cpu_temperature_c",
          "cpu_temperature_sensor", "gpu_collection_status", "cpu_temperature_status"]
GPU_QUERY = ["nvidia-smi", "--id=0",
             "--query-gpu=temperature.gpu,power.draw,utilization.gpu,utilization.memory,memory.used,clocks.gr",
             "--format=csv,noheader,nounits"]
PROCESS_TIMEOUT = 5


def command(args, timeout=PROCESS_TIMEOUT):
    try:
        # Fixed local probes only; no shell expansion or remote input.
        result = subprocess.run(args, shell=False, text=True, capture_output=True,  # nosec B603 # nosemgrep # noqa: S603
                                timeout=timeout, check=True)
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def launch(args, **kwargs):
    # Executing operator-supplied argv is the purpose of this local CLI.
    return subprocess.Popen(args, shell=False, **kwargs)  # nosec B603 # nosemgrep # noqa: S603


def stop_process(process):
    if process is None:
        return
    if process.poll() is None:
        process.terminate()
    try:
        process.wait(timeout=PROCESS_TIMEOUT)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=PROCESS_TIMEOUT)


def read_response(stream, responses):
    try:
        responses.put(stream.readline())
    except (OSError, ValueError):
        responses.put("")


def decode_temperature(line):
    response = json.loads(line)
    if not isinstance(response, dict):
        raise ValueError("helper response must be an object")
    value = response.get("value_c")
    if value is not None and not valid_temperature(value):
        return None, response.get("sensor"), "invalid_reading"
    return value, response.get("sensor"), response.get("status", "unavailable")


def valid_temperature(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(value) and 0 < value <= 125


class TemperatureHelper:
    def __init__(self, args):
        self.process = launch(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                              text=True, bufsize=1)
        self.failed = False

    def sample(self, timeout=PROCESS_TIMEOUT):
        if self.failed or self.process.poll() is not None:
            return None, None, "unavailable"
        responses = queue.Queue(maxsize=1)
        try:
            self.process.stdin.write("sample\n")
            self.process.stdin.flush()
            reader = threading.Thread(target=read_response,
                                      args=(self.process.stdout, responses), daemon=True)
            reader.start()
            line = responses.get(timeout=timeout)
            return decode_temperature(line)
        except queue.Empty:
            self.failed = True
            stop_process(self.process)
            return None, None, "timeout"
        except (OSError, ValueError, AttributeError):
            self.failed = True
            return None, None, "read_error"

    def close(self):
        stop_process(self.process)
        self.process.stdin.close()
        self.process.stdout.close()


def helper_command(parser, path):
    if not path:
        return None
    if platform.system() != "Windows":
        parser.error("--cpu-temp-helper is currently supported only on Windows")
    helper_path = Path(path).expanduser().resolve()
    if not helper_path.is_file():
        parser.error("CPU temperature helper not found")
    args = [str(helper_path)]
    if helper_path.suffix.lower() == ".dll":
        args.insert(0, "dotnet")
    return args


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True, help="Public workload identifier; do not include secrets")
    parser.add_argument("--interval-seconds", type=float, default=5)
    parser.add_argument("--output", required=True, help="New directory for CSV and manifest")
    parser.add_argument("--cpu-temp-helper", help="Windows LibreHardwareMonitor executable or DLL")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="Workload command after --")
    args = parser.parse_args(argv)
    if not math.isfinite(args.interval_seconds) or args.interval_seconds <= 0:
        parser.error("--interval-seconds must be finite and positive")
    args.command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not args.command:
        parser.error("provide the sustained workload command after --")
    args.helper_command = helper_command(parser, args.cpu_temp_helper)
    return args


def gpu_sample(available):
    if not available:
        return [""] * 6, "unavailable"
    output = command(GPU_QUERY)
    if not output:
        return [""] * 6, "query_failed"
    values = [value.strip() for value in output.splitlines()[0].split(",")]
    if len(values) != 6:
        return [""] * 6, "query_failed"
    return [normalize_gpu_value(value) for value in values], "ok"


def normalize_gpu_value(value):
    return "" if value.lower() in ("n/a", "na", "[not supported]") else value


def cpu_utilization(previous, current):
    if not previous or not current:
        return None
    total = current[0] - previous[0]
    if total <= 0:
        return None
    return round(100 * (1 - (current[1] - previous[1]) / total), 2)


def csv_value(value):
    return "null" if value is None or value == "" else value


class Capture:
    def __init__(self, args, out):
        self.args = args
        self.out = out
        self.started = dt.datetime.now(dt.timezone.utc)
        self.start_mono = time.monotonic()
        self.gpu_available = shutil.which("nvidia-smi") is not None
        self.helper = None
        self.process = None
        self.rows = 0
        self.exit_code = None
        self.status = "failed"
        self.previous_cpu = None

    def sample(self, now):
        gpu_values, gpu_status = gpu_sample(self.gpu_available)
        current_cpu = sample_cpu()
        utilization = cpu_utilization(self.previous_cpu, current_cpu)
        self.previous_cpu = current_cpu
        mem = memory()
        temperature, sensor, temperature_status = self.temperature()
        values = [dt.datetime.now(dt.timezone.utc).isoformat(),
                  round(now - self.start_mono, 3), self.args.run_id, *gpu_values,
                  utilization, mem.get("MemTotal"), mem.get("MemAvailable"),
                  temperature, sensor, gpu_status, temperature_status]
        return dict(zip(FIELDS, map(csv_value, values)))

    def temperature(self):
        if self.helper:
            return self.helper.sample()
        if platform.system() == "Windows":
            return None, None, "unavailable"
        return cpu_temp(command)

    def collect(self):
        with (self.out / "telemetry.csv").open("x", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS)
            writer.writeheader()
            while True:
                now = time.monotonic()
                writer.writerow(self.sample(now))
                stream.flush()
                self.rows += 1
                if self.process.poll() is not None:
                    return self.process.wait()
                time.sleep(max(0, self.args.interval_seconds - (time.monotonic() - now)))

    def run(self):
        try:
            if self.args.helper_command:
                self.helper = TemperatureHelper(self.args.helper_command)
            self.previous_cpu = sample_cpu()
            self.process = launch(self.args.command)
            self.exit_code = self.collect()
            self.status = "completed"
        except KeyboardInterrupt:
            self.status = "interrupted"
        finally:
            self.finish()
        return self.exit_code

    def finish(self):
        try:
            stop_process(self.process)
            if self.process is not None:
                self.exit_code = self.process.returncode
        finally:
            try:
                if self.helper:
                    self.helper.close()
            finally:
                self.write_manifest()

    def write_manifest(self):
        manifest = {
            "schema_version": 1, "run_id": self.args.run_id,
            "started_at_utc": self.started.isoformat(),
            "ended_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "elapsed_seconds": round(time.monotonic() - self.start_mono, 3),
            "sample_interval_seconds": self.args.interval_seconds,
            "sample_count": self.rows, "workload_exit_code": self.exit_code,
            "collection_status": self.status, "host": host_metadata(self.gpu_available),
            "sources": source_metadata(self.args, self.gpu_available),
            "telemetry_file": "telemetry.csv",
        }
        (self.out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def gpu_metadata(field, available):
    if not available:
        return None
    return command(["nvidia-smi", "--id=0", f"--query-gpu={field}", "--format=csv,noheader"])


def host_metadata(gpu_available):
    return {"platform": platform.system(), "python": platform.python_version(),
            "cpu_model": cpu_model(), "gpu_model": gpu_metadata("name", gpu_available),
            "gpu_driver": gpu_metadata("driver_version", gpu_available),
            "repository_revision": command(["git", "rev-parse", "HEAD"])}


def source_metadata(args, gpu_available):
    windows = platform.system() == "Windows"
    return {"gpu": "nvidia-smi" if gpu_available else "unavailable", "gpu_index": 0,
            "cpu_temperature": "LibreHardwareMonitor helper" if args.helper_command else "optional hwmon/lm_sensors",
            "cpu_utilization": "GetSystemTimes" if windows else "/proc/stat",
            "memory": "GlobalMemoryStatusEx" if windows else "/proc/meminfo"}


def main(argv=None):
    args = parse_args(argv)
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=False)
    exit_code = Capture(args, out).run()
    print(out)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
