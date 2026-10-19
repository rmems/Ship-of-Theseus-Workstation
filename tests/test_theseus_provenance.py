import argparse
import copy
import importlib.machinery
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
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
SECRET_SERIAL = "SECRET-SERIAL-7Q2X"
SECRET_UUID = "4c4c4544-0042-3510-8051-b4c04f4e4a33"
SECRET_HOST = "secret-build-host"
SECRET_USER = "secret-user"
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
    put(f"{dmi}/product_serial", SECRET_SERIAL + "\n")
    put(f"{dmi}/board_serial", SECRET_SERIAL + "\n")
    put(f"{dmi}/product_uuid", SECRET_UUID + "\n")
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
}


def _is_status_entry(node) -> bool:
    return isinstance(node, dict) and {"source", "status"} <= node.keys()


def _children(node, where):
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
        if args[:3] == ("python3", "-I", "-c"):
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


class CollectionTests(ProvenanceTestCase):
    def test_full_host_manifest_records_expected_values(self):
        data = self.manifest()
        env = data["environment"]
        self.assertEqual(data["schema_version"], "1.0.0")
        self.assertRegex(data["manifest_id"], r"^prov-20261019T120000Z-[0-9a-f]{8}$")
        self.assertEqual(env["os"]["id"]["value"], "fedora")
        self.assertEqual(env["kernel_release"]["value"], "6.17.4-300.fc43.x86_64")
        self.assertEqual(env["firmware"]["bios_version"]["value"], "1801")
        self.assertEqual(env["firmware"]["board_name"]["value"], "ProArt X870E-CREATOR WIFI")
        self.assertEqual(env["cpu"]["scaling_governors"]["value"], ["performance"])
        self.assertEqual(env["cpu"]["amd_pstate_mode"]["value"], "active")
        self.assertIs(env["cpu"]["boost_enabled"]["value"], True)
        self.assertEqual(env["gpu"]["kernel_module_version"]["value"], "580.95.05")
        gpu = env["gpu"]["devices"]["value"][0]
        self.assertEqual(gpu["name"]["value"], "NVIDIA GeForce RTX 5080")
        self.assertEqual(gpu["vbios_version"]["value"], "98.03.4F.00.01")
        self.assertEqual(gpu["power_limit_w"]["value"], 360)
        self.assertEqual(gpu["clocks_max_graphics_mhz"]["value"], 3195)
        self.assertEqual(env["cuda"]["driver_cuda_version"]["value"], "13.0")
        self.assertEqual(env["cuda"]["toolkit_version"]["value"], "13.0")
        self.assertEqual(env["toolchains"]["rustc"]["value"], "1.90.0")
        self.assertEqual(env["frameworks"]["pytorch_cudnn"]["value"], "91300")
        self.assertEqual(data["repositories"][0]["commit"]["value"], SHA_B)
        self.assertIs(data["repositories"][0]["dirty"]["value"], False)
        self.assertEqual(data["telemetry"]["contract_version"]["value"], "2.1.0")
        self.assertEqual(data["telemetry"]["collector_name"]["value"], "gaming-telemetry")
        self.assertEqual(data["node"]["host_role"], "telemetry-capture")
        prov.validate_manifest(data)

    def test_host_fingerprint_is_keyed_hash_not_raw_machine_id(self):
        data = self.manifest()
        fingerprint = data["node"]["host_fingerprint"]["value"]
        self.assertRegex(fingerprint, r"^hmac-sha256:[0-9a-f]{64}$")
        serialized = json.dumps(data)
        self.assertNotIn(MACHINE_ID, serialized)
        import hashlib
        self.assertNotIn(hashlib.sha256(MACHINE_ID.encode()).hexdigest(), serialized, "must be keyed, not a bare hash")
        self.assertEqual(fingerprint, self.manifest()["node"]["host_fingerprint"]["value"], "must be stable")

    def test_host_fingerprint_opt_out_is_explicitly_omitted(self):
        entry = self.manifest(no_host_fingerprint=True)["node"]["host_fingerprint"]
        self.assertEqual(entry, {"source": "machine_id", "status": "omitted", "reason": "operator_opt_out"})


