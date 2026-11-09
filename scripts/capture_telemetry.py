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
import os
import platform
import queue
import shutil
# Required by this local workload runner.
import signal
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
INTERRUPTED_EXIT = 130


def command(args, timeout=PROCESS_TIMEOUT):
    """Run a fixed local probe command and return stripped stdout, or None on failure."""
    try:
        # Fixed local probes only; no shell expansion or remote input.
        result = subprocess.run(args, shell=False, text=True, capture_output=True,  # nosec B603 # nosemgrep # noqa: S603
                                timeout=timeout, check=True)
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def launch(args, **kwargs):
    """Start a child process from an argv list without invoking a shell."""
    if platform.system() != "Windows" and "start_new_session" not in kwargs:
        kwargs["start_new_session"] = True
    # Executing operator-supplied argv is the purpose of this local CLI.
    return subprocess.Popen(args, shell=False, **kwargs)  # nosec B603 # nosemgrep # noqa: S603


def stop_process(process):
    """Terminate a process and its session children, escalating to kill on timeout."""
    if process is None or process.poll() is not None:
        return
    try:
        if platform.system() == "Windows":
            subprocess.run(  # nosec B603 # nosemgrep # noqa: S603
                ["taskkill", "/T", "/PID", str(process.pid)],
                capture_output=True, timeout=PROCESS_TIMEOUT, check=False,
            )
        elif isinstance(process.pid, int):
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        else:
            process.terminate()
    except (OSError, ProcessLookupError, AttributeError, TypeError):
        process.terminate()
    try:
        process.wait(timeout=PROCESS_TIMEOUT)
    except subprocess.TimeoutExpired:
        try:
            if platform.system() != "Windows" and isinstance(process.pid, int):
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            else:
                process.kill()
        except (OSError, ProcessLookupError, AttributeError, TypeError):
            process.kill()
        process.wait(timeout=PROCESS_TIMEOUT)


def read_response(stream, responses):
    """Read one helper response line into a queue for timeout-bounded callers."""
    try:
        responses.put(stream.readline())
    except (OSError, ValueError):
        responses.put("")


def decode_temperature(line):
    """Parse a helper JSON line into temperature, sensor label, and status fields."""
    response = json.loads(line)
    if not isinstance(response, dict):
        raise ValueError("helper response must be an object")
    value = response.get("value_c")
    if value is not None and not valid_temperature(value):
        return None, response.get("sensor"), "invalid_reading"
    return value, response.get("sensor"), response.get("status", "unavailable")


