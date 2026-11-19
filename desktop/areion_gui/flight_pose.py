"""Live Quad X attitude, using the same timestamped estimate as the flight display."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout

from .drone_scene import DroneScene


STYLE = """
QFrame#flightPose {background:#152f3a;border:1px solid #38545e;border-radius:8px;}
QFrame#flightPose QLabel {background:transparent;border:0;color:#eff7f7;}
QLabel#poseTitle {font-size:13px;font-weight:700;}
QLabel#poseAxis {color:#a5c1c7;font-size:9px;font-weight:700;}
"""

# High-contrast state labels on the dark instrument background.
TONES = {'green':'#8ce7b3', 'amber':'#ffc183', 'red':'#ff9393', 'gray':'#b4c4ca'}
AXES = (('roll','ROLL'), ('pitch','PITCH'), ('yaw','REL YAW'))
YAW_TIP = 'Yaw relative to the gyro reference. It can drift. The dashed 0° line marks that reference.'


class FlightPose(QFrame):
    """Draw validated angles. Only the shared AttitudeModel calculates yaw."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('flightPose')
        self.setAccessibleName('Live Quad X attitude')
        self.setStyleSheet(STYLE)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        box = QVBoxLayout(self)
        box.setContentsMargins(6, 4, 6, 5)
        box.setSpacing(3)
        header = QHBoxLayout()
        header.setSpacing(4)
        self.title = QLabel('IMU attitude', objectName='poseTitle')
        header.addWidget(self.title)
        header.addStretch()
        self.status = QLabel()
        header.addWidget(self.status)
        box.addLayout(header)
        self.scene = DroneScene()
        self.scene.setMinimumSize(96, 58)
        self.scene.set_live_pose(None, None)
        box.addWidget(self.scene, 1)
        strip = QGridLayout()
        strip.setHorizontalSpacing(3)
        strip.setVerticalSpacing(0)
        self.readouts = {}
        for column, (axis, title) in enumerate(AXES):
            caption = QLabel(title, objectName='poseAxis')
            value = QLabel('—')
            value.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
            value.setAlignment(Qt.AlignmentFlag.AlignCenter)
            value.setAccessibleName('Relative yaw' if axis == 'yaw' else axis.title())
            if axis == 'yaw':
                caption.setToolTip(YAW_TIP)
                value.setToolTip(YAW_TIP)
            strip.addWidget(caption, 0, column)
            strip.addWidget(value, 1, column)
            strip.setColumnStretch(column, 1)
            self.readouts[axis] = value
        box.addLayout(strip)
        self._small = None
        self._fit_readouts(280)
        self._identity = self._stamp = self._yaw = None
        self._yaw_basis = 0.
        self._state = None
        self._set_state('gray', 'OFFLINE', 'Connect the kit to see its attitude.')

    def _fit_readouts(self, width):
        small = width < 194
        if small == self._small:
            return
        self._small = small
        font = QFont()
        font.setPixelSize(12 if small else 16)
        font.setWeight(QFont.Weight.DemiBold)
        for value in self.readouts.values():
            value.setFont(font)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_readouts(self.width())

    def _set_state(self, tone, label, detail):
        if self._state == (tone, label, detail):
            return
        self._state = tone, label, detail
        self.status.setText(label)
        self.status.setStyleSheet(f'color:{TONES[tone]};font-size:10px;font-weight:700;')
        self.status.setToolTip(detail)
        self.scene.setToolTip(detail)

    def set_attitude(self, model, health):
        live = health.state == 'green' and model.valid
        if live:
            roll, pitch, yaw = model.roll, model.pitch, model.yaw
            # Changes of reference snap immediately. Interpolating a yaw reset would
            # show a turn that the kit never made.
            reset = (self._stamp is None or self._identity != model.identity
                     or not 0 <= model.stamp - self._stamp <= model.MAX_GAP)
            if reset:
                self._yaw_basis = 0.
            if yaw is not None:
                reset |= self._yaw is None or (model.stamp == self._stamp and yaw != self._yaw)
                self._yaw_basis = yaw
            self.scene.set_live_pose(roll, pitch, self._yaw_basis, snap=reset)
            self.scene.set_yaw_reference(yaw is not None)
            if yaw is None:
                self._set_state('amber', 'TILT ONLY', 'Near vertical pitch. Roll and pitch are live. Yaw is unavailable.')
            else:
                self._set_state('green', 'LIVE', 'F marks the front of the airframe. ' + YAW_TIP)
            self._identity, self._stamp, self._yaw = model.identity, model.stamp, yaw
        else:
            roll = pitch = yaw = None
            self._stamp = self._yaw = None
            self.scene.set_live_pose(None, None)
            self.scene.set_yaw_reference(False)
            if health.state == 'green':
                self._set_state('amber', 'WAITING', model.reason)
            else:
                self._set_state(health.state, health.label, health.detail)
        for field, sample in (('roll', roll), ('pitch', pitch), ('yaw', yaw)):
            text = '—' if sample is None else f'{0. if abs(sample) < .05 else sample:+.1f}°'
            if self.readouts[field].text() != text:
                self.readouts[field].setText(text)