class DegradationTests(ProvenanceTestCase):
    """Missing sources are recorded as unavailable with a reason, never omitted or guessed."""

    def assert_status_entry(self, node, where):
        if node["status"] == "available":
            self.assertIn("value", node, where)
            self.assertIsNotNone(node["value"], where)
            return
        self.assertIn("reason", node, where)
        self.assertNotIn("value", node, where)

    def assert_all_leaves_explicit(self, node, where):
        if _is_status_entry(node):
            self.assert_status_entry(node, where)
            return
        for child_where, child in _children(node, where):
            self.assert_all_leaves_explicit(child, child_where)

    def test_no_nvidia_stack_degrades_explicitly(self):
        sysroot = build_sysroot(self.tmp / "no-gpu", nvidia=False)
        probe = prov.Probe(runner=FakeRunner(nvidia=False, torch=None), sysroot=sysroot, machine=lambda: "x86_64")
        data = self.manifest(probe)
        env = data["environment"]
        self.assertEqual(env["gpu"]["devices"], {"source": "nvidia_smi", "status": "unavailable", "reason": "command_not_found"})
        self.assertEqual(env["gpu"]["kernel_module_version"]["reason"], "source_unavailable")
        self.assertEqual(env["cuda"]["driver_cuda_version"]["reason"], "command_not_found")
        self.assertEqual(env["cuda"]["toolkit_version"]["reason"], "command_not_found")
        self.assertEqual(env["frameworks"]["pytorch"]["reason"], "module_not_installed")
        self.assertEqual(env["toolchains"]["julia"]["reason"], "command_not_found")
        prov.validate_manifest(data)

    def test_every_leaf_field_has_status_and_unavailable_fields_carry_reason(self):
        sysroot = build_sysroot(self.tmp / "bare", nvidia=False)
        probe = prov.Probe(runner=FakeRunner(nvidia=False, torch=None), sysroot=sysroot, machine=lambda: "x86_64")
        data = prov.build_manifest(prov.Options(), probe, created_at=FIXED_TIME)
        self.assert_all_leaves_explicit(data["environment"], "environment")
        self.assert_all_leaves_explicit(data["telemetry"], "telemetry")
        self.assertEqual(data["links"]["run_id"]["reason"], "not_provided")
        self.assertEqual(data["links"]["system_report"]["reason"], "not_provided")

    def test_empty_sysroot_still_produces_a_valid_fully_explicit_manifest(self):
        empty = self.tmp / "empty"
        empty.mkdir()
        probe = prov.Probe(runner=FakeRunner(nvidia=False, torch=None), sysroot=empty, machine=lambda: "")
        data = prov.build_manifest(prov.Options(), probe, created_at=FIXED_TIME)
        env = data["environment"]
        self.assertEqual(env["os"]["id"]["status"], "unavailable")
        self.assertEqual(env["kernel_release"]["status"], "unavailable")
        self.assertEqual(env["architecture"]["status"], "unavailable")
        self.assertEqual(env["cpu"]["scaling_governors"]["reason"], "source_unavailable")
        self.assertEqual(data["node"]["host_fingerprint"]["reason"], "source_unavailable")
        prov.validate_manifest(data)

    def test_nvidia_not_supported_columns_are_unavailable_not_zero(self):
        row = "0, NVIDIA GeForce RTX 5080, 580.95.05, [N/A], 12.0, 16303, [N/A], 360.00, 360.00, [Not Supported], 3195, 15001, Disabled, 5, 16\n"
        runner = FakeRunner(overrides={("nvidia-smi", f"--query-gpu={NVIDIA_QUERY}"): lambda _a: prov.CommandResult(0, row, "")})
        probe = prov.Probe(runner=runner, sysroot=self.sysroot, machine=lambda: "x86_64")
        gpu = self.manifest(probe)["environment"]["gpu"]["devices"]["value"][0]
        self.assertEqual(gpu["vbios_version"], {"source": "nvidia_smi", "status": "unavailable", "reason": "not_supported_by_device"})
        self.assertEqual(gpu["power_limit_w"]["reason"], "not_supported_by_device")
        self.assertEqual(gpu["power_max_limit_w"]["reason"], "not_supported_by_device")
        self.assertEqual(gpu["power_default_limit_w"]["value"], 360)

    def test_malformed_nvidia_output_is_unparseable_not_guessed(self):
        runner = FakeRunner(overrides={("nvidia-smi", f"--query-gpu={NVIDIA_QUERY}"): lambda _a: prov.CommandResult(0, "garbage,row\n", "")})
        probe = prov.Probe(runner=runner, sysroot=self.sysroot, machine=lambda: "x86_64")
        devices = self.manifest(probe)["environment"]["gpu"]["devices"]
        self.assertEqual(devices, {"source": "nvidia_smi", "status": "unavailable", "reason": "unparseable_output"})

    def test_command_timeout_and_permission_are_classified(self):
        def timeout(_args):
            raise subprocess.TimeoutExpired("nvcc", 30)

        def denied(_args):
            raise PermissionError("rustc")

        runner = FakeRunner(overrides={("nvcc",): timeout, ("rustc",): denied})
        probe = prov.Probe(runner=runner, sysroot=self.sysroot, machine=lambda: "x86_64")
        env = self.manifest(probe)["environment"]
        self.assertEqual(env["cuda"]["toolkit_version"]["reason"], "command_timeout")
        self.assertEqual(env["toolchains"]["rustc"]["reason"], "permission_denied")

    def test_cpu_only_pytorch_build_is_explicit(self):
        frameworks = self.manifest(self.probe(torch="cpu"))["environment"]["frameworks"]
        self.assertEqual(frameworks["pytorch"]["value"], "2.9.0+cpu")
        self.assertEqual(frameworks["pytorch_cuda_build"]["reason"], "cpu_only_build")

    def test_mixed_governors_are_all_recorded(self):
        sysroot = build_sysroot(self.tmp / "mixed", governors=("performance", "powersave"))
        probe = prov.Probe(runner=FakeRunner(), sysroot=sysroot, machine=lambda: "x86_64")
        governors = self.manifest(probe)["environment"]["cpu"]["scaling_governors"]["value"]
        self.assertEqual(governors, ["performance", "powersave"])

    def test_non_git_and_dirty_workload_repositories(self):
        data = self.manifest(repos=[f"a={self.tmp / 'not-a-repo'}", f"b={self.tmp / 'dirty-workload'}"])
        self.assertEqual(data["repositories"][0]["commit"]["reason"], "not_a_git_repository")
        self.assertEqual(data["repositories"][0]["dirty"]["reason"], "not_a_git_repository")
        self.assertIs(data["repositories"][1]["dirty"]["value"], True)

    def test_require_gate_fails_loud_when_field_unavailable(self):
        probe = prov.Probe(runner=FakeRunner(nvidia=False), sysroot=self.sysroot, machine=lambda: "x86_64")
        with self.assertRaisesRegex(prov.ProvenanceError, r"environment\.gpu\.devices\.0\.vbios_version \(command_not_found\)"):
            self.manifest(probe, require=["environment.gpu.devices.0.vbios_version"])
        with self.assertRaisesRegex(prov.ProvenanceError, "unknown field"):
            self.manifest(require=["environment.nope"])
        self.manifest(require=["environment.gpu.devices.0.vbios_version", "environment.cuda.toolkit_version"])


