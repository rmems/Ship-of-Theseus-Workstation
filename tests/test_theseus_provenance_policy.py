"""Redaction tests for the provenance manifest."""

import copy
import json
from unittest import mock

from .provenance_support import (
    FIXTURE_BOARD_ID,
    FIXTURE_HOST,
    FIXTURE_SERIAL,
    FIXTURE_USER,
    FIXED_TIME,
    MACHINE_ID,
    FakeRunner,
    ProvenanceTestCase,
    prov,
)

class RedactionTests(ProvenanceTestCase):
    """Forbidden identifiers must never appear in a collected manifest, and the validator rejects them."""

    def serialized(self, data):
        return json.dumps(data, sort_keys=True)

    def test_collected_manifest_contains_no_planted_identifiers(self):
        artifact = self.tmp / "home" / FIXTURE_USER / "runs" / "telemetry.csv"
        artifact.parent.mkdir(parents=True)
        artifact.write_text("t,gpu_temp\n0,41\n")
        data = self.manifest(artifacts=[f"telemetry={artifact}"])
        text = self.serialized(data)
        for forbidden in (FIXTURE_SERIAL, FIXTURE_BOARD_ID, FIXTURE_HOST, FIXTURE_USER, MACHINE_ID, str(self.tmp), "/home/", "builder@", "00000000:01:00.0", "local-app"):
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
            "uuid": FIXTURE_BOARD_ID,
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
        data["workload_metadata"]["note"] = f"captured on {FIXTURE_HOST}"
        with self.assertRaisesRegex(prov.ProvenanceError, "local host identity term"):
            prov.validate_manifest(data, extra_forbidden=[FIXTURE_HOST])

    def test_collection_refuses_metadata_that_leaks_the_running_host(self):
        self.identity_patch.stop()
        try:
            with mock.patch.object(prov.socket, "gethostname", return_value="workstation-xyz.local"), mock.patch.object(
                prov.getpass, "getuser", return_value="localuser"
            ):
                with self.assertRaisesRegex(prov.ProvenanceError, "local host identity term"):
                    self.manifest(meta=["operator=localuser"])
                with self.assertRaisesRegex(prov.ProvenanceError, "local host identity term"):
                    self.manifest(meta=["host=workstation-xyz"])
                self.manifest()
        finally:
            self.identity_patch.start()

    def test_hostname_matching_schema_constants_does_not_block_collection(self):
        # A host named "theseus" (or user "ship") matches inside node.label / collector.name,
        # which are schema constants; collection must still succeed, but real leaks still fail.
        self.identity_patch.stop()
        try:
            with mock.patch.object(prov.socket, "gethostname", return_value="theseus"), mock.patch.object(
                prov.getpass, "getuser", return_value="provenance"
            ):
                data = self.manifest()
                prov.validate_manifest(data, extra_forbidden=["theseus", "ship", "provenance"])
                with self.assertRaisesRegex(prov.ProvenanceError, "local host identity term"):
                    self.manifest(meta=["host=theseus"])
        finally:
            self.identity_patch.start()

    def test_compressed_ipv6_relative_paths_and_urls_are_rejected(self):
        base = self.manifest()
        leaks = {
            "2001:db8::1": "ipv6_address",
            "fe80::1%eth0": "ipv6_address",
            "peer [2001:db8::42]:443": "ipv6_address",
            "../private/train.csv": "relative_path",
            "./data/train.csv": "relative_path",
            "https://github.com/someone/private-repo.git": "url",
            "/data/someone/private/train.csv": "absolute_path",
            "/scratch/exp/run1": "absolute_path",
            "/workspace/proj/ckpt.pt": "absolute_path",
            "dataset=D:\\datasets\\private\\x": "absolute_path",
            "C:/datasets/x": "absolute_path",
            "train.csv,/home/someone/x": "home_or_root_path",
            "train.csv,/data/someone/private/x": "absolute_path",
            "[/data/someone/x]": "absolute_path",
            "a|/data/someone/x": "absolute_path",
            "x,~/private/y": "home_or_root_path",
            "a,../p/x": "relative_path",
            "a;D:\\data\\x": "absolute_path",
        }
        for value, label in leaks.items():
            data = copy.deepcopy(base)
            data["workload_metadata"]["note"] = value
            with self.assertRaisesRegex(prov.ProvenanceError, label, msg=value):
                prov.validate_manifest(data)
        for harmless in ("data/train.csv", "std::fmt::Display", "12:30:45", "v1.2.3", "08/15/2026", "2.9.0+cu130", "a/b", "rmems/vahtisiru", "train.csv,val.csv", "x86_64/linux"):
            data = copy.deepcopy(base)
            data["workload_metadata"]["note"] = harmless
            prov.validate_manifest(data)

    def test_logins_matching_schema_enum_words_do_not_block_collection(self):
        # Enum values (source/status/reason) and the os-release ID cannot carry host data,
        # so logins like these must not make every collect fail.
        data = self.manifest()
        for term in ("julia", "python", "nvidia", "operator", "fedora", "git", "available", "dmi"):
            prov.validate_manifest(data, extra_forbidden=[term])
        leaky = self.manifest(meta=["owner=julia"])
        with self.assertRaisesRegex(prov.ProvenanceError, "local host identity term"):
            prov.validate_manifest(leaky, extra_forbidden=["julia"])
        for key in ("source", "status", "reason"):
            leaky = self.manifest(meta=[f"{key}=devbox-01"])
            with self.assertRaisesRegex(prov.ProvenanceError, "local host identity term", msg=key):
                prov.validate_manifest(leaky, extra_forbidden=["devbox"])

    def test_system_report_id_prefix_does_not_match_hostname(self):
        data = self.manifest()
        data["links"]["system_report"] = {
            "source": "operator",
            "status": "available",
            "report_id": "ship-of-theseus-20261019T000000Z",
            "sha256": "0" * 64,
        }
        prov.validate_manifest(data, extra_forbidden=["theseus", "ship"])

    def test_repo_owner_matching_local_login_does_not_block_collection(self):
        data = self.manifest(repos=[f"rmems/gaming-telemetry={self.tmp / 'workload'}"])
        prov.validate_manifest(data, extra_forbidden=["rmems"])
        leaky = self.manifest(repos=[f"rmems/rmems-notes={self.tmp / 'workload'}"])
        with self.assertRaisesRegex(prov.ProvenanceError, "local host identity term"):
            prov.validate_manifest(leaky, extra_forbidden=["rmems"])

    def test_metadata_path_values_are_rejected_at_collection(self):
        with self.assertRaisesRegex(prov.ProvenanceError, "home_or_root_path"):
            self.manifest(meta=["dataset=/home/someone/data.parquet"])
        with self.assertRaisesRegex(prov.ProvenanceError, "home_or_root_path"):
            self.manifest(meta=["dataset=~/data.parquet"])

    def test_fingerprint_method_exemption_is_pinned_to_its_schema_location(self):
        # Blocks review (PR #25): the exemption used to match the key name, so
        # workload_metadata could smuggle any value under that key.
        for value in ("/home/alice/private/data.csv", "10.0.0.7"):
            with self.subTest(value=value), self.assertRaises(prov.ProvenanceError):
                self.manifest(meta=[f"host_fingerprint_method={value}"])
        data = self.manifest()
        named = copy.deepcopy(data)
        named["workload_metadata"]["host_fingerprint_method"] = "run-on-devbox"
        with self.assertRaisesRegex(prov.ProvenanceError, "local host identity term"):
            prov.validate_manifest(named, extra_forbidden=["devbox"])
        self.assertEqual(prov.redaction_violations(data), [])
        tampered = copy.deepcopy(data)
        tampered["redaction"]["host_fingerprint_method"] = "/home/alice/x"
        self.assertIn(
            "$.redaction.host_fingerprint_method: value looks like home_or_root_path",
            prov.redaction_violations(tampered),
        )
