"""Read-only flight telemetry scopes for the native console."""
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QPushButton, QSizePolicy, QStackedWidget, QTabBar,
                               QVBoxLayout, QWidget)

from .combo_box import ConsoleComboBox
from .model import Telemetry
from .scope_data import frozen_telemetry, group_state, imu_spectra, time_series
from .scope_plot import ScopePlot
from .scope_receiver import ScopeReceiver


STYLE = """
QFrame#scopesPage {background:#e8f0ec;border:1px solid #b1c7bf;border-radius:12px;}
QLabel#scopeTitle {color:#16383e;font-size:23px;font-weight:700;background:transparent;}
QLabel#scopeMark {background:#1d4950;border-radius:6px;}
QFrame#scopeToolbar {background:#dbe7e1;border:1px solid #bdcec5;border-radius:7px;}
QTabBar#scopeTabs::tab, QTabBar#rxView::tab {background:transparent;color:#3f5e61;
    border:1px solid transparent;border-radius:5px;padding:4px 12px;font-size:12px;font-weight:600;}
QTabBar#scopeTabs::tab:hover, QTabBar#rxView::tab:hover {background:#cdded7;}
QTabBar#scopeTabs::tab:selected, QTabBar#rxView::tab:selected {background:#235752;color:#f5fbf5;}
QTabBar#rxView::tab {padding:3px 9px;font-size:11px;}
QFrame#scopesPage QPushButton#scopeAction {color:#234851;background:#f6faf6;border:1px solid #a9beb8;
    border-radius:6px;padding:4px 10px;font-size:12px;font-weight:600;min-height:20px;}
QFrame#scopesPage QPushButton#scopeAction:hover {background:#d5e6df;border-color:#779b92;}
QFrame#scopesPage QPushButton#scopeAction:pressed {background:#b9d7c9;}
QFrame#scopesPage QPushButton#scopeAction:checked {background:#f7da93;border-color:#c09f52;color:#4b391a;}
QFrame#scopesPage QPushButton#scopeAction:disabled {background:#e3eae5;border-color:#c1d0c7;color:#768b87;}
QLabel#scopeSpan, QLabel#scopeMeta {color:#496567;background:transparent;font-size:11px;}
QComboBox#scopeWindow {background:#f7faf6;color:#234a4c;border:1px solid #adc2b8;border-radius:5px;
    min-height:19px;padding:1px 5px;font-size:11px;font-weight:600;}
"""
TONES = {
    'Live': ('#125044', '#d1e9db'), 'Online': ('#125044', '#d1e9db'),
    'Frozen': ('#654d0f', '#f9e8af'), 'Waiting': ('#715321', '#f1e4c3'),
    'Stale': ('#7f352e', '#f7dacf'), 'Invalid': ('#8a393b', '#f4d7d8'),
    'Offline': ('#516566', '#dae2de'),
}
# Field references are from the Areion firmware telemetry schema.
MOTION = (
    ('gyro', 'Gyroscope', '°/s', 21, (('Roll', 0), ('Pitch', 1), ('Yaw', 2))),
    ('acc', 'Accelerometer', 'g', 21, (('X', 3), ('Y', 4), ('Z', 5))),
    ('roll', 'Roll attitude', '°', 21, (('Accel', 6), ('Kalman', 8))),
    ('pitch', 'Pitch attitude', '°', 21, (('Accel', 7), ('Kalman', 9))),
)
CONTROL = (
    ('rate_roll', 'Roll rate', '°/s', 0, (('Measured', 0), ('Target', 7))),
    ('rate_pitch', 'Pitch rate', '°/s', 0, (('Measured', 1), ('Target', 8))),
    ('rate_yaw', 'Yaw rate', '°/s', 0, (('Measured', 2), ('Target', 9))),
    ('motors', 'Motor commands', 'µs', 23, tuple((f'M{i+1}', i+3) for i in range(4))),
)
RECEIVER = (
    ('sticks', 'Stick channels', 'µs', 22, tuple((f'CH{i+1}', i) for i in range(4))),
    ('aux', 'Auxiliary channels', 'µs', 22, tuple((f'CH{i+1}', i) for i in range(4, 8))),
)
SPECTRA = (('spectrum_acc', 'Accelerometer spectrum', 'g', ('X', 'Y', 'Z')),
           ('spectrum_gyro', 'Gyroscope spectrum', '°/s', ('Roll', 'Pitch', 'Yaw')))


