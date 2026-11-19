"""Launcher tests use mocks only; no real port is opened."""
import io
import sys
import types
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import config
import list_ports
import main as launcher

PORTS = [types.SimpleNamespace(device="COM5", description="ESP32 USB"),
         types.SimpleNamespace(device="COM7", description="Other adapter")]


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.output = io.StringIO()
        self.stdout = redirect_stdout(self.output)
        self.stdout.__enter__()
        self.defaults = patch.multiple(config, PORT="", BAUDRATE=115200, STARTUP_WAIT_SECONDS=4.0,
                                       AP_SSID="aerion drone", AP_HOST="192.168.4.1", AP_PORT=8080)
        self.defaults.start()

    def tearDown(self):
        self.defaults.stop()
        self.stdout.__exit__(None, None, None)

    def test_number_selection(self):
        with patch("builtins.input", return_value="2"):
            self.assertEqual(launcher.choose_port(PORTS), "COM7")

    def test_bad_indices_retry_and_cancel(self):
        with patch("builtins.input", side_effect=["3", "-1", "q"]):
            self.assertIsNone(launcher.choose_port(PORTS))

    def test_manual_port_names(self):
        for value, expected in (("com9", "COM9"), ("/dev/cu.usbmodem1101", "/dev/cu.usbmodem1101")):
            with self.subTest(value=value), patch("builtins.input", return_value=value):
                self.assertEqual(launcher.choose_port([]), expected)

    def test_attempt_limit(self):
        with patch("builtins.input", return_value="invalid") as read:
            with self.assertRaises(ValueError):
                launcher.choose_port(PORTS)
            self.assertEqual(read.call_count, 5)

    def test_runtime_choice_is_asked_before_usb_port(self):
        with patch.object(launcher, "collect_ports", return_value=PORTS), \
                patch("builtins.input", side_effect=["1", "2"]) as read, \
                patch.object(launcher, "_run_console", return_value=0) as run:
            self.assertEqual(launcher.main([]), 0)
            run.assert_called_once_with(["--transport", "usb", "--ssid", "aerion drone",
                                         "--host", "192.168.4.1", "--udp-port", "8080",
                                         "--baud", "115200", "--startup-wait", "4.0", "--port", "COM7"])
            self.assertIn("Connect using", read.call_args_list[0].args[0])
            self.assertIn("FC port", read.call_args_list[1].args[0])

    def test_configured_port_still_asks_transport(self):
        with patch.object(config, "PORT", "/dev/ttyACM0"), \
                patch("builtins.input", return_value="3") as read, \
                patch.object(launcher, "collect_ports") as discover, \
                patch.object(launcher, "_run_console", return_value=0) as run:
            self.assertEqual(launcher.main([]), 0)
            read.assert_called_once()
            discover.assert_not_called()
            self.assertIn("/dev/ttyACM0", run.call_args.args[0])
            self.assertEqual(run.call_args.args[0][:2], ["--transport", "both"])

    def test_cli_arguments_forwarded_unchanged(self):
        args = ["--transport", "usb", "--port", "COM12", "--startup-wait", "7"]
        with patch.object(launcher, "collect_ports") as discover, \
                patch("builtins.input") as read, \
                patch.object(launcher, "_run_console", return_value=2) as run:
            self.assertEqual(launcher.main(args), 2)
            run.assert_called_once_with(args)
            discover.assert_not_called()
            read.assert_not_called()

    def test_cancel_does_not_launch_or_discover(self):
        with patch.object(launcher, "collect_ports") as discover, \
                patch("builtins.input", return_value="0"), \
                patch.object(launcher, "_run_console") as run:
            self.assertEqual(launcher.main([]), 0)
            run.assert_not_called()
            discover.assert_not_called()

    def test_cancel_port_does_not_launch(self):
        with patch.object(launcher, "collect_ports", return_value=PORTS), \
                patch("builtins.input", side_effect=["1", "q"]), \
                patch.object(launcher, "_run_console") as run:
            self.assertEqual(launcher.main([]), 0)
            run.assert_not_called()

    def test_missing_pyserial_is_clear(self):
        with patch("builtins.input", return_value="1"), \
                patch.object(launcher, "collect_ports", side_effect=ImportError(list_ports.INSTALL_MESSAGE)), \
                patch.object(launcher, "_run_console") as run:
            self.assertEqual(launcher.main([]), 1)
            self.assertIn("pip install -r requirements.txt", self.output.getvalue())
            run.assert_not_called()

    def test_ap_only_skips_serial_discovery(self):
        with patch("builtins.input", return_value="2"), \
                patch.object(launcher, "collect_ports") as discover, \
                patch.object(launcher, "_run_console", return_value=0) as run:
            self.assertEqual(launcher.main([]), 0)
            discover.assert_not_called()
            self.assertEqual(run.call_args.args[0][:2], ["--transport", "ap"])
            self.assertNotIn("--port", run.call_args.args[0])

    def test_both_without_usb_ports_reports_ap_fallback(self):
        with patch("builtins.input", return_value="3"), \
                patch.object(launcher, "collect_ports", return_value=[]), \
                patch.object(launcher, "_run_console", return_value=0) as run:
            self.assertEqual(launcher.main([]), 0)
            self.assertEqual(run.call_args.args[0][:2], ["--transport", "ap"])
            self.assertIn("continuing with AP", self.output.getvalue())

    def test_invalid_configuration_does_not_connect(self):
        with patch.object(config, "STARTUP_WAIT_SECONDS", float("nan")), \
                patch("builtins.input") as read, \
                patch.object(launcher, "_run_console") as run:
            self.assertEqual(launcher.main([]), 1)
            run.assert_not_called()
            read.assert_not_called()

    def test_invalid_mode_retries_then_accepts(self):
        with patch("builtins.input", side_effect=["7", "-1", "ap"]):
            self.assertEqual(launcher.choose_transport(), "ap")

    def test_invalid_modes_bounded(self):
        with patch("builtins.input", return_value="bad") as read:
            with self.assertRaises(ValueError):
                launcher.choose_transport()
            self.assertEqual(read.call_count, 5)

    def test_lazy_console_forwards_to_sdk_sample_main(self):
        fake = types.SimpleNamespace(main=lambda args: args)
        with patch.dict(sys.modules, {"areion_usb": fake}):
            self.assertEqual(launcher._run_console(["--help"]), ["--help"])

    def test_list_ports_only_enumerates(self):
        with patch.object(list_ports, "collect_ports", return_value=PORTS):
            self.assertEqual(list_ports.main(), 0)
            self.assertIn("COM5", self.output.getvalue())


if __name__ == "__main__":
    unittest.main()
