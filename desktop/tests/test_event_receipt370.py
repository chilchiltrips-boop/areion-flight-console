"""Telemetry freshness uses host receipt time, including after a GUI stall."""
import os
import time
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication

from areion_gui.window import MainWindow
from test_actions_sdk import connected_link
from zebjus_areion_link import Message, encode_frame


class TimedEventTests(unittest.TestCase):
    def test_duplicate_route_cannot_refresh_event_and_legacy_poll_returns_message(self):
        link, _, _ = connected_link()
        usb, ap = link._paths
        one = Message('DATA', 21, 1, link.fc_session, 1, tuple([0.] * 10))
        two = Message('DATA', 21, 1, link.fc_session, 2, tuple([1.] * 10))
        link._handle(usb, one, 30.)
        link._handle(ap, one, 31.)
        link._handle(usb, two, 32.)
        self.assertEqual(link.poll_timed(), (one, 30.))
        self.assertEqual(link.poll(), two)
        self.assertIsNone(link.poll_timed())
        with self.assertRaises(ValueError):
            link.poll(-1.)

    def test_reader_stamps_the_frame_before_the_gui_polls(self):
        link, _, ap = connected_link()
        message = Message('DATA', 21, 1, link.fc_session, 1, tuple([0.] * 10))

        def receive_once():
            link._stop.set()
            return encode_frame(message)

        ap.receive = receive_once
        before = time.monotonic()
        link._reader()
        after = time.monotonic()
        event, received_at = link.poll_timed()
        self.assertEqual(event, message)
        self.assertLessEqual(before, received_at)
        self.assertLessEqual(received_at, after)

    def test_gui_does_not_revive_stale_arm_or_overwrite_newer_readback(self):
        app = QApplication.instance() or QApplication([])
        window = MainWindow()
        window.timer.stop()
        link, _, _ = connected_link()
        window.link = link
        try:
            window.navigate(0)
            armed = [True, True, True, 8, .004, 2000, 3000, True, False, False]
            stale_at = time.monotonic() - 2.
            status = Message('DATA', 120, 1, link.fc_session, 1, tuple(armed))
            link._handle(link._paths[0], status, stale_at)
            window.tick()
            self.assertGreater(window.data.age(120), .5)
            self.assertEqual(window.flight_dashboard.last_health['ARM'].label, 'UNKNOWN')
            disarmed = [False, *armed[1:]]
            read_at = time.monotonic()
            self.assertTrue(window.data.put(120, 1, disarmed, read_at, received=False))
            older = Message('DATA', 120, 1, link.fc_session, 2, tuple(armed))
            link._handle(link._paths[0], older, read_at - .1)
            window.tick()
            self.assertEqual(window.data.latest[120], (disarmed, read_at))
        finally:
            window.link = None
            window.close()
            window.deleteLater()
            app.processEvents()