class RedactionTests(ProvenanceTestCase):
    """Forbidden identifiers must never appear in a collected manifest, and the validator rejects them."""

    def serialized(self, data):
        return json.dumps(data, sort_keys=True)

    def test_collected_manifest_contains_no_planted_identifiers(self):
        artifact = self.tmp / "home" / SECRET_USER / "runs" / "telemetry.csv"
        artifact.parent.mkdir(parents=True)
        artifact.write_text("t,gpu_temp\n0,41\n")
        data = self.manifest(artifacts=[f"telemetry={artifact}"])
        text = self.serialized(data)
        for forbidden in (SECRET_SERIAL, SECRET_UUID, SECRET_HOST, SECRET_USER, MACHINE_ID, str(self.tmp), "/home/", "builder@", "00000000:01:00.0", "secret-app"):
            self.assertNotIn(forbidden, text, f"leaked {forbidden!r}")
        self.assertEqual(data["links"]["artifacts"][0]["size_bytes"], artifact.stat().st_size)
        self.assertEqual(prov.redaction_violations(data), [])

    def test_dmi_serial_and_uuid_files_are_never_opened(self):
        opened = []
        real_read = prov.Probe.read

        def spy(self, absolute):
            opened.append(absolute)
            return real_read(self, absolute)

        with mock.patch.object(prov.Probe, "read", spy):
            self.manifest()
        for name in opened:
            self.assertNotRegex(name, r"(serial|uuid|asset_tag)")

    def test_nvidia_query_never_requests_identifying_columns(self):
        runner = FakeRunner()
        prov.build_manifest(self.options(), prov.Probe(runner=runner, sysroot=self.sysroot, machine=lambda: "x86_64"), created_at=FIXED_TIME)
        queries = [arg for call in runner.calls for arg in call if arg.startswith("--query-gpu=")]
        self.assertTrue(queries)
        for query in queries:
            for column in ("uuid", "serial", "pci.bus_id", "pci.device_id", "pci.sub_device_id", "board_id"):
                self.assertNotIn(column, query)

    def test_validator_rejects_forbidden_keys_anywhere(self):
        base = self.manifest()
        for key in ("hostname", "username", "serial_number", "gpu_uuid", "mac_address", "ip_address", "home_dir", "repo_path", "remote_url", "pci_bus_id"):
            data = copy.deepcopy(base)
            data["environment"]["os"][key] = "x"
            with self.assertRaisesRegex(prov.ProvenanceError, "forbidden key", msg=key):
                prov.validate_manifest(data)
        nested = copy.deepcopy(base)
        nested["environment"]["gpu"]["devices"]["value"][0]["serial"] = "x"
        with self.assertRaisesRegex(prov.ProvenanceError, "forbidden key"):
            prov.validate_manifest(nested)

    def test_validator_rejects_identifier_shaped_values(self):
        base = self.manifest()
        leaks = {
            "home_or_root_path": "/home/raul/projects/run",
            "absolute_path": "/var/lib/run/out.csv",
            "ipv4_address": "192.168.1.42",
            "ipv6_address": "fe80:0:0:0:abcd:ef01:2345:6789",
            "mac_address": "a4:5e:60:12:34:56",
            "uuid": SECRET_UUID,
            "email_address": "someone@example.com",
            "url_with_credentials": "https://user:pw@example.com/x",
            "git remote": "git@github.com:rmems/private.git",
        }
        for label, value in leaks.items():
            data = copy.deepcopy(base)
            data["workload_metadata"]["note"] = value
            with self.assertRaisesRegex(prov.ProvenanceError, "redaction violation", msg=label):
                prov.validate_manifest(data)

    def test_validator_rejects_local_hostname_and_username_terms(self):
        data = self.manifest()
        data["workload_metadata"]["note"] = f"captured on {SECRET_HOST}"
        with self.assertRaisesRegex(prov.ProvenanceError, "local host identity term"):
            prov.validate_manifest(data, extra_forbidden=[SECRET_HOST])

    def test_collection_refuses_metadata_that_leaks_the_running_host(self):
        self.identity_patch.stop()
        try:
            with mock.patch.object(prov.socket, "gethostname", return_value="workstation-xyz.local"), mock.patch.object(
                prov.getpass, "getuser", return_value="secretuser"
            ):
                with self.assertRaisesRegex(prov.ProvenanceError, "local host identity term"):
                    self.manifest(meta=["operator=secretuser"])
                with self.assertRaisesRegex(prov.ProvenanceError, "local host identity term"):
                    self.manifest(meta=["host=workstation-xyz"])
                self.manifest()
        finally:
            self.identity_patch.start()

    def test_metadata_path_values_are_rejected_at_collection(self):
        with self.assertRaisesRegex(prov.ProvenanceError, "home_or_root_path"):
            self.manifest(meta=["dataset=/home/someone/data.parquet"])
        with self.assertRaisesRegex(prov.ProvenanceError, "home_or_root_path"):
            self.manifest(meta=["dataset=~/data.parquet"])


