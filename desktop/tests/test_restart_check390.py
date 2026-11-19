"""A changed transport/owner never proves a reboot; audit operations only read."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from areion_gui.restart_check import load_receipt, make_receipt, save_receipt, verify_restart
from areion_gui.setup_backend import run_setup_action
from areion_gui.setup_changes import SETTINGS_GROUPS
from zebjus_areion_link import RemoteError
from fc_fixture import DemoLink
from setup_fixtures import complete_demo_setup


class RestartCheckTests(unittest.TestCase):
    def setUp(self):
        self.link = DemoLink()
        complete_demo_setup(self.link, source=2)
        run_setup_action(self.link, 'begin', {}, lambda: False)
        # Finalization can have no edited fields. The receipt must still contain every verified group.
        final = run_setup_action(self.link, 'finalize', {'groups': {}}, lambda: False)
        self.receipt = make_receipt(final['values'][130], self.link.fc_session,
                                    final['verified_settings'], self.link.demo)
        self.assertEqual(set(self.receipt['settings']), set(SETTINGS_GROUPS))

    def verify(self):
        return verify_restart(self.link, self.receipt, lambda: False)

    def test_same_boot_or_different_kit_can_never_pass(self):
        self.link.session += 1
        self.assertEqual(self.verify()['state'], 'same_boot')
        self.link.demo_restart()
        self.link._setup[15] += '-other'
        self.assertEqual(self.verify()['state'], 'wrong_kit')

    def test_new_boot_reads_active_and_saved_settings_without_commands(self):
        self.link.demo_restart()
        with (patch.object(self.link, 'action', side_effect=AssertionError),
              patch.object(self.link, 'set_group', side_effect=AssertionError),
              patch.object(self.link, 'save_group', side_effect=AssertionError),
              patch.object(self.link, 'disarm', side_effect=AssertionError),
              patch.object(self.link, 'read_group', wraps=self.link.read_group) as reader):
            self.assertEqual(self.verify()['state'], 'verified')
            self.assertEqual({call.args[0] for call in reader.call_args_list if call.kwargs['saved']},
                             set(SETTINGS_GROUPS))
        self.assertFalse(self.link.armed)

    def test_active_stored_and_runtime_differences_name_actual_fields(self):
        self.link.demo_restart()
        self.link.values[6][0] += .1
        self.link.saved[4][4] += 1
        self.link.source = 1
        self.link._setup[0:2] = [True, False]
        result = self.verify()
        self.assertEqual(result['state'], 'mismatch')
        labels = [change[0] for change in result['changes']]
        self.assertIn('Setup complete', labels)
        self.assertIn('Accelerometer X offset · Active', labels)
        self.assertIn('ARM hold · Stored', labels)
        self.assertIn(('Current flight input', 'USB', 'AP'), result['changes'])

    def test_absent_stored_group_is_identified_separately_from_other_differences(self):
        self.link.demo_restart()
        self.link.values[4][4] += 1
        read = self.link.read_group
        def missing(group, *args, **kwargs):
            if group == 6 and kwargs.get('saved'):
                raise RemoteError(SimpleNamespace(data=['NOT_SAVED']))
            return read(group, *args, **kwargs)
        with patch.object(self.link, 'read_group', side_effect=missing):
            result = self.verify()
        self.assertEqual(result['state'], 'mismatch')
        self.assertTrue(any(row[2] == 'No saved copy' for row in result['changes']))
        self.assertTrue(any(row[0] == 'ARM hold · Active' for row in result['changes']))

    def test_cancellation_identity_or_storage_fault_prevent_match(self):
        self.link.demo_restart()
        with self.assertRaisesRegex(RuntimeError, 'Connection changed'):
            verify_restart(self.link, self.receipt, lambda: True)
        self.link.storage_available = False
        with self.assertRaisesRegex(RuntimeError, 'storage is unavailable'):
            self.verify()
        self.link.storage_available = True
        read = self.link.read_group
        def change_after_read(group, *args, **kwargs):
            value = read(group, *args, **kwargs)
            if group == 6:
                self.link.fc_session += 1
            return value
        with patch.object(self.link, 'read_group', side_effect=change_after_read):
            with self.assertRaisesRegex(RuntimeError, 'Connection changed'):
                self.verify()

    def test_durable_receipt_reloads_without_cache_or_confirmation(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'last_verified_setup.json'
            save_receipt(path, self.receipt)
            self.assertEqual(load_receipt(path), self.receipt)
            with patch('areion_gui.wizard_model.os.replace', side_effect=OSError('read only')):
                with self.assertRaises(OSError):
                    save_receipt(path, self.receipt)
            self.assertEqual(load_receipt(path), self.receipt)
            path.write_text('{"format": 1, "setup": []}')
            self.assertIsNone(load_receipt(path))
            self.assertIsNone(load_receipt(path.with_name('missing')))
