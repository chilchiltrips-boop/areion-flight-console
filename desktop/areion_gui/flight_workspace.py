"""Native Flight Data workspace with shared transmitter and instrument views."""
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QCheckBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QProgressBar,
    QSizePolicy, QSlider, QStackedWidget, QTabWidget, QVBoxLayout, QWidget,
)

from .combo_box import ConsoleComboBox
from .flight_dashboard import FlightDashboard
from .gps_map import GpsMapPanel
from .model import CHANNEL_NAMES, FLIGHT_MODES, NEUTRAL
from .scroll_guard import page_action_button as button
from .widgets import Joystick, label


FLIGHT_STYLE = """
QFrame#flightWorkspace {background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #f2f6ef,stop:.58 #e6efec,stop:1 #d9e8e7);
                        border:1px solid #b9cfca; border-radius:14px;}
QLabel#flightTitle {font-size:27px;font-weight:700;color:#14333c;}
QLabel#txLinkBadge {background:#313b44;color:#ffffff;border-radius:5px;padding:4px 8px;font-weight:700;font-size:11px;}
QLabel#txLinkBadge[state="green"] {background:#117239;color:#ffffff;}
QLabel#txLinkBadge[state="amber"] {background:#eb8b23;color:#251503;}
QLabel#flightSourceCaption {font-size:12px;color:#45636b;font-weight:600;}
QComboBox#flightSource {background:#fbfdfc;color:#1b424b;border:1px solid #a8c1bd;border-radius:6px;
                        padding:3px 8px;min-height:21px;}
QPushButton#sourceSave {background:#e0eeea;color:#16474c;border:1px solid #a3c3bd;padding:5px 10px;}
QPushButton#sourceSave:disabled {background:#e4ebe8;color:#667d7d;border-color:#bececa;}
QFrame#txCabinet {background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #223f49,stop:.5 #19333e,stop:1 #122b37);
                  border:1px solid #294956;border-radius:12px;}
QLabel#txTitle {font-size:19px;color:#f4f9f7;font-weight:700;}
QLabel#txIcon {background:#233e49;border:1px solid #3b5961;border-radius:8px;}
QLabel#txMuted {color:#b3c9cf;font-size:11px;}
QLabel#txAxis {color:#bfdbdd;font-size:11px;font-weight:700;letter-spacing:.8px;}
QLabel#txMode {color:#c5ebe4;font-size:11px;font-weight:700;}
QLabel#txSender {color:#c5d6d8;background:#1d3540;border:1px solid #455c66;border-radius:5px;padding:3px 5px;font-size:10px;font-weight:700;}
QLabel#txSource {color:#b5e1da;font-size:11px;font-weight:600;}
QLabel#channelValue {color:#f1f7f5;font-size:11px;font-weight:600;}
QProgressBar#channelMeter {border:0;border-radius:1px;background:#38515d;min-height:2px;max-height:2px;}
QProgressBar#channelMeter::chunk {border:0;border-radius:1px;background:#72c8b6;}
QFrame#txGimbals {background:#102530;border:1px solid #314b56;border-radius:9px;}
QPushButton#flightView {padding:4px 9px;border-radius:6px;font-size:12px;color:#dce7e7;background:#1a313c;border:1px solid #49616b;}
QPushButton#flightView:checked {background:#aee0d6;color:#143c3f;border-color:#aee0d6;}
QPushButton#flightView:hover:!checked {background:#2a4652;}
QPushButton#flightView:disabled {color:#869ca0;background:#20333b;border-color:#3b5058;}
QPushButton#txModeButton {padding:4px 7px;font-size:11px;border-radius:5px;}
QPushButton#txStart {background:#ffd368;color:#233830;border:1px solid #edb84b;border-radius:6px;padding:5px 12px;}
QPushButton#txStart:disabled {background:#4d5046;color:#c5c3a8;border-color:#626352;}
QPushButton#txArm {padding:5px 12px;background:#4b2935;border:1px solid #a45a67;color:#ffd6db;}
QPushButton#txArm:disabled {background:#263841;border-color:#42555e;color:#90a4ac;}
QTabWidget#txDetails::pane {background:#18313d;border:1px solid #3b5460;border-radius:6px;}
QTabWidget#txDetails QTabBar::tab {background:transparent;color:#adc5ca;padding:4px 8px;font-size:11px;}
QTabWidget#txDetails QTabBar::tab:selected {color:#c8eee6;border-bottom:2px solid #6ad6c8;}
QTabWidget#txDetails QCheckBox {font-size:11px;color:#c6d7da;}
QPushButton#txTool {padding:3px 7px;font-size:11px;}
QWidget#txPanel QSlider::groove:horizontal {background:#33515c;height:4px;}
QWidget#txPanel QSlider::sub-page:horizontal {background:#76cbbd;}
QWidget#txPanel QSlider::handle:horizontal {width:12px;margin:-4px 0;background:#a8ddd4;border:1px solid #19313a;}
"""


