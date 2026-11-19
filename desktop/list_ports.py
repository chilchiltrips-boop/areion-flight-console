"""Read-only serial-device listing. This script never opens a port."""

INSTALL_MESSAGE = (
    "Serial support is missing in this Python interpreter.\n"
    "In the PyCharm Terminal, run: python -m pip install -r requirements.txt"
)


def collect_ports():
    try:
        from serial.tools import list_ports as serial_list_ports
    except ImportError as error:
        raise ImportError(INSTALL_MESSAGE) from error
    return sorted(serial_list_ports.comports(), key=lambda port: port.device)


def show_ports(ports):
    if not ports:
        print("No serial ports were found. Check the USB data cable and board connection.")
        return
    print("Available serial ports:")
    for index, port in enumerate(ports, start=1):
        description = getattr(port, "description", None) or "Serial device"
        print(f"  {index}. {port.device} — {description}")


def main():
    try:
        show_ports(collect_ports())
        return 0
    except ImportError as error:
        print(error)
        return 1
    except OSError as error:
        print(f"Could not list serial devices: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
