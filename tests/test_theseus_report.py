import importlib.machinery
import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "theseus-report"
LOADER = importlib.machinery.SourceFileLoader("theseus_report", str(SCRIPT))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
report = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = report
LOADER.exec_module(report)
FIXTURES = ROOT / "tests" / "fixtures" / "system-report"


class FixtureRunner:
    def run(self, *args):
        files = {
            ("lscpu", "--json"): "lscpu.json",
            ("free", "--bytes"): "free.txt",
            ("lsblk", "--json", "--bytes", "--output", "TYPE,SIZE,MODEL,TRAN"): "lsblk.json",
            ("nvidia-smi", "--query-gpu=name,memory.total,driver_version,compute_cap", "--format=csv,noheader,nounits"): "nvidia.csv",
            ("nvcc", "--version"): "nvcc.txt",
        }
        if args not in files:
            raise FileNotFoundError(f"No fixture for command: {args}")
        return report.CommandResult(0, (FIXTURES / files[args]).read_text(), "")


class MissingOptionalRunner(FixtureRunner):
    def run(self, *args):
        if args[0] in {"nvidia-smi", "nvcc"}:
            raise FileNotFoundError(args[0])
        return super().run(*args)


class TheseusReportTests(unittest.TestCase):
    def test_collects_allowlisted_report_without_sensitive_fixture_data(self):
        report_data = report.build_report(FixtureRunner(), FIXTURES / "os-release")
        serialized = json.dumps(report_data)
        self.assertEqual(report_data["identity"]["cpu"]["logical_cpus"], 32)
        self.assertEqual(report_data["identity"]["gpu"][0]["memory_total_bytes"], 16384 * 1024 * 1024)
        self.assertEqual(report_data["identity"]["cuda_toolkit_version"], "13.0")
        for forbidden in ("SECRET-SERIAL", "SECRET-UUID", "/home/test-user", "hostname", "mountpoints"):
            self.assertNotIn(forbidden, serialized)
        report.validate_report(report_data)

    def test_marks_missing_optional_collectors_without_failing_report(self):
        report_data = report.build_report(MissingOptionalRunner(), FIXTURES / "os-release")
        states = {item["collector"]: item["state"] for item in report_data["collection_status"]}
        self.assertEqual(states["nvidia_smi"], "unavailable")
        self.assertEqual(states["nvcc"], "unavailable")
        self.assertNotIn("gpu", report_data["identity"])

    def test_validator_rejects_sensitive_field_and_missing_required_field(self):
        valid = report.build_report(FixtureRunner(), FIXTURES / "os-release")
        valid["identity"]["hostname"] = "not-allowed"
        with self.assertRaises(report.ReportError):
            report.validate_report(valid)
        with self.assertRaises(report.ReportError):
            report.validate_report({"schema_version": "1.0.0"})
        malformed = report.build_report(FixtureRunner(), FIXTURES / "os-release")
        malformed["identity"]["memory"]["total_bytes"] = "many"
        with self.assertRaises(report.ReportError):
            report.validate_report(malformed)

    def test_optional_unparseable_or_unlaunchable_collectors_do_not_abort(self):
        class BrokenOptionalRunner(FixtureRunner):
            def run(self, *args):
                if args[0] == "nvidia-smi":
                    return report.CommandResult(0, "not,csv", "")
                if args[0] == "nvcc":
                    raise PermissionError(args[0])
                return super().run(*args)

        report_data = report.build_report(BrokenOptionalRunner(), FIXTURES / "os-release")
        states = {item["collector"]: item["state"] for item in report_data["collection_status"]}
        self.assertEqual(states["nvidia_smi"], "failed")
        self.assertEqual(states["nvcc"], "failed")

    def test_unparseable_nvcc_and_legacy_free_output_are_handled(self):
        class UnparseableNvccRunner(FixtureRunner):
            def run(self, *args):
                if args[0] == "nvcc":
                    return report.CommandResult(0, "not a CUDA version", "")
                return super().run(*args)

        report_data = report.build_report(UnparseableNvccRunner(), FIXTURES / "os-release")
        states = {item["collector"]: item["state"] for item in report_data["collection_status"]}
        self.assertEqual(states["nvcc"], "failed")
        self.assertIn("uptime", states)
        self.assertEqual(
            report.parse_free("              total        used        free\nMem:        100         25         75\n"),
            {"total_bytes": 100, "available_bytes": 75},
        )

    def test_schema_is_valid_json_and_has_expected_dialect(self):
        schema = json.loads((ROOT / "schemas" / "system-report.schema.json").read_text())
        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertIn("collection_status", schema["required"])

    def test_unreadable_uptime_source_is_reported_as_unavailable(self):
        report_data = report.build_report(
            FixtureRunner(), FIXTURES / "os-release", uptime_path=Path("/nonexistent/uptime")
        )
        states = {item["collector"]: item["state"] for item in report_data["collection_status"]}
        self.assertEqual(states["uptime"], "unavailable")
        self.assertNotIn("uptime_seconds", report_data["volatile"])

    def test_schema_rejects_report_missing_a_known_collector_status(self):
        report_data = report.build_report(FixtureRunner(), FIXTURES / "os-release")
        report_data["collection_status"] = [
            item for item in report_data["collection_status"] if item["collector"] != "nvcc"
        ]
        with self.assertRaises(report.ReportError):
            report.validate_report(report_data)

    def test_validate_report_wraps_schema_load_failure_without_crashing(self):
        with mock.patch.object(report, "SCHEMA_PATH", Path("/nonexistent/schema.json")):
            with self.assertRaises(report.ReportError):
                report.validate_report({"schema_version": "1.0.0"})

    def test_command_runner_forces_stable_locale(self):
        with mock.patch("subprocess.run") as run:
            run.return_value = mock.Mock(returncode=0, stdout="", stderr="")
            report.CommandRunner().run("lscpu", "--json")
        _, kwargs = run.call_args
        self.assertEqual(kwargs["env"]["LC_ALL"], "C")

    def test_json_loads_rejects_nonstandard_numeric_constants(self):
        with self.assertRaises(ValueError):
            json.loads('{"uptime_seconds": NaN}', parse_constant=report.reject_nonstandard_constant)


if __name__ == "__main__":
    unittest.main()
