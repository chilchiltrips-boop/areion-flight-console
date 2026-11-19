"""Areion v2.5.0 console: runtime USB/AP connection, PID and PPM/USB/AP input.

Run main.py in PyCharm for interactive connection selection.
CONTROL is sent only when the user explicitly starts a bounded USB/AP channel burst or live control panel.
No automatic input selection, control replay, PID save or board reset occurs.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time

from receiver_control import (choose_input, send_channel_burst, show_input_status,
                              get_input_status, format_input_status, INPUT_STATUS_GROUP)
from wifi_check import report_wifi

PORT = "/dev/cu.usbmodem101"  # Change to the actual USB device, e.g. "COM5".
BAUDRATE = 115200
STARTUP_WAIT_SECONDS = 4.0  # USB open may reset the board; allow gyro calibration.
RATE_PID, ANGLE_PID, ACCEL_OFFSETS, IMU, RECEIVER, STATUS = 2, 3, 6, 21, 22, 120
LINK_STATUS = 121
SCHEMA = 1
OFFSET_SCHEMA = 2


def group_schema(group):
    return OFFSET_SCHEMA if group == ACCEL_OFFSETS else SCHEMA

FIELD_NAMES = {
    ACCEL_OFFSETS: ("AccelOffsetX g", "AccelOffsetY g", "AccelOffsetZ g"),
    RATE_PID: ("P Roll", "P Pitch", "P Yaw", "I Roll", "I Pitch", "I Yaw",
               "D Roll", "D Pitch", "D Yaw"),
    ANGLE_PID: ("P Roll", "P Pitch", "I Roll", "I Pitch", "D Roll", "D Pitch"),
    IMU: ("RateRoll deg/s", "RatePitch deg/s", "RateYaw deg/s", "AccX g", "AccY g",
          "AccZ g", "AngleRoll deg", "AnglePitch deg", "KalmanRoll deg", "KalmanPitch deg"),
    RECEIVER: tuple(f"CH{i} us" for i in range(1, 9)),
    LINK_STATUS: ("APReady", "APIP", "UDPPort", "OwnerLeaseMs"),
    STATUS: ("Armed", "AngleMode", "ImuReadOK", "ChannelNumber", "LoopDt seconds",
             "ValidCalibrationSamples", "SampleMs", "StorageOK", "RateRestored", "AngleRestored"),
}


def parse_pid(text: str, group: int) -> list[float]:
    """Accept a JSON numeric array or comma-separated numbers; reject NaN/bools."""
    if group not in (RATE_PID, ANGLE_PID):
        raise ValueError("PID group must be 2 (Rate) or 3 (Angle)")
    text = text.strip()
    values = json.loads(text) if text.startswith("[") else [float(x.strip()) for x in text.split(",")]
    count = len(FIELD_NAMES[group])
    if type(values) is not list or len(values) != count:
        raise ValueError(f"Enter exactly {count} values in the displayed order")
    result = []
    for name, value in zip(FIELD_NAMES[group], values):
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError(f"{name} must be a finite number, not boolean or text")
        limit = {"P": 100.0, "I": 500.0, "D": 20.0}[name[0]]
        if not 0 <= value <= limit:
            raise ValueError(f"{name} must be between 0 and {limit:g}")
        result.append(float(value))
    return result


def format_group(group: int, values: list | tuple) -> str:
    names = FIELD_NAMES.get(group)
    if names is None:
        return f"Group {group}: {list(values)}"
    if len(values) != len(names):
        raise ValueError(f"Group {group}: expected {len(names)} values, received {len(values)}; check firmware/schema")
    def display(value):
        if type(value) is bool:
            return "true" if value else "false"
        return f"{value:.6g}" if type(value) is float else str(value)
    return " | ".join(f"{name}={display(value)}" for name, value in zip(names, values))


def get_status(link) -> list:
    values = link.read_group(STATUS, schema=SCHEMA)
    if len(values) != 10:
        raise ValueError("Status group120 must contain 10 values; use matching integration")
    for index in (0, 1, 2, 7, 8, 9):
        if type(values[index]) is not bool:
            raise ValueError(f"Status {FIELD_NAMES[STATUS][index]} must be boolean")
    return values


def require_disarmed(link, saving: bool = False) -> None:
    # Unknown status blocks this sample's writes. The FC also checks its current
    # Armed state when processing SET/SAVE, including changes during a request.
    status = get_status(link)
    if status[0]:
        raise ValueError("FC is ARMED. Disarm before changing or saving settings")
    if saving and not status[7]:
        raise ValueError("StorageOK=false. Storage unavailable; SAVE was not sent")


def read_group(link, group: int) -> None:
    if group == STATUS:
        values = get_status(link)
    else:
        if group == IMU:
            status = get_status(link)
            if not status[2] or status[5] <= 0:
                print("IMU read/calibration unavailable. Values may be old or initial values.")
        values = link.read_group(group, schema=group_schema(group))
    print(format_group(group, values))


def read_saved_pid(link, group: int) -> None:
    if group not in (RATE_PID, ANGLE_PID):
        raise ValueError("Saved PID group must be 2 or 3")
    saved = link.read_group(group, schema=group_schema(group), saved=True)
    print("Stored on FC:", format_group(group, saved))


def edit_pid(link, group: int) -> None:
    require_disarmed(link)
    print("Current:", format_group(group, link.read_group(group, schema=SCHEMA)))
    print("Order:", ", ".join(FIELD_NAMES[group]))
    text = input("Enter all values (commas or [JSON array]); blank cancels: ").strip()
    if not text:
        print("Cancelled")
        return
    values = parse_pid(text, group)
    require_disarmed(link)  # Recheck after time spent typing.
    reply = link.set_group(group, values, schema=SCHEMA)
    print("FC reply:", reply)
    print("Active readback:", format_group(group, link.read_group(group, schema=SCHEMA)))
    print("Updated in RAM. Use menu 9 explicitly to save this PID group.")


def save_pid(link) -> None:
    choice = input("Save 2=Rate PID, 3=Angle PID, 6=Accelerometer offsets; blank cancels: ").strip()
    if not choice:
        print("Cancelled")
        return
    if choice not in ("2", "3", "6"):
        raise ValueError("Choose 2, 3 or 6")
    group = int(choice)
    require_disarmed(link, saving=True)
    active = link.read_group(group, schema=group_schema(group))
    reply = link.save_group(group, schema=group_schema(group))
    saved = link.read_group(group, schema=group_schema(group), saved=True)
    print("FC reply:", reply)
    print("Saved readback:", format_group(group, saved))
    matches = len(active) == len(saved) and all(
        type(a) in (int, float) and type(b) in (int, float)
        and math.isclose(a, b, rel_tol=1e-6, abs_tol=1e-8)
        for a, b in zip(active, saved)
    )
    if not matches:
        raise ValueError("SAVE replied, but stored values differ from the active snapshot; investigate")
    print("SAVED: verified against values read from FC storage.")


def parse_offsets(text):
    values = json.loads(text) if text.strip().startswith("[") else [float(x.strip()) for x in text.split(",")]
    if (type(values) is not list or len(values) != 3
            or any(type(v) not in (int, float) or not math.isfinite(v) or not -0.5 <= v <= 0.5 for v in values)):
        raise ValueError("Enter exactly three finite offsets in -0.5..+0.5 g, X,Y,Z")
    return [float(value) for value in values]


def edit_offsets(link):
    require_disarmed(link)
    print("Current:", format_group(ACCEL_OFFSETS, link.read_group(ACCEL_OFFSETS, schema=OFFSET_SCHEMA)))
    print("Additive offsets in g: AccX=raw/4096+OffsetX (same for Y,Z). Defaults: -0.10,+0.03,+0.12")
    text = input("Enter OffsetX,OffsetY,OffsetZ; blank cancels: ").strip()
    if not text:
        return
    values = parse_offsets(text)
    require_disarmed(link)
    print("FC reply:", link.set_group(ACCEL_OFFSETS, values, schema=OFFSET_SCHEMA))
    active = link.read_group(ACCEL_OFFSETS, schema=OFFSET_SCHEMA)
    if len(active) != 3 or any(type(a) not in (int, float) or not math.isclose(a, b, rel_tol=1e-6, abs_tol=1e-8)
                               for a, b in zip(active, values)):
        raise ValueError("Offset active readback does not match the requested values")
    print("Active readback:", format_group(ACCEL_OFFSETS, active))
    print("Updated in RAM. Menu9 -> group6 explicitly saves offsets on FC.")


def monitor(link, seconds: float = 10.0) -> None:
    if not math.isfinite(seconds) or not 0 < seconds <= 300:
        raise ValueError("Monitor duration must be greater than 0 and at most 300 seconds")
    for _ in range(1024):  # Discard menu-time queued history before monitoring.
        if link.poll(0) is None:
            break
    print("Monitoring; Ctrl+C returns to menu. Ages mean time since Python received each packet.")
    latest = {}
    deadline = time.monotonic() + seconds
    next_display = time.monotonic()
    try:
        while time.monotonic() < deadline:
            message = link.poll(timeout=min(0.1, max(0, deadline - time.monotonic())))
            now = time.monotonic()
            if message is not None and message.group in (STATUS, RECEIVER, IMU, INPUT_STATUS_GROUP):
                latest[message.group] = (message.data, now)
            if now >= next_display:
                next_display = now + 0.5
                if not latest:
                    print("Waiting for main-loop telemetry...")
                for group in (STATUS, RECEIVER, IMU, INPUT_STATUS_GROUP):
                    if group in latest:
                        values, received = latest[group]
                        age = now - received
                        note = " -- no recent packet" if age > 1 else ""
                        summary = format_input_status(values) if group == INPUT_STATUS_GROUP else format_group(group, values)
                        print(f"[{group}, received {age:.1f}s ago{note}] {summary}")
                print()
            if not link.connected:
                raise RuntimeError("No recent confirmed FC connection; no automatic reconnect is attempted")
    except KeyboardInterrupt:
        print("\nMonitor stopped")


def explain_error(error: Exception) -> None:
    code = getattr(error, "code", None)
    messages = {
        "WRITE_LOCKED": "FC refused the write. Disarm and check the main sketch's write guard.",
        "BUSY": "FC ownership was not available within the reconnect wait. Close other clients and disarm locally. With matching v2.5.0 firmware, an abandoned session expires after 5 seconds; run again without unplugging USB.",
        "SESSION_EXPIRED": "This session lost its heartbeat lease. Disarm locally, close this script, and run it again to create a new session.",
        "SESSION_RETIRED": "This session was already released or expired. Disarm locally, close this script, and run it again with a new session.",
        "NOT_SAVED": "No valid saved record for this group. Apply values, then explicitly choose Save.",
        "NO_SAVED_CONFIG": "No valid saved record exists for this group.",
        "NO_STORAGE": "FC storage unavailable; values were not saved.",
        "SAVE_FAILED": "FC could not verify the save. Do not treat it as saved; read back storage.",
        "UNKNOWN_GROUP": "Firmware has not registered that group. Use the matching USB + AP integration.",
        "SCHEMA_MISMATCH": "Python and Arduino group schemas differ; use matching files.",
    }
    if code:
        print(f"FC error {code}: {messages.get(code, str(error))}")
    elif isinstance(error, TimeoutError):
        print("Timeout: FC did not reply. After SET/SAVE the outcome may be unknown.")
        print("Read active/saved values before a new change. Check port, firmware, and startup time.")
    else:
        print(f"{type(error).__name__}: {error}")


def list_ports() -> int:
    try:
        from serial.tools import list_ports as serial_ports
    except ImportError:
        print("Install serial support: python -m pip install pyserial")
        return 1
    ports = list(serial_ports.comports())
    if not ports:
        print("No serial ports found. Connect the board using a data-capable USB cable.")
    for port in ports:
        print(f"{port.device}: {port.description}")
    return 0


def show_transport_status(link) -> None:
    """Report route confirmation and receive age, rather than socket-open alone."""
    for path in link.transport_status:
        age = path.get("last_received_age")
        recent = age is not None and age <= 5.0
        state = ("CONNECTED" if path["active"] and path["confirmed"] and recent
                 else "WAITING" if path["active"] and not path["confirmed"]
                 else "STALE" if path["active"] and path["confirmed"] else "UNAVAILABLE")
        received = f", last packet {age:.1f}s ago" if age is not None else ""
        detail = f", {path['error']}" if path.get("error") else ""
        print(f"{path['name']}: {state}{received}{detail}")


def show_fc_link_status(link) -> None:
    try:
        values = link.read_group(LINK_STATUS, schema=SCHEMA)
    except Exception as error:
        if getattr(error, "code", None) == "UNKNOWN_GROUP":
            print("FC link status unavailable; use the matching v2.5.0 USB + AP sketch.")
            return
        raise
    if (len(values) != 4 or type(values[0]) is not bool or type(values[1]) is not str
            or type(values[2]) is not int or type(values[3]) is not int):
        raise ValueError("Link status group121 does not match the v2.5.0 schema")
    print("FC link:", format_group(LINK_STATUS, values))


def open_transports(args, serial_factory, udp_factory):
    """Open requested paths; one failed path must not close the other in both mode."""
    transports = []
    serial_opened = False
    if args.transport in ("usb", "both"):
        try:
            print(f"Opening {args.port} at {args.baud} baud. Close Arduino Serial Monitor first.")
            transports.append(serial_factory(args.port, args.baud))
            serial_opened = True
        except Exception as error:
            print(f"USB unavailable: {error}")
            if args.transport == "usb":
                raise
    if args.transport in ("ap", "both"):
        report_wifi(getattr(args, "ssid", "aerion drone"))
        try:
            print(f"Opening AP UDP {args.host}:{args.udp_port}. Expected Wi-Fi: {getattr(args, 'ssid', 'aerion drone')}.")
            transports.append(udp_factory(args.host, args.udp_port))
        except Exception as error:
            print(f"AP unavailable: {error}")
            if not transports:
                raise
    if not transports:
        raise RuntimeError("No transport opened. Check USB port or AP Wi-Fi connection.")
    return transports, serial_opened


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Areion USB/AP console with exclusive PPM/USB/AP input selection")
    parser.add_argument("--transport", choices=("usb", "ap", "both"), default="both")
    parser.add_argument("--host", default="192.168.4.1", help="FC AP IP address")
    parser.add_argument("--ssid", default="aerion drone", help="Expected AP Wi-Fi name")
    parser.add_argument("--udp-port", type=int, default=8080)
    parser.add_argument("--port", default=PORT, help=f"USB device (default: {PORT})")
    parser.add_argument("--baud", type=int, default=BAUDRATE)
    parser.add_argument("--startup-wait", type=float, default=STARTUP_WAIT_SECONDS,
                        help="seconds after serial open before HELLO (default:4)")
    parser.add_argument("--list-ports", action="store_true", help="list ports without opening FC")
    args = parser.parse_args(argv)
    if args.list_ports:
        return list_ports()
    if not math.isfinite(args.startup_wait) or not 0 <= args.startup_wait <= 60:
        parser.error("--startup-wait must be between 0 and 60 seconds")
    if args.baud <= 0:
        parser.error("--baud must be positive")
    if not 1 <= args.udp_port <= 65535:
        parser.error("--udp-port must be between 1 and 65535")
    try:
        from zebjus_areion_link import Link, SerialTransport, UDP
    except ImportError:
        print("Keep the bundled zebjus_areion_link folder beside areion_usb.py.")
        print("Extract the full QuickStart ZIP; do not copy only this script.")
        print("Install USB support in this interpreter: python -m pip install pyserial")
        return 1

    transports = []
    link = None
    try:
        transports, serial_opened = open_transports(args, SerialTransport, UDP)
        if serial_opened:
            print(f"Waiting {args.startup_wait:g}s for startup/calibration; no reset command is sent.")
            time.sleep(args.startup_wait)
        print("Connecting; an abandoned session can take up to 6s to clear while disarmed.")
        link = Link(*transports, request_timeout=1.0, retries=3)
        link.connect()
        link.ping()
        status = get_status(link)
        input_status = get_input_status(link)
        if not link.connected:
            raise RuntimeError("FC connection became stale during verification")
        print(f"FC CONNECTED: HELLO + PING + status verified. Session={link.fc_session}")
        show_transport_status(link)
        show_fc_link_status(link)
        print(format_group(STATUS, status))
        print(format_input_status(input_status))
        while True:
            print("\n1 Rate PID | 2 Angle PID | 3 IMU | 4 Receiver | 5 Status")
            print("6 Monitor | 7 Set Rate PID | 8 Set Angle PID | 9 Save PID / offsets")
            print("10 Read Saved Rate PID | 11 Read Saved Angle PID")
            print("12 Select PPM/USB/AP input | 13 Input status | 14 USB/AP 8-channel burst")
            print("15 Live USB/AP panel + ARM/DISARM | 16 DISARM | 17 Read accel offsets")
            print("18 Set accel offsets | 19 Read saved accel offsets | 0 Exit")
            try:
                choice = input("Choose: ").strip()
                if choice == "0":
                    break
                if choice in ("1", "2", "3", "4", "5"):
                    read_group(link, {"1": RATE_PID, "2": ANGLE_PID, "3": IMU,
                                      "4": RECEIVER, "5": STATUS}[choice])
                    if choice == "5":
                        show_transport_status(link)
                        show_fc_link_status(link)
                        show_input_status(link)
                elif choice == "6":
                    text = input("Seconds to monitor [10]: ").strip()
                    monitor(link, float(text) if text else 10.0)
                elif choice in ("7", "8"):
                    edit_pid(link, RATE_PID if choice == "7" else ANGLE_PID)
                elif choice == "9":
                    save_pid(link)
                elif choice in ("10", "11"):
                    read_saved_pid(link, RATE_PID if choice == "10" else ANGLE_PID)
                elif choice == "12":
                    choose_input(link)
                elif choice == "13":
                    show_input_status(link)
                elif choice == "14":
                    send_channel_burst(link)
                elif choice == "15":
                    from live_control import open_control_panel
                    open_control_panel(link)
                elif choice == "16":
                    from live_control import disarm_and_read
                    print(disarm_and_read(link))
                elif choice == "17":
                    read_group(link, ACCEL_OFFSETS)
                elif choice == "18":
                    edit_offsets(link)
                elif choice == "19":
                    print("Stored on FC:", format_group(ACCEL_OFFSETS,
                          link.read_group(ACCEL_OFFSETS, schema=OFFSET_SCHEMA, saved=True)))
                else:
                    print("Choose a menu number 0..19")
            except (EOFError, KeyboardInterrupt):
                print("\nClosing")
                break
            except Exception as error:
                explain_error(error)
                if not link.connected:
                    break
        return 0
    except (EOFError, KeyboardInterrupt):
        print("\nClosing")
        return 0
    except Exception as error:
        explain_error(error)
        return 1
    finally:
        if link is not None:
            link.close()
            if link.release_confirmed:
                print("FC ownership released. You can run this script again immediately.")
            elif link.release_error:
                print(f"Ownership release not confirmed: {link.release_error}")
                print("Close other clients and disarm locally. An abandoned v2.5.0 session clears after 5s.")
        else:
            for transport in transports:
                try:
                    transport.close()
                except Exception:
                    pass
        if transports:
            print("Connections closed. No board-reset command was sent.")


if __name__ == "__main__":
    sys.exit(main())