def _pill(widget, state, text):
    if widget.text() != text:
        widget.setText(text)
    if widget.property('tone') == state:
        return
    widget.setProperty('tone', state)
    ink, background = TONES.get(state, TONES['Waiting'])
    widget.setStyleSheet(f'color:{ink};background:{background};border-radius:4px;'
                         'font-weight:600;font-size:10px;padding:3px 6px;')


def _tabs(name, titles):
    bar = QTabBar()
    bar.setObjectName(name)
    bar.setAccessibleName('Scope views' if name == 'scopeTabs' else 'Receiver views')
    bar.setExpanding(False)
    bar.setDrawBase(False)
    bar.setUsesScrollButtons(True)
    for title in titles:
        bar.addTab(title)
    return bar


def _caption(text, role):
    label = QLabel(text)
    label.setObjectName(role)
    return label


class ScopesPage(QFrame):
    export_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('scopesPage')
        self.setStyleSheet(STYLE)
        self._data = self._identity = self._held = self._held_time = None
        self._now = 0.
        self._connected = False
        self._empty = Telemetry()
        self._draw_key = self._fft_key = self._fft = None
        self._drawn_fft = self._fft_style = None
        self.plots = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(6)
        header = QHBoxLayout()
        header.setSpacing(8)
        mark = _caption('', 'scopeMark')
        mark.setFixedSize(29, 29)
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon = Path(__file__).parent / 'assets' / 'nav-scopes.svg'
        mark.setPixmap(QIcon(str(icon)).pixmap(QSize(21, 21)))
        header.addWidget(mark)
        header.addWidget(_caption('Scopes', 'scopeTitle'))
        self.status_label = QLabel()
        header.addWidget(self.status_label)
        header.addStretch()
        self.freeze_button = QPushButton('Freeze')
        self.freeze_button.setObjectName('scopeAction')
        self.freeze_button.setCheckable(True)
        self.freeze_button.setToolTip('Hold the displayed samples. The kit continues streaming.')
        self.freeze_button.toggled.connect(self._hold)
        header.addWidget(self.freeze_button)
        self.export_button = QPushButton('Export session CSV')
        self.export_button.setObjectName('scopeAction')
        self.export_button.setToolTip('Export the received packet log, including arrivals while the scopes are frozen.')
        self.export_button.clicked.connect(self.export_requested.emit)
        header.addWidget(self.export_button)
        layout.addLayout(header)
        toolbar = QFrame()
        toolbar.setObjectName('scopeToolbar')
        controls = QHBoxLayout(toolbar)
        controls.setContentsMargins(4, 3, 5, 3)
        controls.setSpacing(7)
        self.view_tabs = _tabs('scopeTabs', ('Motion', 'Control', 'Spectrum', 'Receiver'))
        controls.addWidget(self.view_tabs)
        controls.addStretch()
        self.span_label = _caption('Window', 'scopeSpan')
        controls.addWidget(self.span_label)
        self.window_combo = ConsoleComboBox(light=True)
        self.window_combo.setObjectName('scopeWindow')
        self.window_combo.setAccessibleName('Scope time window')
        for seconds in (5, 15, 30):
            self.window_combo.addItem(f'{seconds} s', seconds)
        self.window_combo.setCurrentIndex(1)
        self.window_combo.setMinimumWidth(66)
        controls.addWidget(self.window_combo)
        layout.addWidget(toolbar)
        self.stack = QStackedWidget()
        self.stack.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.stack.addWidget(self._chart_grid(MOTION))
        self.stack.addWidget(self._chart_grid(CONTROL))
        self.stack.addWidget(self._chart_grid(SPECTRA, spectrum=True))
        self.stack.addWidget(self._receiver_page())
        layout.addWidget(self.stack, 1)
        footer = QHBoxLayout()
        footer.setSpacing(5)
        self.indicators = {}
        for name in ('Link', 'IMU', 'Input', 'Output'):
            self.indicators[name] = label = QLabel()
            footer.addWidget(label)
        footer.addStretch()
        self.meta = _caption('', 'scopeMeta')
        self.meta.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        footer.addWidget(self.meta)
        layout.addLayout(footer)
        self.view_tabs.currentChanged.connect(self._view_changed)
        self.rx_tabs.currentChanged.connect(self._receiver_changed)
        self.receiver.raw_button.toggled.connect(self._controls_changed)
        self.window_combo.currentIndexChanged.connect(self._controls_changed)
        self._render(force=True)

    def _chart_grid(self, definitions, spectrum=False):
        area = QWidget()
        grid = QGridLayout(area)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(7)
        for i, item in enumerate(definitions):
            key, title, unit = item[:3]
            self.plots[key] = plot = ScopePlot(title, unit, spectrum=spectrum)
            grid.addWidget(plot, i // 2, i % 2)
        for i in range(2):
            grid.setColumnStretch(i, 1)
        for i in range((len(definitions) + 1) // 2):
            grid.setRowStretch(i, 1)
        return area

    def _receiver_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.rx_tabs = _tabs('rxView', ('Channel monitor', 'Channel history'))
        layout.addWidget(self.rx_tabs, alignment=Qt.AlignmentFlag.AlignLeft)
        self.rx_stack = QStackedWidget()
        self.rx_stack.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.receiver = ScopeReceiver()
        self.rx_stack.addWidget(self.receiver)
        self.rx_stack.addWidget(self._chart_grid(RECEIVER))
        layout.addWidget(self.rx_stack, 1)
        return page

    @property
    def frozen(self):
        return self._held is not None

    @property
    def display_time(self):
        return self._held_time if self.frozen else self._now

    @property
    def display_data(self):
        return self._held if self.frozen else self._data

    def _view_changed(self, index):
        self.stack.setCurrentIndex(index)
        self._controls_changed()

    def _receiver_changed(self, index):
        self.rx_stack.setCurrentIndex(index)
        self._controls_changed()

    def _controls_changed(self, *_):
        use_window = self.view_tabs.currentIndex() != 3 or self.rx_tabs.currentIndex() != 0
        self.window_combo.setVisible(use_window)
        self.span_label.setVisible(use_window)
        if self.isVisible():
            self._render(force=True)

    def showEvent(self, event):
        super().showEvent(event)
        self._render(force=True)

    def _hold(self, enabled):
        if enabled and self._connected and self._data is not None:
            # The receive queue can advance between the last repaint and this click.
            stamps = (stamp for _, stamp in self._data.latest.values())
            self._held_time = max(self._now, max(stamps, default=self._now))
            self._held = frozen_telemetry(self._data, self._held_time)
        else:
            self._held = self._held_time = None
        self.freeze_button.setText('Resume live' if self.frozen else 'Freeze')
        self._fft_key = None
        self._render(force=True)

    def refresh(self, data, now, connected, identity=None):
        reset = (data is not self._data or identity != self._identity
                 or (self._connected and not connected))
        self._data, self._identity = data, identity
        self._now, self._connected = now, connected
        if reset:
            self._held = self._held_time = None
            self.freeze_button.blockSignals(True)
            self.freeze_button.setChecked(False)
            self.freeze_button.blockSignals(False)
            self.freeze_button.setText('Freeze')
            self._fft_key = self._draw_key = None
        if self.isVisible():
            self._render()

    def set_offline(self):
        self.refresh(None, self._now, False)

    def _render(self, force=False):
        data, now = self.display_data, self.display_time
        tab = self.view_tabs.currentIndex()
        seconds = self.window_combo.currentData()
        is_receiver = tab == 3 and self.rx_tabs.currentIndex() == 0
        connected = self._connected and data is not None
        groups = (21, 22, 23)
        states = {g: group_state(data, g, now) if connected else 'Offline' for g in groups}
        state = self._view_state(states, tab, is_receiver, data, now, connected)
        if tab != 2:
            _pill(self.status_label, state, state.upper())
        _pill(self.indicators['Link'], 'Online' if connected else 'Offline',
              'LINK  ' + ('Online' if connected else 'Offline'))
        for title, group in zip(('IMU', 'Input', 'Output'), groups):
            _pill(self.indicators[title], states[group], f'{title.upper()}  {states[group]}')
        self.freeze_button.setEnabled(bool(connected and (self.frozen or
            any(data.scopes.rows.get(g) for g in (21, 22, 23, 131)))))
        self.export_button.setEnabled(bool(self._data and self._data.rows))
        revisions = tuple(data.scopes.revisions.get(g, 0) for g in (21, 22, 23, 120, 122, 131)) if data else ()
        chart_clock = None if self.frozen or not connected else int(now * 10)
        key = (id(data), revisions, tab, seconds, self.rx_tabs.currentIndex(),
               self.frozen, state, tuple(states.values()), chart_clock)
        if key == self._draw_key and not force:
            return
        self._draw_key = key
        if tab != 2:
            self.meta.clear()
        if is_receiver:
            self.receiver.refresh(data if connected else self._empty, now, connected, frozen=self.frozen)
            return
        if tab == 2:
            self._render_spectrum(data, now, seconds, connected, states[21])
            return
        definitions = (MOTION if tab == 0 else CONTROL if tab == 1 else RECEIVER)
        for panel, title, unit, group, labels in definitions:
            if not connected:
                curves = {name: () for name, _ in labels}
                panel_state = 'Offline'
            elif group:
                curves = self._series(data, group, labels, now, seconds)
                panel_state = states[group]
            else:
                curves = self._series(data, 21, labels[:1], now, seconds)
                curves.update(self._series(data, 23, labels[1:], now, seconds))
                panel_state = self._combined_state(states[21], states[23])
            self.plots[panel].set_data(curves, (now - seconds, now),
                                       state='Frozen' if self.frozen else panel_state)

    @staticmethod
    def _series(data, group, labels, now, seconds):
        return time_series(data, group, dict(labels), now, seconds)

    @staticmethod
    def _combined_state(*states):
        for state in ('Offline', 'Invalid', 'Stale', 'Waiting'):
            if state in states:
                return state
        return 'Live'

    def _view_state(self, states, tab, is_receiver, data, now, connected):
        if self.frozen:
            return 'Frozen'
        if not connected:
            return 'Offline'
        if tab == 3:
            if is_receiver and self.receiver.raw_button.isChecked():
                return group_state(data, 131, now)
            return states[22]
        if tab == 1:
            return self._combined_state(states[21], states[23])
        return states[21]

    def _render_spectrum(self, data, now, seconds, connected, imu_state):
        result = None
        if connected and imu_state == 'Live':
            key = (id(data), seconds, data.scopes.revisions.get(21), imu_state)
            if key != self._fft_key:
                self._fft = imu_spectra(data, now, seconds)
                self._fft_key = key
            result = self._fft
        else:
            self._fft_key = self._fft = None
        chart_state = 'Frozen' if self.frozen else imu_state
        if result and result.message and not self.frozen:
            chart_state = 'Waiting'
        _pill(self.status_label, chart_state, chart_state.upper())
        if result and not result.message:
            self.meta.setText(f'{result.sample_rate:.1f} samples/s  ·  {result.count} samples  ·  {result.resolution:.2f} Hz/bin')
        else:
            self.meta.clear()
        if result is self._drawn_fft and self._fft_style == chart_state:
            return
        self._drawn_fft, self._fft_style = result, chart_state
        reason = {'Stale': 'IMU stream is stale', 'Invalid': 'IMU reports unavailable',
                  'Offline': 'Kit offline'}.get(imu_state, 'Waiting for IMU samples')
        detail = result.message if result else reason
        right = result.nyquist if result and result.nyquist else 1.
        for key, _, _, labels in SPECTRA:
            spectra = {name: () for name in labels}
            if result and not result.message:
                spectra = result.acc if key == 'spectrum_acc' else result.gyro
            self.plots[key].set_data(spectra, (0., right), state=chart_state, detail=detail)
