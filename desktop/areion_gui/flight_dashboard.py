"""Flight Data instruments and their read-only flight-controller indications."""
from __future__ import annotations

import math

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from .flight_pose import FlightPose
from .flight_status import SOURCES, flight_status
from .health_board import SystemHealthBoard
from .model import validate_values
from .primary_display import PrimaryFlightDisplay


ALIGN_LEFT = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
ALIGN_RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter


def instrument_font(size, bold=False):
    font = QFont('Sans Serif')
    font.setPixelSize(size)
    font.setWeight(QFont.Weight.DemiBold if bold else QFont.Weight.Normal)
    return font


class MotorReadback(QWidget):
    def __init__(self):
        super().__init__()
        self.values = None
        self.setMinimumHeight(31)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setAccessibleName('Commanded motor pulses')
        self.setToolTip('Output pulse commands reported by the flight controller. Motor speed is not measured.')

    def set_values(self, values):
        values = tuple(values) if values is not None else None
        if values != self.values:
            self.values = values
            self.setAccessibleDescription(' / '.join(f'{v:.0f} microseconds' for v in values) if values else 'Unavailable')
            self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        gap = 5
        cell = (self.width() - 3 * gap) / 4
        for index in range(4):
            rect = QRectF(index * (cell + gap), 0, cell, self.height())
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor('#e9f0ef'))
            p.drawRoundedRect(rect, 5, 5)
            text_area = rect.adjusted(8, 0, -8, -4)
            p.setFont(instrument_font(11, True))
            p.setPen(QColor('#45656c'))
            p.drawText(text_area, ALIGN_LEFT, f'M{index+1}')
            value = self.values[index] if self.values is not None else None
            p.setFont(instrument_font(14, True))
            p.setPen(QColor('#173e47'))
            p.drawText(text_area, ALIGN_RIGHT, f'{value:.0f}' if value is not None else '—')
            bar = QRectF(rect.left() + 8, rect.bottom() - 6, cell - 16, 2)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor('#c9d9d6'))
            p.drawRoundedRect(bar, 1, 1)
            if value is not None and value > 1000:
                bar.setWidth(bar.width() * (value - 1000) / 1000)
                p.setBrush(QColor('#237e76'))
                p.drawRoundedRect(bar, 1, 1)


def flight_indication(groups, health, connected):
    """Translate current FC readbacks into a concise reason; no overall arm-readiness inference."""
    if not connected:
        return None, '—', 'FC disconnected'
    if health['ARM'].label not in ('ARMED', 'DISARMED'):
        reason = 'Invalid FC status' if health['TELEMETRY'].state == 'red' else 'Waiting for FC status'
        return None, '—', reason

    armed = groups[120][0]
    mode = health['MODE'].label
    setup = groups.get(130)
    setup_valid = isinstance(setup, (list, tuple)) and len(setup) == 16 and all(
        type(setup[i]) is bool for i in (0, 1, 5, 6, 7, 8)
    )
    if health['IMU'].state == 'red':
        reason = 'IMU read fault'
    elif groups[120][5] == 0:
        reason = 'Waiting for gyro calibration'
    elif setup_valid and setup[0]:
        reason = 'Setup lock active'
    elif setup_valid and not setup[1]:
        reason = 'Setup incomplete'
    elif health['INPUT'].state == 'red':
        reason = 'Control signal lost' if health['INPUT'].label == 'LOST' else 'Invalid input status'
    elif health['INPUT'].label == 'TX OFF':
        reason = 'PPM transmitter off'
    elif groups.get(122) is None:
        reason = 'Waiting for input status'
    else:
        source = SOURCES[groups[122][0]]
        if health['INPUT'].state == 'green':
            reason = f'{source} input live'
        elif health['INPUT'].label == 'NEUTRAL':
            reason = f'Waiting for neutral · {source}'
        else:
            reason = f'Waiting for {source} signal'
    return armed, mode, reason


