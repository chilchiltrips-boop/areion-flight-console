"""Runtime PPM/USB/AP selection and explicitly started, bounded digital RC samples."""
from __future__ import annotations

import json
import math
import time

from zebjus_areion_link.control import (
    SOURCE_GROUP, INPUT_STATUS_GROUP, SCHEMA, INPUT_SCHEMA, SOURCE_NAMES, INPUT_NAMES, NEUTRAL_CHANNELS, validate_input_status, get_input_status, parse_channels, require_control_path, control_route, input_ready
)


def format_input_status(values):
    values = validate_input_status(values)
    return (f"Selected={SOURCE_NAMES[values[0]]} | "
            f"Active={('NONE', 'PPM', 'AP', 'USB')[values[1]]} | "
            f"PPM signal={values[2]} | AP signal={values[3]} | USB signal={values[8]} | "
            f"InputReady={values[4]} | channels={values[5]} | "
            f"age={values[6]}ms | owner={values[7]}")


def show_input_status(link):
    print(format_input_status(get_input_status(link)))


def require_disarmed(link):
    values = link.read_group(120, schema=SCHEMA)
    if not isinstance(values, (list, tuple)) or len(values) != 10 or type(values[0]) is not bool:
        raise ValueError("Fresh FC armed status is required")
    if values[0]:
        raise ValueError("FC is ARMED. Disarm before selecting input or starting a bench burst")


def choose_input(link):
    require_disarmed(link)
    show_input_status(link)
    text = input("Select flight input: 0=PPM, 1=AP, 2=USB; blank cancels: ").strip()
    if not text:
        return
    if text not in ("0", "1", "2"):
        raise ValueError("Choose exactly one source: 0 PPM, 1 AP or 2 USB")
    require_disarmed(link)  # Recheck after the user spent time typing.
    source = int(text)
    print("FC reply:", link.set_group(SOURCE_GROUP, [source], schema=SCHEMA))
    if link.read_group(SOURCE_GROUP, schema=SCHEMA) != [source]:
        raise RuntimeError("Input selection readback differs; check FC status")
    print("Temporary input selected. Restarting the kit restores its saved flight input.")
    print("Fresh low-throttle, centered input is required. PPM uses stick gestures; USB/AP use explicit ARM/DISARM commands.")
    show_input_status(link)


def require_ap_path(link):
    require_control_path(link, 1)


def run_control_burst(link, values, seconds):
    """Send at50Hz, with fresh neutral bootstrap; stop on loss, stall, or duration.

    This bounded sample is for bench verification, not a live pilot interface.
    No worker keeps transmitting while the console is waiting for user input.
    """
    if (not isinstance(values, (list, tuple)) or len(values) != 8
            or any(type(v) is not int or not 1000 <= v <= 2000 for v in values)):
        raise ValueError("CONTROL requires 8 integer channels in 1000..2000")
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or not 1 <= seconds <= 30:
        raise ValueError("Burst duration must be 1..30 seconds")
    require_disarmed(link)
    initial = get_input_status(link)
    source = initial[0]
    if source not in (1, 2):
        raise ValueError("Select AP or USB flight input first using menu12")
    if initial[7] != link.session:
        raise RuntimeError("FC input owner does not match this Python session")
    require_control_path(link, source)
    for _ in range(1024):
        if link.poll(0) is None:
            break
    start = previous_tick = next_tick = time.monotonic()
    target_started = None
    latest_status = None
    latest_at = None
    sent = 0
    while True:
        now = time.monotonic()
        if now - previous_tick > 0.15:
            raise RuntimeError("Sender paused over150ms; stopped without replaying stale controls")
        previous_tick = now
        require_control_path(link, source)
        if target_started is not None and now - target_started >= seconds:
            return sent
        if target_started is None and now - start > 1.0:
            raise RuntimeError("FC did not confirm fresh neutral digital input; requested channels were not sent")
        channels = NEUTRAL_CHANNELS if target_started is None else values
        link.send_control(channels, **control_route(source))
        sent += 1
        for _ in range(32):
            event = link.poll(0)
            if event is None:
                break
            if event.group == INPUT_STATUS_GROUP and event.schema == INPUT_SCHEMA:
                latest_status = validate_input_status(event.data)
                latest_at = now
                if latest_status[0] != source or latest_status[7] != link.session:
                    raise RuntimeError("FC source/session changed; Digital control stopped")
        if target_started is None:
            if (now - start >= 0.25 and latest_at is not None
                    and now - latest_at < 0.25
                    and input_ready(latest_status, source, link.session)):
                target_started = now
                print("FC confirmed neutral digital input. Sending requested CH1..CH8:", list(values))
        elif (latest_at is None or now - latest_at > 0.5
              or not input_ready(latest_status, source, link.session)):
            raise RuntimeError("FC digital input status is stale/not ready; control stopped")
        next_tick += 0.02
        current = time.monotonic()
        if next_tick < current:
            next_tick += (int((current - next_tick) / 0.02) + 1) * 0.02
        time.sleep(max(0.0, next_tick - time.monotonic()))


def send_channel_burst(link):
    require_disarmed(link)
    source = get_input_status(link)[0]
    require_control_path(link, source)
    print("USB/AP channel bench sample: CH1 Roll, CH2 Pitch, CH3 Throttle, CH4 Yaw, CH5 Mode, CH6..8.")
    print("Neutral example:", list(NEUTRAL_CHANNELS))
    print("Values can operate the existing arming gesture/motors. Use a disarmed bench setup.")
    text = input("Enter 8 channels; blank cancels: ").strip()
    if not text:
        return
    values = parse_channels(text)
    duration = input("Send duration1..30 seconds [5]; Ctrl+C stops: ").strip()
    seconds = float(duration) if duration else 5.0
    try:
        print("Starting explicit 50Hz USB/AP burst; neutral bootstrap first.")
        count = run_control_burst(link, values, seconds)
        print(f"Burst complete; {count} frames sent including neutral bootstrap.")
    except KeyboardInterrupt:
        print("\nChannel burst interrupted.")
    finally:
        # No background sender exists. Silence triggers the FC's own configured
        # input-loss handling; never switch to PPM or replay an arm gesture here.
        print("Channel transmission stopped. FC uses its configured digital input timeout (default250ms); checking reported state...")
        time.sleep(0.3)
        try:
            show_input_status(link)
            state = link.read_group(120, schema=SCHEMA)
            if len(state) == 10 and type(state[0]) is bool:
                print(f"FC reports Armed={state[0]}")
            else:
                print("FC armed status could not be verified.")
        except Exception as error:
            print(f"Stop status not confirmed: {error}")