class SchemaTests(ProvenanceTestCase):
    def test_schema_dialect_and_version_const(self):
        schema = json.loads(prov.SCHEMA_PATH.read_text())
        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertEqual(schema["properties"]["schema_version"]["const"], prov.SCHEMA_VERSION)
        self.assertIn("schema_version", schema["required"])
        from jsonschema import Draft202012Validator
        Draft202012Validator.check_schema(schema)

    def test_missing_schema_version_fails_loud(self):
        data = self.manifest()
        del data["schema_version"]
        with self.assertRaises(prov.SchemaVersionMismatch):
            prov.validate_manifest(data)

    def test_schema_version_mismatch_fails_loud(self):
        for version in ("0.9.0", "1.0.1", "2.0.0", 1, None):
            data = self.manifest()
            data["schema_version"] = version
            with self.assertRaises(prov.SchemaVersionMismatch, msg=repr(version)):
                prov.validate_manifest(data)

    def test_redaction_policy_version_mismatch_fails_loud(self):
        data = self.manifest()
        data["redaction"]["policy_version"] = "0.1.0"
        with self.assertRaises(prov.SchemaVersionMismatch):
            prov.validate_manifest(data)

    def test_schema_file_and_validator_must_agree(self):
        schema = json.loads(prov.SCHEMA_PATH.read_text())
        schema["properties"]["schema_version"]["const"] = "9.9.9"
        bad = self.tmp / "schema.json"
        bad.write_text(json.dumps(schema))
        data = self.manifest()
        with mock.patch.object(prov, "SCHEMA_PATH", bad), self.assertRaises(prov.SchemaVersionMismatch):
            prov.validate_manifest(data)

    def test_schema_rejects_silently_omitted_field(self):
        data = self.manifest()
        del data["environment"]["firmware"]["bios_version"]
        with self.assertRaisesRegex(prov.ProvenanceError, "bios_version"):
            prov.validate_manifest(data)

    def test_schema_rejects_unavailable_without_reason_and_available_without_value(self):
        data = self.manifest()
        data["environment"]["kernel_release"] = {"source": "platform", "status": "unavailable"}
        with self.assertRaises(prov.ProvenanceError):
            prov.validate_manifest(data)
        data = self.manifest()
        data["environment"]["kernel_release"] = {"source": "platform", "status": "available"}
        with self.assertRaises(prov.ProvenanceError):
            prov.validate_manifest(data)
        data = self.manifest()
        data["environment"]["kernel_release"] = {"source": "platform", "status": "unavailable", "reason": "x", "value": "6.1"}
        with self.assertRaises(prov.ProvenanceError):
            prov.validate_manifest(data)

    def test_schema_rejects_unknown_top_level_and_bad_commit(self):
        data = self.manifest()
        data["raw_inventory"] = {}
        with self.assertRaises(prov.ProvenanceError):
            prov.validate_manifest(data)
        data = self.manifest()
        data["repositories"][0]["commit"]["value"] = "main"
        with self.assertRaises(prov.ProvenanceError):
            prov.validate_manifest(data)
        data = self.manifest()
        data["node"]["host_fingerprint"]["value"] = MACHINE_ID
        with self.assertRaises(prov.ProvenanceError):
            prov.validate_manifest(data)

    def test_system_report_link_uses_id_and_digest_only(self):
        report = self.tmp / "system-report.json"
        report.write_text(json.dumps({"report_id": "ship-of-theseus-20261019T120000Z", "schema_version": "1.0.0"}))
        link = self.manifest(system_report=str(report))["links"]["system_report"]
        self.assertEqual(set(link), {"source", "status", "report_id", "sha256"})
        bogus = self.tmp / "bogus.json"
        bogus.write_text("{}")
        with self.assertRaisesRegex(prov.ProvenanceError, "report_id"):
            self.manifest(system_report=str(bogus))

    def test_invalid_operator_inputs_fail_loud(self):
        with self.assertRaises(prov.ProvenanceError):
            self.manifest(repos=["no-equals-sign"])
        with self.assertRaises(prov.ProvenanceError):
            self.manifest(repos=["a=.", "a=."])
        with self.assertRaises(prov.ProvenanceError):
            self.manifest(artifacts=["bogus=/dev/null"])
        with self.assertRaises(prov.ProvenanceError):
            self.manifest(artifacts=[f"telemetry={self.tmp / 'missing.csv'}"])
        with self.assertRaises(prov.ProvenanceError):
            self.manifest(run_id="has space")
        with self.assertRaises(prov.ProvenanceError):
            self.manifest(meta=["BadKey=x"])


