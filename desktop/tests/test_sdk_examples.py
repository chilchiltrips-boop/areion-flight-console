"""External-project control lifecycle uses the same scheduler as the GUI."""
import contextlib
import io
import unittest
from concurrent.futures import Future
from unittest.mock import patch

from examples import control_arrays
from test_receiver_control import Clock, FakeFC
from zebjus_areion_link import ControlSession, NEUTRAL_CHANNELS
import live_control


class ExampleFC(FakeFC):
    def __init__(self, clock):
        super().__init__(clock)
        self.commands = []
        self.version = "2.5.0"
        self.arm_error = None
        self.setup = [False, True, 0, 4, 15, True, True, False, False]
        self.pid_status = [False, 2, 2, ""]
        self.saved_source = 1

    def read_group(self, group, **kwargs):
        if group == 125:
            return [self.version]
        if group == 130:
            return self.setup
        if group == 134 and kwargs.get("saved"):
            return [0, self.saved_source]
        if group == 136:
            return self.pid_status
        if group == 4:
            return [1050, 1900, 1100, 20, 5, 1, 15]
        return super().read_group(group, **kwargs)

    def arm(self, **kwargs):
        self.commands.append(("ARM", kwargs))
        if self.arm_error:
            raise self.arm_error
        self.armed = True
        return ["ARMED"]

    def disarm(self):
        self.commands.append(("DISARM", {}))
        self.armed = False
        return ["DISARMED"]


class ImmediateWorker:
    def __init__(self, **kwargs):
        pass

    def submit(self, call):
        future = Future()
        try:
            future.set_result(call())
        except Exception as error:
            future.set_exception(error)
        return future

    def shutdown(self, **kwargs):
        pass


class ExternalProjectTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.fc = ExampleFC(self.clock)
        for replacement in (patch.object(control_arrays, "time", self.clock),
                            patch.object(control_arrays, "ThreadPoolExecutor", ImmediateWorker)):
            replacement.start()
            self.addCleanup(replacement.stop)

    def run_example(self, source=1, arm=False):
        with contextlib.redirect_stdout(io.StringIO()):
            return control_arrays.run(self.fc, source, seconds=1, arm=arm)

    def test_gui_and_installed_sdk_share_scheduler(self):
        self.assertIs(live_control.ControlSession, ControlSession)

    def test_default_example_sends_neutral_arrays_without_arm(self):
        for source in (1, 2):
            self.clock = Clock()
            self.fc = ExampleFC(self.clock)
            with patch.object(control_arrays, "time", self.clock):
                count = self.run_example(source)
            self.assertGreaterEqual(count, 49)
            self.assertLessEqual(count, 51)
            self.assertTrue(all(v[1] == NEUTRAL_CHANNELS for v in self.fc.values))
            self.assertTrue(all(v[2] == (source == 1) and v[3] == (source == 2)
                                for v in self.fc.values))
            self.assertEqual([c[0] for c in self.fc.commands], ["DISARM"])
            self.assertFalse(self.fc.armed)

    def test_explicit_arm_is_once_with_cancel_before_cleanup(self):
        self.run_example(source=2, arm=True)
        self.assertEqual([c[0] for c in self.fc.commands], ["ARM", "DISARM"])
        self.assertTrue(self.fc.commands[0][1]["serial_only"])
        self.assertTrue(self.fc.commands[0][1]["cancel"].is_set())

    def test_rejected_arm_stops_and_disarms_without_retry(self):
        self.fc.arm_error = RuntimeError("IMU_NOT_READY")
        with self.assertRaisesRegex(RuntimeError, "IMU_NOT_READY"):
            self.run_example(arm=True)
        self.assertEqual([c[0] for c in self.fc.commands], ["ARM", "DISARM"])
        self.assertLess(self.clock.now, .5)

    def test_application_stall_stops_without_delayed_channel_replay(self):
        self.clock.stall = True
        with self.assertRaisesRegex(RuntimeError, "paused"):
            self.run_example(arm=True)
        self.assertLess(self.fc.values[-1][0], .5)
        self.assertEqual(self.fc.commands[-1][0], "DISARM")

    def test_existing_armed_controller_is_not_changed(self):
        self.fc.armed = True
        with self.assertRaisesRegex(RuntimeError, "DISARMED"):
            self.run_example()
        self.assertEqual(self.fc.set_calls, [])
        self.assertEqual(self.fc.commands, [])
        self.assertEqual(self.fc.values, [])

    def test_qualified_kits_use_saved_input_without_overwriting_it(self):
        for version in ("3.1.0", "3.2.0"):
            for source in (1, 2):
                with self.subTest(version=version, source=source):
                    self.fc = ExampleFC(self.clock)
                    self.fc.version = version
                    self.fc.saved_source = self.fc.selected = source
                    self.assertGreater(self.run_example(source=source, arm=True), 0)
                    self.assertEqual([name for name, _ in self.fc.commands], ["ARM", "DISARM"])
                    self.assertEqual(self.fc.set_calls, [])

    def test_source_lock_and_unsaved_gains_block_modern_example(self):
        self.fc.version = "3.2.0"
        self.fc.selected = 1
        self.fc.saved_source = 0
        with self.assertRaisesRegex(RuntimeError, "flight input"):
            self.run_example()
        self.fc.saved_source = 1
        self.fc.setup[0] = True
        with self.assertRaisesRegex(RuntimeError, "setup"):
            self.run_example()
        self.fc.setup[0] = False
        self.fc.pid_status[0] = True
        with self.assertRaisesRegex(RuntimeError, "saved kit PID"):
            self.run_example(arm=True)
        self.assertEqual(self.fc.commands, [])
        self.assertEqual(self.fc.values, [])
        self.assertEqual(self.fc.set_calls, [])

    def test_old_firmware_does_not_start_command_only_example(self):
        self.fc.version = "2.4.0"
        with self.assertRaisesRegex(RuntimeError, "matching"):
            self.run_example()
        self.assertEqual(self.fc.set_calls, [])
        self.assertEqual(self.fc.values, [])


if __name__ == "__main__":
    unittest.main()
