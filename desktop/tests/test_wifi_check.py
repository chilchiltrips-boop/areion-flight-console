import io
import subprocess
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch
from types import SimpleNamespace

import wifi_check as wifi


class WifiTests(unittest.TestCase):
    def test_macos_only_wifi_interfaces(self):
        text = "Hardware Port: Ethernet\nDevice: en1\n\nHardware Port: Wi-Fi\nDevice: en0\nEthernet Address: abc\n"
        self.assertEqual(wifi.parse_macos_ports(text), ["en0"])

    def test_macos_reads_association_not_preferred_networks(self):
        with patch.object(wifi.platform, "system", return_value="Darwin"), \
                patch.object(wifi, "_run", side_effect=["Hardware Port: Wi-Fi\nDevice: en0\n", "Current Wi-Fi Network: aerion drone\n"]) as run:
            self.assertEqual(wifi.check_wifi().state, "associated")
            self.assertEqual(run.call_args.args[0], ["/usr/sbin/networksetup", "-getairportnetwork", "en0"])

    def test_macos_unavailable_ssid_stays_unknown(self):
        for response in ("You are not associated with an AirPort network.\n", "Current Wi-Fi Network: <redacted>\n"):
            with patch.object(wifi.platform, "system", return_value="Darwin"), \
                    patch.object(wifi, "_run", side_effect=["Hardware Port: Wi-Fi\nDevice: en0\n", response]):
                self.assertEqual(wifi.check_wifi().state, "unknown")

    def test_windows_ssid_not_bssid_and_exact_match(self):
        text = "    Name : Wi-Fi\n    State : connected\n    SSID : aerion drone\n    BSSID : aa:bb:cc:dd\n"
        result = wifi.parse_windows(text, "aerion drone")
        self.assertEqual((result.state, result.ssid), ("associated", "aerion drone"))
        self.assertEqual(wifi.parse_windows(text, "Aerion Drone").state, "different")

    def test_windows_empty_or_hidden_ssid_does_not_claim_associated(self):
        for text in ("Name : Wi-Fi\nState : connected\nSSID :\nBSSID : aa:bb\n",
                     "Access is denied. Location permissions required.",
                     "Nombre : Wi-Fi\nEstado : conectado\nSSID : aerion drone\n",
                     "Name : Wi-Fi\nState : connected\nSSID : <redacted>\nName : Wi-Fi2\nState : disconnected\n"):
            self.assertEqual(wifi.parse_windows(text, "aerion drone").state, "unknown")

    def test_windows_disconnected(self):
        result = wifi.parse_windows("Name : Wi-Fi\nState : disconnected\n", "aerion drone")
        self.assertEqual(result.state, "disconnected")

    def test_linux_only_active_row_matches_and_unescapes(self):
        self.assertEqual(wifi.parse_linux("no:aerion drone\nyes:Other\n", "aerion drone").state, "different")
        result = wifi.parse_linux("yes:areion\\:lab\\\\main\n", "areion:lab\\main")
        self.assertEqual(result.state, "associated")
        self.assertEqual(wifi.parse_linux("no:aerion drone\n", "aerion drone").state, "disconnected")
        self.assertEqual(wifi.parse_linux("yes:\n", "aerion drone").state, "unknown")

    def test_timeout_or_missing_tool_returns_unknown(self):
        for error in (FileNotFoundError("nmcli"), subprocess.TimeoutExpired("nmcli", 1.5)):
            with patch.object(wifi.platform, "system", return_value="Linux"), \
                    patch.object(wifi, "_run", side_effect=error):
                self.assertEqual(wifi.check_wifi().state, "unknown")

    def test_subprocess_is_bounded_no_shell_and_no_scan(self):
        with patch.object(wifi.platform, "system", return_value="Linux"), \
                patch.object(wifi.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout="yes:aerion drone\n")) as run:
            self.assertEqual(wifi.check_wifi().state, "associated")
            self.assertEqual(run.call_args.kwargs["timeout"], 1.5)
            self.assertNotIn("shell", run.call_args.kwargs)
            self.assertEqual(run.call_args.args[0][-2:], ["--rescan", "no"])

    def test_report_distinguishes_association_from_fc_connection(self):
        output = io.StringIO()
        with patch.object(wifi, "check_wifi", return_value=wifi.WifiStatus("associated", "aerion drone")), redirect_stdout(output):
            wifi.report_wifi()
        self.assertIn("ASSOCIATED", output.getvalue())
        self.assertNotIn("FC CONNECTED", output.getvalue())
        self.assertIn("confirmed separately", output.getvalue())

    def test_wrong_ssid_report_gives_guidance_without_mutation(self):
        output = io.StringIO()
        with patch.object(wifi, "check_wifi", return_value=wifi.WifiStatus("different", "Home")), redirect_stdout(output):
            wifi.report_wifi()
        self.assertIn("DIFFERENT NETWORK", output.getvalue())
        self.assertIn("Join 'aerion drone'", output.getvalue())


if __name__ == "__main__":
    unittest.main()