class FlightDashboard(QFrame):
    """Flight instruments with a live aircraft view and an always-visible health board."""

    def __init__(self):
        super().__init__()
        self.setObjectName('flightDashboard')
        self.setStyleSheet("""
            QFrame#flightDashboard {background:#f4f8f5; border:1px solid #b3c7c0; border-radius:11px;}
            QLabel#instrumentTitle {color:#183c43; font-size:17px; font-weight:700;}
            QLabel#motorCaption {color:#365761; font-size:10px; font-weight:700;}
            QLabel#imuSummary {color:#3b5d65; font-size:10px;}
            QPushButton#instrumentAction {background:#e9f1ec; color:#234952; border:1px solid #b8cdc3;
                border-radius:5px; padding:3px 7px; min-height:14px; font-size:11px;}
            QPushButton#instrumentAction:hover {background:#d9e9e0;}
            QPushButton#instrumentAction:checked {color:white; background:#25554e; border-color:#25554e;}
            QPushButton#instrumentAction:disabled {background:#edf2ef; color:#72837e; border-color:#cbd7d1;}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)
        header = QHBoxLayout()
        header.setSpacing(5)
        self.title = QLabel('Flight instruments', objectName='instrumentTitle')
        header.addWidget(self.title)
        header.addStretch()
        self.zero_button = QPushButton('Zero yaw', objectName='instrumentAction')
        self.zero_button.setToolTip('Set the current relative yaw to zero on both attitude views.')
        self.zero_button.clicked.connect(self.reset_yaw)
        header.addWidget(self.zero_button)
        self.details_button = QPushButton('Expand health', objectName='instrumentAction')
        self.details_button.setToolTip('Enlarge the system health and IMU views.')
        self.details_button.setCheckable(True)
        header.addWidget(self.details_button)
        layout.addLayout(header)

        self.horizon = PrimaryFlightDisplay()
        self.pose = FlightPose()
        self.health_board = SystemHealthBoard()
        self.tiles = self.health_board.tiles
        self._grid = QGridLayout()
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(5)
        layout.addLayout(self._grid, 1)

        self.imu_values = QLabel(objectName='imuSummary')
        self.imu_values.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.imu_values.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.imu_values.hide()
        layout.addWidget(self.imu_values)
        outputs = QHBoxLayout()
        outputs.setSpacing(6)
        outputs.addWidget(QLabel('MOTORS µs', objectName='motorCaption'))
        self.motor_readback = MotorReadback()
        outputs.addWidget(self.motor_readback, 1)
        layout.addLayout(outputs)
        self._layout_mode = None
        self._place_instruments(430)
        self.details_button.toggled.connect(self._show_details)
        self.last_health = {}
        self.update_state({}, None, 0., None, False)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._place_instruments(event.size().width())

    def _place_instruments(self, width):
        expanded = self.details_button.isChecked()
        # Focus gives the health board the full width. On the smallest
        # stand-alone panel, put the aircraft next to the PFD to fit both.
        stacked = expanded or width < 500
        mode = expanded, stacked
        if self._layout_mode == mode:
            return
        self._layout_mode = mode
        grid = self._grid
        for widget in (self.horizon, self.pose, self.health_board):
            grid.removeWidget(widget)
        self.horizon.setVisible(not expanded)
        grid.setRowStretch(0, 5 if expanded else 6)
        grid.setRowStretch(1, 7 if expanded else 5)
        grid.setColumnStretch(0, 3 if stacked and not expanded else 2)
        grid.setColumnStretch(1, 2 if stacked and not expanded else 4)
        if stacked:
            if expanded:
                grid.addWidget(self.pose, 0, 0, 1, 2)
            else:
                grid.addWidget(self.horizon, 0, 0)
                grid.addWidget(self.pose, 0, 1)
            grid.addWidget(self.health_board, 1, 0, 1, 2)
        else:
            if not expanded:
                grid.addWidget(self.horizon, 0, 0, 1, 2)
            grid.addWidget(self.pose, 1, 0)
            grid.addWidget(self.health_board, 1, 1)

    def _show_details(self, checked):
        self.title.setText('System overview' if checked else 'Flight instruments')
        self.details_button.setText('Show instruments' if checked else 'Expand health')
        self.details_button.setToolTip('Restore the primary flight display.' if checked
                                       else 'Enlarge the system health and IMU views.')
        self.imu_values.setVisible(checked)
        self._place_instruments(self.width())

    def reset_yaw(self):
        self.horizon.reset_yaw()
        self.pose.set_attitude(self.horizon.model, self.last_health['IMU'])

    def update_state(self, groups, stamp, now, identity, connected, *, input_age_s=0.0, tx_status=None):
        fresh_imu = (type(stamp) in (int, float) and type(now) in (int, float)
                     and math.isfinite(stamp) and math.isfinite(now)
                     and 0 <= now - stamp <= self.horizon.model.MAX_AGE)
        # A new status can precede the next IMU record during boot or recalibration.
        # Hide a recent sample from the previous calibration in that interval.
        status = groups.get(120)
        if status is not None:
            try:
                validate_values(120, status)
                if not 0 <= status[3] <= 8 or status[5] < 0 or status[6] < 0:
                    raise ValueError('Invalid FC status counters')
            except (ValueError, OverflowError):
                groups = {**groups, 120: ()}
                status = None
        if not fresh_imu or (status is not None and status[5] == 0):
            groups = {**groups, 21: None}
        self.last_health = flight_status(groups, connected, input_age_s=input_age_s, tx_status=tx_status)
        self.health_board.set_health(self.last_health)

        imu = groups.get(21)
        self.horizon.set_flight_state(*flight_indication(groups, self.last_health, connected))
        self.horizon.update_telemetry(imu, stamp, now, identity, valid=self.last_health['IMU'].state == 'green')
        self.pose.set_attitude(self.horizon.model, self.last_health['IMU'])
        self.zero_button.setEnabled(self.horizon.model.valid and self.horizon.model.yaw is not None)
        if self.horizon.model.valid:
            text = (f'Gyro °/s  {imu[0]:+.1f} / {imu[1]:+.1f} / {imu[2]:+.1f}      '
                    f'ACC g  {imu[3]:+.2f} / {imu[4]:+.2f} / {imu[5]:+.2f}')
        else:
            text = 'Gyro °/s  — / — / —      ACC g  — / — / —'
        if self.imu_values.text() != text:
            self.imu_values.setText(text)
            self.imu_values.setToolTip('X / Y / Z\n' + text)
        output = groups[23][3:7] if self.last_health['OUTPUT'].state == 'green' else None
        self.motor_readback.set_values(output)
