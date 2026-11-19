"""Bounded 50 Hz neutral-array sample. --arm opts into an explicit ARM command.

No takeoff or throttle increase. The main loop drives transmission; a stalled
application cannot leave an independent background channel sender running.
"""
import argparse
import math
import time
from concurrent.futures import ThreadPoolExecutor

from zebjus_areion_link import ControlSession, Link, NEUTRAL_CHANNELS, SerialTransport, UDP
from zebjus_areion_link.control import disarm_and_read, get_input_status


def run(link, source, seconds=5.0, arm=False):
    if source not in (1, 2):
        raise ValueError("Choose AP=1 or USB=2")
    if not math.isfinite(seconds) or not 1 <= seconds <= 30:
        raise ValueError("Duration must be 1..30 seconds")
    status = link.read_group(120)
    if len(status) != 10 or status[0] is not False:
        raise RuntimeError("Start requires confirmed DISARMED status")
    version = link.read_group(125)[0]
    if version != "2.5.0":
        raise RuntimeError("Use matching 2.5.0 firmware for command-only USB/AP arming")
    link.set_group(110, [source])
    if link.read_group(110) != [source]:
        raise RuntimeError("Selected input readback differs")
    session = ControlSession(link)
    session.throttle_low = link.read_group(4, schema=2)[0]
    session.start(link.read_group(120), get_input_status(link), time.monotonic())
    worker = ThreadPoolExecutor(max_workers=1)
    pending = None
    started = time.monotonic()
    try:
        while time.monotonic() - started < seconds:
            now = time.monotonic()
            events = []
            for _ in range(32):
                message = link.poll(0)
                if message is None:
                    break
                events.append(message)
                # Process list(message.data) here without blocking the sender.
            session.tick(now, events)
            if session.ready:
                # CH1 roll, CH2 pitch, CH3 throttle, CH4 yaw, CH5 mode, CH6..8 aux.
                # Supply current application values here. This example keeps neutral.
                session.apply(NEUTRAL_CHANNELS)
                if arm and pending is None:
                    arguments = session.arm_arguments(now)
                    # RPC waits run separately so the 20 ms channel loop continues.
                    def arm_and_read():
                        link.arm(**arguments)
                        if link.read_group(120)[0] is not True:
                            raise RuntimeError("ARM acknowledged; current ARMED not confirmed")
                        return "FC ARMED confirmed"
                    pending = worker.submit(arm_and_read)
            if pending is not None and pending.done():
                pending.result()  # Propagate rejection/timeouts; never auto-retry ARM.
            time.sleep(0.005)
    finally:
        session.stop()  # Cancel any queued ARM before sending DISARM.
        try:
            print(disarm_and_read(link))
        finally:
            worker.shutdown(wait=True, cancel_futures=True)
    return session.sent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    path = parser.add_mutually_exclusive_group(required=True)
    path.add_argument("--usb", metavar="PORT")
    path.add_argument("--ap", metavar="HOST")
    parser.add_argument("--seconds", type=float, default=5.0)
    parser.add_argument("--arm", action="store_true", help="Explicitly arm at neutral throttle")
    args = parser.parse_args()
    if not math.isfinite(args.seconds) or not 1 <= args.seconds <= 30:
        parser.error("--seconds must be 1..30")
    transport = SerialTransport(args.usb) if args.usb else UDP(args.ap, 8080)
    link = Link(transport)
    try:
        if args.usb:
            time.sleep(4.0)
        link.connect()
        print("Frames sent:", run(link, 2 if args.usb else 1, args.seconds, args.arm))
    except KeyboardInterrupt:
        pass
    finally:
        link.close()


if __name__ == "__main__":
    main()
