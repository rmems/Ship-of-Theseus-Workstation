"""Read-only CPU, memory and Linux temperature probes for capture_telemetry."""
import ctypes
import ctypes.wintypes
import json
import math
import os
import platform
from pathlib import Path


class MemoryStatus(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.wintypes.DWORD), ("dwMemoryLoad", ctypes.wintypes.DWORD),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


def ticks(value):
    return (value.dwHighDateTime << 32) | value.dwLowDateTime


def windows_cpu():
    idle, kernel, user = (ctypes.wintypes.FILETIME() for _ in range(3))
    if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
        return None
    # Windows kernel time includes idle time.
    return ticks(kernel) + ticks(user), ticks(idle)


def sample_cpu():
    """Return aggregate and idle CPU jiffies for utilization deltas."""
    if platform.system() == "Windows":
        return windows_cpu()
    try:
        values = [int(value) for value in Path("/proc/stat").read_text().splitlines()[0].split()[1:]]
        # guest and guest_nice are already included in user and nice.
        return sum(values[:8]), values[3] + values[4]
    except (OSError, ValueError, IndexError):
        return None


def windows_memory():
    status = MemoryStatus()
    status.dwLength = ctypes.sizeof(status)
    if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return {"MemTotal": status.ullTotalPhys, "MemAvailable": status.ullAvailPhys}
    return {}


def parse_memory(lines):
    found = {}
    for line in lines:
        key, value = line.split(":", 1)
        if key in ("MemTotal", "MemAvailable"):
            found[key] = int(value.strip().split()[0]) * 1024
    return found


def memory():
    """Return MemTotal and MemAvailable in bytes when the platform exposes them."""
    if platform.system() == "Windows":
        return windows_memory()
    try:
        return parse_memory(Path("/proc/meminfo").read_text().splitlines())
    except (OSError, ValueError, IndexError):
        return {}


def cpu_model():
    """Return a human-readable CPU model string when available."""
    if platform.system() == "Windows":
        return os.environ.get("PROCESSOR_IDENTIFIER")
    try:
        return linux_cpu_model(Path("/proc/cpuinfo").read_text().splitlines())
    except OSError:
        return None


def linux_cpu_model(lines):
    for line in lines:
        if line.lower().startswith("model name"):
            return line.split(":", 1)[1].strip()
    return None


def sensor_rank(label):
    """Rank CPU temperature sensor labels with Tctl/Tdie preferred."""
    name = label.replace(" ", "").replace("/", "").lower()
    if "tctltdie" in name:
        return 0
    if "tctl" in name or "tdie" in name:
        return 1
    if "package" in name:
        return 2
    return 99


def eligible_chip(name):
    return name.startswith(("k10temp", "coretemp"))


def hwmon_candidate(path):
    try:
        chip = (path.parent / "name").read_text().strip()
        if not eligible_chip(chip):
            return None
        label = path.with_name(path.name.replace("_input", "_label")).read_text().strip()
        value = int(path.read_text().strip()) / 1000
        return sensor_rank(label), f"{chip}/{label}", value
    except (OSError, ValueError):
        return None


def choose_temperature(candidates):
    """Return the best-ranked finite temperature reading and a collection status."""
    for rank, label, value in sorted(candidates):
        if rank >= 99:
            continue
        if math.isfinite(value) and 0 < value <= 125:
            return value, label, "ok"
    return None


def sensor_inputs(values):
    if not isinstance(values, dict):
        return
    for key, value in values.items():
        if key.endswith("_input") and isinstance(value, (int, float)):
            yield value


def chip_candidates(chip, values):
    if not isinstance(values, dict):
        return
    for label, inputs in values.items():
        for value in sensor_inputs(inputs):
            yield sensor_rank(label), f"{chip}/{label}", value


def lm_candidates(output):
    values = json.loads(output)
    if not isinstance(values, dict):
        return []
    candidates = []
    for chip, sensors in values.items():
        if eligible_chip(chip):
            candidates.extend(chip_candidates(chip, sensors))
    return candidates


def lm_temperature(command):
    output = command(["sensors", "-j"])
    if not output:
        return None
    try:
        return choose_temperature(lm_candidates(output))
    except (ValueError, TypeError):
        return None


def cpu_temp(command, root=Path("/sys/class/hwmon")):
    """Read CPU temperature from hwmon or lm_sensors with ranked sensor selection."""
    candidates = filter(None, (hwmon_candidate(path) for path in root.glob("hwmon*/temp*_input")))
    result = choose_temperature(candidates)
    if result is not None:
        return result
    return lm_temperature(command) or (None, None, "unavailable")
