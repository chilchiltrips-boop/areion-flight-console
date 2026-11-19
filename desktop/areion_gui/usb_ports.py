"""Passive serial device discovery and the local last-confirmed USB preference."""
from concurrent.futures import Future
import json
import re
import threading

from PySide6.QtCore import QEvent, QObject, QSignalBlocker, Qt, QTimer

from .wizard_model import write_json_atomic


def start_scan():
    """Only enumerate device metadata. A blocked OS scan cannot hold the FC worker."""
    future = Future()

    def discover():
        try:
            from serial.tools import list_ports
            ports = {}
            for info in list_ports.comports():
                if info.device:
                    ports[info.device] = info.description or ''
            # COM2 precedes COM10. Keep the OS device strings intact as serial endpoints.
            def order(device):
                return tuple(int(s) if i % 2 else s.casefold()
                             for i, s in enumerate(re.split(r'(\d+)', device)))
            future.set_result([(path, ports[path]) for path in sorted(ports, key=order)])
        except Exception as error:
            future.set_exception(error)

    threading.Thread(target=discover, name='areion-usb-discovery', daemon=True).start()
    return future


def load_preference(path):
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        port = data['last_confirmed_port']
        return port if isinstance(port, str) and port.strip() else ''
    except (OSError, ValueError, TypeError, KeyError):
        return ''


def save_preference(path, port):
    write_json_atomic(path, {'last_confirmed_port': port})


def set_selection(combo, path):
    if combo.currentText() == path:
        return
    with QSignalBlocker(combo):
        index = combo.findText(path, Qt.MatchFlag.MatchExactly)
        combo.setCurrentIndex(index)
        if index < 0:
            combo.setEditText(path)


class PopupCloseObserver(QObject):
    """Finish reordering after Qt commits a popup choice and returns focus."""
    def __init__(self, parent, callback):
        super().__init__(parent)
        self.deferred = QTimer(self, interval=0, singleShot=True)
        self.deferred.timeout.connect(callback)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Hide:
            self.deferred.start()
        return False


def merge_open(combo, devices):
    """Keep existing row positions stable while the user points or navigates."""
    discovered = dict(devices)
    existing = set()
    with QSignalBlocker(combo), QSignalBlocker(combo.lineEdit()):
        for index in range(combo.count()):
            device = combo.itemText(index)
            existing.add(device)
            item = combo.model().item(index)
            present = device in discovered
            item.setEnabled(present)
            item.setToolTip((discovered[device] or device) if present else 'USB port unavailable')
        for device, description in devices:
            if device not in existing:
                combo.addItem(device)
                combo.setItemData(combo.count() - 1, description or device, Qt.ItemDataRole.ToolTipRole)


def populate(combo, devices, selection):
    editor = combo.lineEdit()
    keep_cursor = selection == combo.currentText() and editor.hasFocus()
    cursor = editor.cursorPosition()
    start, selected = editor.selectionStart(), editor.selectedText()
    with QSignalBlocker(combo), QSignalBlocker(editor):
        combo.clear()
        for device, description in devices:
            combo.addItem(device)
            combo.setItemData(combo.count() - 1, description or device, Qt.ItemDataRole.ToolTipRole)
        index = combo.findText(selection, Qt.MatchFlag.MatchExactly)
        combo.setCurrentIndex(index)
        if index < 0:
            combo.setEditText(selection)
        if keep_cursor and selected:
            if cursor == start:
                editor.setSelection(start + len(selected), -len(selected))
            else:
                editor.setSelection(start, len(selected))
        elif keep_cursor:
            editor.setCursorPosition(cursor)
