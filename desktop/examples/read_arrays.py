"""Receive FC arrays without sending flight input or ARM/DISARM commands."""
import argparse
import time

from zebjus_areion_link import Link, SerialTransport, UDP
from zebjus_areion_link.schema import DRONE_GROUPS


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    path = parser.add_mutually_exclusive_group(required=True)
    path.add_argument("--usb", metavar="PORT")
    path.add_argument("--ap", metavar="HOST")
    args = parser.parse_args()
    transport = SerialTransport(args.usb) if args.usb else UDP(args.ap, 8080)
    link = Link(transport)
    try:
        if args.usb:
            time.sleep(4.0)  # Allow the FC startup/calibration after serial open.
        link.connect()
        while True:
            message = link.poll(timeout=0.2)
            if message is not None:
                name = DRONE_GROUPS.get(message.group, {}).get("name", str(message.group))
                # Process sensor arrays in your project here; no sensor feedback is sent.
                print(name, list(message.data))
            if not link.connected:
                raise RuntimeError("FC connection lost; reconnect explicitly")
    except KeyboardInterrupt:
        pass
    finally:
        link.close()


if __name__ == "__main__":
    main()

