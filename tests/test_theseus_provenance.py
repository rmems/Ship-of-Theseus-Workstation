"""Collection and degradation tests for the provenance manifest."""

import hashlib
import json
import os
import sys
from unittest import mock

from .provenance_support import (
    FIXED_TIME,
    MACHINE_ID,
    NVIDIA_QUERY,
    SHA_B,
    FakeRunner,
    ProvenanceTestCase,
    child_nodes,
    is_status_entry,
    build_sysroot,
    prov,
)

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
        if is_status_entry(node):
            self.assert_status_entry(node, where)
            return
        for child_where, child in child_nodes(node, where):
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
            raise prov.subprocess.TimeoutExpired("nvcc", 30)

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

    def test_cuda_build_without_cudnn_is_not_called_cpu_only(self):
        frameworks = self.manifest(self.probe(torch="cuda-no-cudnn"))["environment"]["frameworks"]
        self.assertEqual(frameworks["pytorch_cuda_build"]["value"], "13.0")
        self.assertEqual(frameworks["pytorch_cudnn"]["reason"], "source_unavailable")

    def test_torch_probe_sees_pythonpath_installs_but_not_the_current_directory(self):
        # Real interpreter: a torch on PYTHONPATH (as with pip --user or a vendored build)
        # must be found, while a stray torch.py in the working directory must not shadow it.
        stub = self.tmp / "site" / "torch"
        (stub / "backends").mkdir(parents=True)
        (stub / "version.py").write_text("cuda = '13.0'\n")
        (stub / "backends" / "__init__.py").write_text("from . import cudnn\n")
        (stub / "backends" / "cudnn.py").write_text("def is_available():\n    return True\ndef version():\n    return 91300\n")
        (stub / "__init__.py").write_text("__version__ = '9.9.9-stub'\nfrom . import version, backends\n")
        cwd = self.tmp / "cwd"
        cwd.mkdir()
        (cwd / "torch.py").write_text("raise SystemExit('shadowed by cwd')\n")
        env = {"PYTHONPATH": str(self.tmp / "site"), "PATH": "/usr/bin:/bin"}
        with mock.patch.dict(os.environ, env, clear=True):
            result = prov.CommandRunner().run(sys.executable, "-c", prov.TORCH_PROBE, cwd=cwd)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["version"], "9.9.9-stub")

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

    def test_directory_inside_another_checkout_is_not_given_its_commit(self):
        data = self.manifest(repos=[f"x/vendored={self.tmp / 'subdir-of-workload'}"])
        self.assertEqual(data["repositories"][0]["commit"]["reason"], "not_a_git_repository")

    def test_real_git_subdirectory_is_rejected_but_root_is_recorded(self):
        root = self.tmp / "real-repo"
        (root / "docs").mkdir(parents=True)
        # Isolate from the developer's git: no inherited GIT_* (a hook may set GIT_DIR),
        # no global/system config, no commit signing.
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env["GIT_CONFIG_GLOBAL"] = env["GIT_CONFIG_SYSTEM"] = os.devnull
        git = ("git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false")

        def git_run(*args: str) -> None:
            result = prov.CommandRunner().run(*args)
            self.assertEqual(result.returncode, 0, result.stderr)

        with mock.patch.dict(os.environ, env, clear=True):
            git_run("git", "init", "-q", str(root))
            (root / "docs" / "a.txt").write_text("a\n")
            git_run(*git, "add", ".")
            git_run(*git, "commit", "-q", "-m", "init")
        probe = prov.Probe(sysroot=self.sysroot, machine=lambda: "x86_64")
        commit, _dirty = prov.git_commit(probe, root)
        self.assertEqual(commit["status"], "available")
        commit, dirty = prov.git_commit(probe, root / "docs")
        self.assertEqual((commit["reason"], dirty["reason"]), ("not_a_git_repository", "not_a_git_repository"))

    def test_require_gate_fails_loud_when_field_unavailable(self):
        probe = prov.Probe(runner=FakeRunner(nvidia=False), sysroot=self.sysroot, machine=lambda: "x86_64")
        with self.assertRaisesRegex(prov.ProvenanceError, r"environment\.gpu\.devices\.0\.vbios_version \(command_not_found\)"):
            self.manifest(probe, require=["environment.gpu.devices.0.vbios_version"])
        with self.assertRaisesRegex(prov.ProvenanceError, "unknown field"):
            self.manifest(require=["environment.nope"])
        self.manifest(require=["environment.gpu.devices.0.vbios_version", "environment.cuda.toolkit_version"])


