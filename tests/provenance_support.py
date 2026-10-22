"""Shared fixtures for the provenance manifest tests."""

import importlib.machinery
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "theseus-provenance"
LOADER = importlib.machinery.SourceFileLoader("theseus_provenance", str(SCRIPT))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
prov = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = prov
LOADER.exec_module(prov)
FIXTURES = ROOT / "tests" / "fixtures" / "provenance"

MACHINE_ID = "0123456789abcdef0123456789abcdef"
FIXTURE_SERIAL = "UNREAD-SERIAL-7Q2X"
FIXTURE_BOARD_ID = "4c4c4544-0042-3510-8051-b4c04f4e4a33"
FIXTURE_HOST = "build-host-marker"
FIXTURE_USER = "local-login"
SHA_A = "a" * 40
SHA_B = "b" * 40
FIXED_TIME = "2026-10-19T12:00:00Z"
NVIDIA_QUERY = ",".join(name for _key, name in prov.NVIDIA_QUERY_FIELDS)


def build_sysroot(root: Path, *, nvidia: bool = True, governors=("performance", "performance")) -> Path:
    def put(rel: str, text: str) -> None:
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    put("etc/os-release", (FIXTURES / "os-release").read_text())
    put("etc/machine-id", MACHINE_ID + "\n")
    put("proc/sys/kernel/osrelease", "6.17.4-300.fc43.x86_64\n")
    put("proc/cpuinfo", "processor\t: 0\nmodel name\t: AMD Ryzen 9 9950X 16-Core Processor\n")
    dmi = "sys/class/dmi/id"
    put(f"{dmi}/bios_vendor", "American Megatrends Inc.\n")
    put(f"{dmi}/bios_version", "1801\n")
    put(f"{dmi}/bios_date", "08/15/2026\n")
    put(f"{dmi}/board_vendor", "ASUSTeK COMPUTER INC.\n")
    put(f"{dmi}/board_name", "ProArt X870E-CREATOR WIFI\n")
    # Identifiers that sit next to the allowlisted attributes and must never be read.
    put(f"{dmi}/product_serial", FIXTURE_SERIAL + "\n")
    put(f"{dmi}/board_serial", FIXTURE_SERIAL + "\n")
    put(f"{dmi}/product_uuid", FIXTURE_BOARD_ID + "\n")
    for index, governor in enumerate(governors):
        put(f"sys/devices/system/cpu/cpu{index}/cpufreq/scaling_governor", governor + "\n")
        put(f"sys/devices/system/cpu/cpu{index}/cpufreq/energy_performance_preference", "performance\n")
    put("sys/devices/system/cpu/amd_pstate/status", "active\n")
    put("sys/devices/system/cpu/cpufreq/boost", "1\n")
    if nvidia:
        put("proc/driver/nvidia/version", (FIXTURES / "proc-driver-nvidia-version.txt").read_text())
    return root


def _ok(out: str):
    return prov.CommandResult(0, out, "")


NVIDIA_SMI_FIXTURES = {
    ("nvidia-smi", f"--query-gpu={NVIDIA_QUERY}", "--format=csv,noheader,nounits"): "nvidia-query.csv",
    ("nvidia-smi",): "nvidia-smi-banner.txt",
}
NVCC_FIXTURES = {("nvcc", "--version"): "nvcc.txt"}
STATIC_OUTPUTS = {
    ("python3", "--version"): "Python 3.13.7\n",
    ("rustc", "--version"): "rustc 1.90.0 (1159e78c4 2026-09-14)\n",
    ("cargo", "--version"): "cargo 1.90.0 (840b83a10 2026-07-30)\n",
    ("gcc", "-dumpfullversion"): "15.2.1\n",
}
TORCH_PROBES = {
    None: {"installed": False},
    "cpu": {"installed": True, "version": "2.9.0+cpu", "cuda": None, "cudnn": None},
    "cuda": {"installed": True, "version": "2.9.0+cu130", "cuda": "13.0", "cudnn": 91300},
    "cuda-no-cudnn": {"installed": True, "version": "2.9.0+cu130", "cuda": "13.0", "cudnn": None},
}


