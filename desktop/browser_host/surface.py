"""Render the real Qt widgets and deliver browser input in Qt's UI thread."""
import math
import time
from PySide6.QtCore import (QBuffer, QByteArray, QEvent, QIODevice, QObject, QPoint,
                            QPointF, Qt, QTimer, Signal)
from PySide6.QtGui import QImage, QInputMethodEvent, QKeyEvent, QPainter, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget
from shiboken6 import isValid

from .server import Session

BUTTONS = {0: Qt.MouseButton.LeftButton, 1: Qt.MouseButton.MiddleButton, 2: Qt.MouseButton.RightButton}
MODS = {'Shift': Qt.KeyboardModifier.ShiftModifier, 'Control': Qt.KeyboardModifier.ControlModifier,
        'Alt': Qt.KeyboardModifier.AltModifier, 'Meta': Qt.KeyboardModifier.MetaModifier}
KEYS = {s: getattr(Qt.Key, 'Key_' + v) for s, v in {
    'ArrowLeft':'Left', 'ArrowRight':'Right', 'ArrowUp':'Up','ArrowDown':'Down',
    'Tab':'Tab','Enter':'Return','Escape':'Escape','Backspace':'Backspace',
    'Delete':'Delete','Home':'Home','End':'End','PageUp':'PageUp','PageDown':'PageDown',
    'Insert':'Insert','Shift':'Shift','Control':'Control','Alt':'Alt','Meta':'Meta',
    ' ':'Space','CapsLock':'CapsLock', **{f'F{i}':f'F{i}' for i in range(1, 13)}
}.items()}
VISUAL = {QEvent.Type.Paint, QEvent.Type.Show, QEvent.Type.Hide, QEvent.Type.Move,
          QEvent.Type.Resize, QEvent.Type.ZOrderChange, QEvent.Type.WindowActivate}


def number(value, default=0):
    return int(value) if type(value) in (int, float) and abs(value) < 1e8 and math.isfinite(value) else default


