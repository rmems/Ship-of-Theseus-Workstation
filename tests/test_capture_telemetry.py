import csv
import importlib.util
import io
import json
# Tests launch only fixed Python snippets in child interpreters.
import subprocess  # nosec B404
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location("capture_telemetry", SCRIPTS / "capture_telemetry.py")
telemetry = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(telemetry)
sensors = sys.modules["telemetry_sensors"]


class TelemetryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.out = Path(self.temp.name) / "capture"

    def capture(self, workload=None):
        args = telemetry.parse_args([
            "--run-id", "test-run", "--interval-seconds", "0.01",
            "--output", str(self.out), "--",
            *(workload or [sys.executable, "-c", "pass"]),
        ])
        self.out.mkdir()
        return telemetry.Capture(args, self.out)

    def test_linux_cpu_excludes_guest_counters(self):
        with mock.patch.object(sensors.platform, "system", return_value="Linux"):
            with mock.patch.object(Path, "read_text", return_value="cpu 100 20 30 400 5 6 7 8 50 10\n"):
                self.assertEqual(sensors.sample_cpu(), (576, 405))

    def test_memory_and_utilization(self):
        self.assertEqual(sensors.parse_memory(["MemTotal: 100 kB", "MemAvailable: 30 kB"]),
                         {"MemTotal": 102400, "MemAvailable": 30720})
        self.assertEqual(telemetry.cpu_utilization((100, 50), (200, 75)), 75)
        self.assertIsNone(telemetry.cpu_utilization(None, (200, 75)))
        self.assertIsNone(telemetry.cpu_utilization((100, 50), (100, 50)))

    def hwmon(self, index, chip, label, value):
        folder = Path(self.temp.name) / f"hwmon{index}"
        folder.mkdir()
        (folder / "name").write_text(chip)
        (folder / "temp1_label").write_text(label)
        (folder / "temp1_input").write_text(value)

    def test_tctl_beats_motherboard_and_package(self):
        self.hwmon(0, "nct6775", "CPUTIN", "30000")
        self.hwmon(1, "coretemp", "Package id 0", "40000")
        self.hwmon(3, "k10temp", "Tctl", "65000")
        self.assertEqual(sensors.cpu_temp(mock.Mock(), Path(self.temp.name)),
                         (65, "k10temp/Tctl", "ok"))

    def test_lm_sensors_fallback_is_ranked_and_limited_to_cpu(self):
        output = json.dumps({"nct6775-isa": {"CPUTIN": {"temp1_input": 20}},
                             "k10temp-pci": {"Tctl": {"temp1_input": 68},
                                            "Tdie": {"temp2_input": 200}}})
        self.assertEqual(sensors.cpu_temp(lambda _: output, Path(self.temp.name)),
                         (68, "k10temp-pci/Tctl", "ok"))
        self.assertEqual(sensors.cpu_temp(lambda _: "[]", Path(self.temp.name)),
                         (None, None, "unavailable"))
        self.assertEqual(sensors.cpu_temp(lambda _: "{", Path(self.temp.name)),
                         (None, None, "unavailable"))

    def test_invalid_temperatures_are_not_recorded(self):
        for value in (0, -1, 126, float("nan"), float("inf"), True, "50"):
            self.assertFalse(telemetry.valid_temperature(value))
        self.assertTrue(telemetry.valid_temperature(65))
        self.assertEqual(telemetry.decode_temperature('{"value_c": 200, "sensor": "Tctl"}'),
                         (None, "Tctl", "invalid_reading"))
        with self.assertRaises(ValueError):
            telemetry.decode_temperature("[]")

    def test_gpu_selects_index_zero_without_multiline_corruption(self):
        output = "65, 250, 99, 40, 12000, 2100\n50, 30, 0, 0, 500, 300"
        with mock.patch.object(telemetry, "command", return_value=output) as probe:
            self.assertEqual(telemetry.gpu_sample(True), (["65", "250", "99", "40", "12000", "2100"], "ok"))
            self.assertIn("--id=0", probe.call_args.args[0])
        self.assertEqual(telemetry.gpu_sample(False), ([""] * 6, "unavailable"))
        with mock.patch.object(telemetry, "command", return_value="bad"):
            self.assertEqual(telemetry.gpu_sample(True)[1], "query_failed")
        self.assertEqual(telemetry.normalize_gpu_value("[Not Supported]"), "")

    def test_helper_valid_and_invalid_responses(self):
        program = (
            "import sys\n"
            "for line in sys.stdin:\n"
            "    if line.strip() == 'sample':\n"
            "        print('{\"value_c\":65,\"sensor\":\"CPU/Tctl\",\"status\":\"ok\"}', flush=True)"
        )
        helper = telemetry.TemperatureHelper([sys.executable, "-u", "-c", program])
        self.addCleanup(helper.close)
        self.assertEqual(helper.sample(), (65, "CPU/Tctl", "ok"))
        self.assertEqual(helper.sample(), (65, "CPU/Tctl", "ok"))

    def test_partial_response_times_out_and_disables_helper(self):
        program = "import sys,time; sys.stdout.write('{'); sys.stdout.flush(); time.sleep(60)"
        helper = telemetry.TemperatureHelper([sys.executable, "-u", "-c", program])
        self.addCleanup(helper.close)
        started = time.monotonic()
        self.assertEqual(helper.sample(timeout=0.1), (None, None, "timeout"))
        self.assertLess(time.monotonic() - started, 3)
        self.assertIsNotNone(helper.process.poll())
        self.assertEqual(helper.sample(), (None, None, "unavailable"))

    def test_stop_escalates_after_timeout(self):
        process = mock.Mock()
        process.poll.return_value = None
        process.wait.side_effect = [subprocess.TimeoutExpired("helper", 5), 0]
        telemetry.stop_process(process)
        process.terminate.assert_called_once()
        process.kill.assert_called_once()
        self.assertEqual(process.wait.call_count, 2)

    def test_workload_launch_failure_stops_helper_and_writes_manifest(self):
        capture = self.capture(["nonexistent-theseus-test-command"])
        capture.args.helper_command = ["helper"]
        helper = mock.Mock()
        with mock.patch.object(telemetry, "TemperatureHelper", return_value=helper):
            with mock.patch.object(telemetry, "host_metadata", return_value={}):
                with self.assertRaises(FileNotFoundError):
                    capture.run()
        helper.close.assert_called_once()
        manifest = json.loads((self.out / "manifest.json").read_text())
        self.assertEqual(manifest["collection_status"], "failed")
        self.assertIsNone(manifest["workload_exit_code"])

    def test_csv_failure_stops_real_workload_and_preserves_manifest(self):
        capture = self.capture([sys.executable, "-c", "import time; time.sleep(60)"])
        with mock.patch.object(capture, "sample", side_effect=OSError("write failed")):
            with mock.patch.object(telemetry, "host_metadata", return_value={}):
                with self.assertRaises(OSError):
                    capture.run()
        self.assertIsNotNone(capture.process.poll())
        manifest = json.loads((self.out / "manifest.json").read_text())
        self.assertEqual(manifest["collection_status"], "failed")
        self.assertIsNotNone(manifest["workload_exit_code"])

    def test_interrupt_stops_workload_and_records_status(self):
        capture = self.capture([sys.executable, "-c", "import time; time.sleep(60)"])
        with mock.patch.object(capture, "collect", side_effect=KeyboardInterrupt):
            with mock.patch.object(telemetry, "host_metadata", return_value={}):
                capture.run()
        self.assertIsNotNone(capture.process.poll())
        self.assertEqual(json.loads((self.out / "manifest.json").read_text())["collection_status"], "interrupted")

    def test_helper_shutdown_timeout_still_produces_manifest(self):
        capture = self.capture()
        helper = mock.Mock()
        helper.close.side_effect = subprocess.TimeoutExpired("helper", 5)
        capture.helper = helper
        with mock.patch.object(telemetry, "host_metadata", return_value={}):
            with self.assertRaises(subprocess.TimeoutExpired):
                capture.finish()
        self.assertTrue((self.out / "manifest.json").is_file())

    def test_bad_intervals_and_unsupported_helper_create_no_output(self):
        for interval in ("0", "-1", "nan", "inf"):
            with mock.patch("sys.stderr", new_callable=io.StringIO):
                with self.assertRaises(SystemExit):
                    telemetry.main(["--run-id", "test", "--output", str(self.out),
                                    "--interval-seconds", interval, "--", "unused"])
            self.assertFalse(self.out.exists())
        with mock.patch.object(telemetry.platform, "system", return_value="Linux"):
            with mock.patch("sys.stderr", new_callable=io.StringIO):
                with self.assertRaises(SystemExit):
                    telemetry.main(["--run-id", "test", "--output", str(self.out),
                                    "--cpu-temp-helper", "helper", "--", "unused"])
        self.assertFalse(self.out.exists())

    def test_real_cli_writes_csv_manifest_and_workload_exit_code(self):
        result = subprocess.run(  # nosec B603 # nosemgrep # noqa: S603
            [sys.executable, str(SCRIPTS / "capture_telemetry.py"),
             "--run-id", "smoke", "--interval-seconds", "0.01", "--output", str(self.out),
             "--", sys.executable, "-c", "import sys; sys.exit(7)", "private-workload-marker"],
            capture_output=True, text=True, timeout=30, check=False,
        )
        self.assertEqual(result.returncode, 7, result.stderr)
        manifest_text = (self.out / "manifest.json").read_text()
        manifest = json.loads(manifest_text)
        self.assertEqual(manifest["workload_exit_code"], 7)
        self.assertEqual(manifest["collection_status"], "completed")
        self.assertEqual(manifest["sources"]["gpu_index"], 0)
        self.assertNotIn("hostname", manifest_text)
        self.assertNotIn("workload_argv", manifest_text)
        self.assertNotIn("private-workload-marker", manifest_text)
        with (self.out / "telemetry.csv").open(newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(len(rows), manifest["sample_count"])
        self.assertGreater(len(rows), 0)
        self.assertTrue(all(set(row) == set(telemetry.FIELDS) for row in rows))
        with self.assertRaises(FileExistsError):
            telemetry.main(["--run-id", "reuse", "--output", str(self.out), "--", "unused"])


if __name__ == "__main__":
    unittest.main()
