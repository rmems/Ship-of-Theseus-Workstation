"""Schema, CLI, and live-host tests for the provenance manifest."""

import io
import json
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from jsonschema import Draft202012Validator

from .provenance_support import MACHINE_ID, ROOT, ProvenanceTestCase, prov

class SchemaTests(ProvenanceTestCase):
    def test_schema_dialect_and_version_const(self):
        schema = json.loads(prov.SCHEMA_PATH.read_text())
        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertEqual(schema["properties"]["schema_version"]["const"], prov.SCHEMA_VERSION)
        self.assertIn("schema_version", schema["required"])
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

    def test_command_runner_drops_git_location_variables(self):
        with mock.patch.dict(os.environ, {"GIT_DIR": "/elsewhere/.git", "GIT_WORK_TREE": "/elsewhere"}):
            with mock.patch("subprocess.run") as run:
                run.return_value = mock.Mock(returncode=0, stdout="", stderr="")
                prov.CommandRunner().run("git", "-C", "x", "rev-parse", "HEAD")
        env = run.call_args.kwargs["env"]
        self.assertNotIn("GIT_DIR", env)
        self.assertNotIn("GIT_WORK_TREE", env)

    def test_metadata_keys_are_checked_for_host_identity(self):
        data = self.manifest(meta=["devbox_run=1"])
        with self.assertRaisesRegex(prov.ProvenanceError, "key contains a local host identity term"):
            prov.validate_manifest(data, extra_forbidden=["devbox"])


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
