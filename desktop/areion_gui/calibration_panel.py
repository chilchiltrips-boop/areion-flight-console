"""Read-only attitude illustrations and guided ACC / gyro capture controls."""
from copy import deepcopy
import math
import time

from PySide6.QtCore import Qt, Signal, QTimer, QVariantAnimation
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QBoxLayout, QCheckBox, QDoubleSpinBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QProgressBar, QSizePolicy, QTabWidget, QVBoxLayout, QWidget,
)

from shiboken6 import isValid

from .attitude_model import AttitudeModel
from .drone_scene import DroneScene
from .model import equal_values
from .scroll_guard import page_action_button as button
from .sensor_calibration import (
    MAX_AGE_S, MIN_DURATION_S, MIN_SAMPLES, POSES, POSE_BY_KEY,
    AutomaticSixFaceCalibration, GyroCalibration, corrected_acc_preview, corrected_gyro_preview,
)
from .widgets import label


def note(value, role='muted'):
    widget = label(value, role)
    widget.setWordWrap(True)
    return widget


class CaptureStatus(QLabel):
    """A fixed-gutter status lamp changes immediately, with a brief halo on transitions."""

    COLORS = {'idle': '#96b0bc', 'capture': '#62cef2', 'done': '#62dfb1', 'error': '#ff9a88'}

    def __init__(self, text):
        super().__init__(text)
        self.state = 'idle'
        self.setObjectName('captureStatus')
        self.setContentsMargins(23, 0, 2, 0)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.setWordWrap(True)
        self.setMinimumHeight(34)
        self.pulse = QVariantAnimation(self)
        self.pulse.setDuration(380)
        self.pulse.setStartValue(1.)
        self.pulse.setEndValue(0.)
        self.pulse.valueChanged.connect(lambda _: self.update())

    def show_status(self, state, text):
        if state == self.state and text == self.text():
            return
        if state != self.state and self.isVisible():
            self.pulse.stop()
            self.pulse.start()
        self.state = state
        self.setText(text)
        self.setAccessibleName(text)

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(self.COLORS[self.state])
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        cy = self.height() // 2
        p.drawEllipse(6, cy - 3, 7, 7)
        pulse = float(self.pulse.currentValue() or 0.)
        if pulse and self.pulse.state() == QVariantAnimation.State.Running:
            color.setAlpha(int(90 * pulse))
            p.setBrush(color)
            radius = round(5 + (1. - pulse) * 4)
            p.drawEllipse(9 - radius, cy - radius, 2 * radius, 2 * radius)
        p.end()


