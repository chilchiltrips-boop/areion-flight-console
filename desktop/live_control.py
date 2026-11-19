"""Explicit USB/AP bench control panel; no sender survives a stopped UI loop."""
from __future__ import annotations

import queue
import threading
import time

from zebjus_areion_link.control import ControlSession, disarm_and_read

from receiver_control import (NEUTRAL_CHANNELS, INPUT_STATUS_GROUP, INPUT_SCHEMA,
                              SOURCE_NAMES, control_route, get_input_status,
                              input_ready, parse_channels, require_control_path,
                              validate_input_status)


def open_control_panel(link):
    try:
        import tkinter as tk
        from tkinter import ttk
    except ImportError as error:
        raise RuntimeError("The live panel needs Python with Tk support. Use a Tk-enabled Python interpreter in PyCharm; console menus still work.") from error
    try:
        root = tk.Tk()
    except tk.TclError as error:
        raise RuntimeError("A desktop display and Tk-enabled Python are required for the live control panel") from error
    root.title("Areion USB / AP — 8 channels + ARM / DISARM")
    root.resizable(False, False)
    session = ControlSession(link)
    results = queue.Queue()
    generation = [0]
    busy = [False]
    stopping = [False]
    closing = [False]
    message = tk.StringVar(value="Stopped. Select USB or AP using console menu12, then Start.")
    state = tk.StringVar(value="FC Armed: unknown | input: not ready | sender: stopped")
    fields = [tk.StringVar(value=str(v)) for v in NEUTRAL_CHANNELS]
    body = ttk.Frame(root, padding=14)
    body.grid()
    ttk.Label(body, text="Bench control — remove propellers before testing").grid(row=0, column=0, columnspan=4, sticky="w")
    ttk.Label(body, text="20ms / 50Hz target. Focus loss, Stop or closing ends transmission.").grid(row=1, column=0, columnspan=4, sticky="w")
    names = ("Roll", "Pitch", "Throttle", "Yaw", "Mode", "Aux6", "Aux7", "Aux8")
    for i, (name, variable) in enumerate(zip(names, fields)):
        ttk.Label(body, text=f"CH{i+1} {name}").grid(row=i+2, column=0, sticky="w")
        ttk.Spinbox(body, from_=1000, to=2000, increment=10, textvariable=variable, width=8).grid(row=i+2, column=1)
    ttk.Label(body, textvariable=state, wraplength=620).grid(row=12, column=0, columnspan=4, sticky="w", pady=8)
    ttk.Label(body, textvariable=message, wraplength=620).grid(row=13, column=0, columnspan=4, sticky="w")

    def reset_fields():
        for field, value in zip(fields, NEUTRAL_CHANNELS):
            field.set(str(value))

    def task(kind, function, token):
        def work():
            try:
                result = function()
                results.put((kind, token, result, None))
            except Exception as error:
                results.put((kind, token, None, error))
        threading.Thread(target=work, daemon=True, name=f"areion-panel-{kind}").start()

    def start():
        if busy[0] or stopping[0] or session.running:
            return
        busy[0] = True
        generation[0] += 1
        token = generation[0]
        message.set("Checking disarmed state and selected input...")
        task("start", lambda: (link.read_group(120, schema=1), get_input_status(link)), token)

    def stop(reason="Stopped; DISARM requested"):
        generation[0] += 1
        session.stop()  # Cancel queued/in-flight ARM before scheduling DISARM.
        busy[0] = False
        reset_fields()
        message.set(reason + ". Waiting for FC confirmation...")
        if not stopping[0]:
            stopping[0] = True
            task("stop", lambda: disarm_and_read(link), generation[0])

    def arm():
        if busy[0] or stopping[0]:
            return
        try:
            arguments = session.arm_arguments(time.monotonic())
        except Exception as error:
            message.set(str(error))
            return
        busy[0] = True
        token = generation[0]
        def request():
            reply = link.arm(**arguments)
            current = link.read_group(120, schema=1)
            if len(current) != 10 or current[0] is not True:
                raise RuntimeError(f"ARM reply {reply}; current Armed=true not confirmed")
            return "FC ARMED: command and current status verified"
        task("arm", request, token)
        message.set("ARM requested; checking current FC state...")

    def apply_channels():
        try:
            session.apply(parse_channels(",".join(v.get() for v in fields)))
            message.set("Updated CH1..CH8; transmitting current values at50Hz target")
        except Exception as error:
            message.set(str(error))

    def close():
        if not closing[0]:
            closing[0] = True
            stop("Closing; DISARM requested")
            # Bound UI handoff; no control sender exists after stop().
            root.after(2500, root.destroy)

    def check_focus():
        if not closing[0] and root.focus_displayof() is None and (session.running or busy[0]):
            stop("Window lost focus; stream stopped and DISARM requested")

    def update():
        try:
            for _ in range(16):
                try:
                    kind, token, result, error = results.get_nowait()
                except queue.Empty:
                    break
                if kind == "stop":
                    stopping[0] = False
                    message.set(str(error) if error else result)
                    if closing[0]:
                        root.destroy()
                        return
                elif token == generation[0]:
                    busy[0] = False
                    if error:
                        stop(str(error))
                    elif kind == "start":
                        try:
                            session.start(*result, time.monotonic())
                            reset_fields()
                            message.set(f"{SOURCE_NAMES[session.source]}: sending neutral input; waiting for FC readiness")
                        except Exception as error:
                            message.set(str(error))
                    else:
                        message.set(result)
            now = time.monotonic()
            was_ready = session.ready
            try:
                session.tick(now)
            except Exception as error:
                stop(str(error))
            if session.ready and not was_ready:
                message.set("FC input ready. ARM requires low throttle and centered roll/pitch/yaw. Apply sends edited channels.")
            armed = "unknown"
            if session.status_at is not None and now - session.status_at < 0.5:
                armed = str(session.latest_status[0])
            rate = session.sent / max(0.001, now - session.started) if session.running else 0.0
            state.set(f"FC Armed={armed} | InputReady={session.ready} | sender={'ON' if session.running else 'OFF'} | measured send {rate:.1f}Hz")
            root.after(5, update)
        except tk.TclError:
            session.stop()

    ttk.Button(body, text="Start 50Hz (neutral)", command=start).grid(row=10, column=0, pady=10)
    ttk.Button(body, text="Apply 8 channels", command=apply_channels).grid(row=10, column=1)
    ttk.Button(body, text="ARM", command=arm).grid(row=10, column=2, padx=8)
    ttk.Button(body, text="DISARM / Stop", command=stop).grid(row=10, column=3)
    ttk.Button(body, text="Close", command=close).grid(row=11, column=3)
    root.protocol("WM_DELETE_WINDOW", close)
    root.bind("<FocusOut>", lambda event: root.after(50, check_focus))
    root.bind("<Escape>", lambda event: stop("Escape pressed; DISARM requested"))
    root.after(5, update)
    try:
        root.mainloop()
    finally:
        session.stop()