class FlightWorkspace:
    """Build the cockpit against the existing MainWindow control handlers."""

    def _flight_page(self):
        self.flight_workspace = QFrame()
        self.flight_workspace.setObjectName('flightWorkspace')
        self.flight_workspace.setStyleSheet(FLIGHT_STYLE)
        self.pages.addWidget(self.flight_workspace)
        layout = QVBoxLayout(self.flight_workspace)
        layout.setContentsMargins(14, 10, 14, 13)
        layout.setSpacing(8)
        header = QHBoxLayout()
        header.addWidget(label('Flight Data', 'flightTitle'))
        self.tx_link_badge = label('TX INACTIVE', 'txLinkBadge')
        self.tx_link_badge.setAccessibleName('PPM transmitter link')
        header.addWidget(self.tx_link_badge)
        header.addStretch()
        self.input_state = label('Active: — · Saved: —', 'flightSourceCaption')
        header.addWidget(self.input_state)
        self.source_box = ConsoleComboBox(light=True)
        self.source_box.setObjectName('flightSource')
        self.source_box.setAccessibleName('Flight input')
        for name, value in [('PPM receiver', 0), ('USB channels', 2), ('AP Wi-Fi channels', 1)]:
            self.source_box.addItem(name, value)
        header.addWidget(self.source_box)
        self.source_apply = button('Save input', self.select_source, 'sourceSave')
        header.addWidget(self.source_apply)
        layout.addLayout(header)

        instruments = QHBoxLayout()
        instruments.setSpacing(10)
        cabinet = QFrame()
        cabinet.setObjectName('txCabinet')
        cabinet_layout = QVBoxLayout(cabinet)
        cabinet_layout.setContentsMargins(9, 9, 9, 9)
        cabinet_layout.setSpacing(7)
        switch = QHBoxLayout()
        switch.setSpacing(4)
        self.tx_view_button = button('Joystick TX', lambda: self._set_flight_view(0), 'flightView')
        self.map_view_button = button('GPS map', lambda: self._set_flight_view(1), 'flightView')
        for choice in (self.tx_view_button, self.map_view_button):
            choice.setCheckable(True)
            switch.addWidget(choice)
        self.tx_view_button.setChecked(True)
        self.map_view_button.setToolTip('View the GPS map when the sender is stopped.')
        switch.addStretch()
        self.sender_label = label('SENDER OFF', 'txSender')
        switch.addWidget(self.sender_label)
        cabinet_layout.addLayout(switch)
        self.tx_stack = QStackedWidget()
        self.tx_stack.addWidget(self._transmitter_panel())
        self.gps_map = GpsMapPanel()
        self.tx_stack.addWidget(self.gps_map)
        cabinet_layout.addWidget(self.tx_stack, 1)
        instruments.addWidget(cabinet, 34)
        self.flight_dashboard = FlightDashboard()
        instruments.addWidget(self.flight_dashboard, 66)
        layout.addLayout(instruments, 1)

    def _transmitter_panel(self):
        panel = QWidget()
        panel.setObjectName('txPanel')
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        title_row = QHBoxLayout()
        title_row.setSpacing(6)
        icon = QLabel()
        icon.setObjectName('txIcon')
        icon.setFixedSize(25, 25)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setPixmap(QIcon(str(Path(__file__).parent / 'assets' / 'launch-input.svg')).pixmap(18, 18))
        title_row.addWidget(icon)
        self.tx_title = label('Virtual transmitter', 'txTitle')
        title_row.addWidget(self.tx_title)
        title_row.addStretch()
        self.tx_note = label('USB / AP input', 'txSource')
        title_row.addWidget(self.tx_note)
        layout.addLayout(title_row)

        chamber = QFrame()
        chamber.setObjectName('txGimbals')
        chamber.setMaximumHeight(315)
        chamber_box = QVBoxLayout(chamber)
        chamber_box.setContentsMargins(4, 6, 4, 5)
        chamber_box.setSpacing(2)
        poles = QHBoxLayout()
        poles.setSpacing(4)
        self.left_stick = Joystick(True)
        self.right_stick = Joystick(False)
        self.stick_captions = []
        for stick, axes in ((self.left_stick, 'THROTTLE  /  YAW'), (self.right_stick, 'PITCH  /  ROLL')):
            stick.setAccessibleName(axes)
            stick.setMinimumSize(106, 104)
            pole = QVBoxLayout()
            pole.setSpacing(0)
            pole.addWidget(label(axes, 'txAxis'), alignment=Qt.AlignmentFlag.AlignHCenter)
            pole.addWidget(stick, 1)
            caption = label('', 'txMuted')
            caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
            pole.addWidget(caption)
            self.stick_captions.append(caption)
            poles.addLayout(pole, 1)
        self.left_stick.moved.connect(lambda x, y, held: self._stick_input(True, x, y, held))
        self.right_stick.moved.connect(lambda x, y, held: self._stick_input(False, x, y, held))
        chamber_box.addLayout(poles, 1)
        self.tx_view = label('Local TX channels', 'txMuted')
        self.tx_view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.tx_view.setWordWrap(True)
        chamber_box.addWidget(self.tx_view)
        layout.addWidget(chamber, 3)

        modes = QHBoxLayout()
        modes.setSpacing(4)
        self.mode_actual = label('FC MODE: —', 'txMode')
        self.mode_actual.setWordWrap(True)
        modes.addWidget(self.mode_actual, 1)
        self.mode_buttons = {}
        for mode, name in FLIGHT_MODES.items():
            control = button(name, lambda checked=False, m=mode: self.choose_flight_mode(m), 'txModeButton')
            control.setCheckable(True)
            control.setEnabled(False)
            self.mode_buttons[mode] = control
            modes.addWidget(control)
        layout.addLayout(modes)
        actions = QHBoxLayout()
        self.start_button = button('Start sender · 50 Hz', self.start_stream, 'txStart')
        self.arm_button = button('ARM', self.arm, 'txArm')
        self.start_button.setEnabled(False)
        self.arm_button.setEnabled(False)
        actions.addWidget(self.start_button)
        actions.addWidget(self.arm_button)
        actions.addStretch()
        layout.addLayout(actions)
        self.tx_details = QTabWidget()
        self.tx_details.setObjectName('txDetails')
        self.tx_details.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.tx_details.addTab(self._all_channels_panel(), 'Channels 1–8')
        self.tx_details.addTab(self._aux_channels_panel(), 'Auxiliary')
        self.tx_details.addTab(self._controls_panel(), 'Controls')
        layout.addWidget(self.tx_details, 2)
        return panel

    def _aux_channels_panel(self):
        panel = QWidget()
        box = QVBoxLayout(panel)
        box.setContentsMargins(8, 7, 8, 7)
        box.setSpacing(5)
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(1)
        self.aux = []
        self.aux_labels = []
        for i in range(4, 8):
            value = label(f'CH{i+1}   1000', 'txMuted')
            row, column = divmod(i - 4, 2)
            grid.addWidget(value, row * 2, column)
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setAccessibleName(f'Channel {i+1}')
            slider.setRange(1000, 2000)
            slider.setSingleStep(50)
            slider.setValue(1000)
            slider.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            slider.valueChanged.connect(lambda value, c=i: self._aux(c, value))
            grid.addWidget(slider, row * 2 + 1, column)
            self.aux.append(slider)
            self.aux_labels.append(value)
        box.addLayout(grid)
        self.mode_note = label('Flight mode · Offline', 'txMuted')
        self.mode_note.setWordWrap(True)
        box.addWidget(self.mode_note)
        return panel

    def _all_channels_panel(self):
        panel = QWidget()
        grid = QGridLayout(panel)
        grid.setContentsMargins(8, 8, 8, 7)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(5)
        for column in range(2):
            grid.setColumnStretch(column, 1)
        self.channel_labels = []
        self.channel_bars = []
        self.channel_names = []
        for i, name in enumerate(CHANNEL_NAMES):
            block = QVBoxLayout()
            block.setSpacing(2)
            line = QHBoxLayout()
            line.setSpacing(3)
            name_label = label(f'CH{i+1} {name}', 'txMuted')
            line.addWidget(name_label)
            value = label('—', 'channelValue')
            value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            line.addWidget(value, 1)
            block.addLayout(line)
            bar = QProgressBar()
            bar.setRange(1000, 2000)
            bar.setTextVisible(False)
            bar.setValue(NEUTRAL[i])
            bar.setFixedHeight(2)
            bar.setObjectName('channelMeter')
            bar.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            block.addWidget(bar)
            grid.addLayout(block, i % 4, i // 4)
            self.channel_names.append(name_label)
            self.channel_labels.append(value)
            self.channel_bars.append(bar)
        self.channels_caption = label('TX command / received FC value', 'txMuted')
        grid.addWidget(self.channels_caption, 4, 0, 1, 2)
        return panel

    def _controls_panel(self):
        panel = QWidget()
        box = QVBoxLayout(panel)
        box.setContentsMargins(8, 4, 8, 4)
        box.setSpacing(3)
        keys = QHBoxLayout()
        self.keyboard = QCheckBox('Keyboard control')
        self.keyboard.setChecked(True)
        self.keyboard.toggled.connect(lambda: self._clear_keys())
        self.configure_key_button = button('Configure keys', self.configure_keys, 'txTool')
        keys.addWidget(self.keyboard)
        keys.addWidget(self.configure_key_button)
        keys.addStretch()
        box.addLayout(keys)
        self.key_hint = label('', 'txMuted')
        self.key_hint.setWordWrap(True)
        box.addWidget(self.key_hint)
        self._key_hint()
        self.pid_live_confirm = QCheckBox('Secured tripod · enable live PID tuning')
        self.pid_live_confirm.setToolTip('Allow live PID tuning on a secured tripod.')
        self.pid_live_confirm.toggled.connect(self._sync_bench_confirmation)
        box.addWidget(self.pid_live_confirm)
        self.flight_meta = label('', 'txMuted')
        self.flight_meta.setWordWrap(True)
        box.addWidget(self.flight_meta)
        return panel

    def _tx_visible(self):
        return self.tx_stack.currentIndex() == 0

    def _set_flight_view(self, index):
        """A display change never starts or stops a transmitter session."""
        if index == 1 and (self._running() or self.command_busy or self.stopping):
            self.map_view_button.setChecked(False)
            return
        if self.tx_stack.currentIndex() != index:
            self.controls.reset()
            self.left_stick.held = self.right_stick.held = False
            self.tx_stack.widget(0).setEnabled(index == 0)
            self.tx_stack.setCurrentIndex(index)
        self.tx_view_button.setChecked(self._tx_visible())
        self.map_view_button.setChecked(not self._tx_visible())