class CalibrationPanel(QWidget):
    changed = Signal()
    read_requested = Signal()

    def __init__(self, configuration):
        super().__init__()
        self.config = deepcopy(configuration)
        self.loading = True
        self.values = {}
        self.stamp = self.identity = self.read_available = None
        self.now = 0.
        self.demo = self.safe = False
        self.bank = self.gyro = self.gyro_preview = None
        self.saved_measurement = None
        self.pose_key = 'level'
        self.attitude = AttitudeModel()
        self.live_angles = None
        self.expiry = QTimer(self)
        self.expiry.setSingleShot(True)
        self.expiry.setTimerType(Qt.TimerType.PreciseTimer)
        self.expiry.timeout.connect(self._expire_readings)
        self.setStyleSheet('''
            QFrame#imuStage {background:#122b36; border:1px solid #34515d; border-radius:8px;}
            QLabel#imuLegend {color:#b9d8dd; font-size:11px; font-weight:700;}
            QLabel#imuReading {color:#ecf6f4; font-size:13px; font-weight:600;}
            QLabel#posePrompt {color:#eff8f6; font-size:19px; font-weight:700;}
            QLabel#poseTile {color:#aec3ce; background:#1b303d; border:1px solid #354c57;
                             border-radius:5px; padding:5px 7px; font-size:12px;}
            QLabel#poseTile[mark="detected"] {color:#cdedff; background:#214554; border-color:#59adcc;}
            QLabel#poseTile[mark="done"] {color:#bff4df; background:#193f39; border-color:#3a7567;}
            QLabel#captureStatus {color:#dce8ea; font-size:12px;}
            QProgressBar#captureMeter {background:#253d49; border:0; border-radius:3px; min-height:6px; max-height:6px;}
            QProgressBar#captureMeter::chunk {background:#57c9ac; border-radius:3px;}
        ''')
        self.columns = QBoxLayout(QBoxLayout.Direction.LeftToRight, self)
        self.columns.setContentsMargins(0, 0, 0, 0)
        self.columns.setSpacing(9)
        scene_row = QHBoxLayout()
        scene_row.setSpacing(8)
        self.pose_art, self.pose_title = self._scene(scene_row, 'Target position')
        self.live_scene, self.live_status = self._scene(scene_row, 'Live IMU')
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        self.columns.addLayout(layout, 56)
        self.columns.addLayout(scene_row, 44)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._acc_tab(), 'Accelerometer')
        self.tabs.addTab(self._gyro_tab(), 'Gyroscope')
        self.tabs.addTab(self._offsets_tab(), 'ACC offsets')
        self.tabs.currentChanged.connect(self._tab_changed)
        layout.addWidget(self.tabs)
        self.loading = False
        self._set_target('level')
        if self.config.get('result'):
            self.acc_status.show_status('idle', 'Saved ACC estimate (historical).')
        if self.config.get('gyro_result'):
            self.gyro_status.show_status('idle', 'Saved gyro result is historical. Capture again.')
        self._readings()
        self._buttons()

    def _scene(self, row, caption):
        stage = QFrame()
        stage.setObjectName('imuStage')
        box = QVBoxLayout(stage)
        box.setContentsMargins(7, 5, 7, 5)
        box.setSpacing(2)
        box.addWidget(label(caption, 'imuLegend'))
        scene = DroneScene()
        scene.setAccessibleName(caption)
        scene.setMinimumHeight(120)
        scene.setMaximumHeight(236)
        box.addWidget(scene, 1)
        summary = label('—', 'imuReading')
        summary.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        box.addWidget(summary)
        row.addWidget(stage, 1)
        return scene, summary

    @staticmethod
    def _meter(title):
        meter = QProgressBar()
        meter.setObjectName('captureMeter')
        meter.setAccessibleName(title)
        meter.setRange(0, 100)
        meter.setValue(0)
        meter.setTextVisible(False)
        return meter

    def _acc_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 7, 10, 7)
        layout.setSpacing(4)
        heading = QHBoxLayout()
        self.target_label = note('Calibrate six positions', 'posePrompt')
        heading.addWidget(self.target_label, 1)
        self.face_count = label('0 / 6', 'imuReading')
        heading.addWidget(self.face_count)
        layout.addLayout(heading)
        self.acc_status = CaptureStatus('Start once. Turn the kit onto each side and hold still.')
        layout.addWidget(self.acc_status)
        self.acc_progress = self._meter('Stable samples for this position')
        layout.addWidget(self.acc_progress)
        grid = QGridLayout()
        grid.setSpacing(4)
        self.pose_tiles = {}
        for i, pose in enumerate(POSES):
            key = pose['key']
            tile = label(pose['title'], 'poseTile')
            self.pose_tiles[key] = tile
            grid.addWidget(tile, i // 3, i % 3)
        layout.addLayout(grid)
        actions = QHBoxLayout()
        self.capture_button = button('Start calibration', self.start_calibration, 'primary')
        self.reset_button = button('Cancel', self.reset_acc)
        actions.addWidget(self.capture_button)
        actions.addWidget(self.reset_button)
        actions.addStretch()
        layout.addLayout(actions)
        self.stored_state = note('', 'imuLegend')
        layout.addWidget(self.stored_state)
        self.result_summary = note('', 'imuReading')
        self.result_summary.hide()
        layout.addWidget(self.result_summary)
        layout.addStretch()
        return page

    def _gyro_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 7, 10, 7)
        layout.setSpacing(4)
        self.stationary = QCheckBox('Kit is resting on a stable surface.')
        self.stationary.toggled.connect(self._confirmation_changed)
        layout.addWidget(self.stationary)
        grid = QGridLayout()
        self.gyro_live, self.gyro_corrected = [], []
        for col, title in enumerate(('Axis', 'FC rate (°/s)', 'After Python zero (°/s)')):
            grid.addWidget(label(title, 'eyebrow'), 0, col)
        for i, axis in enumerate(('Roll / X', 'Pitch / Y', 'Yaw / Z')):
            before, after = label('—', 'imuReading'), label('—', 'imuReading')
            self.gyro_live.append(before)
            self.gyro_corrected.append(after)
            for col, widget in enumerate((label(axis), before, after)):
                grid.addWidget(widget, i+1, col)
        layout.addLayout(grid)
        actions = QHBoxLayout()
        self.gyro_button = button('Capture gyro zero', self.start_gyro, 'primary')
        self.gyro_clear = button('Clear Python zero', self.clear_gyro)
        actions.addWidget(self.gyro_button)
        actions.addWidget(self.gyro_clear)
        self.zero_yaw = button('Zero yaw', self._reset_yaw)
        self.zero_yaw.setToolTip('Use the present orientation as the relative gyro yaw reference.')
        actions.addWidget(self.zero_yaw)
        actions.addStretch()
        layout.addLayout(actions)
        self.gyro_progress = self._meter('Gyro zero capture')
        layout.addWidget(self.gyro_progress)
        self.gyro_status = CaptureStatus('Keep the kit level and still. The FC calibrates its gyro at startup.')
        layout.addWidget(self.gyro_status)
        layout.addStretch()
        return page

    def _offsets_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(3)
        grid = QGridLayout()
        grid.setVerticalSpacing(2)
        self.offsets, self.corrected_labels = [], []
        for i, title in enumerate(('Axis', 'Offset (g)', 'Preview (g)')):
            grid.addWidget(label(title, 'eyebrow'), 0, i)
        for i, axis in enumerate('XYZ'):
            editor = QDoubleSpinBox()
            editor.setRange(-.5, .5)
            editor.setDecimals(4)
            editor.setSingleStep(.001)
            editor.setMaximumWidth(150)
            editor.setValue(self.config['offsets'][i])
            editor.setAccessibleName(f'Accelerometer offset {axis} in g')
            editor.valueChanged.connect(lambda value, axis=i: self._edited(axis, value))
            editor.destroyed.connect(self.expiry.stop)
            corrected = label('—', 'imuReading')
            for col, widget in enumerate((label(axis), editor, corrected)):
                grid.addWidget(widget, i+1, col)
            self.offsets.append(editor)
            self.corrected_labels.append(corrected)
        layout.addLayout(grid)
        self.read_button = button('Read FC offsets', self.read_requested.emit)
        self.read_button.setToolTip('Load the kit’s active offsets. The preview includes edits before saving.')
        layout.addWidget(self.read_button)
        layout.addStretch()
        return page

    def _reset_yaw(self):
        self.attitude.reset_yaw()
        self._readings()

    def _tab_changed(self, index):
        self._guide()
        self._readings()

    def _guide(self):
        key = self.pose_key if self.tabs.currentIndex() == 0 else 'level'
        self.pose_art.set_guide_pose(key)
        self.pose_title.setText(POSE_BY_KEY[key]['title'])

    def _fresh(self, now):
        imu = self.values.get(21)
        status = self.values.get(120)
        return bool(isinstance(status, (list, tuple)) and len(status) == 10 and status[2] is True
                    and type(status[5]) is int and status[5] > 0 and isinstance(imu, (list, tuple))
                    and len(imu) == 10 and all(type(v) in (float, int) and math.isfinite(v) for v in imu)
                    and type(self.stamp) in (int, float) and 0 <= now - self.stamp <= MAX_AGE_S)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        direction = (QBoxLayout.Direction.LeftToRight if event.size().width() >= 680
                     else QBoxLayout.Direction.TopToBottom)
        if self.columns.direction() != direction:
            self.columns.setDirection(direction)
        scene_height = 158 if event.size().width() < 980 else 236
        self.pose_art.setMaximumHeight(scene_height)
        self.live_scene.setMaximumHeight(scene_height)

    def hideEvent(self, event):
        if isValid(self.expiry):
            self.expiry.stop()
        super().hideEvent(event)

    def _expire_readings(self):
        if not all(isValid(editor) for editor in self.offsets):
            return
        now = time.monotonic()
        if self.stamp is not None and now - self.stamp > MAX_AGE_S:
            self.update_telemetry(self.values, self.stamp, now, self.identity, self.demo, self.safe)

    @property
    def active(self):
        return bool((self.bank and self.bank.running) or self.gyro)

    @property
    def has_current_result(self):
        result = self.bank.result if self.bank else None
        return bool(result and self.saved_measurement is None and result['gyro_residual_ok'] and self._valid()
                    and self.identity is not None and self.config['result'] == result
                    and equal_values(self.config['offsets'], result['candidate_offsets'])
                    and 6 in self.values and equal_values(self.values[6], self.bank.baseline))

    def snapshot(self):
        return deepcopy(self.config)

    def _edited(self, axis, value):
        if self.loading:return
        self.saved_measurement=None
        # The editors show four decimals. Keep the other axes at full FC precision.
        self.config['offsets'][axis] = value
        self.config.update(offsets_origin='manual', result=None)
        self.bank=None;self.acc_progress.setValue(0);self.acc_status.show_status('idle', 'Offsets edited · capture cleared.')
        self._buttons();self._readings();self.changed.emit()

    def set_offsets(self,values,origin='fc_readback'):
        self.saved_measurement=None;self.bank=None;self.loading=True
        for e,v in zip(self.offsets,values):e.setValue(v)
        self.loading=False;self.config.update(offsets=list(values),offsets_origin=origin,result=None)
        self.acc_progress.setValue(0);self.acc_status.show_status('idle', 'Kit offsets loaded.')
        self._buttons();self._readings();self.changed.emit()

    def _set_target(self,key):
        self.pose_key = key
        self._guide()

    def _valid(self):
        return bool(self.safe and self._fresh(time.monotonic()) and self.values[120][0] is False)

    def _buttons(self):
        ready=self._valid() and self.identity is not None and not self.active
        report = self.config.get('result') if self.saved_measurement else None
        faces=self.bank.faces if self.bank else report.get('faces', {}) if report else {}
        detected=self.bank.current_key if self.bank and self.bank.running else None
        self.face_count.setText(f'{len(faces)} / {len(POSES)}')
        self.face_count.setAccessibleName(f'{len(faces)} of {len(POSES)} positions captured')
        for pose in POSES:
            key=pose['key']; tile=self.pose_tiles[key]
            mark='done' if key in faces else 'detected' if key==detected else 'pending'
            if tile.property('mark') != mark:
                icon, name = {'done':('✓', 'Captured'), 'detected':('●', 'Sampling'), 'pending':('○', 'Pending')}[mark]
                tile.setProperty('mark',mark)
                tile.setText(f'{icon}  {pose["title"]}')
                tile.setAccessibleName(f'{pose["title"]} · {name}')
                tile.style().unpolish(tile)
                tile.style().polish(tile)
        self.capture_button.setText('Capturing…' if self.bank and self.bank.running else
                                    'Restart calibration' if self.bank and self.bank.error else 'Start calibration')
        self.gyro_button.setText('Retry gyro zero' if self.gyro_status.state == 'error' else 'Capture gyro zero')
        self.capture_button.setEnabled(ready and 6 in self.values and not (self.bank and self.bank.result))
        self.reset_button.setText('Cancel' if self.bank and self.bank.running else 'Clear result')
        self.reset_button.setEnabled(self.bank is not None and self.gyro is None)
        for index in range(self.tabs.count()):
            self.tabs.setTabEnabled(index, not self.active or index == self.tabs.currentIndex())
        self.gyro_button.setEnabled(ready and self.stationary.isChecked())
        self.gyro_clear.setEnabled(not self.active);self._read_button_state()
        for e in self.offsets:e.setEnabled(not self.active)
        if self.bank is None and self.saved_measurement is None:
            if self.pose_key != 'level':
                self._set_target('level')
            self.target_label.setText('Calibrate six positions')
            self.result_summary.hide()
        elif self.saved_measurement:
            self.target_label.setText('Calibration saved')

    def set_read_available(self,available):
        # Reading offsets is independent of permission to capture/calibrate.
        # Keep one owner for this button: telemetry and navigation must not
        # alternate between the props-off capture guard and connection guard.
        self.read_available=bool(available)
        self._read_button_state()

    def _read_button_state(self):
        allowed=self.safe if self.read_available is None else self.read_available
        enabled=bool(allowed and not self.active)
        if self.read_button.isEnabled()!=enabled:self.read_button.setEnabled(enabled)

    def _confirmation_changed(self,*args):
        if not self.stationary.isChecked() and self.gyro:self.suspend('stationary confirmation withdrawn')
        self._buttons()

    def start_calibration(self):
        if not self.capture_button.isEnabled():return
        self.saved_measurement=None
        try:
            self.bank=AutomaticSixFaceCalibration(self.values[6],self.demo,started=time.monotonic())
        except (ValueError, TypeError):
            self.acc_status.show_status('error','Read valid offsets from the kit before starting.')
            return
        self.config['result']=None
        self._set_target('level')
        self.acc_progress.setValue(0)
        self.result_summary.hide()
        self.target_label.setText('Place the kit flat')
        self.acc_status.show_status('capture','Turn to any unfinished position and hold still.')
        self._buttons();self.changed.emit()

    def reset_acc(self):
        cancelled=bool(self.bank and self.bank.running)
        self.saved_measurement=None
        self.bank=None;self.config['result']=None;self.acc_progress.setValue(0)
        self.acc_status.show_status('idle', 'Capture cancelled.' if cancelled else 'Ready to start a new calibration.')
        self._set_target('level');self._buttons();self.changed.emit()

    def start_gyro(self):
        if not self.gyro_button.isEnabled():return
        self.gyro=GyroCalibration(time.monotonic(),self.demo);self.gyro_preview=None;self.config['gyro_result']=None
        self.gyro_progress.setValue(0);self.gyro_status.show_status('capture', 'Capturing gyro zero… hold still.')
        self._readings();self._buttons();self.changed.emit()

    def clear_gyro(self):
        self.gyro=None;self.gyro_preview=None;self.config['gyro_result']=None;self.gyro_progress.setValue(0)
        self.gyro_status.show_status('idle', 'Python gyro zero cleared.')
        self._readings();self._buttons();self.changed.emit()

    def suspend(self,reason):
        if self.bank and self.saved_measurement is None:
            self.bank=None
            self.acc_progress.setValue(0)
            self.acc_status.show_status('error', 'Capture cancelled · '+reason)
        if self.gyro:
            self.gyro = None
            self.gyro_progress.setValue(0)
            self.gyro_status.show_status('error', 'Capture cancelled · '+reason)
        self._buttons();self.changed.emit()

    def new_visit(self):
        self.suspend('new setup visit');self.bank=None;self.gyro_preview=None;self.stationary.setChecked(False)
        self.saved_measurement=None
        self.acc_progress.setValue(0);self.gyro_progress.setValue(0)
        self.acc_status.show_status('idle', 'Saved estimate (historical). Capture again.' if self.config.get('result') else '0 / 6 positions captured.')
        self.gyro_status.show_status('idle', 'Capture gyro zero for this session.')
        self._set_target('level')
        self._buttons()

    def update_telemetry(self,values,stamp,now,identity,demo,safe):
        changed_identity=self.identity is not None and identity!=self.identity
        self.values=values;self.stamp=stamp;self.now=now;self.identity=identity;self.demo=demo;self.safe=safe
        status=values.get(120);imu=values.get(21)
        setup_state=values.get(130)
        verified=bool(isinstance(setup_state,(list,tuple)) and len(setup_state)>5 and setup_state[5])
        self.stored_state.setText('Kit sensor check verified' if verified and self._fresh(now) else '')
        setup = values.get(134)
        if isinstance(setup, (list, tuple)) and len(setup) == 11:
            profile = 'areion250' if setup[0] == 1 else 'areion450'
            self.pose_art.set_profile(profile)
            self.live_scene.set_profile(profile)
        fresh = self._fresh(now)
        if fresh and self.isVisible():
            self.expiry.start(max(1, math.ceil(1000 * (MAX_AGE_S - (now-stamp))) + 1))
        else:
            self.expiry.stop()
        continuous = bool(safe and fresh and status[0] is False)
        saved_matches=bool(self.saved_measurement and self.saved_measurement[0] == identity
                           and verified and fresh and 6 in values
                           and equal_values(values[6], self.saved_measurement[1]))
        if not saved_matches:
            self.saved_measurement=None
        changed_baseline=bool(self.bank and not saved_matches and
                              (6 not in values or not equal_values(values[6],self.bank.baseline)))
        if changed_identity or changed_baseline or not continuous:
            if self.bank:
                self.bank=None;self.acc_progress.setValue(0)
                if not saved_matches:
                    self.acc_status.show_status('error', 'Capture reset · connection, offsets or sensor state changed.')
                self.changed.emit()
            if self.gyro:
                self.gyro=None;self.gyro_progress.setValue(0)
                self.gyro_status.show_status('error', 'Gyro capture stopped · check connection and hold still to retry.')
            if self.gyro_preview:self.gyro_status.show_status('idle', 'Previous gyro zero is historical. Capture again.')
            self.gyro_preview=None
        elif self.bank and self.bank.running:
            state = self.bank.add(imu, stamp, now, continuous)
            self._show_automatic_capture(state)
        elif self.gyro:
            self.gyro.add(imu,stamp,now,self.stationary.isChecked())
            self._capture_progress(self.gyro, self.gyro_progress, self.gyro_status, 'Gyro zero')
            if self.gyro.error:
                self.gyro_status.show_status('error', self.gyro.error)
                self.gyro_progress.setValue(0)
                self.gyro = None
            elif self.gyro.result:
                self.config['gyro_result']=deepcopy(self.gyro.result);self.gyro_preview=deepcopy(self.gyro.result);self.gyro=None
                self.gyro_status.show_status('done', ('DEMO · ' if self.demo else '')+'Gyro zero captured · Python preview only.')
                self.changed.emit()
        self._readings();self._buttons()

    def _show_automatic_capture(self, state):
        bank = self.bank
        target = bank.current_key or bank.suggested_key
        if target and target != self.pose_key:
            self._set_target(target)
        if state == 'complete':
            result = deepcopy(bank.result)
            self.config.update(result=result, offsets_origin=result['kind'],
                               offsets=list(result['candidate_offsets']))
            self.loading = True
            try:
                for editor, offset in zip(self.offsets, result['candidate_offsets']):
                    editor.setValue(offset)
            finally:
                self.loading = False
            self.target_label.setText('Ready to save')
            self.acc_progress.setValue(100)
            self.acc_status.show_status('done', ('DEMO · ' if self.demo else '') +
                                        '6 / 6 positions captured · stationary gyro check passed.')
            offsets = '   '.join(f'{axis} {offset:+.4f}' for axis, offset in zip('XYZ', result['candidate_offsets']))
            self.result_summary.setText(f'{offsets}  g\nMaximum corrected error  {result["max_additive_residual_g"]:.3f} g')
            self.result_summary.show()
            self.changed.emit()
        elif state == 'error':
            self.target_label.setText('Calibration interrupted')
            self.acc_progress.setValue(0)
            self.acc_status.show_status('error', bank.error)
            self.changed.emit()
        elif bank.current:
            name = POSE_BY_KEY[bank.current_key]['title']
            self.target_label.setText('Hold still · ' + name)
            self._capture_progress(bank.current, self.acc_progress, self.acc_status, name)
        else:
            self.target_label.setText('Next · ' + POSE_BY_KEY[target]['title'])
            self.acc_progress.setValue(0)
            if bank.last_captured and bank.detected_key == bank.last_captured:
                self.acc_status.show_status('done', POSE_BY_KEY[bank.last_captured]['title'] +
                                            ' captured. Turn to an unfinished position.')
            else:
                self.acc_status.show_status('capture', bank.hint)
            if state == 'captured':
                self.changed.emit()

    def mark_saved(self):
        self.saved_measurement=(self.identity, list(self.config['offsets']))
        self.acc_progress.setValue(100)
        self.acc_status.show_status('done', 'Accelerometer offsets saved and verified on the kit.')
        self.target_label.setText('Calibration saved')
        self._buttons()

    @staticmethod
    def _capture_progress(capture, meter, status, title):
        elapsed = 0. if capture.first_stamp is None else capture.last_stamp - capture.first_stamp
        meter.setValue(int(capture.progress * 100))
        sample_label = 'sample' if len(capture.samples) == 1 else 'samples'
        status.show_status('capture', f'{title} · {len(capture.samples)} {sample_label} · '
                           f'{elapsed:.1f} / {MIN_DURATION_S:.0f} s')
        meter.setAccessibleDescription(f'{len(capture.samples)} samples, minimum {MIN_SAMPLES}')

    def _readings(self):
        now = time.monotonic()
        imu = self.values.get(21)
        fresh = self._fresh(now)
        self.attitude.update(imu, self.stamp, now, self.identity, valid=fresh)
        self.zero_yaw.setEnabled(self.attitude.valid and self.attitude.yaw is not None)
        self.live_angles = None
        if fresh and self.attitude.valid:
            if self.tabs.currentIndex() == 1:
                roll, pitch, yaw = self.attitude.roll, self.attitude.pitch, self.attitude.yaw
                self.live_angles = (roll, pitch, yaw)
                y_text = '—' if yaw is None else f'{yaw:+.0f}°'
                summary = f'R {roll:+.0f}°   P {pitch:+.0f}°   Y {y_text}'
                self.live_status.setToolTip('Filtered roll and pitch; yaw is relative to the current gyro reference.')
            else:
                # During a stationary six-face check gravity distinguishes an
                # inverted kit from a level kit even when FC pitch/roll fold.
                ax, ay, az = imu[3:6]
                projection = math.hypot(ay, az)
                if .6 <= math.hypot(ax, projection) <= 1.5:
                    roll = math.degrees(math.atan2(ay, az)) if projection > .04 else 0.
                    pitch = math.degrees(math.atan2(-ax, projection))
                    self.live_angles = (roll, pitch, None)
                    r_text = f'{roll:+.0f}°' if projection > .04 else '—'
                    summary = f'R {r_text}    P {pitch:+.0f}°'
                    self.live_status.setToolTip('Stationary gravity tilt. Heading is fixed for comparison with the target.')
                else:
                    summary = 'Hold still · check acceleration'
        else:
            summary = 'Waiting for live IMU'
        if self.live_angles is None:
            self.live_scene.set_live_pose(None, None)
        else:
            self.live_scene.set_live_pose(*self.live_angles)
        self.live_status.setText(summary)

        try:
            acc = corrected_acc_preview(imu, self.values[6], self.config['offsets']) if fresh and 6 in self.values else None
        except (ValueError, TypeError):
            acc = None
        for i, readout in enumerate(self.corrected_labels):
            readout.setText(f'{acc[i]:+.4f} g' if acc is not None else '—')
        rates = corrected_gyro_preview(imu, self.gyro_preview) if fresh and self.gyro_preview else None
        for i, readout in enumerate(self.gyro_live):
            readout.setText(f'{imu[i]:+.3f}' if fresh else '—')
        for i, readout in enumerate(self.gyro_corrected):
            readout.setText(f'{rates[i]:+.3f}' if rates is not None else '—')