def valid_temperature(value):
    """Return whether value is a finite CPU temperature in degrees Celsius."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(value) and 0 < value <= 125


class TemperatureHelper:
    """Optional Windows helper that answers sample requests over stdin/stdout."""

    def __init__(self, args):
        self.process = launch(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                              text=True, bufsize=1)
        self.failed = False

    def sample(self, timeout=PROCESS_TIMEOUT):
        """Request one temperature reading; unavailable results stay distinguishable."""
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
    """Resolve the optional Windows CPU temperature helper path to an argv list."""
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
    """Parse CLI arguments and validate run configuration."""
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
    """Read GPU index 0 metrics from nvidia-smi when the tool is available."""
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
    """Normalize GPU query placeholders to empty CSV fields."""
    return "" if value.lower() in ("n/a", "na", "[not supported]") else value


def cpu_utilization(previous, current):
    """Compute CPU utilization percent between two jiffies samples."""
    if not previous or not current:
        return None
    total = current[0] - previous[0]
    if total <= 0:
        return None
    return round(100 * (1 - (current[1] - previous[1]) / total), 2)


def csv_value(value):
    """Serialize a CSV field, using the literal null token for missing values."""
    return "null" if value is None or value == "" else value


class Capture:
    """Collect telemetry samples for one workload run."""

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
        self._stop_requested = False

    def sample(self):
        """Collect one telemetry row aligned to the time probes complete."""
        gpu_values, gpu_status = gpu_sample(self.gpu_available)
        current_cpu = sample_cpu()
        utilization = cpu_utilization(self.previous_cpu, current_cpu)
        self.previous_cpu = current_cpu
        mem = memory()
        temperature, sensor, temperature_status = self.temperature()
        elapsed = round(time.monotonic() - self.start_mono, 3)
        values = [dt.datetime.now(dt.timezone.utc).isoformat(),
                  elapsed, self.args.run_id, *gpu_values,
                  utilization, mem.get("MemTotal"), mem.get("MemAvailable"),
                  temperature, sensor, gpu_status, temperature_status]
        return dict(zip(FIELDS, map(csv_value, values)))

    def temperature(self):
        """Return CPU temperature using the helper on Windows or sysfs/lm_sensors on Linux."""
        if self.helper:
            return self.helper.sample()
        if platform.system() == "Windows":
            return None, None, "unavailable"
        return cpu_temp(command)

    def wait_interval(self, interval_start):
        """Sleep until the next sample, returning early when the workload exits."""
        deadline = interval_start + self.args.interval_seconds
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                return self.process.wait()
            time.sleep(min(0.05, deadline - time.monotonic()))
        return None

    def collect(self):
        """Sample until the workload exits."""
        with (self.out / "telemetry.csv").open("x", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS)
            writer.writeheader()
            while not self._stop_requested:
                if self.process.poll() is not None:
                    return self.process.wait()
                interval_start = time.monotonic()
                row = self.sample()
                if self.process.poll() is not None or self._stop_requested:
                    break
                writer.writerow(row)
                stream.flush()
                self.rows += 1
                if self.process.poll() is not None:
                    return self.process.wait()
                exit_code = self.wait_interval(interval_start)
                if exit_code is not None:
                    return exit_code
            if self.process.poll() is not None:
                return self.process.wait()
            return None

    def request_stop(self):
        self._stop_requested = True

    def run(self):
        """Run the workload and write telemetry until it exits or collection stops."""
        previous_handler = None
        if hasattr(signal, "SIGTERM"):
            previous_handler = signal.signal(signal.SIGTERM, self._handle_stop_signal)
        try:
            if self.args.helper_command:
                try:
                    self.helper = TemperatureHelper(self.args.helper_command)
                except OSError:
                    self.helper = None
            self.previous_cpu = sample_cpu()
            self.process = launch(self.args.command)
            self.exit_code = self.collect()
            if self.status != "interrupted":
                self.status = "completed"
        except KeyboardInterrupt:
            self.status = "interrupted"
            self.request_stop()
        finally:
            if previous_handler is not None:
                signal.signal(signal.SIGTERM, previous_handler)
            self.finish()
        if self.status == "interrupted" and self.process is None:
            return INTERRUPTED_EXIT
        return self.exit_code

    def _handle_stop_signal(self, _signum, _frame):
        self.status = "interrupted"
        self.request_stop()

    def finish(self):
        """Stop child processes and always attempt to write a manifest."""
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
        """Write run metadata without hostname or workload argv."""
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
    """Read one nvidia-smi metadata field for GPU index 0."""
    if not available:
        return None
    return command(["nvidia-smi", "--id=0", f"--query-gpu={field}", "--format=csv,noheader"])


def host_metadata(gpu_available):
    """Return redacted host metadata for the manifest."""
    return {"platform": platform.system(), "python": platform.python_version(),
            "cpu_model": cpu_model(), "gpu_model": gpu_metadata("name", gpu_available),
            "gpu_driver": gpu_metadata("driver_version", gpu_available),
            "repository_revision": command(["git", "rev-parse", "HEAD"])}


def cpu_temperature_source(args):
    """Describe the configured CPU temperature backend in manifest sources."""
    if platform.system() == "Windows":
        return "LibreHardwareMonitor helper" if args.helper_command else "unavailable"
    return "sysfs_hwmon/lm_sensors"


def source_metadata(args, gpu_available):
    """Return manifest source labels for each telemetry channel."""
    windows = platform.system() == "Windows"
    return {"gpu": "nvidia-smi" if gpu_available else "unavailable", "gpu_index": 0,
            "cpu_temperature": cpu_temperature_source(args),
            "cpu_utilization": "GetSystemTimes" if windows else "/proc/stat",
            "memory": "GlobalMemoryStatusEx" if windows else "/proc/meminfo"}


def remove_uninitialized_output(path):
    """Remove an output directory created before manifest emission on failed init."""
    if not path.is_dir() or (path / "manifest.json").exists():
        return
    try:
        shutil.rmtree(path)
    except OSError:
        pass


def main(argv=None):
    """CLI entry point."""
    args = parse_args(argv)
    out = Path(args.output)
    created = False
    try:
        out.mkdir(parents=True, exist_ok=False)
        created = True
        exit_code = Capture(args, out).run()
        print(out)
        return 0 if exit_code is None else exit_code
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException:
        if created:
            remove_uninitialized_output(out)
        raise


if __name__ == "__main__":
    sys.exit(main())
