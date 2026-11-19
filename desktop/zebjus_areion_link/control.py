"""Reusable 50 Hz control scheduler and input helpers; no GUI dependency.

Call tick() from the application loop that owns current control intent. Only
explicit ARM/DISARM commands change the digital arming state in firmware 2.5.0.
"""
from __future__ import annotations

import json
import threading

SOURCE_GROUP = 110

INPUT_STATUS_GROUP = 122

SCHEMA = 1

INPUT_SCHEMA = 2

SOURCE_NAMES = {0: "PPM", 1: "AP", 2: "USB"}

INPUT_NAMES = ("SelectedSource", "ActiveSource", "PPMFresh", "APFresh",
               "InputReady", "ChannelCount", "InputAgeMs", "OwnerSession", "USBFresh")

NEUTRAL_CHANNELS = (1500, 1500, 1000, 1500, 1000, 1000, 1000, 1000)

def validate_input_status(values):
    if not isinstance(values, (list, tuple)) or len(values) != 9:
        raise ValueError("Input status group122 requires the matching firmware (schema2, 9 fields)")
    if type(values[0]) is not int or values[0] not in (0, 1, 2):
        raise ValueError("Invalid selected input source")
    if type(values[1]) is not int or values[1] not in (0, 1, 2, 3):
        raise ValueError("Invalid active input source")
    if any(type(values[i]) is not bool for i in (2, 3, 4, 8)):
        raise ValueError("Input freshness/readiness must be boolean")
    if type(values[5]) is not int or not 0 <= values[5] <= 8:
        raise ValueError("Invalid input channel count")
    if any(type(values[i]) is not int or not 0 <= values[i] <= 0xFFFFFFFF for i in (6, 7)):
        raise ValueError("Invalid input status age/session")
    return list(values)

def get_input_status(link):
    return validate_input_status(link.read_group(INPUT_STATUS_GROUP, schema=INPUT_SCHEMA))

def parse_channels(text):
    text = text.strip()
    if text.startswith("["):
        values = json.loads(text)
    else:
        values = [int(part.strip()) for part in text.split(",")]
    if (type(values) is not list or len(values) != 8
            or any(type(v) is not int or not 1000 <= v <= 2000 for v in values)):
        raise ValueError("Enter exactly 8 integer channels, each 1000..2000")
    return values

def require_control_path(link, source):
    if source not in (1, 2):
        raise ValueError("Select AP or USB flight input first using menu12")
    if not link.connected:
        raise RuntimeError("FC connection is stale; control stopped")
    if not any(p.get("datagram") == (source == 1) and p["active"] and p["confirmed"]
               and p.get("last_received_age") is not None
               and 0 <= p["last_received_age"] < 0.5
               for p in link.transport_status):
        raise RuntimeError(f"No fresh confirmed {SOURCE_NAMES[source]} route. Control never falls back to another route")

def control_route(source):
    if source == 1:
        return {"datagram_only": True}
    if source == 2:
        return {"serial_only": True}
    raise ValueError("Digital control requires AP or USB selection")

def input_ready(values, source, session):
    return (values[0] == source and values[1] == source + 1
            and values[3 if source == 1 else 8] and values[4]
            and values[5] == 8 and values[6] < 250 and values[7] == session)

