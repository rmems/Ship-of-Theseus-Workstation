import importlib.machinery
import importlib.util
import json
import sys
import unittest
from pathlib import Path


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
        for forbidden in ("SECRET-SERIAL", "SECRET-UUID", "/home/raulmc", "hostname", "mountpoints"):
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

    def test_schema_is_valid_json_and_has_expected_dialect(self):
        schema = json.loads((ROOT / "schemas" / "system-report.schema.json").read_text())
        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertIn("collection_status", schema["required"])


if __name__ == "__main__":
    unittest.main()