class Surface(QObject):
    input_received = Signal(int, object)
    release_requested = Signal(int)

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.app = QApplication.instance()
        self.session = Session(self.input_received.emit, self.release_requested.emit)
        self.input_received.connect(self.dispatch, Qt.ConnectionType.QueuedConnection)
        self.release_requested.connect(self.release, Qt.ConnectionType.QueuedConnection)
        self.dirty = True
        self.windows = []
        self.pressed = {}
        self.last_paint = 0.
        self.reset_generation = -1
        self.app.installEventFilter(self)
        self.app.clipboard().dataChanged.connect(self.clipboard_changed)
        self.tick = QTimer(self)
        self.tick.setTimerType(Qt.TimerType.PreciseTimer)
        self.tick.timeout.connect(self.refresh)
        self.tick.start(25)
        window.move(0, 0)
        window.resize(self.session.width, self.session.height)
        window.show()
        window.activateWindow()

    def clipboard_changed(self):
        # Copy the text produced by the isolated Qt clipboard. Never inspect a
        # system clipboard on the browser workstation.
        self.session.clipboard = self.app.clipboard().text()[:262144]

    def eventFilter(self, obj, event):
        if isinstance(obj, QWidget) and event.type() in VISUAL:
            self.dirty = True
            if obj.isWindow() and obj is not self.window and event.type() in (
                    QEvent.Type.Show, QEvent.Type.ZOrderChange, QEvent.Type.WindowActivate):
                self.windows = [w for w in self.windows if isValid(w) and w is not obj]
                self.windows.append(obj)
        return False

    def layers(self):
        self.windows = [w for w in self.windows if isValid(w) and w.isVisible()]
        result = list(self.windows)
        for top in (self.app.activeModalWidget(), self.app.activePopupWidget()):
            if top is not None and top.isVisible() and top is not self.window:
                result = [w for w in result if w is not top] + [top]
        return [self.window] + result

    def refresh(self):
        session = self.session
        with session.lock:
            session.active_controls = (self.window._running() or
                (self.window.command_busy and not (self.window._setup_guard or self.window._calibration_guard)) or
                any(self.motor_active(p) for p in (self.window._setup_wizard, *self.window._maintenance.values())))
            if not session.client:
                return
            if session.expired():
                session._drop()
                return
        now = time.monotonic()
        if (self.dirty or session.frame is None) and now - self.last_paint >= .06:
            self.last_paint = now
            self.capture()

    @staticmethod
    def motor_active(panel):
        if not panel:
            return False
        pending = getattr(panel, 'pending', None)
        return (getattr(panel, 'motor_running', False) or
                bool(pending and pending[0] == 'command' and pending[1].get('command') == 'MOTOR_START'))

    def capture(self):
        size = self.window.size()
        image = QImage(size, QImage.Format.Format_RGB32)
        image.fill(Qt.GlobalColor.black)
        painter = QPainter(image)
        try:
            origin = self.window.mapToGlobal(QPoint(0, 0))
            for layer in self.layers():
                pos = layer.mapToGlobal(QPoint(0, 0)) - origin
                painter.drawPixmap(pos, layer.grab())
        finally:
            painter.end()
        self.dirty = False
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if image.save(buffer, 'JPEG', 82):
            self.session.publish(bytes(data), size.width(), size.height())

    def release(self, generation):
        if generation <= self.reset_generation:
            return
        self.reset_generation = generation
        self.release_inputs()

    def release_inputs(self):
        # A provisional wizard motor start can still be waiting for its ACK.
        # Its urgent stop cancels that transaction as well as the test.
        wizard = self.window._setup_wizard
        if wizard and wizard.connected and wizard.pending and wizard.pending[0] == 'command' and wizard.pending[1].get('command') == 'MOTOR_START':
            wizard.action_requested.emit('command', {'command':'MOTOR_STOP', 'args':[0,0,0,0]})
        # Stop/clear before releasing widgets. Put the release well outside a
        # pressed button so abandoning a tab can never complete a button click.
        self.window._application_state(Qt.ApplicationState.ApplicationInactive)
        for button, handler in self.pressed.items():
            if isValid(handler):
                QTest.mouseRelease(handler, button, Qt.KeyboardModifier.NoModifier, QPoint(-100, -100))
        self.pressed.clear()
        self.window.left_stick.held = self.window.right_stick.held = False
        self.window.controls.pressed.clear()
        self.dirty = True

    def dispatch(self, generation, events):
        if not self.session.consume(generation, len(events)):
            return
        for event in events:
            with self.session.lock:
                if generation != self.session.generation or self.session.client is None:
                    return
            self.handle(event)
        self.dirty = True

    def handle(self, event):
        kind = event.get('type')
        if kind == 'reset':
            self.release_inputs()
            return
        if kind == 'resize':
            width = max(900, min(2048, number(event.get('width'), 1280)))
            height = max(700, min(1536, number(event.get('height'), 800)))
            self.window.resize(width, height)
            return
        if kind not in ('keyDown', 'keyUp', 'text', 'move', 'down', 'up', 'dblclick', 'wheel'):
            return
        mods = Qt.KeyboardModifier.NoModifier
        names = event.get('mods', [])
        if isinstance(names, list):
            for name in MODS:
                if name in names:
                    mods |= MODS[name]
        if kind in ('keyDown', 'keyUp', 'text'):
            return self.key(kind, event, mods)
        x = max(0, min(self.window.width()-1, number(event.get('x'))))
        y = max(0, min(self.window.height()-1, number(event.get('y'))))
        point = self.window.mapToGlobal(QPoint(x, y))
        top = self.window
        for layer in reversed(self.layers()):
            if layer.rect().contains(layer.mapFromGlobal(point)):
                top = layer
                break
        popup = self.app.activePopupWidget()
        modal = self.app.activeModalWidget()
        if popup:
            top = popup
        elif modal and top is not modal and not modal.isAncestorOf(top):
            return
        handle = top.windowHandle()
        if handle is None:
            return
        button = BUTTONS.get(number(event.get('button')), Qt.MouseButton.LeftButton)
        if kind == 'up':
            old = self.pressed.pop(button, None)
            if old is not None and isValid(old):
                handle = old
        elif kind == 'move' and self.pressed:
            old = next(iter(self.pressed.values()))
            if isValid(old):
                handle = old
        position = handle.mapFromGlobal(point)
        if kind == 'down':
            self.pressed[button] = handle
            QTest.mousePress(handle, button, mods, position)
        elif kind == 'up':
            QTest.mouseRelease(handle, button, mods, position)
        elif kind == 'dblclick':
            QTest.mouseDClick(handle, button, mods, position)
        elif kind == 'move':
            QTest.mouseMove(handle, position, 0)
        elif kind == 'wheel':
            local = top.mapFromGlobal(point)
            target = top.childAt(local) or top
            delta = QPoint(-number(event.get('dx')), -number(event.get('dy')))
            wheel = QWheelEvent(QPointF(target.mapFromGlobal(point)), QPointF(point), delta, delta,
                Qt.MouseButton.NoButton, mods, Qt.ScrollPhase.NoScrollPhase, False)
            self.app.sendEvent(target, wheel)

    def key(self, kind, event, mods):
        target = self.app.focusWidget() or self.app.activePopupWidget() or self.app.activeModalWidget() or self.window
        text = event.get('text', '')
        if not isinstance(text, str):
            return
        if kind == 'text':
            message = QInputMethodEvent()
            message.setCommitString(text[:8192])
            self.app.sendEvent(target, message)
            return
        name = event.get('key', '')
        if not isinstance(name, str) or len(name) > 32:
            return
        key = KEYS.get(name)
        if key is None and len(name) == 1 and len(name.upper()) == 1:
            key = ord(name.upper())
        if key is None:
            return
        etype = QEvent.Type.KeyPress if kind == 'keyDown' else QEvent.Type.KeyRelease
        text = text or (name if len(name) == 1 else '')
        self.app.sendEvent(target, QKeyEvent(etype, key, mods, text[:64], event.get('repeat') is True))
