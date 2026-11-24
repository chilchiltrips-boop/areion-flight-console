"""Validate and select this extracted project's SDK and desktop package."""
from __future__ import annotations

import importlib
import os
from pathlib import Path
import shlex
import subprocess
import sys

PROJECT_ROOT = Path(__file__).resolve().parent
SDK_VERSION = "3.12.3"
GUI_VERSION = "3.12.3"
SDK_FILES = ("__init__.py", "client.py", "control.py", "protocol.py",
             "registry.py", "schema.py", "transports.py")
GUI_FILES = ("__init__.py", "window.py", "backend.py", "model.py", "widgets.py",
             "setup_wizard.py", "wizard_extended.py", "wizard_model.py",
             "setup_config.py", "setup_backend.py", "setup_visuals.py",
             "wizard_chrome.py", "wizard_step_views.py", "receiver_sticks.py", "drone_scene.py",
             "setup_changes.py", "restart_check.py", "restart_page.py",
             "health_board.py", "flight_pose.py", "combo_box.py", "usb_ports.py", "receiver_history.py", "tx_link.py", "tx_link_panel.py", "assets/down-dark.svg",
             "pid_workspace.py", "pid_matrix.py", "pid_response.py",
             "scopes_page.py", "scope_data.py", "scope_plot.py", "scope_receiver.py",
             "assets/airframes/areion450.obj", "assets/airframes/areion250.obj",
             "assets/airframes/areion.mtl",
             "calibration_panel.py", "sensor_calibration.py", "profile_artwork.py", "receiver_calibration.py", "attitude_model.py", "scroll_guard.py", "flight_dashboard.py", "primary_display.py", "flight_status.py", "calibration_page.py", "console_layout.py", "welcome.py", "launcher_tile.py", "link_activity.py",
             "flight_workspace.py", "gps_map.py", "assets/world-land-110m.svg",
             "assets/areion-mark.png", "assets/launch-wizard.svg", "assets/launch-flight.svg",
             "assets/launch-input.svg", "assets/launch-imu.svg", "assets/launch-esc.svg",
             "assets/launch-pid.svg", "assets/launch-scopes.svg",
             "assets/nav-welcome.svg", "assets/nav-flight.svg", "assets/nav-configuration.svg", "assets/nav-system.svg", "assets/nav-scopes.svg", "assets/nav-hitl.svg", "assets/nav-firmware.svg", "assets/check.svg", "assets/down.svg", "assets/up.svg")


def _check_files(require_gui):
    required = [PROJECT_ROOT / "zebjus_areion_link" / name for name in SDK_FILES]
    if require_gui:
        required += [PROJECT_ROOT / "areion_gui" / name for name in GUI_FILES]
        required += [PROJECT_ROOT / name for name in
                     ("gui.py", "live_control.py", "receiver_control.py", "wifi_check.py")]
    missing = [path for path in required if not path.is_file()]
    if missing:
        raise ProjectSetupError(
            f"The extracted Areion project is incomplete. Project: {PROJECT_ROOT}\nMissing:\n"
            + "\n".join(str(path) for path in missing)
            + "\nExtract the ENTIRE ZIP into a new folder. In PyCharm open that folder "
              "and Run its main.py; do not copy only main.py into an older project. "
              "Installing requirements cannot restore these project files.")


def _check_origin(module, package_name):
    expected = PROJECT_ROOT / package_name / "__init__.py"
    origin = getattr(module, "__file__", None)
    if not origin or Path(origin).resolve() != expected.resolve():
        raise ProjectSetupError(
            f"Wrong Areion package loaded: {package_name}\nLocation: {origin}\n"
            f"Expected: {expected}\nRestart the PyCharm Python Console and Run "
            "main.py from the complete extracted project.")


class ProjectSetupError(RuntimeError):
    pass


def install_command():
    args = [sys.executable, str(PROJECT_ROOT / "install_requirements.py")]
    return subprocess.list2cmdline(args) if os.name == "nt" else shlex.join(args)


