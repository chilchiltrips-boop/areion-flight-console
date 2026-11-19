"""Best-effort, read-only Wi-Fi association checks; FC connectivity is separate.

No credentials, stored Wi-Fi profiles, network changes or sudo requests. SSID
access can be unavailable under OS privacy rules or localization; UNKNOWN must
never block the protocol handshake or be presented as FC CONNECTED.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
import platform
import re
import subprocess


@dataclass(frozen=True)
class WifiStatus:
    state: str  # associated, different, disconnected, unknown
    ssid: str | None = None
    detail: str = ""


def _run(command: list[str]) -> str:
    env = os.environ.copy()
    env.update({"LC_ALL": "C", "LANG": "C"})
    completed = subprocess.run(command, capture_output=True, text=True,
                               errors="replace", timeout=1.5, check=False, env=env)
    if completed.returncode != 0:
        raise OSError(f"{command[0]} could not read Wi-Fi state (exit {completed.returncode})")
    return completed.stdout[:65536]


def _match(ssids: list[str], expected: str) -> WifiStatus:
    # Several Wi-Fi adapters are possible. Match the requested SSID exactly.
    if expected in ssids:
        return WifiStatus("associated", expected, "OS reports association with the requested Wi-Fi")
    if ssids:
        return WifiStatus("different", ssids[0], "OS reports a different Wi-Fi network")
    return WifiStatus("unknown", detail="The OS did not expose a current SSID")


def parse_macos_ports(text: str) -> list[str]:
    result = []
    for block in re.split(r"\n\s*\n", text):
        port = re.search(r"^Hardware Port:\s*(.+)$", block, re.MULTILINE)
        device = re.search(r"^Device:\s*(\S+)$", block, re.MULTILINE)
        if port and device and port.group(1).strip().lower() in ("wi-fi", "airport"):
            if re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", device.group(1)):
                result.append(device.group(1))
    return result[:2]  # Keep preflight bounded even with many adapters.


def parse_macos_network(text: str) -> str | None:
    match = re.search(r"^Current (?:Wi-Fi|AirPort) Network:[ \t]*(.+)$", text, re.MULTILINE)
    if not match:
        return None
    ssid = match.group(1).strip()
    return None if ssid.lower() in ("<redacted>", "<hidden>", "<unknown>") else ssid


def parse_windows(text: str, expected: str) -> WifiStatus:
    ssids = []
    disconnected = False
    connected_without_ssid = False
    # "Name" introduces each interface. Unknown/localized output stays UNKNOWN.
    for block in re.split(r"(?m)^\s*Name\s*:", text):
        state = re.search(r"(?mi)^[ \t]*State[ \t]*:[ \t]*([^\r\n]+)", block)
        ssid = re.search(r"(?mi)^[ \t]*SSID[ \t]*:[ \t]*([^\r\n]+)", block)
        if state and state.group(1).strip().lower() == "connected" and ssid:
            value = ssid.group(1).strip()
            if value and value.lower() not in ("<redacted>", "<hidden>", "<unknown>"):
                ssids.append(value)
            else:
                connected_without_ssid = True
        if state and state.group(1).strip().lower() == "connected" and not ssid:
            connected_without_ssid = True
        if state and state.group(1).strip().lower() == "disconnected":
            disconnected = True
    if ssids:
        return _match(ssids, expected)
    if connected_without_ssid:
        return WifiStatus("unknown", detail="Wi-Fi is active but the OS did not expose SSID")
    if disconnected:
        return WifiStatus("disconnected", detail="OS reports Wi-Fi disconnected")
    return WifiStatus("unknown", detail="SSID unavailable, permission denied, or unsupported OS output")


def _unescape_nmcli(value: str) -> str:
    # --terse --escape yes escapes colons/backslashes in an SSID.
    return re.sub(r"\\([\\:])", r"\1", value)


def parse_linux(text: str, expected: str) -> WifiStatus:
    ssids = []
    valid_rows = 0
    active_without_ssid = False
    for line in text.splitlines():
        active, separator, ssid = line.partition(":")
        if not separator or active not in ("yes", "no"):
            continue
        valid_rows += 1
        if active == "yes":
            if ssid:
                ssids.append(_unescape_nmcli(ssid))
            else:
                active_without_ssid = True
    if ssids:
        return _match(ssids, expected)
    if active_without_ssid:
        return WifiStatus("unknown", detail="Wi-Fi is active but SSID is hidden by the OS")
    if valid_rows:
        return WifiStatus("disconnected", detail="No active Wi-Fi association in NetworkManager")
    return WifiStatus("unknown", detail="No readable active Wi-Fi information from NetworkManager")


def check_wifi(expected_ssid: str = "aerion drone") -> WifiStatus:
    if not isinstance(expected_ssid, str) or not expected_ssid:
        raise ValueError("Expected Wi-Fi name must be non-empty")
    try:
        system = platform.system()
        if system == "Darwin":
            devices = parse_macos_ports(_run(["/usr/sbin/networksetup", "-listallhardwareports"]))
            ssids = []
            for device in devices:
                try:
                    value = parse_macos_network(_run(["/usr/sbin/networksetup", "-getairportnetwork", device]))
                except (OSError, subprocess.TimeoutExpired):
                    continue
                if value:
                    ssids.append(value)
            if ssids:
                return _match(ssids, expected_ssid)
            # Some macOS versions hide SSID, even with an active association.
            return WifiStatus("unknown", detail="macOS did not expose SSID; check Wi-Fi in the menu bar")
        if system == "Windows":
            return parse_windows(_run(["netsh", "wlan", "show", "interfaces"]), expected_ssid)
        if system == "Linux":
            return parse_linux(_run(["nmcli", "--terse", "--escape", "yes", "--fields", "ACTIVE,SSID",
                                     "device", "wifi", "list", "--rescan", "no"]), expected_ssid)
        return WifiStatus("unknown", detail=f"Automatic SSID check is unavailable on {system}")
    except (OSError, subprocess.TimeoutExpired) as error:
        return WifiStatus("unknown", detail=f"Wi-Fi check unavailable: {error}")


def report_wifi(expected_ssid: str = "aerion drone") -> WifiStatus:
    status = check_wifi(expected_ssid)
    if status.state == "associated":
        print(f"Wi-Fi association: ASSOCIATED with '{status.ssid}'. Checking the FC next.")
    elif status.state == "different":
        print(f"Wi-Fi association: DIFFERENT NETWORK ('{status.ssid}'). Join '{expected_ssid}' in Wi-Fi settings.")
    elif status.state == "disconnected":
        print(f"Wi-Fi association: DISCONNECTED. Join '{expected_ssid}' in Wi-Fi settings.")
    else:
        print(f"Wi-Fi association: UNKNOWN. {status.detail}. Join '{expected_ssid}' if needed.")
    print("FC connection is confirmed separately by protocol replies; Wi-Fi association alone is insufficient.")
    return status
