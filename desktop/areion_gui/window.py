"""Areion desktop console. All Qt widgets and channel ticks live on the UI thread."""
from __future__ import annotations
import csv
import json
import os
import tempfile
from pathlib import Path
import threading
import time
from PySide6.QtCore import Qt, QTimer, QEvent, QStandardPaths
from PySide6.QtGui import QFont, QIcon
from shiboken6 import isValid
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QFrame, QLabel,
    QVBoxLayout, QHBoxLayout, QGridLayout, QStackedWidget, QScrollArea, QComboBox,
    QLineEdit, QSpinBox, QDoubleSpinBox, QSlider, QCheckBox, QProgressBar,
    QTableWidget, QTableWidgetItem, QHeaderView, QPlainTextEdit, QFileDialog,
    QAbstractItemView, QTabWidget, QDialog, QDialogButtonBox)
from zebjus_areion_link.schema import DRONE_GROUPS
from live_control import ControlSession, disarm_and_read
from receiver_control import get_input_status
from .combo_box import ConsoleComboBox
from . import tx_link, usb_ports
from .model import (Controls, Telemetry, PpmMonitor, NEUTRAL, CHANNEL_NAMES, KEY_CHOICES, DEFAULT_KEYS,
                    SETTINGS, field_label, FLIGHT_MODES, flight_mode_for_value, flight_mode_channel_value, matching_pid_gains)
from .backend import Jobs, open_link, read_section, require_disarmed, apply_section, save_section, apply_pid, save_input
from .widgets import Card, Metric, Joystick, Horizon, Plot, SettingsCard, label, button, TEAL, ACCENT
from .flight_workspace import FlightWorkspace
from .flight_status import flight_status
from .calibration_page import CalibrationPage
from .console_layout import ConsoleLayout, CHROME_STYLE
from .wizard_extended import ExtendedSetupWizard as SetupWizard
from .setup_backend import run_setup_action
from .restart_check import load_receipt, make_receipt, save_receipt, verify_restart
from .scroll_guard import install_scroll_guard, remove_scroll_guard, focus_page, page_action_button as button

STYLE = '''
QMainWindow, QWidget#base {background:#0b111b;color:#e5edf7;}
QWidget {color:#e5edf7;font-family:"Inter","Segoe UI","Arial";font-size:13px;}
QWidget#sidebar {background:#101927;border-right:1px solid #263346;}
QFrame#card {background:#141f2e;border:1px solid #26364a;border-radius:14px;}
QLabel {background:transparent;}
QLabel#title {font-size:30px;font-weight:700;color:#f5f7fa;}
QLabel#cardTitle {font-size:16px;font-weight:600;}
QLabel#brand {font-size:24px;font-weight:800;letter-spacing:4px;}
QLabel#eyebrow {font-size:10px;letter-spacing:1px;color:#8da1b8;font-weight:600;}
QLabel#muted {color:#8da1b8;font-size:12px;}
QLabel#metric {font-size:23px;font-weight:600;color:#eaf3ff;}
QLabel#pill {background:#203146;border:1px solid #3b526d;border-radius:12px;padding:6px 12px;color:#c3d7ed;font-weight:600;}
QLabel#notice {background:#17263a;border:1px solid #284463;border-radius:9px;padding:10px;color:#b8d5f3;}
QPushButton {background:#223247;border:1px solid #3a4d64;border-radius:8px;padding:6px 12px;font-weight:600;}
QPushButton:hover {background:#2d425b;border-color:#758ba3;}
QPushButton:pressed {background:#122236;}
QPushButton:checked {background:#294c4b;border-color:#5cddc2;color:#baf7e9;}
QPushButton:disabled {color:#60728a;background:#172230;border-color:#223145;}
QPushButton#primary {background:#ffad66;color:#151a22;border-color:#ffad66;}
QPushButton#primary:hover {background:#ffc28d;}
QPushButton#primary:disabled {background:#554232;color:#a48d77;border-color:#554232;}
QPushButton#danger {background:#49232d;color:#ffb7bd;border-color:#934956;}
QPushButton#danger:hover {background:#70313c;}
QPushButton#nav {text-align:left;background:transparent;border:0;padding:15px 16px;color:#97abc1;}
QPushButton#nav:checked {background:#22364a;color:#ffe0c2;border-left:3px solid #ffad66;border-radius:5px;}
QLineEdit,QComboBox,QSpinBox,QDoubleSpinBox {background:#0e1826;border:1px solid #34465d;border-radius:7px;padding:7px;selection-background-color:#385778;min-height:20px;}
QLineEdit:focus,QComboBox:focus,QSpinBox:focus,QDoubleSpinBox:focus {border-color:#ffad66;}
QComboBox QAbstractItemView {background:#17283b;selection-background-color:#365473;color:#e5edf7;}
QComboBox::drop-down {border:0;width:20px;}
QSpinBox::up-button,QDoubleSpinBox::up-button {width:16px;border:0;background:#263c53;}
QSpinBox::down-button,QDoubleSpinBox::down-button {width:16px;border:0;background:#21344b;}
QAbstractSpinBox QLineEdit {background:transparent;border:0;padding:0;min-height:0;}
QSpinBox:disabled,QDoubleSpinBox:disabled {color:#687d96;border-color:#28364a;}
QSlider::groove:horizontal {background:#304258;height:5px;border-radius:2px;}
QSlider::sub-page:horizontal {background:#f3a361;border-radius:2px;}
QSlider::handle:horizontal {background:#f6d3ad;border:2px solid #1b293a;width:17px;margin:-7px 0;border-radius:8px;}
QCheckBox {spacing:8px;color:#c4d2e3;}
QCheckBox::indicator {width:16px;height:16px;border:1px solid #637b96;border-radius:4px;background:#0e1826;}
QCheckBox::indicator:checked {background:#ffad66;border-color:#ffad66;}
QProgressBar {background:#0c1522;border:0;border-radius:4px;text-align:right;color:#b7c9dc;min-height:9px;max-height:9px;}
QProgressBar::chunk {background:#5cddc2;border-radius:4px;}
QScrollArea {border:0;background:transparent;}
QScrollBar:vertical {background:#101a28;width:7px;}
QScrollBar::handle:vertical {background:#384c64;border-radius:3px;min-height:30px;}
QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical {height:0;}
QTabWidget::pane {border:1px solid #2a3e55;border-radius:8px;background:#141f2e;}
QTabBar::tab {background:#162334;color:#8da1b8;padding:7px 12px;}
QTabBar::tab:selected {background:#263d52;color:#ffcc9d;}
QTableWidget {background:#111c2b;alternate-background-color:#162334;border:1px solid #293b51;gridline-color:#24364a;selection-background-color:#294760;}
QHeaderView::section {background:#1b2c40;color:#9db2c9;border:0;padding:9px;text-align:left;}
QPlainTextEdit {background:#0d1725;border:1px solid #2c4058;border-radius:8px;color:#a7bdd6;font-family:"DejaVu Sans Mono","Menlo";font-size:11px;}
QDialog {background:#101b2a;}
QToolTip {background:#23374f;color:#f0f4f8;border:1px solid #536e8c;padding:6px;}
'''