def is_status_entry(node) -> bool:
    return isinstance(node, dict) and {"source", "status"} <= node.keys()


def child_nodes(node, where):
    if isinstance(node, dict):
        return [(f"{where}.{key}", value) for key, value in node.items()]
    if isinstance(node, list):
        return [(f"{where}[{index}]", value) for index, value in enumerate(node)]
    return []


class FakeRunner:
    """Answers the exact commands the collector issues; anything else is 'not installed'."""

    def __init__(self, *, nvidia: bool = True, torch: str | None = "cuda", overrides=None):
        self.nvidia = nvidia
        self.torch = torch
        self.overrides = overrides or {}
        self.calls: list[tuple[str, ...]] = []

    def run(self, *args, timeout=None, cwd=None):
        self.calls.append(args)
        override = self._find_override(args)
        if override is not None:
            return override(args)
        if args[:2] == ("python3", "-c"):
            return self._torch_probe()
        handler = self._HANDLERS.get(args[0], FakeRunner._static)
        return handler(self, args)

    def _find_override(self, args):
        return next((handler for prefix, handler in self.overrides.items() if args[: len(prefix)] == prefix), None)

    def _require_nvidia(self, command):
        if not self.nvidia:
            raise FileNotFoundError(command)

    def _static(self, args):
        if args not in STATIC_OUTPUTS:
            raise FileNotFoundError(args[0])
        return _ok(STATIC_OUTPUTS[args])

    def _fixture(self, table, args):
        self._require_nvidia(args[0])
        if args not in table:
            raise FileNotFoundError(args[0])
        return _ok((FIXTURES / table[args]).read_text())

    def _nvidia_smi(self, args):
        return self._fixture(NVIDIA_SMI_FIXTURES, args)

    def _nvcc(self, args):
        return self._fixture(NVCC_FIXTURES, args)

    def _torch_probe(self):
        payload = TORCH_PROBES.get(self.torch, TORCH_PROBES["cuda"])
        return _ok(json.dumps(payload) + "\n")

    def _git(self, args):
        repo = args[2]
        if "not-a-repo" in repo:
            return prov.CommandResult(128, "", "fatal: not a git repository")
        if args[3:5] == ("rev-parse", "--show-prefix"):
            return _ok("docs/\n" if "subdir" in repo else "\n")
        if args[3:5] == ("rev-parse", "--verify"):
            return _ok((SHA_B if "workload" in repo else SHA_A) + "\n")
        if args[3] == "status":
            return _ok(" M src/lib.rs\n" if "dirty" in repo else "")
        raise FileNotFoundError(args[0])

    _HANDLERS = {"nvidia-smi": _nvidia_smi, "nvcc": _nvcc, "git": _git}


class ProvenanceTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.sysroot = build_sysroot(self.tmp / "sysroot")
        self.identity_patch = mock.patch.object(prov, "local_identity_terms", return_value=[])
        self.identity_patch.start()

    def tearDown(self):
        self.identity_patch.stop()
        self._tmp.cleanup()

    def probe(self, **runner_kwargs):
        return prov.Probe(runner=FakeRunner(**runner_kwargs), sysroot=self.sysroot, machine=lambda: "x86_64")

    def options(self, **overrides):
        base = dict(
            host_role="telemetry-capture",
            run_id="telemetry-2026-10-19-001",
            run_kind="telemetry",
            repos=[f"rmems/gaming-telemetry={self.tmp / 'workload'}"],
            telemetry_contract="2.1.0",
            telemetry_collector="gaming-telemetry=0.6.0",
            meta=["workload_class=gpu-ml"],
        )
        base.update(overrides)
        return prov.Options(**base)

    def manifest(self, probe=None, **overrides):
        return prov.build_manifest(self.options(**overrides), probe or self.probe(), created_at=FIXED_TIME)

