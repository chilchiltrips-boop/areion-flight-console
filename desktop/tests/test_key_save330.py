import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
from areion_gui.model import Controls
from areion_gui.window import MainWindow


class KeySaveTests(unittest.TestCase):
    def test_failed_commit_retains_live_and_saved_mapping(self):
        with tempfile.TemporaryDirectory() as directory:
            target=SimpleNamespace(controls=Controls(),config_path=Path(directory)/'controls.json')
            original=list(target.controls.keys)
            MainWindow._save_key_bindings(target,original)
            stored=target.config_path.read_bytes()
            edited=list(original);edited[0]=tuple(reversed(edited[0]))
            with patch('areion_gui.window.os.replace',side_effect=OSError('disk unavailable')):
                with self.assertRaises(OSError):MainWindow._save_key_bindings(target,edited)
            self.assertEqual(list(target.controls.keys),original)
            self.assertEqual(target.config_path.read_bytes(),stored)
            self.assertEqual(list(Path(directory).glob('*.tmp')),[])
            MainWindow._save_key_bindings(target,edited)
            self.assertEqual(list(target.controls.keys),edited)
            self.assertEqual(json.loads(target.config_path.read_text())['keys'],[list(x) for x in edited])

    def test_invalid_keys_do_not_create_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            target=SimpleNamespace(controls=Controls(),config_path=Path(directory)/'controls.json')
            with self.assertRaises(ValueError):MainWindow._save_key_bindings(target,[('A','A')]*8)
            self.assertFalse(target.config_path.exists())
