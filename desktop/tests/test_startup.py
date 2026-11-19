"""Exercise clean processes, old installed packages and incomplete extractions."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class StartupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.project = self.base / 'new project'
        shutil.copytree(ROOT, self.project,
                        ignore=shutil.ignore_patterns('__pycache__', 'build', '*.egg-info', 'tests'))
        self.old = self.base / 'old installed SDK'
        package = self.old / 'zebjus_areion_link'
        package.mkdir(parents=True)
        (package / '__init__.py').write_text('__version__ = "2.4.0"\n')
        gui = self.old / 'areion_gui'
        gui.mkdir()
        (gui / '__init__.py').write_text('__version__ = "2.4.0"\n')
        (gui / 'window.py').write_text("raise AssertionError('Old GUI was imported')\n")

    def tearDown(self):
        self.temp.cleanup()

    def run_process(self, code=None):
        args = ([sys.executable, '-c', code] if code else
                [sys.executable, str(self.project / 'main.py'), '--check'])
        return subprocess.run(args, cwd=self.base, env=os.environ.copy(),
                              capture_output=True, text=True, timeout=20)

    def gui_code(self):
        return f"import sys;sys.path.insert(0,{str(self.project)!r});sys.argv=['gui.py','--check'];from gui import main;main()"

    def test_complete_project_check_from_another_working_directory(self):
        result = self.run_process()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Setup OK', result.stdout)
        self.assertIn('SDK: 3.12.3', result.stdout)
        self.assertIn('GUI: 3.12.3', result.stdout)
        self.assertIn('Setup wizard module:', result.stdout)
        self.assertIn(str(self.project / 'areion_gui' / 'wizard_extended.py'), result.stdout)
        self.assertIn(str(self.project / 'zebjus_areion_link' / 'control.py'), result.stdout)
        self.assertIn('Compatible FC firmware: 3.1.0', result.stdout)

    def test_complete_project_path_with_trailing_space(self):
        renamed = self.base / 'areon drone '
        self.project.rename(renamed)
        self.project = renamed
        result = self.run_process()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('GUI: 3.12.3', result.stdout)
        self.assertIn(str(renamed / 'areion_gui' / 'wizard_extended.py'), result.stdout)

    def test_unloaded_old_sdk_cannot_shadow_the_bundled_package(self):
        code = (f"import sys;sys.path[:0]=[{str(self.old)!r},{str(self.project)!r}];"
                "sys.argv=['gui.py','--check'];from gui import main;main()")
        result = self.run_process(code)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('SDK: 3.12.3', result.stdout)

    def test_cached_old_sdk_reports_restart_instead_of_reloading_it(self):
        code = (f"import sys;sys.path.insert(0,{str(self.old)!r});import zebjus_areion_link;"
                + self.gui_code())
        result = self.run_process(code)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('already loaded', result.stderr)
        self.assertIn('Stop/restart the PyCharm Python Console', result.stderr)
        self.assertNotIn('pip install -r', result.stderr)

    def test_unloaded_old_gui_cannot_shadow_the_bundled_package(self):
        code = (f"import sys;sys.path[:0]=[{str(self.old)!r},{str(self.project)!r}];"
                "sys.argv=['gui.py','--check'];from gui import main;main()")
        result = self.run_process(code)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('GUI: 3.12.3', result.stdout)
        self.assertIn(str(self.project / 'areion_gui' / 'wizard_extended.py'), result.stdout)

    def test_cached_old_gui_reports_restart_instead_of_reloading_it(self):
        code = (f"import sys;sys.path.insert(0,{str(self.old)!r});import areion_gui;"
                + self.gui_code())
        result = self.run_process(code)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('already loaded: areion_gui', result.stderr)
        self.assertIn(str(self.old / 'areion_gui' / '__init__.py'), result.stderr)
        self.assertIn('Stop/restart the PyCharm Python Console', result.stderr)
        self.assertNotIn('pip install -r', result.stderr)

    def test_missing_direct_calibration_module_reports_incomplete_extraction(self):
        (self.project / 'areion_gui' / 'calibration_page.py').unlink()
        result=self.run_process()
        self.assertNotEqual(result.returncode,0)
        self.assertIn('calibration_page.py',result.stderr)
        self.assertIn('project is incomplete',result.stderr)

    def test_missing_3d_airframe_identifies_the_asset_at_startup(self):
        airframe = self.project / 'areion_gui' / 'assets' / 'airframes' / 'areion450.obj'
        airframe.unlink()
        result = self.run_process()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(str(airframe), result.stderr)
        self.assertIn('Extract the ENTIRE ZIP', result.stderr)

    def test_missing_control_file_reports_incomplete_extraction(self):
        (self.project / 'zebjus_areion_link' / 'control.py').unlink()
        result = self.run_process()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('project is incomplete', result.stderr)
        self.assertIn(str(self.project / 'zebjus_areion_link' / 'control.py'), result.stderr)
        self.assertIn('cannot restore these project files', result.stderr)

    def test_missing_gui_files_report_exact_paths_before_qt_import(self):
        no_qt = '''import importlib.abc,sys
class NoQt(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'PySide6' or fullname.startswith('PySide6.'):
            raise ModuleNotFoundError("No module named 'PySide6'", name='PySide6')
sys.meta_path.insert(0,NoQt())
'''
        for relative in ('wizard_extended.py', 'calibration_panel.py', '__init__.py',
                         'assets/check.svg', 'assets/up.svg', 'assets/down.svg'):
            with self.subTest(missing=relative):
                path = self.project / 'areion_gui' / relative
                original = path.read_bytes()
                path.unlink()
                try:
                    result = self.run_process(no_qt + self.gui_code())
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('project is incomplete', result.stderr)
                    self.assertIn(str(path), result.stderr)
                    self.assertIn('cannot restore these project files', result.stderr)
                    self.assertNotIn('Install the dependencies and bundled SDK', result.stderr)
                finally:
                    path.write_bytes(original)

    def test_removed_demo_argument_is_rejected_by_each_entry_point(self):
        for arguments in (('gui.py',), ('main.py',), ('main.py', '--console')):
            with self.subTest(entry=arguments):
                result = subprocess.run(
                    [sys.executable, str(self.project / arguments[0]), *arguments[1:], '--demo'],
                    cwd=self.base, env=os.environ.copy(), capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn('unrecognized arguments: --demo', result.stderr)

    def test_console_help_does_not_require_desktop_gui_files(self):
        shutil.rmtree(self.project / 'areion_gui')
        result = subprocess.run(
            [sys.executable, str(self.project / 'main.py'), '--console', '--help'],
            cwd=self.base, env=os.environ.copy(), capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('usage:', result.stdout.lower())
        self.assertNotIn('project is incomplete', result.stderr)

    def test_mixed_local_versions_report_a_new_extraction(self):
        init = self.project / 'zebjus_areion_link' / '__init__.py'
        init.write_text(init.read_text().replace('"3.12.3"', '"2.4.0"'))
        result = self.run_process()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Mixed Areion project versions', result.stderr)

    def test_mixed_local_gui_version_reports_a_new_extraction(self):
        init = self.project / 'areion_gui' / '__init__.py'
        init.write_text(init.read_text().replace('"3.12.3"', '"2.7.0"'))
        result = self.run_process()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Mixed Areion GUI versions', result.stderr)
        self.assertIn(str(init), result.stderr)

    def test_missing_top_layout_sources_and_icons_report_complete_zip(self):
        for relative in ('console_layout.py','link_activity.py','assets/nav-flight.svg'):
            with self.subTest(missing=relative):
                path=self.project/'areion_gui'/relative;original=path.read_bytes();path.unlink()
                try:
                    result=self.run_process();self.assertNotEqual(result.returncode,0)
                    self.assertIn('project is incomplete',result.stderr)
                    self.assertIn(relative,result.stderr)
                finally:path.write_bytes(original)

    def test_missing_qt_gets_dependency_install_command_with_correct_interpreter(self):
        code = '''import importlib.abc,sys
class NoQt(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'PySide6' or fullname.startswith('PySide6.'):
            raise ModuleNotFoundError("No module named 'PySide6'", name='PySide6')
sys.meta_path.insert(0,NoQt())
''' + self.gui_code()
        result = self.run_process(code)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Install the dependencies and bundled SDK', result.stderr)
        self.assertIn('install_requirements.py', result.stderr)
        self.assertIn(sys.executable, result.stderr)

    def test_setup_check_does_not_open_serial_or_network(self):
        code = f'''import sys,socket
sys.path.insert(0,{str(self.project)!r})
def forbidden(*args,**kwargs):raise AssertionError('Hardware opened during setup check')
socket.socket=forbidden
import serial
serial.Serial=forbidden
sys.argv=['gui.py','--check']
from gui import main
main()
'''
        result = self.run_process(code)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Setup OK', result.stdout)


if __name__ == '__main__':
    unittest.main()
