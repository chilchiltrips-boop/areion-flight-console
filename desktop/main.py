"""PyCharm entry point for one FC over USB, AP, or both paths."""
from __future__ import annotations

import math
import re
import sys

import config
from list_ports import collect_ports, show_ports


def choose_port(ports, attempts=5):
    """Return an explicitly selected port, or None when the user cancels."""
    show_ports(ports)
    print("Choose a number, or enter a port name such as COM5 or /dev/cu.usbmodem101.")
    print("Enter q or 0 to quit without opening a port.")
    devices = [port.device for port in ports]
    for _ in range(attempts):
        answer = input("FC port: ").strip()
        if answer.lower() in ("q", "quit", "exit", "0"):
            return None
        if re.fullmatch(r"[+-]?\d+", answer):
            number = int(answer)
            if 1 <= number <= len(devices):
                return devices[number - 1]
            print(f"Invalid number. Choose 1..{len(devices)}, a port name, or q." if devices
                  else "No numbered ports are available. Enter a port name or q.")
            continue
        if answer in devices:
            return answer
        if re.fullmatch(r"COM\d+", answer, flags=re.IGNORECASE):
            return answer.upper()
        if answer.startswith("/dev/") and len(answer) > 5 and not any(c.isspace() or ord(c) < 32 for c in answer):
            return answer
        print("Enter a listed number, COM port, /dev/... device, or q.")
    raise ValueError("No valid port selected after five attempts. Run main.py again to choose.")


def choose_transport(attempts=5):
    """Choose the communication path for this run; never infer a flight input."""
    print("Connection: 1 USB | 2 AP Wi-Fi | 3 USB + AP | 0 Exit")
    choices = {"1": "usb", "usb": "usb", "2": "ap", "ap": "ap",
               "3": "both", "both": "both"}
    for _ in range(attempts):
        answer = input("Connect using: ").strip().lower()
        if answer in ("0", "q", "quit", "exit"):
            return None
        if answer in choices:
            return choices[answer]
        print("Choose 1 USB, 2 AP, 3 both, or 0 to exit.")
    raise ValueError("No valid connection selected after five attempts")


def _run_console(arguments):
    # Import lazily: --help/listing and test imports do not open any hardware.
    import areion_usb
    return areion_usb.main(arguments)


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments:
        # Command-line choices belong to the console's argparse interface.
        return _run_console(arguments)
    try:
        if not isinstance(config.PORT, str):
            raise ValueError("config.PORT must be a string; use '' to choose a port")
        if type(config.BAUDRATE) is not int or config.BAUDRATE <= 0:
            raise ValueError("config.BAUDRATE must be a positive integer")
        wait = config.STARTUP_WAIT_SECONDS
        if type(wait) not in (int, float) or not math.isfinite(wait) or not 0 <= wait <= 60:
            raise ValueError("config.STARTUP_WAIT_SECONDS must be a number between 0 and 60")
        if not isinstance(config.AP_HOST, str) or not config.AP_HOST.strip():
            raise ValueError("config.AP_HOST must be the FC AP address")
        if type(config.AP_PORT) is not int or not 1 <= config.AP_PORT <= 65535:
            raise ValueError("config.AP_PORT must be between 1 and 65535")
        if not isinstance(config.AP_SSID, str) or not config.AP_SSID:
            raise ValueError("config.AP_SSID must be the FC Wi-Fi name")
        mode = choose_transport()
        if mode is None:
            print("Cancelled. No connection was opened.")
            return 0
        port = config.PORT.strip()
        if mode != "ap" and not port:
            try:
                ports = collect_ports()
            except ImportError:
                if mode == "usb":
                    raise
                ports = []
                print("USB support unavailable; continuing with AP. Install requirements for USB.")
            if mode == "both" and not ports:
                print("No USB ports listed; continuing with AP. Set PORT to use an unlisted device.")
                mode = "ap"
            else:
                port = choose_port(ports)
        if port is None:
            print("Cancelled. No connection was opened.")
            return 0
        arguments = ["--transport", mode, "--ssid", config.AP_SSID,
                     "--host", config.AP_HOST.strip(),
                     "--udp-port", str(config.AP_PORT), "--baud", str(config.BAUDRATE),
                     "--startup-wait", str(wait)]
        if mode != "ap":
            arguments.extend(["--port", port])
        return _run_console(arguments)
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled. No automatic connection or retry is attempted.")
        return 0
    except (ImportError, OSError, ValueError) as error:
        print(error)
        return 1


if __name__ == "__main__":
    from runtime_setup import prepare_project, ProjectSetupError, import_failure
    try:
        desktop = "--console" not in sys.argv and (
            not sys.argv[1:] or sys.argv[1:] == ["--check"])
        prepare_project(require_gui=desktop)
    except ProjectSetupError as error:
        raise SystemExit(str(error)) from None
    except ImportError as error:
        raise SystemExit(import_failure(error)) from None
    if "--console" in sys.argv:
        arguments = [a for a in sys.argv[1:] if a != "--console"]
        raise SystemExit(main(arguments))
    elif not sys.argv[1:] or sys.argv[1:] == ["--check"]:
        from gui import main as gui_main
        raise SystemExit(gui_main())
    else:
        raise SystemExit(main())