def prepare_project(require_gui=False):
    """Use this extraction; never reload packages already in use elsewhere."""
    _check_files(require_gui)

    # PyCharm's persistent Python Console can retain modules from an old
    # project even after sys.path or the working directory has changed.
    for name, module in tuple(sys.modules.items()):
        if not (name == "zebjus_areion_link" or name.startswith("zebjus_areion_link.")
                or name == "areion_gui" or name.startswith("areion_gui.")):
            continue
        origin = getattr(module, "__file__", None)
        if not origin or not Path(origin).resolve().is_relative_to(PROJECT_ROOT):
            raise ProjectSetupError(
                f"An earlier project is already loaded: {name}\nLocation: {origin}\n"
                "Stop/restart the PyCharm Python Console, then Run main.py from "
                f"this extracted project:\n{PROJECT_ROOT}\n"
                "Do not reuse a running console from the old project.")

    root = str(PROJECT_ROOT)
    sys.path[:] = [root] + [entry for entry in sys.path if entry != root]
    importlib.invalidate_caches()
    sdk = importlib.import_module("zebjus_areion_link")
    _check_origin(sdk, "zebjus_areion_link")
    if getattr(sdk, "__version__", None) != SDK_VERSION:
        raise ProjectSetupError(
            f"Mixed Areion project versions: expected SDK {SDK_VERSION}, "
            f"loaded {getattr(sdk, '__version__', 'unknown')} from {sdk.__file__}.\n"
            "Extract the complete new ZIP into a new folder and Run its main.py.")
    if require_gui:
        gui = importlib.import_module("areion_gui")
        _check_origin(gui, "areion_gui")
        if getattr(gui, "__version__", None) != GUI_VERSION:
            raise ProjectSetupError(
                f"Mixed Areion GUI versions: expected {GUI_VERSION}, loaded "
                f"{getattr(gui, '__version__', 'unknown')} from {gui.__file__}.\n"
                "Extract the entire new ZIP into a new folder and Run its main.py.")
    return sdk


def import_failure(error):
    """Distinguish third-party dependencies from broken/mixed project files."""
    name = getattr(error, "name", "") or ""
    details = f"{error}\nPython interpreter: {sys.executable}\nProject: {PROJECT_ROOT}"
    if name == "PySide6" or name.startswith("PySide6.") or name == "serial" or name.startswith("serial."):
        return (details + "\nInstall the dependencies and bundled SDK in this same interpreter:\n"
                + install_command())
    return (details + "\nThe project import failed. Extract the complete new ZIP into a new folder, "
            "restart any old Python Console, then Run that folder's main.py. "
            "This is not necessarily a missing third-party requirement.")


def setup_report():
    sdk = prepare_project(require_gui=True)
    control = importlib.import_module("zebjus_areion_link.control")
    qt = importlib.import_module("PySide6")
    serial = importlib.import_module("serial")
    gui = importlib.import_module("areion_gui")
    # Import the complete GUI graph, without constructing widgets or a Link.
    importlib.import_module("areion_gui.window")
    wizard = importlib.import_module("areion_gui.wizard_extended")
    importlib.import_module("areion_gui.scopes_page")
    importlib.import_module("areion_gui.pid_workspace")
    importlib.import_module("areion_gui.flight_dashboard")
    return (f"Setup OK\nPython: {sys.executable}\nProject: {PROJECT_ROOT}\n"
            f"SDK: {sdk.__version__} at {sdk.__file__}\nControl module: {control.__file__}\n"
            f"GUI: {gui.__version__} at {gui.__file__}\nSetup wizard module: {wizard.__file__}\n"
            f"PySide6: {qt.__version__}\npyserial: {serial.__version__}\n"
            "Compatible FC firmware: 3.1.0, 3.2.0 or 3.3.0. No hardware connection was opened.")