class CliTests(ProvenanceTestCase):
    def run_main(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = prov.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_validate_cli_exit_codes(self):
        good = self.tmp / "good.json"
        good.write_text(json.dumps(self.manifest()))
        self.assertEqual(self.run_main(["validate", str(good)])[0], 0)

        mismatched = self.manifest()
        mismatched["schema_version"] = "2.0.0"
        bad_version = self.tmp / "v2.json"
        bad_version.write_text(json.dumps(mismatched))
        code, _out, err = self.run_main(["validate", str(bad_version)])
        self.assertEqual(code, 3)
        self.assertIn("schema version mismatch", err)

        leaky = self.manifest()
        leaky["environment"]["os"]["hostname"] = "x"
        leak_file = self.tmp / "leak.json"
        leak_file.write_text(json.dumps(leaky))
        self.assertEqual(self.run_main(["validate", str(leak_file)])[0], 2)

        nan_file = self.tmp / "nan.json"
        nan_file.write_text(json.dumps(self.manifest()).replace('"value": 360', '"value": NaN', 1))
        self.assertEqual(self.run_main(["validate", str(nan_file)])[0], 2)

    def test_collect_refuses_to_overwrite_and_cleans_temp_files(self):
        destination = self.tmp / "out" / "manifest.json"
        with mock.patch.object(prov, "build_manifest", return_value=self.manifest()):
            args = prov.parser().parse_args(["collect", "--output", str(destination)])
            self.assertEqual(prov.collect_command(args), 0)
            first = destination.read_text()
            with self.assertRaisesRegex(prov.ProvenanceError, "refusing to overwrite"):
                prov.collect_command(args)
        self.assertEqual(destination.read_text(), first)
        self.assertEqual(sorted(p.name for p in destination.parent.iterdir()), ["manifest.json"])

    def test_command_runner_forces_stable_locale_and_no_git_prompt(self):
        with mock.patch("subprocess.run") as run:
            run.return_value = mock.Mock(returncode=0, stdout="", stderr="")
            prov.CommandRunner().run("git", "--version")
        _, kwargs = run.call_args
        self.assertEqual(kwargs["env"]["LC_ALL"], "C")
        self.assertEqual(kwargs["env"]["GIT_TERMINAL_PROMPT"], "0")


class LiveHostTests(unittest.TestCase):
    """Runs the real collector against whatever host executes the tests (CI, sandbox, or the workstation)."""

    def test_live_collection_validates_and_respects_redaction(self):
        data = prov.build_manifest(prov.Options(repos=[f"rmems/Ship-of-Theseus-Workstation={ROOT}"]))
        prov.validate_manifest(data, extra_forbidden=prov.local_identity_terms())
        text = json.dumps(data)
        self.assertNotIn(str(Path.home()), text)
        self.assertNotIn(str(ROOT), text)


if __name__ == "__main__":
    unittest.main()
