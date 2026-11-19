"""Read-only, animated gimbals for the PPM calibration monitor."""
import math
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout

from .widgets import Joystick


class MonitorGimbal(Joystick):
    def __init__(self, left):
        super().__init__(left=left)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setToolTip('Tracks the physical transmitter.')
        self.setMinimumSize(116, 142)
        self.setMaximumHeight(158)
        self.sync(None, None)

    def mousePressEvent(self, event):
        event.ignore()

    def mouseMoveEvent(self, event):
        event.ignore()

    def mouseReleaseEvent(self, event):
        event.ignore()


class ReceiverSticks(QFrame):
    """Display normalized roll, pitch, throttle and yaw, without a control path."""
    COLORS = {'live': ('#a9ebd3', '#214b43'), 'idle': ('#c1d1da', '#29404d'),
              'warning': ('#ffdd9c', '#514531'), 'error': ('#ffbdc4', '#513640')}

    def __init__(self):
        super().__init__()
        self.setObjectName('receiverSticks')
        self.setStyleSheet("""
            QFrame#receiverSticks {background:#112e3a;border:1px solid #385663;border-radius:10px;}
            QFrame#receiverSticks QLabel {background:transparent;}
            QLabel#stickHeading {color:#eff8f4;font-size:14px;font-weight:700;}
            QLabel#stickAxes {color:#bddbd9;font-size:10px;font-weight:700;}
            QLabel#stickValues {color:#e0eded;font-size:11px;}
        """)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 8, 10, 8)
        outer.setSpacing(3)
        header = QHBoxLayout()
        header.addWidget(QLabel('Receiver sticks', objectName='stickHeading'))
        header.addStretch()
        self.signal_label = QLabel()
        header.addWidget(self.signal_label)
        outer.addLayout(header)
        grid = QGridLayout()
        grid.setSpacing(2)
        self.left = MonitorGimbal(True)
        self.right = MonitorGimbal(False)
        self.readouts = []
        for column, (gimbal, title) in enumerate(((self.left, 'THROTTLE  /  YAW'), (self.right, 'PITCH  /  ROLL'))):
            name = QLabel(title, objectName='stickAxes')
            readout = QLabel('—  /  —', objectName='stickValues')
            for widget in (name, readout):
                widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.readouts.append(readout)
            grid.addWidget(name, 0, column)
            grid.addWidget(gimbal, 1, column)
            grid.addWidget(readout, 2, column)
            grid.setColumnStretch(column, 1)
        outer.addLayout(grid)
        self.target = None
        self._state = None
        self.quality = ''
        self._frame_at = 0.
        self.motion = QTimer(self)
        self.motion.setInterval(33)
        self.motion.timeout.connect(self._animate)
        self.set_sample(None, 'idle', 'Waiting', 'Waiting for a receiver frame.')

    def set_sample(self, values, quality, label, detail):
        status = (quality, label, detail)
        if status != self._state:
            if self.quality != quality:
                ink, bg = self.COLORS[quality]
                self.signal_label.setStyleSheet(
                    f'color:{ink};background:{bg};border-radius:5px;padding:2px 5px;font-size:10px;font-weight:700;')
            self.signal_label.setText(label)
            self.signal_label.setToolTip(detail)
            self._state = status
            self.quality = quality

        previous = self.target
        self.target = tuple(values[:4]) if values is not None else None
        if self.target == previous:
            return
        labels = ('—  /  —', '—  /  —')
        if self.target is not None:
            roll, pitch, throttle, yaw = self.target
            labels = (f'{throttle}  /  {yaw} µs', f'{pitch}  /  {roll} µs')
        for widget, text in zip(self.readouts, labels):
            widget.setText(text)
        if self.target is None:
            self.motion.stop()
            self.left.sync(None, None)
            self.right.sync(None, None)
        elif previous is None or not self.isVisible():
            self._position(1.)
        elif not self.motion.isActive():
            self._frame_at = time.monotonic()
            self.motion.start()

    def _position(self, fraction):
        roll, pitch, throttle, yaw = self.target
        settled = True
        for stick, horizontal, vertical in ((self.left, yaw, throttle), (self.right, roll, pitch)):
            tx, ty = (horizontal - 1500) / 500., (vertical - 1500) / 500.
            dx, dy = tx - stick.x, ty - stick.y
            if fraction == 1. or max(abs(dx), abs(dy)) < .004:
                stick.sync(tx, ty)
            else:
                settled = False
                stick.sync(stick.x + fraction * dx, stick.y + fraction * dy)
        return settled

    def _animate(self):
        now = time.monotonic()
        fraction = 1. - math.exp(-max(0., now - self._frame_at) / .055)
        self._frame_at = now
        if self.target is None or self._position(fraction):
            self.motion.stop()

    def hideEvent(self, event):
        self.motion.stop()
        if self.target is not None:
            self._position(1.)
        super().hideEvent(event)