class MainWindow(ConsoleLayout,FlightWorkspace,QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('AREION · Flight Console 3.12.3')
        self.setWindowIcon(QIcon(str(Path(__file__).parent / 'assets' / 'areion-mark.png')))
        self.resize(1380, 930);self.setMinimumSize(900, 700)
        self.link=None;self.session=None;self.data=Telemetry();self.controls=Controls()
        self.ppm_monitor=PpmMonitor()
        self.jobs=Jobs();self.jobs.finished.connect(self._job_finished);self.callbacks={};self.job_number=0
        self.connect_cancel=threading.Event();self.connecting=False
        self._connection_lost=False;self._last_close_context=None
        self.generation=0;self.command_busy=False;self.stopping=False
        self.closing=False;self.close_ready=False;self.last_tick=time.monotonic();self.last_render=0;self.last_control_render=0
        self._close_timer=None
        self.cards={};self.nav=[];self.table_rows=[];self.last_notice='Ready'
        self._setup_wizard=None;self._wizard_ports=[];self._setup_guard=False
        self._maintenance={};self._calibration_guard=False
        self._pid_pending_cards={}
        self._pid_unverified={}
        self.config_path=Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation))/'controls.json'
        self._tx_link_cache_key = None
        self._tx_link_profile = None
        self._usb_pref_path = self.config_path.with_name('usb_port.json')
        self._preferred_usb_port = usb_ports.load_preference(self._usb_pref_path)
        self._usb_user_choice = False
        self._usb_scan = None
        self._usb_scan_error = None
        self._usb_scanned = False
        self._usb_open_pickers = set()
        self._usb_popup_observer = usb_ports.PopupCloseObserver(self, self._settle_usb_pickers)
        self._pending_usb_preference = None
        self._restart_path = self.config_path.with_name('last_verified_setup.json')
        self._restart_receipt = load_receipt(self._restart_path)
        self._restart_job = None
        self._restart_attempt = None
        try:
            self.controls.set_bindings(json.loads(self.config_path.read_text())['keys'])
        except (OSError, ValueError, KeyError, TypeError):
            pass
        self._build()
        assets=Path(__file__).parent/'assets'
        extra=f'QComboBox::down-arrow,QSpinBox::down-arrow,QDoubleSpinBox::down-arrow {{image:url("{(assets/"down.svg").as_posix()}");width:12px;height:8px;}} QSpinBox::up-arrow,QDoubleSpinBox::up-arrow {{image:url("{(assets/"up.svg").as_posix()}");width:12px;height:8px;}}'
        self.setStyleSheet(STYLE+CHROME_STYLE+extra)
        self.timer=QTimer(self);self.timer.setTimerType(Qt.TimerType.PreciseTimer);self.timer.setInterval(5)
        self.timer.timeout.connect(self.tick);self.timer.start()
        QApplication.instance().installEventFilter(self)
        install_scroll_guard(self)
        QApplication.instance().applicationStateChanged.connect(self._application_state)
        usb_ports.set_selection(self.port, self._preferred_usb_port)
        self._watch_port_picker(self.port)
        self._sync_endpoint()
        self._port_scan_poll = QTimer(self, interval=80)
        self._port_scan_poll.timeout.connect(self._finish_port_scan)
        self.port_scan_timer = QTimer(self, interval=2000)
        self.port_scan_timer.timeout.connect(self.refresh_ports)
        self.port_scan_timer.start()
        self.refresh_ports()

    def _build(self):
        self._build_console()

    def page(self,title,subtitle):
        inner=QWidget();inner.setObjectName('base');layout=QVBoxLayout(inner);layout.setContentsMargins(0,0,8,8);layout.setSpacing(10)
        layout.addWidget(label(title,'title'))
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(inner);self.pages.addWidget(scroll)
        return layout

    def showEvent(self,event):
        install_scroll_guard(self)
        super().showEvent(event)

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self,'imu_grid'):
            columns=5 if self.width()>=1300 else 3
            for i,metric in enumerate(self.imu_metrics):self.imu_grid.addWidget(metric,i//columns,i%columns)

    def _aux(self,channel,value):
        if self._tx_visible() and not self._ppm_selected():self.controls.values[channel]=value

    def _ppm_selected(self):
        inputs=self.data.values(122)
        return bool(inputs and inputs[0]==0)

    def _stick_input(self,left,x,y,held):
        if self._tx_visible() and not self._ppm_selected():self.controls.stick(left,x,y,held)

    def _render_transmitter(self,now):
        connected=self._connected()
        ppm,received,note=self.ppm_monitor.view(self.data,connected,now)
        values=received if ppm else self.controls.values
        actual=self.data.values(22,.5,now) if connected else None
        settings=self.data.values(7);mode_channel=settings[0] if settings else 5
        self.tx_title.setText('Receiver monitor' if ppm else 'Virtual transmitter')
        inputs = self.data.values(122, .5, now) if connected else None
        source_note = 'Awaiting input' if connected else 'Offline'
        if inputs:
            source_note = {0: 'PPM input', 1: 'AP input', 2: 'USB input'}.get(inputs[0], source_note)
        self.tx_note.setText(source_note)
        self.tx_view.setText(note.split(' · ', 1)[0] if ppm else 'Local TX channels')
        self.tx_view.setToolTip(note if ppm else 'Local channel commands. Compare with the FC readback below.')
        self.channels_caption.setText('Received PPM channels · µs' if ppm else 'TX command / received FC value')
        self.keyboard.setEnabled(not ppm);self.configure_key_button.setEnabled(not ppm);self.key_hint.setVisible(not ppm)
        if ppm:
            self.controls.pressed.clear();self.controls.mouse_left=self.controls.mouse_right=False
        for stick,caption,left in zip((self.left_stick,self.right_stick),self.stick_captions,(True,False)):
            stick.setEnabled(not ppm)
            if ppm:stick.held=False
            stick.setCursor(Qt.CursorShape.ArrowCursor if ppm else Qt.CursorShape.CrossCursor)
            stick.setToolTip('Live receiver display; use the physical transmitter.' if ppm else
                             ('Drag to control. Throttle holds; yaw returns to center.' if left else 'Drag to control. Both axes return to center on release.'))
            if ppm:
                a, b = (2, 3) if left else (1, 0)
                caption.setText(f'{values[a]} / {values[b]} µs' if values else '— / — µs')
            else:
                caption.setText('Throttle holds' if left else 'Spring return')
        if values is None:
            self.left_stick.sync(None,None);self.right_stick.sync(None,None)
        else:
            self.left_stick.sync((values[3]-1500)/500,(values[2]-1500)/500)
            self.right_stick.sync((values[0]-1500)/500,(values[1]-1500)/500)
        for i in range(8):
            value=values[i] if values else None
            name = ('Roll', 'Pitch', 'Thr', 'Yaw')[i] if i < 4 else ('Mode' if i+1==mode_channel else 'Aux')
            self.channel_names[i].setText(f'{i+1} · {name}')
            self.channel_names[i].setToolTip(f'CH{i+1} {CHANNEL_NAMES[i]}'+(' · Flight mode' if i+1==mode_channel else ''))
            self.channel_labels[i].setText(('—' if value is None else str(value)) if ppm else f'{value} / {actual[i] if actual else "—"}')
            self.channel_bars[i].setEnabled(value is not None)
            self.channel_bars[i].setValue(value if value is not None else 1000)
        for i,(slider,lbl) in enumerate(zip(self.aux,self.aux_labels),4):
            value=values[i] if values else None
            slider.setEnabled(not ppm);slider.setVisible(value is not None)
            slider.blockSignals(True);slider.setValue(value if value is not None else 1000);slider.blockSignals(False)
            lbl.setText(f'CH{i+1}   '+('—' if value is None else str(value)))

    def choose_flight_mode(self,mode):
        now=time.monotonic();inputs=self.data.values(122,.5,now);settings=self.data.values(7)
        if not (self._tx_visible() and self._connected() and self.session and self.session.running and self.session.ready
                and inputs and self.data.values(120,.5,now) and inputs[0] in (1,2) and inputs[4] and settings
                and not self.command_busy and not self.stopping):
            self.log('Start USB/AP channels and wait for input readiness before choosing a mode.');return
        channel=settings[0]-1
        if channel<4:
            self.log('Choose an AUX channel CH5–CH8 in Settings for the USB/AP mode switch. CH1–CH4 are stick axes.');return
        self.controls.values[channel]=flight_mode_channel_value(settings,mode)
        self.log(f'{FLIGHT_MODES[mode]} requested on CH{channel+1}; FC MODE shows the received controller state.')
        self.render_status(now)

    def _imu_page(self):
        box=self.page('IMU readings & calibration','Corrected acceleration, angular rates and attitude from the kit.')
        row=QHBoxLayout();attitude=Card('Attitude','Roll / pitch · relative yaw');self.horizon=Horizon();self.horizon.setMinimumHeight(240);attitude.box.addWidget(self.horizon,1)
        attitude.box.addWidget(button('Reset relative yaw',self.horizon.reset_yaw))
        self.imu_fresh=label('Waiting for IMU','muted');attitude.box.addWidget(self.imu_fresh);row.addWidget(attitude,2)
        metrics=QGridLayout();self.imu_grid=metrics;self.imu_metrics=[]
        names=[('Rate roll','°/s'),('Rate pitch','°/s'),('Rate yaw','°/s'),('Acc X','g'),('Acc Y','g'),('Acc Z','g'),('Angle roll','°'),('Angle pitch','°'),('Kalman roll','°'),('Kalman pitch','°')]
        for i,(name,unit) in enumerate(names):
            metric=Metric(name,unit);metrics.addWidget(metric,i//5,i%5);self.imu_metrics.append(metric)
        row.addLayout(metrics,5);box.addLayout(row)
        self.add_settings(box,6,'Accelerometer offsets','')
        tabs=QTabWidget();self.imu_plots=[]
        for title,indices in [('Acceleration',(3,4,5)),('Angles',(6,7)),('Kalman',(8,9)),('Angular rates',(0,1,2))]:
            plot=Plot(title+' · last 15 seconds');tabs.addTab(plot,title);self.imu_plots.append((plot,indices))
        box.addWidget(tabs)
        box.addStretch()
        live=self.pages.widget(1);self.pages.removeWidget(live)
        self.imu_tabs=QTabWidget();self.imu_tabs.addTab(live,'Readings')
        self.imu_calibration_placeholder=QWidget();self.imu_tabs.addTab(self.imu_calibration_placeholder,'Calibration')
        self.imu_tabs.currentChanged.connect(self._imu_tab_changed)
        self.pages.insertWidget(1,self.imu_tabs)

    def add_settings(self,layout,group,title,subtitle=''):
        card=SettingsCard(group,title,subtitle,persist_on_apply=group in (2,3));card.requested.connect(self.settings_request);self.cards[group]=card;layout.addWidget(card)
        return card

    def _settings_page(self):
        from .pid_workspace import PidWorkspace
        self.pid_workspace = PidWorkspace()
        page = QScrollArea()
        page.setFrameShape(QFrame.Shape.NoFrame)
        page.setWidgetResizable(True)
        page.setWidget(self.pid_workspace)
        self.pages.addWidget(page)
        self.pid_bench_confirm = self.pid_workspace.bench
        self.pid_bench_confirm.toggled.connect(self._sync_bench_confirmation)
        self.pid_state = self.pid_workspace.pid_state
        self.device_label = self.pid_workspace.board
        for group, card in self.pid_workspace.cards.items():
            card.requested.connect(self.settings_request)
            self.cards[group] = card

    def _live_page(self):
        box=self.page('System','Live values, packet ages and the session log. Time-series charts are available in Scopes.')
        row=QHBoxLayout()
        row.addStretch();row.addWidget(button('Export CSV',self.export_csv));row.addWidget(button('Copy diagnostics',self.copy_diagnostics));box.addLayout(row)
        self.live_tabs=QTabWidget();self.table=QTableWidget();self.table.setColumnCount(5);self.table.setHorizontalHeaderLabels(['Section','Field','Value','Age','State'])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);self.table.setAlternatingRowColors(True);self.table.verticalHeader().hide()
        for group in DRONE_GROUPS:
            if group in (9,123):continue
            for field in DRONE_GROUPS[group]['fields']:self.table_rows.append((group,field['index'],field['name']))
        self.table.setRowCount(len(self.table_rows));self.table.setMinimumHeight(330)
        for r,(group,index,name) in enumerate(self.table_rows):
            for c,value in enumerate([f'{group} · '+DRONE_GROUPS[group]['name'],field_label(name),'—','—','WAITING']):self.table.setItem(r,c,QTableWidgetItem(value))
        # ResizeToContents rescans every row after every streaming cell edit.
        # Stable user-adjustable widths avoid a repeated full-table layout on
        # macOS while preserving selection and the user's scroll position.
        header=self.table.horizontalHeader();header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for column,width in enumerate((200,280,140,80,135)):self.table.setColumnWidth(column,width)
        header.setSectionResizeMode(1,QHeaderView.ResizeMode.Stretch)
        self.table.setWordWrap(False);self.table.verticalHeader().setDefaultSectionSize(28)
        self._live_cells={}
        self.live_tabs.addTab(self.table,'All values');self.log_view=QPlainTextEdit();self.log_view.setReadOnly(True);self.log_view.setMaximumBlockCount(500);self.live_tabs.addTab(self.log_view,'Event log');box.addWidget(self.live_tabs,1)
        self.live_tabs.currentChanged.connect(lambda:self._render_live_data(time.monotonic(),self._connected()))

    def navigate(self,index,initial=False):
        if index is None or not 0<=index<self.pages.count():return
        tuning_route=(self.pid_live_confirm.isChecked() and
                      self.pages.currentIndex() in (0,2) and index in (0,2))
        if not initial and index!=self.pages.currentIndex() and (self._running() or (self.command_busy and not (self._setup_guard or self._calibration_guard or self._calibration_read_pending()))):
            if not tuning_route:self.stop('Page changed; transmitter stopped')
            else:
                self._clear_keys();self.controls.mouse_left=self.controls.mouse_right=False
                self.left_stick.held=self.right_stick.held=False
                self.log('Secured PID tuning · sender continues; throttle holds. DISARM / STOP remains available.')
        leaving_restart = index != 5 and self._viewing_restart()
        if index != 5 and self.pages.currentIndex() == 5:
            self._restart_job = None
            self._restart_attempt = None
        if index==5 and not self.setup_wizard.restart_view_active:
            self._setup_guard=True
            self.setup_wizard.on_enter(self._connection_options())
        if index==6:
            panel=self.calibration_page('esc');panel.on_enter(self._connection_options())
        if index==11:
            panel=self.calibration_page('receiver');panel.on_enter(self._connection_options())
        self.controls.pressed.clear()
        if index == 8:
            self.pages.setCurrentWidget(self.scopes_page)
        else:
            self.pages.setCurrentIndex(index)
        if leaving_restart:
            self._setup_wizard.restart_view_active = False
        if index==1 and self.imu_tabs.currentIndex()==1:self._imu_tab_changed(1)
        if index==6:self._update_calibration_connection(self._maintenance['esc'],time.monotonic())
        if index==11:self._update_calibration_connection(self._maintenance['receiver'],time.monotonic())
        focus_page(self.pages.currentWidget())
        if index==5:
            self._update_wizard_connection(time.monotonic())
        self._sync_navigation(index)
        if index == 0:
            self._refresh_flight_instruments(time.monotonic(), self._connected())
        if index in (2,4,8):self._render_live_data(time.monotonic(),self._connected())

    @property
    def setup_wizard(self):
        # Build the additional form/diagram widgets only when first opened.
        # Opening the transmitter keeps its original startup/layout workload.
        if self._setup_wizard is None:
            wizard=SetupWizard(self.config_path.with_name('setup_wizard.json'))
            wizard.use_shared_chrome()
            wizard.connect_requested.connect(self._wizard_connect)
            wizard.disconnect_requested.connect(self.disconnect)
            wizard.refresh_ports_requested.connect(self.refresh_ports)
            wizard.saved.connect(lambda path:self.log('Setup backup saved: '+path+' · FC status determines ARM permission.'))
            wizard.action_requested.connect(self._wizard_action)
            wizard.restart_check_requested.connect(self._verify_last_setup)
            wizard.finish_requested.connect(lambda: self.navigate(7))
            if self._restart_receipt:
                wizard.set_restart_context(self._restart_receipt, False, None, None, False)
            self._register_port_picker(wizard.port)
            self.pages.removeWidget(self.wizard_placeholder);self.wizard_placeholder.deleteLater()
            self.pages.insertWidget(5,wizard);self._setup_wizard=wizard
        return self._setup_wizard

    def calibration_page(self,scope):
        if scope not in self._maintenance:
            panel=CalibrationPage(self.config_path.with_name(scope+'_calibration.json'),scope)
            panel.connection_card.hide()
            self._maintenance[scope]=panel
            panel.connect_requested.connect(self._calibration_connect)
            panel.disconnect_requested.connect(self.disconnect)
            panel.refresh_ports_requested.connect(self.refresh_ports)
            panel.action_requested.connect(lambda action,payload,p=panel:self._configuration_action(p,action,payload))
            panel.saved.connect(lambda path:self.log('Calibration backup saved: '+path))
            self._register_port_picker(panel.port)
            if scope=='imu':
                self.imu_tabs.blockSignals(True)
                self.imu_tabs.removeTab(1);self.imu_calibration_placeholder.deleteLater()
                self.imu_tabs.insertTab(1,panel,'Calibration');self.imu_tabs.setCurrentIndex(1)
                self.imu_tabs.blockSignals(False)
            elif scope=='esc':
                self.pages.removeWidget(self.esc_placeholder);self.esc_placeholder.deleteLater()
                self.pages.insertWidget(6,panel)
            else:
                self.pages.removeWidget(self.receiver_placeholder);self.receiver_placeholder.deleteLater()
                self.pages.insertWidget(11,panel)
        return self._maintenance[scope]

    def _imu_tab_changed(self,index):
        if index!=1:return
        panel=self.calibration_page('imu');panel.on_enter(self._connection_options())
        self._update_calibration_connection(panel,time.monotonic())

    def _calibration_connect(self,options):
        if self.connecting:return
        self.transport.setCurrentText(options['mode']);self.select_usb_port(options['port'])
        self.baud.setValue(options['baud']);self.wait.setValue(options['startup_wait'])
        self.host.setText(options['host']);self.udp_port.setValue(options['udp_port']);self.ssid.setText(options['ssid'])
        self.connect_fc()

    def _calibration_read_pending(self):
        # A status read before Begin/Resume is read-only. Losing focus during
        # that read must not send DISARM and consume a saved ESC request.
        return any(panel.operation_busy and panel.pending and panel.pending[0]=='read'
                   for panel in self._maintenance.values())

    def _update_calibration_connection(self,panel,now):
        connected=self._connected();status=self.data.values(120,.5,now) if connected else None
        panel.set_connection_state(connected=connected,connecting=self.connecting,
            has_link=bool(self.link),demo=bool(self.link and getattr(self.link,'demo',False)),
            disarmed=bool(status is not None and not status[0]),
            busy=self._running() or self.command_busy or self.stopping,
            paths=self.link.transport_status if self.link else [],detail=self.last_notice)
        values={g:self.data.values(g,.5 if g in (21,120,122,130,131) else None,now)
                for g in (2,3,4,6,7,112,21,120,122,125,130,131,132,134)} if connected else {}
        values['_raw_stamp']=self.data.latest.get(131,(None,None))[1] if connected else None
        panel.receive_telemetry(values,self.data.latest.get(21,(None,None))[1] if connected else None,
            now,(id(self.link),self.link.fc_session) if self.link else None)

    def _connection_options(self):
        return {'mode':self.transport.currentText(),'port':self.port.currentText().strip(),
                'baud':self.baud.value(),'startup_wait':self.wait.value(),'host':self.host.text().strip(),
                'udp_port':self.udp_port.value(),'ssid':self.ssid.text().strip()}

    def _wizard_connect(self,options):
        if self.connecting:return
        self.transport.setCurrentText(options['mode']);self.select_usb_port(options['port'])
        self.baud.setValue(options['baud']);self.wait.setValue(options['startup_wait'])
        self.host.setText(options['host']);self.udp_port.setValue(options['udp_port']);self.ssid.setText(options['ssid'])
        self.connect_fc()
        self._update_wizard_connection(time.monotonic())

    def _viewing_restart(self):
        return bool(self._setup_wizard is not None and self._setup_wizard.restart_view_active
                    and self.pages.currentIndex() == 5)

    def open_restart_check(self):
        if self._restart_receipt is None:
            self.log('Finish and verify setup first.')
            return
        setup = self.data.values(130, .5) if self._connected() else None
        if (self._setup_guard or self._calibration_guard or self._running()
                or self.command_busy or self.stopping or (setup and setup[8])):
            self.log('Finish the active setup, calibration or transmitter operation first.')
            return
        wizard = self.setup_wizard
        self._restart_attempt = None
        if wizard.show_restart_check():
            self.navigate(5)

    def _verify_last_setup(self):
        receipt = self._restart_receipt
        if (not self._viewing_restart() or not receipt or self._restart_job is not None
                or self.command_busy or self.stopping or self._running() or not self._connected()):
            return
        wizard = self._setup_wizard
        link = self.link
        boot = link.fc_session
        generation = self.generation
        job = self._restart_job = object()
        self._restart_attempt = (id(link), boot)
        def cancelled():
            return (self.closing or self.generation != generation or self.link is not link
                    or link.fc_session != boot or self._restart_job is not job)
        def work():
            return verify_restart(link, receipt, cancelled)
        def done(result, error):
            if self._restart_job is not job:
                return
            # Back can briefly return to the completed review while this read is in flight.
            current = not cancelled() and self._connected() and self._restart_receipt is receipt
            self._restart_job = None
            if current:
                wizard.set_restart_result({'state': 'error', 'message': str(error), 'changes': []}
                                          if error else result)
        wizard.set_restart_result({'state': 'reading', 'message': 'Reading kit settings…', 'changes': []})
        self._submit(work, done)

    def _record_restart_receipt(self, result, state, boot):
        self._restart_receipt = None
        self._restart_attempt = None
        try:
            receipt = make_receipt(state, boot, result.get('verified_settings'), result.get('demo'))
        except (TypeError, ValueError, KeyError) as error:
            self._discard_stale_restart_file()
            self.log('Kit saved. Restart verification unavailable: ' + str(error))
            return
        self._restart_receipt = receipt
        try:
            save_receipt(self._restart_path, receipt)
        except (OSError, TypeError, ValueError) as error:
            self._discard_stale_restart_file()
            self.log('Kit saved. Restart receipt available for this desktop session only: ' + str(error))

    def _discard_stale_restart_file(self):
        try:
            self._restart_path.unlink(missing_ok=True)
        except OSError as error:
            self.log('Last receipt on disk belongs to an earlier save: ' + str(error))

    def _update_wizard_connection(self,now):
        connected=self._connected()
        status=self.data.values(120,.5,now) if connected else None
        self.setup_wizard.set_connection_state(connected=connected,connecting=self.connecting,
            has_link=bool(self.link),demo=bool(self.link and getattr(self.link,'demo',False)),
            disarmed=bool(status is not None and not status[0]),
            busy=self._running() or self.command_busy or self.stopping,
            paths=self.link.transport_status if self.link else [],detail=self.last_notice)
        wizard = self.setup_wizard
        if self._restart_receipt or wizard.restart_view_active:
            setup = self.data.values(130, .5, now) if connected else None
            kit_id = setup[15] if setup else None
            boot = self.link.fc_session if connected else None
            busy = self.command_busy or self.stopping or self._running()
            wizard.set_restart_context(self._restart_receipt, connected, boot, kit_id, busy)
            if wizard.restart_view_active:
                if (self._viewing_restart() and self._restart_receipt and kit_id == self._restart_receipt['kit_id']
                        and boot and boot != self._restart_receipt['fc_session'] and not busy
                        and self._restart_attempt != (id(self.link), boot)):
                    self._verify_last_setup()
                return
        values={g:self.data.values(g,.5 if g in (21,120,122,130,131) else None,now)
                for g in (2,3,4,6,7,112,21,120,122,125,130,131,132,134)} if connected else {}
        values['_raw_stamp']=self.data.latest.get(131,(None,None))[1] if connected else None
        stamp=self.data.latest.get(21,(None,None))[1] if connected else None
        self.setup_wizard.receive_telemetry(values,stamp,now,
            (id(self.link),self.link.fc_session) if self.link else None)
        # The lock obligation survives leaving the page, including entering
        # offline and connecting later. Do not wait for a visible-widget timer.
        wizard=self.setup_wizard
        if (self._setup_guard and not self.closing and connected
                and not wizard.begin_requested and not wizard.operation_busy
                and not self.command_busy and not self.stopping and not self._running()):
            wizard.begin_requested=True
            wizard._request('begin',{'props_removed':wizard.propeller_check.isChecked()})

    def _wizard_action(self,action,payload):
        self._configuration_action(self.setup_wizard,action,payload)

    def _configuration_action(self,wizard,action,payload):
        link=self.link
        if isinstance(wizard,CalibrationPage) and action=='begin':
            self._calibration_guard=True;self._setup_guard=False
        urgent=action=='command' and payload.get('command') in ('STOP','MOTOR_STOP')
        heartbeat=action=='command' and payload.get('command')=='MOTOR_SET'
        if heartbeat and self.command_busy:return
        if not self._connected() or ((self.command_busy or self.stopping or self._running()) and not urgent):
            wizard.action_finished(None,RuntimeError('Connect and stop the sender before setup actions.'));return
        if urgent:
            self.generation+=1
            if self.session:self.session.stop()
            # A stop cancels the outstanding setup transaction and its chained
            # verification. Its ACK must never complete a different request.
            wizard.pending=None;wizard.after_action=None;wizard.operation_busy=False
        pending=wizard.pending
        token=self.generation;self.command_busy=True;fc_session=link.fc_session
        def cancelled():return self.closing or self.link is not link or self.generation!=token or link.fc_session!=fc_session
        def work():return run_setup_action(link,action,payload,cancelled)
        def done(result,error):
            if self.generation==token:self.command_busy=False
            if cancelled():
                if self.link is not link or self.closing:return
                if heartbeat or wizard.pending is pending:
                    wizard.action_finished({'action':'command','command':'MOTOR_SET','values':{}} if heartbeat else None,
                        RuntimeError('Connection or control state changed. Re-read the FC to verify any partial write.'))
                return
            if not heartbeat and wizard.pending is not pending:return
            if not error:
                result['fc_session']=link.fc_session
                for group,values in result.get('values',{}).items():
                    self.data.put(group,DRONE_GROUPS[group]['schema'],values,received=False)
                    if group in self.cards:self.cards[group].loaded=False
                if 110 in result.get('values',{}):self._select_source_value(result['values'][110][0])
                state=result.get('values',{}).get(130)
                if action=='finalize' and result.get('complete') and state and state[1] and not state[0]:
                    self._setup_guard=False;self._calibration_guard=False
                    if wizard is self._setup_wizard:
                        self._record_restart_receipt(result, state, fc_session)
                        wizard.set_restart_context(self._restart_receipt, True, fc_session, state[15], False)
            wizard.action_finished({'action':'command','command':'MOTOR_SET','values':{}} if heartbeat and error else result,error)
            if error or not heartbeat:
                context='Calibration' if isinstance(wizard,CalibrationPage) else 'Setup'
                self.log(context+' action failed: '+str(error) if error else context+' '+action+': '+('completed' if result.get('complete',True) else 'partial failure; see status'))
        self._submit(work,done,0 if urgent else 10)

    def _setup_arm_allowed(self,now=None):
        now=time.monotonic() if now is None else now
        state=self.data.values(130,.5,now)
        return bool(state and state[1] and not state[0] and not self._setup_guard and not self._calibration_guard and self.pages.currentIndex()!=5)

    def _scheduled_esc_disconnect(self):
        # Retain the last observed locked calibration across the expected
        # power-off gap. Sending DISARM to a recovered board would cancel its
        # durable one-shot request. Freshness is shown separately in the UI.
        context=self._close_context()
        state=context['setup'];status=context['status']
        return bool(state and status and not status[0] and state[0] and not state[1]
                    and state[3] in (1,2,3,4,5) and not state[8])

    def _close_context(self):
        previous=self._last_close_context or {}
        return {'read_only':self._viewing_restart() and not self._running(),
                'setup':self.data.values(130) or previous.get('setup'),
                'status':self.data.values(120) or previous.get('status'),
                'input':self.data.values(122) or previous.get('input')}

    def _cancel_local_connection_work(self,reason):
        self._pending_usb_preference = None
        self.generation+=1;self.command_busy=False;self.stopping=False
        self._restart_job = None
        self._restart_attempt = None
        self._calibration_guard=False
        for panel in self._maintenance.values():panel.connection_lost(reason)
        self.pid_live_confirm.blockSignals(True);self.pid_live_confirm.setChecked(False);self.pid_live_confirm.blockSignals(False)
        self.pid_bench_confirm.blockSignals(True);self.pid_bench_confirm.setChecked(False);self.pid_bench_confirm.blockSignals(False)
        self._pid_pending_cards.clear()
        self._pid_unverified.clear()
        if self.session:self.session.stop()
        self.controls.reset();self.left_stick.held=self.right_stick.held=False
        if self._setup_wizard is not None:
            wizard=self._setup_wizard
            wizard.connection_lost(reason)
            # A suspended capture/test is not automatically resumed. A new
            # connection must read the firmware before enabling any action.
            wizard.begin_requested=False;wizard.begin_confirmed=False

    def _clear_connection_telemetry(self):
        now = time.monotonic()
        self.gps_map.set_link(None, now)
        self.data=Telemetry();self.ppm_monitor=PpmMonitor()
        self._refresh_flight_instruments(now, False)
        for card in self.cards.values():
            card.busy=False;card.allowed=False;card.loaded=False;card.active=None;card.refresh()

    @staticmethod
    def _close_link(link,context,preserve_esc):
        warning=None
        try:
            if link.connected and not context.get('read_only'):
                state=context.get('setup');inputs=context.get('input')
                if state and state[8]:
                    # Stop a bench test independently of flight-input choice.
                    link.action(135,['MOTOR_STOP',0,0,0,0],schema=1)
                if inputs and inputs[0] in (1,2) and not preserve_esc:link.disarm()
        except Exception as error:
            warning='Previous connection stop unconfirmed: '+str(error)
        finally:
            link.close()
        return warning

    def _connection_became_stale(self):
        if self._connection_lost:return
        self._connection_lost=True;self._last_close_context=self._close_context()
        self._cancel_local_connection_work('Connection lost')
        self._clear_connection_telemetry()
        self.connection_detail.setText('OFFLINE / STALE')
        self.log('Connection lost. Reconnect using USB or AP; saved kit settings are retained. Controls and motor tests will not resume automatically.')

    def _running(self):
        return bool(self.session and self.session.running)

    def _connected(self):
        # A late reply cannot revive a session after the UI has discarded its
        # telemetry and canceled local work. Only an explicit reconnect does.
        return bool(self.link and not self._connection_lost and self.link.connected)

    def log(self,text):
        self.last_notice=str(text);self.notice.setText(self.last_notice)
        self.log_view.appendPlainText(time.strftime('%H:%M:%S')+'  '+str(text))

    def _submit(self,function,callback,priority=10):
        self.job_number+=1;tag=str(self.job_number);self.callbacks[tag]=callback;self.jobs.submit(tag,function,priority)

    def _job_finished(self,tag,result,error):
        callback=self.callbacks.pop(tag,None)
        if callback:callback(result,error)

    def _linked(self,function,callback,priority=10):
        link=self.link
        def work():
            if self.link is not link or not self._connected():raise RuntimeError('FC connection is unavailable')
            return function(link)
        def done(result,error):
            if self.link is link and not self._connection_lost:callback(result,error)
        self._submit(work,done,priority)

    def _port_pickers(self):
        yield self.port
        if self._setup_wizard is not None:
            yield self._setup_wizard.port
        for panel in self._maintenance.values():
            yield panel.port

    def _watch_port_picker(self, picker):
        picker.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        picker.view().installEventFilter(self._usb_popup_observer)
        picker.currentTextChanged.connect(self.select_usb_port)
        # Selecting the already highlighted choice is an explicit selection too.
        picker.textActivated.connect(self.select_usb_port)

    def _register_port_picker(self, picker):
        usb_ports.populate(picker, self._wizard_ports, self.port.currentText())
        self._watch_port_picker(picker)

    def select_usb_port(self, path):
        self._usb_user_choice = True
        for picker in self._port_pickers():
            usb_ports.set_selection(picker, path)
        self._sync_endpoint()

    def refresh_ports(self):
        if self.closing or self._usb_scan is not None:
            return
        self._usb_scan = usb_ports.start_scan()
        self._port_scan_poll.start()

    def _finish_port_scan(self):
        scan = self._usb_scan
        if self.closing or scan is None or not scan.done():
            return
        self._port_scan_poll.stop()
        self._usb_scan = None
        try:
            devices = scan.result()
        except Exception as error:
            if self._usb_scan_error != str(error):
                self.log('USB port scan: ' + str(error))
            self._usb_scan_error = str(error)
            return
        self._usb_scan_error = None
        if self._usb_scanned and self._wizard_ports == devices:
            return
        self._usb_scanned = True
        self._wizard_ports = devices
        self._update_usb_pickers()

    def _settle_usb_pickers(self):
        if not self.closing and not self.close_ready and any(not p.view().isVisible() for p in self._usb_open_pickers):
            self._update_usb_pickers()

    def _update_usb_pickers(self):
        devices = self._wizard_ports
        self._usb_open_pickers = {p for p in self._port_pickers() if p.view().isVisible()}
        path = self.port.currentText()
        if not self._usb_user_choice and not self._usb_open_pickers:
            if self._preferred_usb_port:
                path = self._preferred_usb_port
            elif path not in dict(devices):
                path = devices[0][0] if len(devices) == 1 else ''
        for picker in self._port_pickers():
            if picker in self._usb_open_pickers:
                usb_ports.merge_open(picker, devices)
            else:
                usb_ports.populate(picker, devices, path)
        self._sync_endpoint()

    def _remember_confirmed_usb(self):
        if self._pending_usb_preference is None or not self._connected():
            return
        port, baud = self._pending_usb_preference
        route = f'serial://{port}@{baud}'
        if not any(p.get('name') == route and p.get('datagram') is False
                   and p.get('active') and p.get('confirmed') for p in self.link.transport_status):
            return
        self._pending_usb_preference = None
        if self._preferred_usb_port == port:
            return
        try:
            usb_ports.save_preference(self._usb_pref_path, port)
        except OSError as error:
            self.log(f'USB connected. Could not remember {port}: {error}')
            return
        self._preferred_usb_port = port
        self._sync_endpoint()

    def check_wifi(self):
        from wifi_check import check_wifi
        expected=self.ssid.text().strip()
        def done(result,error):
            if error:self.wifi_detail.setText(str(error));return
            self._show_wifi(result)
        self._submit(lambda:check_wifi(expected),done)

    def _show_wifi(self,value):
        if value:self.wifi_detail.setText(f'Wi-Fi: {value.state.upper()}\n{value.ssid or "SSID unavailable"}\n{value.detail}')

    def connect_fc(self):
        if self.connecting or self.closing:return
        options=self._connection_options()
        if options['mode'] == 'USB' and not options['port']:
            self.log('Choose a USB port before connecting.');return
        if options['mode']!='USB' and (not options['host'] or not options['ssid']):
            self.log('Enter AP address and expected Wi-Fi name.');return
        old_link=self.link;context=self._close_context();preserve_esc=self._scheduled_esc_disconnect()
        self._cancel_local_connection_work('Reconnecting')
        self.link=None;self.session=None;self._last_close_context=context
        self._clear_connection_telemetry()
        self.connecting=True;cancel=threading.Event();self.connect_cancel=cancel
        token=self.generation
        self.connection_detail.setText('CONNECTING\nOpening selected paths and verifying the FC…');self.log('Connecting; USB startup calibration and ownership recovery can take a few seconds.')
        def work():
            warning=self._close_link(old_link,context,preserve_esc) if old_link else None
            if cancel.is_set():raise RuntimeError('Connection cancelled')
            result=open_link(options,cancel)
            if warning:result[3].insert(0,warning)
            return result
        def done(result,error):
            # A canceled attempt must never replace a newer session or clear
            # the newer attempt's CONNECTING state.
            if self.connect_cancel is not cancel or self.generation!=token or cancel.is_set() or self.closing:
                if result:self._submit(result[0].close,lambda *_:None,0)
                if self.connect_cancel is cancel:self.connecting=False
                return
            self.connecting=False
            if error:self.connection_detail.setText('CONNECTION FAILED\n'+str(error));self.log(error);return
            link,values,wifi,warnings=result
            self.install_link(link,values);self._show_wifi(wifi)
            if options['mode'] in ('USB', 'USB + AP') and options['port'] and not getattr(link, 'demo', False):
                self._pending_usb_preference = options['port'], options['baud']
                self._remember_confirmed_usb()
            if warnings:self.log('Connected with path warnings: '+'; '.join(warnings))
        self._submit(work,done,0 if old_link else 10)

    def install_link(self,link,values):
        self.link=link;self.session=ControlSession(link);self.data=Telemetry();self.controls.reset()
        self.pid_live_confirm.blockSignals(True);self.pid_live_confirm.setChecked(False);self.pid_live_confirm.blockSignals(False)
        self.pid_bench_confirm.blockSignals(True);self.pid_bench_confirm.setChecked(False);self.pid_bench_confirm.blockSignals(False)
        self._pid_pending_cards.clear()
        self._pid_unverified.clear()
        self._connection_lost=False;self._last_close_context=None
        self.ppm_monitor=PpmMonitor()
        for card in self.cards.values():card.loaded=False;card.active=None;card.busy=False
        for group,items in values.items():self.data.put(group,DRONE_GROUPS[group]['schema'],items,received=False)
        self._refresh_flight_instruments(time.monotonic(), self._connected())
        self._select_source_value(values[122][0])
        demo=getattr(link,'demo',False)
        self.connection_detail.setText(('DEMO · NO HARDWARE' if demo else 'FC CONNECTED')+f'\nFC session {link.fc_session}\nOwner session {link.session}')
        self.log('DEMO active. Values are generated locally; no hardware connection.' if demo else 'FC CONNECTED: handshake, current status and firmware sections verified.')
        if self._setup_wizard is not None:self._update_wizard_connection(time.monotonic())
        for group in SETTINGS:
            self.settings_request(group,'read',[])

    def disconnect(self):
        context=self._close_context();preserve_esc=self._scheduled_esc_disconnect()
        self.connect_cancel.set();self.connecting=False
        self._cancel_local_connection_work('FC disconnected')
        link=self.link;self.link=None;self.session=None;self._last_close_context=context
        self._clear_connection_telemetry()
        if link:
            token=self.generation
            def done(result,error):
                if self.generation!=token or self.connecting or self.link:return
                self.log('Closed locally: '+str(error) if error else result or 'Disconnected.')
            self._submit(lambda:self._close_link(link,context,preserve_esc),done,0)
        self.connection_detail.setText('OFFLINE\nNo active FC connection.');self.log('Connection closed; no automatic reconnect.')
        if self._setup_wizard is not None:self._update_wizard_connection(time.monotonic())

    def _select_source_value(self,source):
        for widget in (self.source_box,self.config_source):
            i=widget.findData(source)
            if i>=0:widget.setCurrentIndex(i)

    def select_source(self):
        if not self.link:return
        if self._running() or self.command_busy or self.stopping:
            self.log('DISARM and stop the sender before saving flight input.');return
        source=self.source_box.currentData();self.command_busy=True;token=self.generation
        original_link=self.link;fc_session=original_link.fc_session
        def work(link):
            return save_input(link,source,cancel=lambda:token!=self.generation or self.link is not original_link or link.fc_session!=fc_session)
        def done(result,error):
            if token!=self.generation:return
            if self.link is not original_link or original_link.fc_session!=fc_session:
                self._connection_became_stale();return
            self.command_busy=False
            if error:self.log(error);return
            self.controls.reset()
            for group,values in result['values'].items():
                self.data.put(group,DRONE_GROUPS[group]['schema'],values,received=False)
            self._select_source_value(source)
            self.log('SAVED input: '+{0:'PPM',1:'AP',2:'USB'}[source]+'. Active and boot setting verified. Fresh neutral input is required.')
        self._linked(work,done)

    def start_stream(self):
        if not self._tx_visible() or not self.link or self.command_busy or self.stopping or self._running():return
        if not self._setup_arm_allowed():self.log('SETUP LOCKED · Complete setup and verified Save before flight controls.');return
        self.generation+=1;token=self.generation;self.command_busy=True;self.controls.reset();self.left_stick.held=self.right_stick.held=False
        def work(link):
            if token!=self.generation:raise RuntimeError('Start cancelled')
            return require_disarmed(link),get_input_status(link)
        def done(result,error):
            if token!=self.generation:return
            self.command_busy=False
            if error:self.log(error);return
            try:self.session.start(*result,time.monotonic());self.log('Sending neutral channels at 50 Hz target. Waiting for FC input readiness…')
            except Exception as exc:self.log(exc)
        self._linked(work,done)

    def arm(self):
        if not self._tx_visible() or not self.session or self.command_busy or self.stopping:return
        if not self._setup_arm_allowed():self.log('ARM blocked: complete setup and verified Save first.');return
        limits=self.data.values(4)
        if limits:self.session.throttle_low=limits[0]
        try:arguments=self.session.arm_arguments(time.monotonic())
        except Exception as error:self.log(error);return
        self.command_busy=True;token=self.generation
        def work(link):
            setup=read_section(link,130)
            if setup[0] or not setup[1]:raise RuntimeError('FC setup is locked or not saved.')
            link.arm(**arguments);state=read_section(link,120)
            if not state[0]:raise RuntimeError('ARM acknowledged, but current Armed=true is not confirmed')
            return state
        def done(result,error):
            if token!=self.generation:return
            self.command_busy=False
            if error:self.stop('ARM failed: '+str(error));return
            self.data.put(120,1,result,received=False);self.log('FC ARMED • confirmed by current status.')
        self._linked(work,done,5)

    def stop(self,reason='DISARM requested'):
        if self._setup_wizard is not None:self._setup_wizard.suspend(reason)
        for panel in self._maintenance.values():panel.suspend(reason,request_stop=False)
        self.generation+=1;self.command_busy=False
        if self.session:self.session.stop()
        self.controls.reset();self.left_stick.held=self.right_stick.held=False
        self.log(str(reason)+'. Channel sender stopped.')
        if not self.link or self.stopping:return
        self.stopping=True
        def done(result,error):
            self.stopping=False
            if error:self.log('Sender OFF. DISARM unconfirmed: '+str(error));return
            self.log(result)
        self._linked(disarm_and_read,done,0)

    def settings_request(self,group,action,values):
        card=self.cards[group];link=self.link
        if not link:card.finish(action,error='Connect to the FC first');return
        if group in (2,3) and action in ('apply','save'):
            self._pid_request(group,values);return
        if action in ('apply','save') and (self._running() or self.command_busy):
            card.finish(action,error='Stop the sender before changing settings');return
        card.busy=True;card.refresh();token=self.generation;fc_session=link.fc_session
        connection = self.session
        cancelled=lambda:token!=self.generation or self.link is not link or link.fc_session!=fc_session
        def work(l):
            if action in ('read','stored'):return read_section(l,group,action=='stored',cancel=cancelled)
            if action=='apply':return apply_section(l,group,values)
            return save_section(l,group,values)
        def done(result,error):
            if self.link is not link or self.session is not connection:
                return
            if token != self.generation:
                card.finish(action, error='Request interrupted. Read FC again to confirm values.')
                return
            if link.fc_session!=fc_session:
                self._connection_became_stale();return
            card.finish(action,result,error)
            if error:self.log(f'{DRONE_GROUPS[group]["name"]}: {error}');return
            if action!='stored':self.data.put(group,DRONE_GROUPS[group]['schema'],result,received=False)
            self.log(f'{DRONE_GROUPS[group]["name"]}: '+{'read':'active values read','stored':'saved copy read; not applied','apply':'applied in RAM; not saved','save':'saved and storage readback verified'}[action])
        self._linked(work,done)

    def _sync_bench_confirmation(self,checked):
        for name in ('pid_live_confirm','pid_bench_confirm'):
            widget=getattr(self,name,None)
            if widget is not None:
                widget.blockSignals(True);widget.setChecked(checked);widget.blockSignals(False)
        if not checked and hasattr(self,'pages') and self.pages.currentIndex()==2 and self._running():
            self.stop('Live tuning confirmation cleared')

    def _pid_request(self,group,values):
        card=self.cards[group]
        if self.command_busy or self.stopping:
            card.finish('apply',error='Wait for the current command to finish.');return
        status=self.data.values(120,.5)
        if status is None:
            card.finish('apply',error='Wait for fresh FC status before applying PID.');return
        if status[0] and not self.pid_live_confirm.isChecked():
            card.finish('apply',error='Confirm the secured tripod before live PID tuning.');return
        self.command_busy=True;card.busy=True;card.refresh();token=self.generation
        bench=self.pid_live_confirm.isChecked();original_link=self.link;fc_session=original_link.fc_session
        def work(link):
            return apply_pid(link,group,values,bench_confirmed=bench,cancel=lambda:token!=self.generation or self.link is not original_link or link.fc_session!=fc_session)
        def done(result,error):
            card.busy=False
            if token!=self.generation:
                message='Request interrupted. Read FC to confirm active and saved PID.'
                self._pid_unverified[group]=message
                card.finish('apply',error=message)
                self._render_pid_state(time.monotonic())
                return
            if self.link is not original_link or original_link.fc_session!=fc_session:
                self._connection_became_stale();return
            self.command_busy=False
            if error:
                self._pid_unverified[group]=str(error)
                card.finish('apply',error=error)
                self._render_pid_state(time.monotonic())
                self.log('PID: '+str(error))
                return
            self._pid_unverified.pop(group,None)
            for number,items in result['values'].items():
                self.data.put(number,DRONE_GROUPS[number]['schema'],items,received=False)
            card.finish('apply',result['values'][group])
            message='SAVED · verified' if result['saved'] else 'APPLIED LIVE · Save pending until DISARM. Keep the FC powered.'
            card.note.setText(message)
            if result['pending']:self._pid_pending_cards[group]=(result['values'][136][1],list(result['values'][group]))
            else:self._pid_pending_cards.pop(group,None)
            self._render_pid_state(time.monotonic());self.log(message)
        self._linked(work,done,5)

    def _render_pid_state(self,now):
        tuning=self.data.values(136,.5,now) if self._connected() else None
        if not tuning:
            text='PID · Status unavailable';color='#b8d5f3'
        elif tuning[3]:
            text='PID SAVE FAILED · '+str(tuning[3])+' · ARM remains locked.';color='#ff9caa'
        elif tuning[0]:
            text=f'PID revision {tuning[1]} APPLIED LIVE · Save pending until DISARM. Keep the FC powered.';color='#ffd094'
        elif tuning[1]!=tuning[2]:
            text='PID · Save unconfirmed';color='#ffd094'
        elif tuning[1]==0:
            text='PID · No pending changes';color='#b8d5f3'
        else:
            text=f'FC PID SAVED · revision {tuning[2]}';color='#8ee9c9'
        # A revision alone cannot verify the values returned by an apply request.
        # Keep the panel-specific discrepancy until the kit verifies that group.
        if self._pid_unverified and not (tuning and tuning[3]):
            sections=' / '.join('Rate' if group==2 else 'Attitude' for group in sorted(self._pid_unverified))
            text=f'{sections} PID · Apply unverified'
            if tuning and tuning[0]:
                text+=' · Save pending until DISARM'
            color='#ffd094'
        elif tuning and not tuning[0] and not tuning[3] and any(
                self.cards[g].loaded and self.cards[g].active is not None
                and not matching_pid_gains(self.cards[g].values(), self.cards[g].active) for g in (2,3)):
            text+=' · Unapplied edits'
            color='#ffd094'
        if self.pid_state.text()!=text:self.pid_state.setText(text);self.pid_state.setStyleSheet('color:'+color+';')
        for group,(revision,applied) in list(self._pid_pending_cards.items()):
            card=self.cards[group]
            if tuning and tuning[3]:
                card.note.setText('SAVE FAILED · '+str(tuning[3]));self._pid_pending_cards.pop(group,None)
            elif tuning and not tuning[0] and tuning[1]==tuning[2] and tuning[2]>=revision:
                if card.busy:continue
                if group not in self._pid_unverified and matching_pid_gains(card.values(),applied):
                    card.note.setText('SAVED after DISARM · verified')
                self._pid_pending_cards.pop(group,None)
                self.log('PID saved after DISARM; FC verified persistence.')

    def _clear_keys(self):
        self.controls.pressed.clear()
        for i in (0,1,3):self.controls.values[i]=1500

    def _key_hint(self):
        keys=self.controls.keys
        self.key_hint.setText(f'Throttle {keys[2][1]} / {keys[2][0]}  ·  Yaw {keys[3][0]} / {keys[3][1]}  ·  Pitch {keys[1][1]} / {keys[1][0]}  ·  Roll {keys[0][0]} / {keys[0][1]}')

    def configure_keys(self):
        if self._running() or self.command_busy:self.stop('Key configuration opened')
        dialog=QDialog(self);dialog.setWindowTitle('Transmitter key mapping');layout=QVBoxLayout(dialog)
        layout.addWidget(label('Key mapping','cardTitle'))
        grid=QGridLayout();pairs=[]
        for i,name in enumerate(CHANNEL_NAMES):
            grid.addWidget(label(f'CH{i+1} {name}'),i,0);pair=[]
            for j in range(2):
                combo=ConsoleComboBox();combo.addItems(KEY_CHOICES);combo.setCurrentText(self.controls.keys[i][j]);grid.addWidget(combo,i,j+1);pair.append(combo)
            pairs.append(pair)
        layout.addLayout(grid);note=label('Columns: decrease / increase. Escape and Space always stop.','muted');note.setWordWrap(True);layout.addWidget(note)
        def defaults():
            for pair,keys in zip(pairs,DEFAULT_KEYS):
                for combo,key in zip(pair,keys):combo.setCurrentText(key)
            note.setText('Defaults · not saved')
        layout.addWidget(button('Reset keys',defaults))
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel)
        layout.addWidget(buttons);buttons.rejected.connect(dialog.reject)
        def save():
            try:
                bindings=[tuple(combo.currentText() for combo in pair) for pair in pairs]
                self._save_key_bindings(bindings)
            except (ValueError,OSError) as error:note.setText(str(error));return
            self._key_hint();dialog.accept()
        buttons.accepted.connect(save);dialog.exec();self.controls.pressed.clear()
        # Resume transmitter shortcuts after the modal editor closes, even if
        # the source selector held focus before key configuration was opened.
        dialog.deleteLater();self.activateWindow()
        self.keyboard.setFocus(Qt.FocusReason.OtherFocusReason)

    def _save_key_bindings(self,bindings):
        candidate=Controls();candidate.set_bindings(bindings)
        self.config_path.parent.mkdir(parents=True,exist_ok=True)
        temporary=None
        try:
            with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=self.config_path.parent,
                    prefix='.controls-',suffix='.tmp',delete=False) as stream:
                temporary=Path(stream.name)
                stream.write(json.dumps({'keys':candidate.keys},indent=2)+'\n')
                stream.flush();os.fsync(stream.fileno())
            os.replace(temporary,self.config_path)
        finally:
            if temporary is not None:
                try:temporary.unlink(missing_ok=True)
                except OSError:pass
        # A rejected Save/Cancel must retain the previously active key map.
        self.controls.set_bindings(candidate.keys)

    def eventFilter(self,watched,event):
        if self.closing or self.close_ready:return super().eventFilter(watched,event)
        if watched is self and event.type()==QEvent.Type.WindowDeactivate:
            self._application_state(Qt.ApplicationState.ApplicationInactive)
        if event.type() in (QEvent.Type.KeyPress,QEvent.Type.KeyRelease):
            # Only this console owns its controls. Closed/other windows must not
            # steal keys through the application-wide event filter.
            if not isinstance(watched,QWidget) or not (watched is self or self.isAncestorOf(watched)):
                return super().eventFilter(watched,event)
            down=event.type()==QEvent.Type.KeyPress
            key=event.key()
            names={Qt.Key.Key_Left:'Left',Qt.Key.Key_Right:'Right',Qt.Key.Key_Up:'Up',Qt.Key.Key_Down:'Down'}
            name=names.get(key,chr(key) if 48<=key<=90 else event.text().upper())
            # Always clear released keys, even if focus moved into an editor.
            if not down and not event.isAutoRepeat():self.controls.key(name,False)
            if QApplication.activeModalWidget():return super().eventFilter(watched,event)
            popup = QApplication.activePopupWidget()
            if down and (key==Qt.Key.Key_Escape or (key==Qt.Key.Key_Space and self._running())):
                if not event.isAutoRepeat() and (popup is None or self._connected() or self._running()):
                    self.stop('Stop key pressed')
                if popup is not None and key==Qt.Key.Key_Escape:
                    return super().eventFilter(watched,event)
                event.accept();return True
            # Port menus and unfolded input lists own their navigation keys.
            if popup is not None:
                return super().eventFilter(watched,event)
            focus=QApplication.focusWidget()
            editing=isinstance(focus,(QLineEdit,QComboBox,QSpinBox,QDoubleSpinBox,QPlainTextEdit))
            if self.pages.currentIndex()==0 and self._tx_visible() and self.keyboard.isChecked() and not self._ppm_selected() and not editing and event.modifiers()==Qt.KeyboardModifier.NoModifier:
                if name in [k for pair in self.controls.keys for k in pair]:
                    if not event.isAutoRepeat():self.controls.key(name,down)
                    # Consume both repeat press/release events; otherwise Qt
                    # applies arrow keys to the previously focused AUX slider.
                    event.accept();return True
                if key in names:
                    # Unassigned arrows are not implicit slider/navigation keys.
                    event.accept();return True
        return super().eventFilter(watched,event)

    def _application_state(self,state):
        if state!=Qt.ApplicationState.ApplicationActive:
            if self._setup_wizard is not None:self._setup_wizard.suspend('window focus lost')
            for panel in self._maintenance.values():panel.suspend('window focus lost')
            self.controls.pressed.clear()
            # The wizard suspends active motor tests above. Background setup
            # reads/saves must not issue DISARM and cancel a scheduled ESC boot.
            if self._running() or (self.command_busy and not (self._setup_guard or self._calibration_guard or self._calibration_read_pending())):self.stop('Window focus lost')

    def tick(self):
        now=time.monotonic();dt=now-self.last_tick;self.last_tick=now
        self.controls.step(dt,self._tx_visible() and self.keyboard.isChecked() and not self._ppm_selected() and self.pages.currentIndex()==0)
        if self.link:
            events=[]
            timed_poll = getattr(self.link, 'poll_timed', None)
            if not self.link.connected:self._connection_became_stale()
            for _ in range(64):
                if timed_poll is None:
                    event, received_at = self.link.poll(0), now
                else:
                    entry = timed_poll(0)
                    if entry is None:break
                    event, received_at = entry
                    now = max(now, received_at)
                if event is None:break
                if self._connection_lost:continue
                events.append(event)
                previous = self.data.latest.get(event.group)
                if previous is not None and received_at < previous[1]:
                    # A direct readback can be newer than an event waiting in the queue.
                    continue
                accepted=self.data.put(event.group,event.schema,event.data,received_at)
                if accepted and (event.group == 21 or
                                 (event.group == 120 and (not event.data[2] or event.data[5] <= 0)) or
                                 (event.group == 130 and event.data[14] == "IMU_STARTUP_FAILED")):
                    # Integrate every received gyro sample. Qt coalesces paints during this poll.
                    imu = self.data.flight_imu(now)
                    self.flight_dashboard.horizon.update_telemetry(
                        imu, received_at, now, (id(self.link), self.link.fc_session), valid=imu is not None)
                if accepted and event.group==122:self.ppm_monitor.view(self.data,self.link.connected,now)
            if self.session and self.session.running:
                try:
                    if self.session.ready:self.session.apply(self.controls.values)
                    before=self.session.ready;self.session.tick(now,events=events)
                    if not before and self.session.ready:self.log('FC input READY • low throttle and neutral sticks. ARM is available.')
                except Exception as error:self.stop(str(error))
            if not self.link.connected:self._connection_became_stale()
        if now-self.last_control_render>=.02 and self.pages.currentIndex()==0 and self._tx_visible():
            self.last_control_render=now;self._render_transmitter(now)
        if now-self.last_render>=.1:self.last_render=now;self.render_status(now)

    def _flight_instrument_groups(self, now):
        groups = {g: self.data.values(g, .5, now) for g in (23, 120, 130, 136)}
        groups[21] = self.data.flight_imu(now)
        # The input classifier checks the independent FC frame and host report ages.
        groups.update({g: self.data.values(g) for g in (7, 110, 112, 122, 125, 132, 134)})
        return groups

    def _tx_link_status(self, now, connected):
        observation = tx_link.observe(self.data, now, connected)
        key = (observation.session, observation.kit_id) if observation.kit_id else None
        if self._tx_link_cache_key != key:
            self._tx_link_profile = tx_link.load_profile(self.config_path.parent, observation.kit_id) if key else None
            self._tx_link_cache_key = key
        return observation, self._tx_link_profile, tx_link.classify(observation, self._tx_link_profile)

    def save_tx_link_profile(self, profile):
        observation, _, _ = self._tx_link_status(time.monotonic(), self._connected())
        if (not observation.connected or observation.armed is not False or observation.source != 0
                or tx_link.classify(observation, profile).code != 'on'):
            raise ValueError('Connect the same disarmed kit with PPM and the transmitter on, then retry.')
        tx_link.save_profile(self.config_path.parent, profile)
        self._tx_link_profile = dict(profile)

    def clear_tx_link_profile(self, kit_id):
        observation, _, _ = self._tx_link_status(time.monotonic(), self._connected())
        if not kit_id or kit_id != observation.kit_id or observation.armed is not False:
            raise ValueError('Connect the same disarmed kit to clear its transmitter check.')
        tx_link.remove_profile(self.config_path.parent, kit_id)
        self._tx_link_profile = None

    def _refresh_flight_instruments(self, now, connected, tx_snapshot=None):
        observation, profile, indication = tx_snapshot or self._tx_link_status(now, connected)
        text = indication.label if indication.label.startswith('TX ') else 'TX ' + indication.label
        if indication.label == 'NO PPM':
            known_pulse_loss = (profile and profile['kind'] == 'pulse'
                                and tuple(profile['mapping']) == observation.mapping
                                and profile['mode_channel'] == observation.mode_channel)
            text = 'TX OFF · NO PPM' if known_pulse_loss else 'TX · NO PPM'
        badge = self.tx_link_badge
        if badge.text() != text:
            badge.setText(text)
        if badge.property('state') != indication.state:
            badge.setProperty('state', indication.state)
            badge.style().unpolish(badge)
            badge.style().polish(badge)
            badge.update()
        if badge.toolTip() != indication.detail:
            badge.setToolTip(indication.detail)
            badge.setAccessibleDescription(indication.detail)
        groups = self._flight_instrument_groups(now)
        stamp = self.data.latest.get(21, (None, None))[1]
        identity = (id(self.link), self.link.fc_session) if connected else None
        self.flight_dashboard.update_state(groups, stamp, now, identity, connected,
                                          input_age_s=self.data.age(122, now), tx_status=indication)

    def render_status(self,now):
        if self._pending_usb_preference is not None:
            self._remember_confirmed_usb()
        # Hidden wizard labels need no polling/re-layout while the transmitter
        # is running. Navigation refreshes the wizard immediately on entry.
        if self.pages.currentIndex()==5 or (self._setup_guard and self._setup_wizard is not None):self._update_wizard_connection(now)
        for panel in self._maintenance.values():
            if panel.isVisible() or panel.motor_running or panel.operation_busy:self._update_calibration_connection(panel,now)
        connected=self._connected();demo=bool(connected and getattr(self.link,'demo',False))
        status=self.data.values(120,.5,now) if connected else None
        inputs=self.data.values(122,.5,now) if connected else None
        armed='UNKNOWN' if status is None else ('ARMED' if status[0] else 'DISARMED')
        setup=self.data.values(130,.5,now) if connected else None
        if connected and (not setup or setup[0] or not setup[1] or self._setup_guard or self._calibration_guard):
            if status and status[0]:armed='ARMED · DISARM REQUIRED'
            elif setup and setup[0]:armed='ARM LOCKED · CALIBRATION' if self._calibration_guard else 'ARM LOCKED · SETUP'
            elif self._setup_guard or self._calibration_guard:armed='CALIBRATION LOCK REQUESTED'
            else:armed='ARM UNAVAILABLE · SETUP'
        self.arm_pill.setText(armed);self.arm_pill.setStyleSheet('color:#ff9caa;' if status and status[0] else 'color:#a8d8ca;')
        self.route_pill.setText('DEMO · NO HARDWARE' if demo else ('FC CONNECTED' if connected else ('CONNECTING…' if self.connecting else 'OFFLINE / STALE')))
        self.side_state.setText('DEMO' if demo else ('CONNECTED' if connected else 'OFFLINE'))
        self.stop_button.setEnabled(connected)
        self.connect_button.setEnabled(not self.connecting and not self.command_busy and not self.stopping and not self._running())
        self.connect_button.setText('Reconnect' if self.link else 'Connect')
        self.disconnect_button.setEnabled(bool(self.link or self.connecting))
        disarmed=bool(status is not None and not status[0]);running=self._running()
        self.source_apply.setEnabled(connected and disarmed and not running and not self.command_busy and not self.stopping)
        setup_ready=self._setup_arm_allowed(now)
        self.map_view_button.setEnabled(not running and not self.command_busy and not self.stopping)
        self.start_button.setEnabled(self._tx_visible() and setup_ready and connected and disarmed and not running and not self.command_busy and not self.stopping and bool(inputs and inputs[0] in (1,2)))
        self.arm_button.setEnabled(self._tx_visible() and setup_ready and connected and disarmed and bool(self.session and self.session.ready) and not self.command_busy and not self.stopping)
        live_pid=bool(self.pid_live_confirm.isChecked() and setup_ready and status and status[0]
                      and status[2] and status[7] and inputs and inputs[4] and self.data.values(21,.5,now))
        for group,card in self.cards.items():
            card.can_read=connected
            writable=(disarmed and (not running or group in (2,3))) or (group in (2,3) and live_pid)
            card.allowed=bool(connected and writable and not self.command_busy and not self.stopping);card.refresh()
        self._render_pid_state(now)
        hz=self.session.sent/max(.001,now-self.session.started) if running else 0
        self.sender_label.setText(f'{hz:.1f} Hz  ·  '+('READY' if self.session.ready else 'NEUTRAL') if running else 'SENDER OFF')
        flight_settings=self.data.values(7);mode_channel=flight_settings[0] if flight_settings else 5
        mode_name = FLIGHT_MODES[0 if status[1] else 1] if status and type(status[1]) is bool else 'UNKNOWN / STALE'
        self.mode_actual.setText('FC MODE: '+mode_name)
        can_choose=bool(connected and status and running and self.session.ready and inputs and inputs[0] in (1,2)
                        and inputs[4] and flight_settings and mode_channel>=5
                        and not self.command_busy and not self.stopping)
        requested=flight_mode_for_value(flight_settings,self.controls.values[mode_channel-1]) if flight_settings else None
        for mode,control in self.mode_buttons.items():
            control.setEnabled(can_choose)
            control.setChecked(bool(inputs and inputs[0] in (1,2) and requested==mode))
        if flight_settings:
            mapping=f'CH{mode_channel} · Low (<1500): {FLIGHT_MODES[flight_settings[4]]} · High (≥1500): {FLIGHT_MODES[flight_settings[5]]}'
            detail='PPM mode follows the receiver switch.' if inputs and inputs[0]==0 else (
                'Select AUX CH5–CH8 in Settings to use the USB/AP mode buttons.' if mode_channel<5 else (
                f'TX request: {FLIGHT_MODES[requested]} ({self.controls.values[mode_channel-1]}). FC MODE is telemetry.' if can_choose else
                'Start USB/AP channels to enable the mode buttons.'))
            self.mode_note.setText(mapping);self.mode_note.setToolTip(detail)
        else:self.mode_note.setText('Flight mode · Offline')
        self._render_transmitter(now)
        boot=self.data.values(134)
        self.input_state.setText('Active: '+(('NONE','PPM','AP','USB')[inputs[1]] if inputs else '—')+' · Saved: '+({0:'PPM',1:'AP',2:'USB'}.get(boot[1],'—') if boot else '—'))
        self.flight_meta.setText('Input ready: '+(str(inputs[4]) if inputs else '—')+'   ·   IMU: '+('OK' if status and status[2] else 'UNAVAILABLE')+'   ·   Mode: '+(('ANGLE' if status[1] else 'RATE') if status else '—'))
        imu=self.data.values(21,.5,now) if status and status[2] and status[5]>0 else None
        for i,metric in enumerate(self.imu_metrics):metric.set_value(imu[i] if imu else None)
        imu_stamp=self.data.latest.get(21,(None,None))[1]
        self.horizon.update_telemetry(imu,imu_stamp,now,
            (id(self.link),self.link.fc_session) if self.link else None,
            valid=bool(connected and status and status[2]))
        self.gps_map.set_link((id(self.link),self.link.fc_session) if connected else None,now)
        tx_snapshot = self._tx_link_status(now, connected)
        if self.pages.currentIndex() == 10 or (self.tx_link_panel.dialog and self.tx_link_panel.dialog.isVisible()):
            self.tx_link_panel.refresh(*tx_snapshot)
        if self.pages.currentIndex()==0:
            self._refresh_flight_instruments(now, connected, tx_snapshot)
            health = self.flight_dashboard.last_health
        elif connected:
            health = flight_status(self._flight_instrument_groups(now), True,
                                   input_age_s=self.data.age(122, now), tx_status=tx_snapshot[2])
        if connected:
            self.data.receiver_health.indicators(health, self.data, now)
        age=self.data.age(21,now);self.imu_fresh.setText(f'LIVE · last sample {age*1000:.0f} ms ago' if imu else 'IMU STALE / UNAVAILABLE')
        if self.pages.currentIndex()==1 and self.imu_tabs.currentIndex()==0:
            for plot,indices in self.imu_plots:
                plot.set_series([self.data.history.get((21,i),[]) for i in indices],[DRONE_GROUPS[21]['fields'][i]['name'] for i in indices])
        self._render_live_data(now,connected)
        self._render_console(now,connected,status,setup)
        device=self.data.values(125)
        if device:self.device_label.setText(f'Firmware {device[0]}  ·  Loop target {device[1]} Hz  ·  PPM GPIO {device[2]}\nMotor GPIOs {device[3:7]}  ·  PWM {device[7]} Hz / {device[8]} bits  ·  Duty {device[9]}–{device[10]}  ·  Control target {device[11]} Hz')
        if self.link:
            self.paths_detail.setText('\n\n'.join(f'{p["name"]}\n'+('CONFIRMED' if p['confirmed'] and p['active'] and p.get('last_received_age') is not None and p['last_received_age']<.5 else 'STALE / UNAVAILABLE')+(f'  ·  age {p["last_received_age"]:.2f} s' if p.get("last_received_age") is not None else '  ·  no reply')+f'\n{p.get("error") or ""}' for p in self.link.transport_status))

    def _render_live_data(self,now,connected):
        # Telemetry collection and safety checks continue on every page. Only
        # the visible presentation is rebuilt; opening this page uses latest
        # data immediately without synchronously reading the flight controller.
        page = self.pages.currentIndex()
        if page not in (2,4,8):return
        if page in (2,8):
            identity = (id(self.link), self.link.fc_session) if connected and self.link else None
            if page == 2:
                self.pid_workspace.refresh(self.data, now, connected, identity)
            else:
                self.scopes_page.refresh(self.data, now, connected, identity)
            return
        if self.live_tabs.currentIndex()!=0:return
        sections={}
        changes=[]
        for row,(group,index,_) in enumerate(self.table_rows):
            if group not in sections:
                values=self.data.values(group);age=self.data.age(group,now)
                static=group in SETTINGS or group in (110,121,125)
                state='WAITING' if age is None else ('OFFLINE' if not connected else
                    ('READ SNAPSHOT' if static else ('LIVE' if age<.5 else 'STALE')))
                sections[group]=(values,'—' if age is None else f'{age:.1f}s',state)
            values,age_text,state=sections[group]
            text='—' if values is None else (f'{values[index]:.6g}' if type(values[index]) is float else str(values[index]))
            for column,value in ((2,text),(3,age_text),(4,state)):
                if self._live_cells.get((row,column))!=value:
                    changes.append((row,column,value))
        if not changes:return
        was_enabled=self.table.updatesEnabled();self.table.setUpdatesEnabled(False)
        try:
            for row,column,value in changes:
                self.table.item(row,column).setText(value);self._live_cells[row,column]=value
        finally:self.table.setUpdatesEnabled(was_enabled)

    def export_csv(self):
        path,_=QFileDialog.getSaveFileName(self,'Export received telemetry','areion_telemetry.csv','CSV (*.csv)')
        if not path:return
        try:
            with open(path,'w',newline='',encoding='utf-8') as stream:
                writer=csv.writer(stream);writer.writerow(['seconds_since_connect','group','schema','values_json'])
                for elapsed,group,schema,values in self.data.rows:writer.writerow([f'{elapsed:.6f}',group,schema,json.dumps(values)])
            self.log(f'Exported {len(self.data.rows)} received packets to {path}')
        except OSError as error:self.log(error)

    def copy_diagnostics(self):
        connected = self._connected()
        setup = self.data.values(130, .5) if connected else None
        complete = bool(setup[1] and not setup[0]) if setup else None
        wizard = (self._setup_wizard.diagnostic_snapshot()
                  if self._setup_wizard is not None else {'stage': 'not_opened'})
        wizard.update(setup_status=setup, wizard_complete=complete,
                      hardware_applied=complete if not getattr(self.link, 'demo', False) else False)
        observation, profile, indication = self._tx_link_status(time.monotonic(), connected)
        marker = profile.get('channel') if profile else None
        tx_report = {'code': indication.code, 'state': indication.state, 'label': indication.label,
                     'detail': indication.detail, 'ppm_pulses': observation.pulse,
                     'verification': profile.get('kind') if profile else None, 'channel': marker,
                     'channel_us': observation.marker(marker) if marker else None}
        report={'app':'Areion Flight Console 3.12.3','demo':bool(self.link and getattr(self.link,'demo',False)),
                'connected':connected,'sender':self._running(),
                'fc_session':self.link.fc_session if self.link else None,
                'paths':self.link.transport_status if self.link else [],
                'groups':{str(g):{'values':v,'age_s':self.data.age(g)} for g,(v,_) in self.data.latest.items()},
                'receiver_health':self.data.receiver_health.snapshot(self.data, time.monotonic()),
                'tx_link':tx_report,
                'setup_wizard':wizard,
                'calibration_pages':{scope:panel.diagnostic_snapshot() for scope,panel in self._maintenance.items()},
                'navigation':{'page':self.pages.currentIndex(),'position':'top'},
                'link_activity':self.link_activity.state,
                'pid_tuning':{'bench_confirmed':self.pid_live_confirm.isChecked(),
                              'pending_groups':list(self._pid_pending_cards),
                              'unverified_groups':dict(self._pid_unverified),
                              'status':self.data.values(136)},
                'last_event':self.last_notice}
        QApplication.clipboard().setText(json.dumps(report,indent=2));self.log('Diagnostics copied. Paste into a message or text file.')

    def closeEvent(self,event):
        self.port_scan_timer.stop()
        self._port_scan_poll.stop()
        if self.close_ready:
            remove_scroll_guard(self);event.accept();return
        event.ignore()
        if self.closing:return
        context=self._close_context();preserve_esc=self._scheduled_esc_disconnect()
        self.closing=True;self.connect_cancel.set();self.connecting=False
        self._cancel_local_connection_work('Window closed')
        link=self.link;self.link=None;self.session=None;self._clear_connection_telemetry()
        def finish(*args):
            # Worker completion and the timeout can both arrive. Neither may
            # touch Qt children after this window has already been destroyed.
            if self.close_ready or not isValid(self):return
            self.close_ready=True
            if self._close_timer is not None and isValid(self._close_timer):self._close_timer.stop()
            if not isValid(self.timer):return
            self.timer.stop()
            app=QApplication.instance()
            if app is not None and isValid(app):app.removeEventFilter(self)
            self.close()
        if link:
            # Parenting the fallback timer also cancels it if the whole
            # window is destroyed before the worker finishes.
            self._close_timer=QTimer(self);self._close_timer.setSingleShot(True)
            self._close_timer.timeout.connect(finish);self._close_timer.start(3500)
            self._submit(lambda:self._close_link(link,context,preserve_esc),finish,0)
        else:
            finish()
            # There is no worker to wait for. finish() runs inside this close
            # event, where Qt ignores a re-entrant close(); accept the original
            # event and detach its application-wide guard explicitly.
            remove_scroll_guard(self);event.accept()

def launch():
    app=QApplication.instance() or QApplication([])
    app.setOrganizationName('Zebjus');app.setApplicationName('AreionFlightConsole')
    app.setStyle('Fusion');app.setFont(QFont('Sans Serif',10))
    window=MainWindow();window.show()
    return app.exec()