class ControlSession:
    """Application-driven 50Hz scheduler, with fresh neutral bootstrap and watchdogs.

    tick() must run on the active application/control thread. RPC workers never send channels.
    A stalled/destroyed application loop therefore stops controls; the FC enforces its configured
    input timeout independently. This is a bench controller, not a flight UI.
    """
    def __init__(self, link):
        self.link = link
        self.throttle_low = 1050
        self.running = self.ready = False
        self.source = None
        self.values = list(NEUTRAL_CHANNELS)
        self.cancel_arm = threading.Event()
        self.latest_input = self.latest_status = None
        self.input_at = self.status_at = None
        self.started = self.previous = self.next_send = 0.0
        self.sent = 0
        self.ever_armed = False

    def start(self, status, inputs, now):
        if len(status) != 10 or type(status[0]) is not bool or status[0]:
            raise ValueError("Start requires confirmed disarmed FC status")
        inputs = validate_input_status(inputs)
        if inputs[0] not in (1, 2) or inputs[7] != self.link.session:
            raise ValueError("Select USB or AP input for this owner using menu12")
        require_control_path(self.link, inputs[0])
        for _ in range(1024):
            if self.link.poll(0) is None:
                break
        self.cancel_arm = threading.Event()
        self.source = inputs[0]
        self.values = list(NEUTRAL_CHANNELS)
        self.latest_input = self.latest_status = None
        self.input_at = self.status_at = None
        self.started = self.previous = self.next_send = now
        self.sent = 0
        self.ever_armed = False
        self.ready = False
        self.running = True

    def stop(self):
        self.cancel_arm.set()
        self.running = self.ready = False
        self.values = list(NEUTRAL_CHANNELS)

    def apply(self, values):
        if not self.running or not self.ready:
            raise ValueError("Start and wait for fresh neutral input before applying channels")
        self.values = parse_channels(str(list(values)))

    def arm_arguments(self, now):
        if (not self.running or not self.ready or self.input_at is None
                or now - self.input_at >= 0.25
                or not input_ready(self.latest_input, self.source, self.link.session)):
            raise ValueError("ARM requires fresh selected USB/AP input")
        if (self.values[2] >= self.throttle_low
                or any(not 1400 <= self.values[i] <= 1600 for i in (0, 1, 3))):
            raise ValueError("ARM requires low throttle and centered roll/pitch/yaw")
        require_control_path(self.link, self.source)
        return dict(control_route(self.source), cancel=self.cancel_arm)

    def tick(self, now, events=None):
        if not self.running:
            return
        try:
            if now - self.previous > 0.15:
                raise RuntimeError("UI/sender paused over150ms; stream stopped")
            self.previous = now
            require_control_path(self.link, self.source)
            if events is None:
                events = []
                for _ in range(32):
                    event = self.link.poll(0)
                    if event is None:
                        break
                    events.append(event)
            for event in events:
                if event.group == INPUT_STATUS_GROUP and event.schema == INPUT_SCHEMA:
                    values = validate_input_status(event.data)
                    if values[0] != self.source or values[7] != self.link.session:
                        raise RuntimeError("FC input source/owner changed; stream stopped")
                    self.latest_input, self.input_at = values, now
                elif event.group == 120 and event.schema == 1:
                    if len(event.data) != 10 or type(event.data[0]) is not bool:
                        raise RuntimeError("Invalid FC armed status")
                    if self.ever_armed and not event.data[0]:
                        raise RuntimeError("FC disarmed; stream stopped until an explicit new Start")
                    self.ever_armed = self.ever_armed or event.data[0]
                    self.latest_status, self.status_at = event.data, now
            if not self.ready:
                if now - self.started > 1.0:
                    raise RuntimeError("FC did not confirm fresh neutral input")
                if (now - self.started >= 0.25 and self.input_at is not None
                        and now - self.input_at < 0.25
                        and input_ready(self.latest_input, self.source, self.link.session)):
                    self.ready = True
            elif (self.input_at is None or now - self.input_at > 0.5
                  or not input_ready(self.latest_input, self.source, self.link.session)):
                raise RuntimeError("FC input status stale/not ready; stream stopped")
            if now >= self.next_send:
                values = self.values if self.ready else NEUTRAL_CHANNELS
                self.link.send_control(values, **control_route(self.source))
                self.sent += 1
                # Do not burst old samples to catch up after a scheduling delay.
                self.next_send += 0.02
                if self.next_send <= now:
                    missed = int((now - self.next_send) / 0.02) + 1
                    self.next_send += missed * 0.02
        except BaseException:
            self.stop()
            raise

def disarm_and_read(link):
    """ACK is historical command completion; explicitly read current state."""
    reply = link.disarm()
    status = link.read_group(120, schema=1)
    if len(status) != 10 or type(status[0]) is not bool or status[0]:
        raise RuntimeError(f"DISARM reply {reply}, but current disarmed state is not confirmed")
    return "FC DISARMED: command and current status verified"
