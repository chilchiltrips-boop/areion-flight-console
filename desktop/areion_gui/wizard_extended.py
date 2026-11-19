"""Guarded setup and optional read-only post-restart verification."""
from __future__ import annotations
from copy import deepcopy
from pathlib import Path
import time
from PySide6.QtCore import Qt, QTimer, Signal
from shiboken6 import isValid
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QGridLayout,QScrollArea,
    QStackedWidget,QPushButton,QButtonGroup,QCheckBox,QSpinBox,QDoubleSpinBox,
    QLineEdit,QSlider,QProgressBar,QTableWidget,QTableWidgetItem,QHeaderView,QTabWidget,QSizePolicy)
from .combo_box import ConsoleComboBox
from .wizard_chrome import STYLE as WIZARD_STYLE, STEP_ICONS, StepButton, WizardGlyph, install_action_feedback, set_visual_state
from .widgets import Card,label
from .scroll_guard import focus_page,page_action_button as button
from .setup_visuals import WiringView
from .drone_scene import DroneScene
from .wizard_step_views import EscSequence, ModeBand, MotorOutputScene, PropellerGuide, ReviewTile
from .profile_artwork import ProfileArt
from .calibration_panel import CalibrationPanel
from .receiver_calibration import ReceiverCapture, normalize_channels, raw_channels, MAX_TELEMETRY_AGE_S
from .receiver_sticks import ReceiverSticks
from .restart_page import RestartCheckPage
from .setup_changes import PROFILE_KEYS, SETTINGS_GROUPS as KIT_SETTINGS, settings_snapshot, setting_changes
from .setup_config import (default_configuration,migrate_configuration,esc_configuration,
    PROFILE_NAMES,ESC_PROFILES,BASE_RATE,BASE_ANGLE,SOURCE_IDS)
from .wizard_model import DEFAULT_SELECTIONS,read_draft,save_draft
from .model import equal_values,validate_values


def note(value,role='muted'):
    item=label(value,role);item.setWordWrap(True);return item


def intspin(value,minimum,maximum,suffix=''):
    item=QSpinBox();item.setRange(minimum,maximum);item.setValue(value);item.setSuffix(suffix);return item


class EscChoice(QPushButton):
    def __init__(self, title, kind):
        super().__init__()
        self.setCheckable(True)
        self.setMinimumHeight(90)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName(title)
        box = QVBoxLayout(self)
        box.setContentsMargins(6, 3, 6, 6); box.setSpacing(2)
        art = ProfileArt(kind)
        art.setFixedHeight(53)
        art.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        box.addWidget(art)
        item = note(title)
        item.setAlignment(Qt.AlignmentFlag.AlignCenter)
        item.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        box.addWidget(item)


class ExtendedSetupWizard(QWidget):
    connect_requested=Signal(dict)
    disconnect_requested=Signal()
    refresh_ports_requested=Signal()
    saved=Signal(str)
    restart_check_requested=Signal()
    finish_requested=Signal()
    action_requested=Signal(str,dict)
    STEP_TITLES=('Safety & connect','Aircraft profile','Input & wiring','Sensors',
                 'PPM receiver','ESC calibration','Motor outputs','Arming & flight modes','Review & save','Verify after restart (optional)')
    SETTINGS_GROUPS = KIT_SETTINGS

    def __init__(self,draft_path):
        super().__init__();self.draft_path=Path(draft_path);self.step=0
        self.restart_view_active=False
        self._restart_from_review=False
        self._restart_chrome_state=None
        self.selections=dict(DEFAULT_SELECTIONS);self.configuration=default_configuration();self.last_saved=None
        self.restore_error=''
        try:
            if self.draft_path.exists():
                self.last_saved=read_draft(self.draft_path)
                self.configuration=migrate_configuration(self.last_saved.get('configuration',self.configuration))
        except (OSError,ValueError,TypeError,KeyError) as error:self.restore_error=str(error)
        self.live={};self.fc_identity=None;self.kit_id=None;self.demo=False;self.connected=False;self.imu_stamp=None
        self.last_status=None;self.last_settings={};self.checkpoint_error='';self.reconnect_waiting=False
        self.reset_unverified=False
        self.opening_settings = None
        self.opening_kit = None
        self.review_read_session = None
        self._change_view = None
        resume=self.configuration.get('checks',{}).get('resume',{})
        if isinstance(resume,dict):
            try:
                state=validate_values(130,resume.get('status'))
                self.last_status=state;self.kit_id=state[15]
                if (self.last_saved.get('stage') == 'initial_selections' and state[0]
                        and 'opening_settings' in resume and type(resume.get('demo')) is bool):
                    self.opening_settings = settings_snapshot(resume['opening_settings'])
                    self.opening_kit = (state[15], resume['demo'])
            except (ValueError,TypeError,KeyError):pass
        self.disarmed=False;self.external_busy=False;self.operation_busy=False;self.pending=None;self.after_action=None
        self.visit_active=False;self.begin_requested=False;self.begin_confirmed=False;self.finalized_this_visit=False;self.loaded_identity=None
        self.last_error='';self.last_message='Connect kit to begin.'
        self.rx_capture=None;self.rx_result=None;self.rx_stamp=None;self.raw=None;self.receiver_review_available=False
        self.motor_running=False;self.motor_last_mask=0;self.motor_last_tx=0.
        self.motor_candidate=list(self.configuration['motors']['candidate_min_us']);self._loading=True
        self._build();self._loading=False
        self.timer=QTimer(self);self.timer.setInterval(100);self.timer.timeout.connect(self._tick);self.timer.start()
        self._show_step(0)

    def _build(self):
        self.setObjectName('setupExperience')
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setStyleSheet(WIZARD_STYLE)
        self._message_step = None
        self._shared_chrome = False
        box = QVBoxLayout(self)
        box.setContentsMargins(12, 8, 12, 8)
        box.setSpacing(6)
        self.heading_row = QHBoxLayout()
        self.heading_row.setSpacing(8)
        self.heading_row.addWidget(WizardGlyph('frame', 23, light=True))
        self.title_label = label('Setup wizard', 'wizardTitle')
        self.heading_row.addWidget(self.title_label)
        self.step_label = label('Step 1 of 9', 'wizardNumber')
        self.heading_row.addWidget(self.step_label)
        self.heading_row.addStretch()
        self.lock_note = label('Waiting for kit', 'wizardLock')
        self.heading_row.addWidget(self.lock_note)
        box.addLayout(self.heading_row)
        self._build_connection(box)
        self.nav_area = QWidget()
        self.nav_area.setObjectName('wizardRoute')
        route = QHBoxLayout(self.nav_area)
        route.setContentsMargins(0, 0, 0, 0)
        route.setSpacing(4)
        self.step_picker = ConsoleComboBox(light=True, objectName='wizardStepPicker')
        self.step_picker.setAccessibleName('Setup step')
        self.step_picker.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.step_picker.addItems(self.STEP_TITLES)
        route.addWidget(self.step_picker)
        self.step_buttons = []
        for i, title in enumerate(self.STEP_TITLES):
            control = StepButton(i, title)
            control.clicked.connect(lambda checked=False, n=i: self._show_step(n))
            self.step_buttons.append(control)
            route.addWidget(control, 1)
        self.step_picker.activated.connect(self._pick_step)
        self.step_progress = QProgressBar(objectName='wizardProgress')
        self.step_progress.setRange(0, len(self.STEP_TITLES))
        self.step_progress.setTextVisible(False)
        self.step_progress.setAccessibleName('Current step position')
        route.addWidget(self.step_progress, 1)
        box.addWidget(self.nav_area)
        self.stack = QStackedWidget()
        self.scrolls = []
        box.addWidget(self.stack, 1)
        self._safety_page();self._aircraft_page();self._wiring_page();self._sensor_page();self._receiver_page()
        self._esc_page();self._motor_page();self._arming_page();self._review_page()
        self._restart_page()
        footer = QHBoxLayout()
        footer.setSpacing(8)
        self.back_button = button('Back', self.back, 'wizardBack')
        footer.addWidget(self.back_button)
        self.message = note(self.last_message, 'wizardMessage')
        self.message.setAccessibleName('Setup result')
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        footer.addWidget(self.message, 1)
        self.footer_note = note('')
        self.footer_note.hide()
        footer.addWidget(self.footer_note)
        self.restart_open_button = button('Verify after restart', self._open_restart_from_review, 'wizardRetry')
        self.restart_open_button.hide()
        footer.addWidget(self.restart_open_button)
        self.next_button = button('Next', self.advance, 'wizardAdvance')
        footer.addWidget(self.next_button)
        box.addLayout(footer)
        self._fit_navigation()
        install_action_feedback(self)

    def _page(self, title, description):
        scroll = QScrollArea(objectName='wizardScroll')
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        body = QWidget(objectName='wizardBody')
        box = QVBoxLayout(body)
        box.setContentsMargins(12, 10, 12, 10)
        box.setSpacing(8)
        heading = QHBoxLayout()
        heading.setSpacing(7)
        heading.addWidget(WizardGlyph(STEP_ICONS[len(self.scrolls)], 20))
        title_label = note(title, 'wizardPageTitle')
        title_label.setToolTip(description)
        heading.addWidget(title_label, 1)
        box.addLayout(heading)
        scroll.setWidget(body)
        self.stack.addWidget(scroll)
        self.scrolls.append(scroll)
        return box

    def _fit_navigation(self):
        if not hasattr(self, 'step_progress') or hasattr(self, 'scope'):
            return
        compact = self.width() < 980
        for control in self.step_buttons:
            control.setVisible(not compact)
        self.step_picker.setVisible(compact)
        self.step_progress.setVisible(compact)

    def _pick_step(self, index):
        if 0 <= index < len(self.step_buttons) and self.step_buttons[index].isEnabled():
            self._show_step(index)
        else:
            self.step_picker.setCurrentIndex(self.step)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_navigation()

    def use_shared_chrome(self):
        """The console supplies USB/AP controls; both step navigators share the same gates."""
        self._shared_chrome = True
        self.connection_card.hide()
        self.retry_begin.setText('Retry setup lock')
        self.retry_begin.setObjectName('wizardRetry')
        self.heading_row.insertWidget(self.heading_row.count() - 1, self.retry_begin)
        self._fit_navigation()
        self._update_navigation()

    def _safety_page(self):
        box = self._page('Prepare the kit', 'Remove all propellers and check the setup lock.')
        hero = Card()
        row = QHBoxLayout()
        row.addWidget(PropellerGuide(), 2)
        text = QVBoxLayout()
        text.addWidget(note('Remove all four propellers', 'cardTitle'))
        text.addWidget(note('Motors can start during ESC and output checks. Keep the propellers off until setup is complete.'))
        self.propeller_check = QCheckBox('I have removed every propeller.')
        self.propeller_check.toggled.connect(self._update_navigation)
        text.addWidget(self.propeller_check)
        row.addLayout(text, 4)
        hero.box.addLayout(row)
        box.addWidget(hero)

        options = QHBoxLayout()
        current = Card('Use current kit settings')
        self.current_settings_status = note('Connect to load saved settings.')
        current.box.addWidget(self.current_settings_status)
        self.read_current_button = button('Reload from kit', self._read_current_settings)
        current.box.addWidget(self.read_current_button)
        current.box.addStretch()
        options.addWidget(current, 1)
        reset = Card('Restore defaults')
        self.reset_confirm = QCheckBox('Clear saved settings and calibration checks.')
        self.reset_confirm.setToolTip('This also clears pending ESC calibration.')
        self.reset_confirm.toggled.connect(self._update_navigation)
        reset.box.addWidget(self.reset_confirm)
        self.reset_button = button('Reset all settings', self._reset_all_settings, 'danger')
        reset.box.addWidget(self.reset_button)
        self.reset_progress = QProgressBar()
        self.reset_progress.setRange(0, 100); self.reset_progress.setValue(0)
        self.reset_progress.hide()
        reset.box.addWidget(self.reset_progress)
        self.reset_status = note('Optional · also clears pending ESC calibration.')
        reset.box.addWidget(self.reset_status)
        options.addWidget(reset, 1)
        box.addLayout(options)
        box.addStretch()

    def _read_current_settings(self):
        return self._request('read',{'groups':[*self.SETTINGS_GROUPS,110,120,122,130,131,136]})

    def _reset_all_settings(self):
        if not self.reset_button.isEnabled():return
        self.reset_progress.setRange(0,0);self.reset_progress.show()
        self.reset_status.setText('Restoring defaults and verifying saved settings on the kit…')
        if not self._request('reset_all',{'props_removed':self.propeller_check.isChecked(),
                                         'confirmed':self.reset_confirm.isChecked()}):
            self.reset_progress.setRange(0,100);self.reset_progress.setValue(0)
            self.reset_status.setText('Reset was not started. Confirm the connection and setup lock.')

    def _accept_reset(self,values):
        """Discard old draft evidence only after a complete, locked FC readback."""
        for group in (*self.SETTINGS_GROUPS,130):validate_values(group,values.get(group))
        status=values[130]
        if not status[0] or status[1] or status[3]!=0 or status[4] or status[5] or status[6] or status[8]:
            raise ValueError('The kit did not confirm cleared setup checks with flight arming locked.')
        self._loading=True
        self.configuration=default_configuration();self.selections=dict(DEFAULT_SELECTIONS)
        self.sensor_panel.config=deepcopy(self.configuration['imu']);self.sensor_panel.new_visit()
        self.rx_capture=None;self.rx_result=None;self.receiver_review_available=False
        self.rx_progress.setValue(0);self.rx_status.setStyleSheet('');self.rx_extent.setText('Receiver defaults');self.rx_status.setText('Kit receiver defaults loaded. Capture range before flight.')
        self.motor_running=False;self.motor_candidate=[None]*4;self.motor_slider.setValue(1000)
        for item in self.minimum_labels:item.setText('Start not recorded')
        for checkbox in (self.orientation_check,self.rx_direction_check,self.esc_compatible,
                         self.esc_response,self.esc_skip_check,self.output_prop_check,
                         self.battery_check,self.motor_verified_check,self.save_ack,self.reset_confirm):
            checkbox.setChecked(False)
        self.esc_buttons[self.configuration['esc']['profile']].setChecked(True)
        self.last_status=list(status);self.last_settings={g:list(values[g]) for g in self.SETTINGS_GROUPS}
        self._load_fc_values(values);self.sensor_panel.set_offsets(values[6]);self._loading=False
        self.reset_unverified=False;self.finalized_this_visit=False
        self.reset_progress.setRange(0,100);self.reset_progress.setValue(100)
        self.reset_status.setText('Defaults saved and verified. Continue setup; flight arming stays locked until final save.')
        self._set_message('All kit settings reset and read back. Complete the setup checks before final save.')

    def _build_connection(self,parent):
        card=Card();grid=QGridLayout();self.mode=ConsoleComboBox();self.mode.addItems(['USB','AP','USB + AP'])
        self.port=ConsoleComboBox();self.port.setEditable(True);self.port.setMinimumWidth(130)
        self.host=QLineEdit('192.168.4.1');self.host.setMaximumWidth(150)
        self.udp_port=intspin(8080,1,65535);self.ssid=QLineEdit('aerion drone')
        self.baud=intspin(115200,9600,2000000);self.startup_wait=QDoubleSpinBox();self.startup_wait.setRange(0,30);self.startup_wait.setValue(4)
        self.refresh_button=button('↻',self.refresh_ports_requested.emit);self.refresh_button.setToolTip('Refresh USB ports')
        self.connect_button=button('Connect kit',self._request_connection,'primary')
        self.disconnect_button=button('Disconnect',self.disconnect_requested.emit)
        for col,widget in enumerate((self.mode,self.port,self.refresh_button,self.host,self.connect_button,self.disconnect_button)):grid.addWidget(widget,0,col)
        grid.setColumnStretch(1,1);card.box.addLayout(grid)
        statusrow=QHBoxLayout();self.connection_status=note('OFFLINE');statusrow.addWidget(self.connection_status,1)
        self.connection_details=QCheckBox('Details');statusrow.addWidget(self.connection_details);card.box.addLayout(statusrow)
        details=QWidget();dg=QGridLayout(details)
        for i,(name,widget) in enumerate((('Baud',self.baud),('Startup wait (s)',self.startup_wait),('UDP port',self.udp_port),('Wi-Fi name',self.ssid))):dg.addWidget(note(name),i//2,(i%2)*2);dg.addWidget(widget,i//2,(i%2)*2+1)
        self.ap_hint=note('Join aerion drone in your computer’s Wi-Fi settings using the kit Wi-Fi password.');dg.addWidget(self.ap_hint,2,0,1,4)
        self.retry_begin=button('Confirm setup lock',lambda:self._request('begin',{'props_removed':self.propeller_check.isChecked()}));dg.addWidget(self.retry_begin,3,0,1,4)
        details.hide();self.connection_details.toggled.connect(details.setVisible);card.box.addWidget(details)
        self.connection_card=card;parent.addWidget(card)
        self.mode.currentTextChanged.connect(self._connection_mode);self._connection_mode()

    def _aircraft_page(self):
        box = self._page('Choose the aircraft', 'Choose the frame you are building.')
        self.profile_keys = PROFILE_KEYS
        self.pid_buttons = {}
        details = ('450-class utility frame', '250-class compact frame', 'Standard Quad X', 'Other Quad X frame')
        profile = Card()
        row = QHBoxLayout()
        names = QVBoxLayout()
        names.addWidget(note('Frame profile', 'cardTitle'))
        group = QButtonGroup(self)
        for key, description in zip(self.profile_keys, details):
            b = button(PROFILE_NAMES[key], lambda checked=False, k=key: self._choose_profile(k))
            b.setCheckable(True); b.setToolTip(description)
            b.setMinimumWidth(147)
            group.addButton(b); names.addWidget(b)
            self.pid_buttons[key] = b
        names.addStretch()
        row.addLayout(names, 1)
        stage = QVBoxLayout()
        self.aircraft_scene = DroneScene(self.configuration['pid']['selected'])
        self.aircraft_scene.setMinimumHeight(175); self.aircraft_scene.setMaximumHeight(285)
        self.aircraft_scene.set_presentation()
        stage.addWidget(self.aircraft_scene, 1)
        self.profile_caption = note('', 'muted')
        self.profile_caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        stage.addWidget(self.profile_caption)
        row.addLayout(stage, 3)
        profile.box.addLayout(row)
        box.addWidget(profile)
        for key, b in self.pid_buttons.items():
            b.toggled.connect(lambda checked, k=key: self._present_profile(k) if checked else None)
        self.pid_buttons[self.configuration['pid']['selected']].setChecked(True)
        row = QHBoxLayout()
        self.aircraft_apply = button('Save profile', self._save_aircraft, 'primary')
        row.addWidget(self.aircraft_apply)
        row.addWidget(note('Loads the profile’s PID values. Tune them later in PID settings.'), 1)
        box.addLayout(row); box.addStretch()

    def _present_profile(self, key):
        self.aircraft_scene.set_profile(key)
        if hasattr(self, 'motor_view'):
            self.motor_view.scene.set_profile(key)
        self.profile_caption.setText(PROFILE_NAMES[key] + '  ·  Quad X  ·  Brushless ESCs')

    def _wiring_page(self):
        box = self._page('Flight input and wiring', 'Choose the input that will control the aircraft.')
        row = QHBoxLayout(); self.input_buttons = {}; group = QButtonGroup(self)
        for key, title in (('PPM','PPM receiver'),('AP','AP Wi-Fi'),('USB','USB commands')):
            b = button(title, lambda checked=False, k=key: self._choose_input(k))
            b.setCheckable(True); group.addButton(b); self.input_buttons[key] = b
            b.setChecked(self.configuration['input_source'] == key)
            row.addWidget(b)
        row.addStretch()
        self.input_apply = button('Save input', self._save_input, 'primary'); row.addWidget(self.input_apply)
        box.addLayout(row)
        card = Card('Signal connections')
        self.wiring_view = WiringView()
        self.wiring_view.setMinimumHeight(190); self.wiring_view.setMaximumHeight(330)
        card.box.addWidget(self.wiring_view, 1)
        focus = QHBoxLayout(); wire_group = QButtonGroup(self)
        self.wire_buttons = []
        for i, name in enumerate(('OUT 1','OUT 2','OUT 3','OUT 4','PPM','IMU')):
            b = button(name, lambda checked=False, n=i: self._focus_wire(n))
            b.setCheckable(True); wire_group.addButton(b); focus.addWidget(b); self.wire_buttons.append(b)
        focus.addStretch(); card.box.addLayout(focus)
        self.wire_detail = note('', 'notice'); card.box.addWidget(self.wire_detail)
        self._focus_wire(4 if self.configuration['input_source'] == 'PPM' else 0)
        box.addWidget(card)
        box.addWidget(note('Disconnect USB and battery power before wiring. Check polarity.'))
        box.addStretch()

    def _focus_wire(self, index):
        self.wiring_view.set_focus(index)
        self.wire_buttons[index].setChecked(True)
        labels = ('OUT 1  ·  D0 / GPIO 0   →   ESC 1   →   M1 front left, CW',
                  'OUT 2  ·  D1 / GPIO 1   →   ESC 2   →   M2 front right, CCW',
                  'OUT 3  ·  D2 / GPIO 2   →   ESC 3   →   M3 back right, CW',
                  'OUT 4  ·  D3 / GPIO 21   →   ESC 4   →   M4 back left, CCW',
                  'Receiver PPM signal   →   D10 / GPIO 18',
                  'IMU SDA   →   D4 / GPIO 22       IMU SCL   →   D5 / GPIO 23')
        self.wire_detail.setText(labels[index])

    def _sensor_page(self):
        box=self._page('Sensors','Capture the six ACC positions, then place the kit level and verify the live attitude direction.')
        self.sensor_panel=CalibrationPanel(self.configuration['imu'])
        self.sensor_panel.read_requested.connect(lambda:self._request('read',{'groups':[6]}))
        self.sensor_panel.changed.connect(self._sensor_changed);box.addWidget(self.sensor_panel)
        self.orientation_check=QCheckBox('Level and movement match the board.');self.orientation_check.toggled.connect(self._update_navigation);box.addWidget(self.orientation_check)
        self.sensor_save=button('Save offsets',self._save_sensors,'primary');box.addWidget(self.sensor_save);box.addStretch()

    def _receiver_page(self):
        box = self._page('PPM receiver', 'Move the sticks on your physical transmitter.')
        self.rx_available = False
        self.rx_skip_note = note('Move the physical transmitter sticks to check their direction.')
        box.addWidget(self.rx_skip_note)
        row = QHBoxLayout()
        row.setSpacing(10)
        self.rx_sticks = ReceiverSticks()
        row.addWidget(self.rx_sticks, 5)
        capture = Card('Capture receiver range')
        capture.box.setContentsMargins(12, 9, 12, 9)
        capture.box.setSpacing(6)
        self.rx_start = button('Capture range', self._start_receiver, 'primary')
        self.rx_finish = button('Capture neutral', self._finish_receiver)
        buttons = QHBoxLayout()
        buttons.addWidget(self.rx_start)
        buttons.addWidget(self.rx_finish)
        buttons.addStretch()
        capture.box.addLayout(buttons)
        self.rx_progress = QProgressBar()
        self.rx_progress.setRange(0, 100)
        self.rx_progress.setTextVisible(False)
        self.rx_progress.setFixedHeight(7)
        self.rx_progress.setValue(0)
        self.rx_progress.setAccessibleName('Receiver capture progress')
        capture.box.addWidget(self.rx_progress)
        self.rx_extent = note('Roll  ·  Pitch  ·  Throttle  ·  Yaw')
        capture.box.addWidget(self.rx_extent)
        self.rx_status = note('Sweep all four axes from end to end.')
        capture.box.addWidget(self.rx_status)
        capture.box.addStretch()
        row.addWidget(capture, 4)
        box.addLayout(row)

        self.rx_direction_check = QCheckBox('Stick directions match. Throttle is low.')
        self.rx_direction_check.toggled.connect(self._update_navigation)
        box.addWidget(self.rx_direction_check)
        self.rx_save = button('Save receiver', self._save_receiver, 'primary')
        self.rx_detail_toggle = button('Mapping && endpoints', None)
        self.rx_detail_toggle.setCheckable(True)
        actions = QHBoxLayout()
        actions.addWidget(self.rx_save)
        actions.addWidget(self.rx_detail_toggle)
        actions.addStretch()
        box.addLayout(actions)

        self.rx_details = Card()
        mapping = QGridLayout()
        self.mapping_boxes = []
        for index, (role, value) in enumerate(zip(('Roll', 'Pitch', 'Throttle', 'Yaw'), self.configuration['setup_values'][2:6])):
            mapping.addWidget(note(role), 0, index)
            editor = ConsoleComboBox()
            editor.setAccessibleName(f'{role} receiver channel')
            editor.addItems([f'CH{i}' for i in range(1, 9)])
            editor.setCurrentIndex(value - 1)
            editor.currentIndexChanged.connect(self._mapping_changed)
            self.mapping_boxes.append(editor)
            mapping.addWidget(editor, 1, index)
        self.rx_details.box.addLayout(mapping)
        self.rx_table = QTableWidget(8, 6)
        self.rx_table.setHorizontalHeaderLabels(['Channel', 'Raw µs', 'Min', 'Centre', 'Max', 'Reverse'])
        self.rx_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.rx_table.verticalHeader().hide()
        self.rx_table.verticalHeader().setDefaultSectionSize(29)
        self.rx_table.setMinimumHeight(268)
        self.rx_reverse = []
        for i in range(8):
            for col in range(5):
                item = QTableWidgetItem(f'CH{i+1}' if col == 0 else '—')
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.rx_table.setItem(i, col, item)
            check = QCheckBox()
            check.setAccessibleName(f'Reverse receiver channel {i+1}')
            check.setChecked(bool(self.configuration['receiver']['values'][4*i+3]))
            check.toggled.connect(self._reverse_changed)
            self.rx_table.setCellWidget(i, 5, check)
            self.rx_reverse.append(check)
        self.rx_details.box.addWidget(self.rx_table)
        self.rx_preview = note('Calibrated preview · waiting for RAW PPM')
        self.rx_details.box.addWidget(self.rx_preview)
        box.addWidget(self.rx_details)
        self.rx_details.hide()
        self.rx_detail_toggle.toggled.connect(self.rx_details.setVisible)
        box.addStretch()

    def _esc_page(self):
        box = self._page('ESC endpoint calibration', 'Schedule one calibration for the next startup.')
        row = QHBoxLayout(); group = QButtonGroup(self); self.esc_buttons = {}
        for key, title in ESC_PROFILES.items():
            b = EscChoice(title, 'esc_' + key)
            group.addButton(b); row.addWidget(b); self.esc_buttons[key] = b
            b.setChecked(self.configuration['esc']['profile'] == key)
            b.clicked.connect(lambda checked=False, k=key: self._select_esc(k))
        box.addLayout(row)
        sequence = Card('One-time calibration')
        self.esc_sequence = EscSequence(); sequence.box.addWidget(self.esc_sequence)
        self.esc_status = note('Connect to read ESC status.', 'notice')
        sequence.box.addWidget(self.esc_status)
        self.esc_progress = QProgressBar(); self.esc_progress.setRange(0,100)
        self.esc_progress.setTextVisible(False); self.esc_progress.setMaximumHeight(6)
        self.esc_progress.setValue(0); sequence.box.addWidget(self.esc_progress)
        row = QHBoxLayout()
        self.esc_compatible = QCheckBox('ESC supports PWM endpoint calibration.')
        self.esc_compatible.toggled.connect(self._update_navigation); row.addWidget(self.esc_compatible, 1)
        self.esc_schedule = button('Schedule calibration', lambda: self._command('ESC_SCHEDULE',[1,0,0,0]), 'primary')
        row.addWidget(self.esc_schedule); sequence.box.addLayout(row)
        sequence.box.addWidget(note('After scheduling, disconnect USB and LiPo. With props removed, power up as the ESC maker specifies. Reconnect to read the result.'))
        row = QHBoxLayout()
        self.esc_read_status = button('Read result', lambda: self._request('read', {'groups':[120,130,134]}))
        row.addWidget(self.esc_read_status)
        self.esc_response = QCheckBox('I heard the expected ESC tones.')
        self.esc_response.toggled.connect(self._update_navigation); row.addWidget(self.esc_response, 1)
        self.esc_verify = button('Confirm response', lambda: self._command('ESC_VERIFY',[1,0,0,0]))
        row.addWidget(self.esc_verify); sequence.box.addLayout(row); box.addWidget(sequence)
        row = QHBoxLayout()
        self.esc_skip_check = QCheckBox('My ESC does not require endpoint calibration.')
        self.esc_skip_check.toggled.connect(self._update_navigation); row.addWidget(self.esc_skip_check, 1)
        self.esc_skip = button('Skip calibration', lambda: self._command('ESC_SKIP',[1,0,0,0]))
        row.addWidget(self.esc_skip); box.addLayout(row)
        box.addStretch()

    def _motor_page(self):
        box = self._page('Motor output check', 'Find each motor’s starting command and verify position and direction.')
        checks = QHBoxLayout()
        self.output_prop_check = QCheckBox('Propellers off · frame secured')
        self.battery_check = QCheckBox('LiPo connected · polarity checked')
        for w in (self.output_prop_check, self.battery_check):
            w.toggled.connect(self._update_navigation); checks.addWidget(w)
        checks.addStretch(); box.addLayout(checks)
        row = QHBoxLayout()
        controls = Card('Test output'); self.motor_choice = ConsoleComboBox()
        for title, mask in (('M1 · front left · CW',1),('M2 · front right · CCW',2),('M3 · back right · CW',4),('M4 · back left · CCW',8),('All four motors',15)):
            self.motor_choice.addItem(title, mask)
        self.motor_choice.currentIndexChanged.connect(self._motor_selection_changed)
        controls.box.addWidget(self.motor_choice)
        self.motor_slider = QSlider(Qt.Orientation.Horizontal)
        self.motor_slider.setRange(1000,1500); self.motor_slider.setValue(1000)
        self.motor_value = label('1000 µs','metric')
        self.motor_slider.valueChanged.connect(lambda v: self.motor_value.setText(f'{v} µs'))
        controls.box.addWidget(self.motor_value); controls.box.addWidget(self.motor_slider)
        actions = QHBoxLayout()
        self.motor_start = button('Start test', self._start_motor, 'primary')
        self.motor_stop = button('STOP motors', self._stop_motor, 'danger')
        actions.addWidget(self.motor_start); actions.addWidget(self.motor_stop); actions.addStretch()
        controls.box.addLayout(actions)
        self.record_min = button('Record minimum', self._record_minimum); controls.box.addWidget(self.record_min)
        self.motor_status = note('Waiting for motor status.'); controls.box.addWidget(self.motor_status)
        row.addWidget(controls, 2)
        visual = Card('Motor position & commands')
        self.motor_view = MotorOutputScene()
        self.motor_view.scene.set_profile(self.configuration['pid']['selected'])
        visual.box.addWidget(self.motor_view)
        row.addWidget(visual, 3); box.addLayout(row)
        minima = Card('Starting output')
        grid = QGridLayout(); self.idle_boxes = []; self.minimum_labels = []
        for i, value in enumerate(self.configuration['setup_values'][7:11]):
            editor = intspin(value,1000,1500,' µs'); self.idle_boxes.append(editor)
            grid.addWidget(note(f'M{i+1}'),0,i)
            grid.addWidget(editor,1,i)
            lab = note('No capture'); self.minimum_labels.append(lab); grid.addWidget(lab,2,i)
        minima.box.addLayout(grid)
        actions = QHBoxLayout()
        self.motor_verified_check = QCheckBox('Position, direction and start checked.')
        self.motor_verified_check.toggled.connect(self._update_navigation); actions.addWidget(self.motor_verified_check, 1)
        self.motor_confirm = button('Save motor check', self._confirm_motor); actions.addWidget(self.motor_confirm)
        minima.box.addLayout(actions); box.addWidget(minima)
        box.addWidget(note('Test one motor first. Output readings are commanded pulse widths. Observe the motor to verify rotation.'))
        box.addStretch()

    def _arming_page(self):
        box = self._page('Arming & flight modes', 'Review timing and the transmitter’s two-position mode switch.')
        self.arming_guide = note('', 'notice'); box.addWidget(self.arming_guide)
        row = QHBoxLayout()
        timing = Card('Arming timing')
        grid = QGridLayout(); self.arming_fields = []; self.advanced_arming = []
        specs = [('Throttle low',1001,1200,' µs'),('ARM yaw threshold',1700,2000,' µs'),('DISARM yaw threshold',1000,1300,' µs'),('Throttle movement',1,200,' µs'),('ARM hold',1,15,' s'),('DISARM hold',1,10,' s'),('Idle auto-disarm',1,300,' s')]
        for i, ((name,lo,hi,suffix),v) in enumerate(zip(specs,self.configuration['arming'])):
            lab = note(name); editor = intspin(v,lo,hi,suffix); self.arming_fields.append(editor)
            grid.addWidget(lab,(i+3)%7,0); grid.addWidget(editor,(i+3)%7,1)
            if i<4:
                lab.hide(); editor.hide(); self.advanced_arming.extend([lab,editor])
        timing.box.addLayout(grid)
        advanced = QCheckBox('Advanced thresholds')
        for w in self.advanced_arming: advanced.toggled.connect(w.setVisible)
        timing.box.addWidget(advanced)
        self.restore_defaults = button('Reset timings', self._restore_timing); timing.box.addWidget(self.restore_defaults)
        timing.box.addStretch(); row.addWidget(timing, 1)

        modes = Card('Flight mode switch')
        self.mode_channel = ConsoleComboBox(); self.mode_channel.addItems([f'CH{i}' for i in range(1,9)])
        self.mode_low = ConsoleComboBox(); self.mode_high = ConsoleComboBox()
        for w in (self.mode_low,self.mode_high): w.addItems(['ANGLE','RATE / ACRO'])
        self.mode_band = ModeBand()
        modes.box.addWidget(self.mode_band)
        self.mode_test = note('Switch test · Waiting for PPM')
        self.mode_test.setAccessibleName('Live PPM switch test')
        modes.box.addWidget(self.mode_test)
        self._mode_test_identity = None
        self._mode_positions = set()
        settings = QGridLayout()
        for i, (title, w) in enumerate((('Channel',self.mode_channel),('Low',self.mode_low),('High',self.mode_high))):
            settings.addWidget(note(title),i,0); settings.addWidget(w,i,1)
        modes.box.addLayout(settings); modes.box.addStretch(); row.addWidget(modes, 1)
        box.addLayout(row)
        timeouts = QHBoxLayout()
        self.ppm_timeout = intspin(250,50,1000,' ms'); self.digital_timeout = intspin(250,100,500,' ms')
        for title, editor in (('PPM loss timeout',self.ppm_timeout),('USB/AP loss timeout',self.digital_timeout)):
            timeouts.addWidget(note(title)); timeouts.addWidget(editor)
        timeouts.addStretch(); box.addLayout(timeouts)
        save = QHBoxLayout()
        self.arming_save = button('Save settings',self._save_arming,'primary'); save.addWidget(self.arming_save)
        self.arming_status = note(''); save.addWidget(self.arming_status, 1); box.addLayout(save)
        self._load_arming()
        for widget in (*self.arming_fields,self.ppm_timeout,self.digital_timeout): widget.valueChanged.connect(self._update_navigation)
        def draw_mapping():
            self.mode_band.set_mapping(self.mode_channel.currentText(),self.mode_low.currentText(),self.mode_high.currentText())
        for widget in (self.mode_channel,self.mode_low,self.mode_high):
            widget.currentIndexChanged.connect(draw_mapping)
            widget.currentIndexChanged.connect(self._update_navigation)
        draw_mapping()
        box.addStretch()

    def _clear_mode_test(self, message):
        self._mode_test_identity = None
        self._mode_positions.clear()
        self.mode_band.set_pulse(None)
        if self.mode_test.text() != message:
            self.mode_test.setText(message)

    def _refresh_mode_test(self, now):
        if self.step != 7:
            if self._mode_test_identity is not None:
                self._clear_mode_test('Switch test · Waiting for PPM')
            return
        if self.configuration['input_source'] != 'PPM':
            self._clear_mode_test('Switch test · PPM input only')
            return
        if not self.connected or self.fc_identity is None:
            self._clear_mode_test('Switch test · Kit offline')
            return
        source = self.live.get(122)
        if not source or len(source) != 9 or type(source[0]) is not int:
            self._clear_mode_test('Switch test · Waiting for input status')
            return
        if source[0] != 0:
            self._clear_mode_test('Switch test · Select and save PPM on the kit')
            return
        channel = self.mode_channel.currentIndex() + 1
        low, high = self.mode_low.currentIndex(), self.mode_high.currentIndex()
        axes = tuple(widget.currentIndex() + 1 for widget in self.mapping_boxes)
        if low == high or channel in axes:
            text = ('Choose different Low and High modes' if low == high
                    else f'CH{channel} is assigned to a stick')
            self._clear_mode_test('Switch test · ' + text)
            return
        stamp = self.rx_stamp
        if type(stamp) not in (int, float) or not 0 <= now - stamp <= MAX_TELEMETRY_AGE_S:
            self._clear_mode_test('Switch test · Waiting for fresh PPM')
            return
        timeout_ms = (self.live.get(112) or (250,))[0]
        try:
            pulses, _ = raw_channels(self.raw, max(4, channel, *axes), max_age_ms=timeout_ms)
        except ValueError as error:
            self._clear_mode_test(f'Switch test · {error}')
            return
        if source[2] is not True or self.raw[10] + (now - stamp) * 1000 >= timeout_ms:
            self._clear_mode_test('Switch test · Signal expired')
            return
        # The FC reads the physical mode-switch pulse before axis calibration or reversal.
        pulse = pulses[channel - 1]
        side = 'LOW' if pulse < 1500 else 'HIGH'
        key = (self.fc_identity, self.kit_id, channel, low, high, axes)
        if key != self._mode_test_identity:
            self._mode_positions.clear()
            self._mode_test_identity = key
        self._mode_positions.add(side)
        self.mode_band.set_pulse(pulse)
        mode = self.mode_low.currentText() if side == 'LOW' else self.mode_high.currentText()
        fc_flight = self.live.get(7)
        assignment = 'Preview'
        if fc_flight and len(fc_flight) == 6:
            same = (channel, low, high) == (fc_flight[0], fc_flight[4], fc_flight[5])
            assignment = 'Kit mapping' if same else 'Draft mapping'
        progress = ('Both positions seen' if len(self._mode_positions) == 2
                    else 'Switch to ' + ('HIGH' if side == 'LOW' else 'LOW'))
        text = f'Switch test · CH{channel} · {pulse} µs · {side} → {mode}\n{assignment} · {progress}'
        if self.mode_test.text() != text:
            self.mode_test.setText(text)

    def _review_page(self):
        box = self._page('Review & save', 'Verify the kit’s checks before releasing the setup lock.')
        changes = Card('What changed?')
        self.change_summary = note('Waiting for the first kit settings read.')
        self.change_rows = note('', 'muted')
        self.change_rows.setTextFormat(Qt.TextFormat.PlainText)
        self.change_more = QCheckBox('Show all changes')
        self.change_more.toggled.connect(self._refresh_change_review)
        changes.box.addWidget(self.change_summary)
        changes.box.addWidget(self.change_rows)
        changes.box.addWidget(self.change_more)
        self.change_rows.hide(); self.change_more.hide()
        box.addWidget(changes)
        self.review_rows = {}; self.review_tiles = {}
        grid = QGridLayout(); grid.setHorizontalSpacing(8); grid.setVerticalSpacing(7)
        for i, name in enumerate(('Aircraft','Flight input','Sensors','Receiver','ESC','Motors','Arming settings','Storage')):
            tile = ReviewTile(name); self.review_tiles[name] = tile; self.review_rows[name] = tile.value
            grid.addWidget(tile,i//2,i%2)
        box.addLayout(grid)
        final = Card('Final verification')
        self.fc_save_status = note('Awaiting kit status.', 'notice'); final.box.addWidget(self.fc_save_status)
        self.save_ack = QCheckBox('Checks reviewed · props off · motors stopped.')
        self.save_ack.toggled.connect(self._update_navigation); final.box.addWidget(self.save_ack)
        final.box.addWidget(note('Save & finish verifies the stored setup. The kit stays disarmed.'))
        box.addWidget(final); box.addStretch()

    def _restart_page(self):
        layout = self._page('Verify after restart', 'Optional read-only comparison with the final setup save.')
        self.restart_page = RestartCheckPage()
        self.restart_check_button = self.restart_page.check_button
        self.restart_status = self.restart_page.status
        self.restart_table = self.restart_page.table
        self.restart_page.check_requested.connect(self.restart_check_requested)
        layout.addWidget(self.restart_page, 1)

    def set_restart_context(self, receipt, connected, fc_session, kit_id, busy):
        previous = self.restart_page.state, bool(self.restart_page.receipt)
        self.restart_page.set_context(receipt, connected, fc_session, kit_id, busy)
        if (previous != (self.restart_page.state, bool(self.restart_page.receipt))
                and (self.restart_view_active or self.finalized_this_visit)):
            self._update_navigation()

    def set_restart_result(self, result):
        self.restart_page.set_result(result)
        if self.restart_view_active:
            self._update_navigation()

    def _open_restart_from_review(self):
        if self.finalized_this_visit and self.restart_page.receipt:
            self.show_restart_check(from_review=True)

    def show_restart_check(self, *, from_review=False):
        if hasattr(self, 'scope') or self.operation_busy or self.motor_running:
            return False
        self.restart_view_active = True
        # Fresh status will be supplied when returning to the editable workspace.
        self.live = {}
        self.raw = None
        self._restart_from_review = from_review
        self._restart_chrome_state = None
        self.visit_active = False
        self._show_step(9)
        return True

    def _leave_completed_setup(self):
        self.visit_active = False
        self.finish_requested.emit()
        self.restart_view_active = False

    def _connection_mode(self,*args):
        usb=self.mode.currentText()!='AP';ap=self.mode.currentText()!='USB'
        self.port.setEnabled(usb);self.refresh_button.setEnabled(usb);self.host.setEnabled(ap);self.ap_hint.setVisible(ap)

    def _request_connection(self):
        self.connect_requested.emit({'mode':self.mode.currentText(),'port':self.port.currentText(),
            'baud':self.baud.value(),'startup_wait':self.startup_wait.value(),'host':self.host.text().strip(),
            'udp_port':self.udp_port.value(),'ssid':self.ssid.text()})

    def set_ports(self,ports):
        value=self.port.currentText();self.port.clear()
        for item in ports:
            if isinstance(item,dict):device=item.get('device','')
            elif isinstance(item,(tuple,list)):device=item[0]
            else:device=getattr(item,'device',str(item))
            self.port.addItem(str(device))
        if value:self.port.setEditText(value)

    def set_connection_state(self,**state):
        self.connected=bool(state.get('connected'));self.disarmed=bool(state.get('disarmed'))
        self.demo=bool(state.get('demo'));self.external_busy=bool(state.get('busy'))
        self.connection_status.setText(('DEMO · no physical hardware' if self.demo else 'KIT CONNECTED' if self.connected else 'OFFLINE')+
            (' · DISARMED' if self.connected and self.disarmed else ' · disarmed state unconfirmed' if self.connected else ''))
        connecting=bool(state.get('connecting'));has_link=bool(state.get('has_link'))
        self.connect_button.setText('Connecting…' if connecting else 'Reconnect' if has_link or self.reconnect_waiting else 'Connect kit')
        self.connect_button.setEnabled(not connecting)
        self.disconnect_button.setEnabled(has_link and not connecting)
        if not self.connected:
            self.review_read_session = None
            if self.rx_capture:self.rx_capture=None;self.rx_status.setText('Capture cancelled: disconnected. Capture all endpoints again.')
            self.motor_running=False;self.motor_slider.setValue(1000);self.begin_requested=False;self.begin_confirmed=False;self.loaded_identity=None
        self._update_navigation()

    def on_enter(self,connection_options=None):
        if self.restart_view_active:
            return
        self.visit_active=True;self.begin_requested=False;self.begin_confirmed=False;self.finalized_this_visit=False
        self.propeller_check.setChecked(False);self.output_prop_check.setChecked(False);self.battery_check.setChecked(False)
        self.orientation_check.setChecked(False);self.save_ack.setChecked(False);self.esc_compatible.setChecked(False)
        self.esc_response.setChecked(False);self.esc_skip_check.setChecked(False)
        self.motor_verified_check.setChecked(False);self.rx_direction_check.setChecked(False);self.sensor_panel.new_visit()
        self.reset_confirm.setChecked(False)
        if connection_options:
            for name,widget in (('mode',self.mode),('port',self.port)):
                value=connection_options.get(name)
                if value is not None:
                    if name=='mode':widget.setCurrentText(value)
                    else:widget.setEditText(value)
            for name,widget in (('host',self.host),('ssid',self.ssid)):
                if name in connection_options:widget.setText(str(connection_options[name]))
            for name,widget in (('baud',self.baud),('startup_wait',self.startup_wait),('udp_port',self.udp_port)):
                if name in connection_options:widget.setValue(connection_options[name])
        self._show_step(0)

    def suspend(self,reason='Setup paused',request_stop=True):
        if self.restart_view_active:
            return
        self.sensor_panel.suspend(reason)
        if self.rx_capture:self.rx_capture=None;self.rx_status.setText('Capture cancelled: '+str(reason))
        if request_stop and (self.motor_running or bool(self.status and self.status[8])):self._stop_motor()
        elif not request_stop:self.motor_running=False
        self.motor_slider.setValue(1000);self.output_prop_check.setChecked(False);self.battery_check.setChecked(False)
        # Pending one-shot ESC calibration survives navigation and reconnects.
        # Only an explicit global STOP cancels that durable firmware request.

    def _checkpoint(self):
        if self.restart_view_active:
            return
        state=self.status or self.last_status
        if not state or not state[0] or not self.begin_confirmed:return
        try:
            resume = {'status':list(state),'step':self.step,'demo':self.demo}
            if self.opening_settings is not None and self.opening_kit == (state[15], self.demo):
                resume['opening_settings'] = {str(g): list(v) for g, v in self.opening_settings.items()}
            self.configuration['checks']['resume'] = resume
            self.last_saved=save_draft(self.draft_path,self.selections,self._snapshot(),'initial_selections')
            self.checkpoint_error=''
        except (OSError,ValueError,TypeError) as error:self.checkpoint_error=str(error)

    def connection_lost(self,reason='Kit disconnected'):
        self.review_read_session = None
        self._checkpoint();self.suspend(reason,request_stop=False)
        if self.pending and self.pending[0]=='reset_all':
            self.reset_unverified=True;self.reset_progress.setRange(0,100);self.reset_progress.setValue(0)
            self.reset_status.setText('Connection lost before reset verification. Reconnect to read the actual kit settings.')
        self.pending=None;self.after_action=None;self.operation_busy=False
        self.begin_requested=False;self.begin_confirmed=False;self.loaded_identity=None
        self.connected=False;self.disarmed=False;self.live={};self.raw=None;self.imu_stamp=None
        self.motor_view.set_outputs(None)
        self.reconnect_waiting=True
        if self.restart_view_active:
            self.restart_page.set_context(self.restart_page.receipt, False, None, None, False)
        else:
            self._set_message(str(reason)+'. Reconnect here to read saved progress; no settings or motor commands will be replayed.')
        self._update_navigation()

    def _resume_target(self):
        s=self.status
        if not s or not s[0]:return 1
        if s[3] in (1,2,3,6):return 5
        # Normal review starts with the aircraft even when all physical checks
        # are retained. Only an unfinished ESC power-cycle needs direct resume.
        return 1

    def hideEvent(self,event):
        self.visit_active=False
        # Qt can deliver a final hide during application destruction after
        # child controls have been deleted. Normal hides still stop captures
        # and motor tests; destruction must not touch dead C++ widgets.
        controls=(self.sensor_panel,self.motor_slider,self.output_prop_check,
                  self.battery_check,*self.sensor_panel.offsets)
        if all(isValid(widget) for widget in controls):self.suspend('Wizard hidden')
        super().hideEvent(event)

    @property
    def status(self):
        value=self.live.get(130)
        return value if isinstance(value,(list,tuple)) and len(value)==16 else None

    def _live_arm_state(self):
        status = self.live.get(120) if self.connected else None
        if isinstance(status, (tuple, list)) and len(status) == 10 and type(status[0]) is bool:
            return status[0]
        return None

    def _saved_label(self, text):
        """Only a current status message supplies the arm state beside a saved receipt."""
        armed = self._live_arm_state()
        if armed is None:
            return text
        return text + (' · ARMED' if armed else ' · DISARMED')

    def _ready(self):
        return bool(self.connected and self.disarmed and self.status and self.status[0] and self.begin_confirmed
                    and not self.operation_busy and not self.external_busy and not self.finalized_this_visit)

    def _set_message(self,text,error=False):
        self.last_message = str(text)
        self.last_error = self.last_message if error else ''
        self._message_step = self.step
        self.message.setText(self.last_message)
        self.message.setToolTip(self.last_message)
        self.message.setVisible(bool(self.last_message))
        state = 'error' if error else 'success' if self.finalized_this_visit else 'info'
        set_visual_state(self.message, state)

    def _request(self,action,payload,after=None):
        if self.restart_view_active or self.operation_busy or not self.connected:return False
        if action!='begin' and (not self.disarmed or not self.status or not self.status[0]):
            self._set_message('A confirmed setup lock and DISARMED state are required.',True);return False
        self.operation_busy=True;self.pending=(action,deepcopy(payload));self.after_action=after
        self._set_message('Working…' if action!='begin' else 'Locking flight arming on the kit…')
        self._update_navigation();self.action_requested.emit(action,payload);return True

    def _command(self,command,args=None,after=None):
        if command in ('ESC_SCHEDULE','MOTOR_START') and not self.propeller_check.isChecked():return
        return self._request('command',{'command':command,'args':list(args or [0,0,0,0])},after)

    def _apply(self,groups,after=None):
        return self._request('apply_save',{'groups':groups,'acc_origin':self.sensor_panel.snapshot()['offsets_origin']},after)

    def action_finished(self,result,error):
        if result and result.get('command')=='MOTOR_SET':
            self.live.update(result.get('values',{}))
            if error:self.motor_running=False;self.motor_slider.setValue(1000);self._set_message(str(error),True)
            self._update_navigation();return
        pending=self.pending;after=self.after_action;self.pending=None;self.after_action=None;self.operation_busy=False
        action=pending[0] if pending else (result or {}).get('action','')
        payload=pending[1] if pending else {}
        if error or not result or result.get('complete') is False:
            self._set_message(str(error or (result or {}).get('error','Operation did not complete. Read the kit before retrying.')),True)
            if action=='begin':
                self.begin_requested=True;self.begin_confirmed=False  # explicit retry prevents repeated automatic writes
            if action=='command' and payload.get('command') in ('MOTOR_START','MOTOR_SET'):
                self.motor_running=False;self.motor_slider.setValue(1000)
            if action=='reset_all':
                self.reset_unverified=True;self.reset_progress.setRange(0,100);self.reset_progress.setValue(0)
                self.reset_status.setText('Reset was not verified. Reload from the kit before continuing; some settings may have changed.')
            self._update_navigation();return
        returned=result.get('values',{});self.live.update(returned)
        if action=='begin':
            if not self.status or not self.status[0] or self.status[1]:
                self.begin_confirmed=False;self._set_message('The kit did not confirm a setup lock. Reconnect or retry the lock request.',True);self._update_navigation();return
            if not result.get('resumed') or self.opening_kit != (self.status[15], self.demo):
                self.opening_kit = None
                self.opening_settings = None
            self.review_read_session = None
            self.begin_requested=True
            self.begin_confirmed=True
            self._set_message('Setup lock confirmed. Flight arming is blocked.')
            self._read_current_settings();return
        if action=='read':
            self._remember_opening_settings(returned)
            self._load_fc_values(returned);self._set_message('Current kit settings loaded. Flight arming remains locked.')
            if all(group in returned for group in (*self.SETTINGS_GROUPS,130)):
                if self.reset_unverified:self.reset_status.setText('Current kit settings reloaded. Review these values or confirm Reset all settings again.')
                self.reset_unverified=False
        elif action=='reset_all':
            try:self._accept_reset(returned)
            except (ValueError,TypeError) as exc:
                self.reset_unverified=True;self.reset_progress.setRange(0,100);self.reset_progress.setValue(0)
                self.reset_status.setText('Reset readback is incomplete. Reload from the kit before continuing.')
                self._set_message(str(exc),True);self._update_navigation();return
        elif action=='apply_save':
            # Readback confirms the requested draft; do not erase a just-captured sensor result.
            for g,key in ((4,'arming'),(7,'flight'),(112,'timeouts'),(134,'setup_values')):
                if g in returned:self.configuration[key]=list(returned[g])
            if 132 in returned:self.configuration['receiver']['values']=list(returned[132])
            self._set_message('Settings saved and verified.')
            if (self.configuration['input_source']=='PPM' and self.status and not self.status[6]
                    and any(group in returned for group in (4,7,112))):
                self._set_message('Settings saved · receiver check required.')
        elif action=='command':
            cmd=payload.get('command',result.get('command',''))
            if cmd=='MOTOR_START':
                self.motor_running=bool(self.status and self.status[8]);self.motor_last_mask=payload['args'][0];self.motor_last_tx=0.
                self.motor_slider.setValue(1000);self.motor_verified_check.setChecked(False)
            elif cmd in ('MOTOR_STOP','STOP'):self.motor_running=False;self.motor_slider.setValue(1000)
            if cmd == 'RX_OK':
                self.configuration['receiver_calibration'] = 'verified'
                self.rx_progress.setValue(100)
                self.rx_extent.setText('Receiver saved')
                self.rx_status.setStyleSheet('color:#9be3c1')
                self.rx_status.setText('Endpoints and directions verified by the kit.')
            self._set_message({'ESC_SCHEDULE':'Scheduled for next startup.',
                               'ESC_VERIFY':'ESC response confirmed.',
                               'MOTOR_OK':'Motor checks saved.',
                               'SENSOR_OK':'Sensor check saved.',
                               'RX_OK':'Receiver saved and verified.',
                               'FAILSAFE_OK':'Optional legacy check recorded on the kit.'}.get(cmd,'Kit status updated.'))
        elif action=='input':
            self.configuration['setup_values']=list(returned[134])
            self._set_message('Input active and saved.')
        elif action=='finalize':
            status=self.status
            if not status or status[0] or not status[1]:
                self._set_message('Final save did not confirm the firmware lock release. Arming stays unavailable.',True)
            else:
                self.finalized_this_visit=True;self.motor_running=False;self.visit_active=False
                self.fc_save_status.setText(('DEMO ONLY · ' if self.demo else '')+'Saved and verified. Setup lock released.')
                self._set_message('Setup complete.')
                try:
                    self.last_saved=save_draft(self.draft_path,self.selections,self._snapshot(),'configuration_saved',
                        receipt={'setup_status':list(status),'demo':self.demo})
                    self.saved.emit(str(self.draft_path))
                except (OSError,ValueError,TypeError) as exc:
                    self._set_message('Kit save verified, but local backup failed: '+str(exc),True)
        if action in ('apply_save','command','input','read','reset_all'):self._checkpoint()
        if after:after()
        self._update_navigation()

    def _remember_opening_settings(self, values):
        # Partial reads (for example the IMU offsets button) cannot establish a baseline.
        if not self.connected or not self.begin_confirmed:
            return
        try:
            status = validate_values(130, values.get(130))
            current = settings_snapshot(values)
        except ValueError:
            return
        if not status[0] or status[1] or not status[15]:
            return
        kit = (status[15], self.demo)
        if self.opening_kit != kit or self.opening_settings is None:
            self.opening_kit, self.opening_settings = kit, current
            self.change_more.setChecked(False)
        self.review_read_session = self.fc_identity

    def _refresh_change_review(self, *_):
        if self.step != 8 or self._loading:
            return
        changes = []
        status = self.status
        if not self.connected or not status:
            summary = 'Connect the kit to compare settings.'
        elif (self.opening_settings is None or self.opening_kit != (status[15], self.demo)
              or self.fc_identity is None or self.review_read_session != self.fc_identity):
            summary = 'Waiting for the complete settings read from this kit.'
        elif self.reset_unverified:
            summary = 'Reload the kit settings to verify the reset.'
        else:
            try:
                changes = setting_changes(self.opening_settings, settings_snapshot(self._final_groups()))
                count = len(changes)
                summary = (f'{count} setting{"s" if count != 1 else ""} changed · at start → final'
                           if count else 'Final settings match this kit’s opening values.')
            except ValueError as error:
                summary = f'Check the draft settings: {error}'
        view = (summary, changes, self.change_more.isChecked())
        if view == self._change_view:
            return
        self._change_view = view
        self.change_summary.setText(summary)
        visible = changes if self.change_more.isChecked() else changes[:3]
        self.change_rows.setText('\n'.join(f'{row.label}   {row.before} → {row.after}' for row in visible))
        self.change_rows.setVisible(bool(visible))
        self.change_more.setVisible(len(changes) > 3)

    def _load_fc_values(self,values):
        self._loading=True
        for g,key in ((4,'arming'),(7,'flight'),(112,'timeouts'),(134,'setup_values')):
            if g in values:self.configuration[key]=list(values[g])
        if 132 in values:
            self.configuration['receiver']['values']=list(values[132])
            for i,c in enumerate(self.rx_reverse):c.setChecked(bool(values[132][4*i+3]))
        if 134 in values:
            cfg=values[134];key=self.profile_keys[cfg[0]];self.configuration['pid']['selected']=key
            self.pid_buttons[key].setChecked(True);source=('PPM','AP','USB')[cfg[1]];self.configuration['input_source']=source;self.input_buttons[source].setChecked(True)
            for w,v in zip(self.mapping_boxes,cfg[2:6]):w.setCurrentIndex(v-1)
            for w,v in zip(self.idle_boxes,cfg[7:11]):w.setValue(v)
        if 2 in values:self.configuration['pid']['profiles'][self.configuration['pid']['selected']]['rate']=list(values[2])
        if 3 in values:self.configuration['pid']['profiles'][self.configuration['pid']['selected']]['angle']=list(values[3])
        if 6 in values and not equal_values(self.sensor_panel.snapshot()['offsets'],values[6]):self.sensor_panel.set_offsets(values[6])
        self._load_arming();self._loading=False;self.loaded_identity=self.fc_identity

    def _load_arming(self):
        for widget,value in zip(self.arming_fields,self.configuration['arming']):widget.setValue(value)
        flight=self.configuration['flight'];self.mode_channel.setCurrentIndex(flight[0]-1);self.mode_low.setCurrentIndex(flight[4]);self.mode_high.setCurrentIndex(flight[5])
        self.ppm_timeout.setValue(self.configuration['timeouts'][0]);self.digital_timeout.setValue(self.configuration['timeouts'][1])

    def _choose_profile(self,key):
        if key==self.configuration['pid']['selected']:return
        self.configuration['pid']['selected']=key;self.configuration['pid']['profiles'][key]={'rate':list(BASE_RATE),'angle':list(BASE_ANGLE)}
        self.configuration['setup_values'][0]=self.profile_keys.index(key)
        self._set_message('Aircraft draft changed. Save this profile before continuing.')

    def _save_aircraft(self):
        profile=self.configuration['pid']['profiles'][self.configuration['pid']['selected']]
        self._apply({134:self._setup_values(),2:profile['rate'],3:profile['angle']})

    def _choose_input(self,source):
        self.configuration['input_source']=source;self.configuration['setup_values'][1]=SOURCE_IDS[source]
        self.rx_capture=None;self.rx_result=None;self._update_navigation()

    def _save_input(self):
        source=SOURCE_IDS[self.configuration['input_source']]
        self._request('input',{'source':source})

    def _sensor_changed(self):
        if not self._loading:self.configuration['imu']=self.sensor_panel.snapshot()

    def _save_sensors(self):
        if not self.orientation_check.isChecked():return
        self.configuration['imu']=self.sensor_panel.snapshot()
        self._apply({6:self.configuration['imu']['offsets']},lambda:self._command('SENSOR_OK',[1,0,0,0]))

    def _draft_setup_values(self):
        cfg=list(self.configuration['setup_values']);cfg[0]=self.profile_keys.index(self.configuration['pid']['selected'])
        cfg[1]=SOURCE_IDS[self.configuration['input_source']];cfg[2:6]=[w.currentIndex()+1 for w in self.mapping_boxes]
        cfg[7:11]=[w.value() for w in self.idle_boxes]
        return cfg

    def _setup_values(self):
        cfg = self._draft_setup_values()
        self.configuration['setup_values'] = cfg
        return cfg

    def _mapping_changed(self, *args):
        if self._loading:
            return
        self.rx_capture = self.rx_result = None
        self.receiver_review_available = False
        self.rx_direction_check.setChecked(False)
        self.rx_progress.setValue(0)
        self.rx_extent.setText('Mapping changed')
        self.rx_status.setStyleSheet('')
        self.rx_status.setText('Capture the range for the new assignments.')
        self._refresh_receiver_preview(time.monotonic())
        self._update_navigation()

    def _reverse_changed(self, *args):
        if self._loading:
            return
        self.rx_direction_check.setChecked(False)
        self.rx_status.setStyleSheet('')
        self.rx_status.setText('Check movement in the new direction before saving.')
        self._refresh_receiver_preview(time.monotonic())
        self._update_navigation()

    def _refresh_receiver_preview(self, now):
        channels = None
        physical = None
        count = 0
        state, tag, detail = 'idle', 'Waiting', 'Waiting for raw receiver data.'
        self.rx_available = False
        if not self.connected:
            tag, detail = 'Offline', 'Connect the kit to see its receiver.'
        elif self.configuration['input_source'] != 'PPM':
            tag, detail = 'Inactive', 'PPM calibration applies to the PPM flight input.'
        elif self.raw is not None:
            try:
                if type(self.rx_stamp) not in (float, int) or not 0 <= now - self.rx_stamp <= MAX_TELEMETRY_AGE_S:
                    raise ValueError('Raw receiver telemetry has expired.')
                physical, count = raw_channels(self.raw, 1)
                calibration = list(self.configuration['receiver']['values'])
                for i, check in enumerate(self.rx_reverse):
                    calibration[4*i+3] = int(check.isChecked())
                channels = normalize_channels(physical, calibration, [w.currentIndex()+1 for w in self.mapping_boxes],
                                              self.configuration['setup_values'][6])
                self.rx_available = True
                state, tag, detail = 'live', f'Live · {count} CH', 'Fresh raw receiver pulses.'
            except (ValueError, TypeError) as exc:
                state, tag, detail = 'warning', 'No input', str(exc)
                if physical is not None:
                    state, tag = 'error', 'Mapping'
        self.rx_sticks.set_sample(channels, state, tag, detail)
        for i in range(8):
            text = str(physical[i]) if physical and i < count else '—'
            item = self.rx_table.item(i, 1)
            if item.text() != text:
                item.setText(text)
        if channels is not None:
            details = ' · '.join(f'{axis} {v} µs' for axis, v in zip(('Roll', 'Pitch', 'Throttle', 'Yaw'), channels))
            self.rx_preview.setText('Calibrated preview · ' + details)
        else:
            self.rx_preview.setText(detail)

    def _capture_progress(self):
        capture = self.rx_capture
        spans = []
        complete = []
        for role, channel in zip(('Roll', 'Pitch', 'Throttle', 'Yaw'), capture.mapping):
            i = channel - 1
            span = 0 if capture.minimum[i] is None else capture.maximum[i] - capture.minimum[i]
            spans.append(min(1., span / 400.))
            if span >= 400:
                complete.append(role)
        # 100% is reserved for a successful neutral capture. The other 90%
        # combines per-axis travel and the minimum sampling time/frame count.
        earned = min(capture.progress, sum(spans) / 4.)
        self.rx_progress.setValue(round(earned * 90))
        self.rx_extent.setText(f'{len(complete)} / 4 axes swept · {capture.samples} frames')
        self.rx_extent.setToolTip(', '.join(complete))
        if earned == 1. and not self.rx_status.property('retry'):
            self.rx_status.setText('Centre roll, pitch and yaw. Lower throttle, then capture neutral.')

    def _start_receiver(self):
        if not self._ready() or self.configuration['input_source']!='PPM':return
        try:
            baseline=list(self.configuration['receiver']['values'])
            for i,w in enumerate(self.rx_reverse):baseline[4*i+3]=int(w.isChecked())
            self.rx_capture=ReceiverCapture(baseline,[w.currentIndex()+1 for w in self.mapping_boxes],time.monotonic(),self.fc_identity)
            self.rx_result=None;self.rx_progress.setValue(0);self.rx_extent.setText('0 / 4 axes swept · 0 frames')
            self.rx_status.setProperty('retry',False);self.rx_status.setStyleSheet('');self.rx_status.setText('Move each stick from end to end.');self.rx_direction_check.setChecked(False)
        except ValueError as exc:self._set_message(str(exc),True)
        self._update_navigation()

    def _finish_receiver(self):
        if not self.rx_capture:return
        try:
            result=self.rx_capture.finish(self.raw,self.rx_stamp,time.monotonic(),self.fc_identity)
            self.rx_result=result;self.receiver_review_available=True;self.configuration['receiver']={'values':list(result['values']),'result':result}
            self.configuration['receiver_calibration']='captured';self.rx_capture=None;self.rx_progress.setValue(100)
            self.rx_extent.setText('4 / 4 axes · neutral captured');self.rx_status.setStyleSheet('color:#9be3c1')
            self.rx_status.setText('Captured · check directions and save.')
        except (ValueError,TypeError) as exc:
            self.rx_status.setText(str(exc));self.rx_status.setProperty('retry',True);self.rx_status.setStyleSheet('color:#ffc886')
        self._update_navigation()

    def _save_receiver(self):
        if self.rx_capture or not self.rx_direction_check.isChecked() or not (self.rx_result or self.receiver_review_available):return
        values=list(self.configuration['receiver']['values'])
        for i,w in enumerate(self.rx_reverse):values[4*i+3]=int(w.isChecked())
        self.configuration['receiver']['values']=values
        self._apply({132:values,134:self._setup_values()},lambda:self._command('RX_OK',[1,0,0,0]))

    def _select_esc(self,key):
        self.configuration['esc']=esc_configuration(key);self.esc_compatible.setChecked(False);self.esc_response.setChecked(False);self.esc_skip_check.setChecked(False)
        self._set_message('ESC profile selected. Confirm its actual supported calibration procedure before scheduling.')

    def _motor_selection_changed(self,*args):
        self.motor_view.set_selection(self.motor_choice.currentData())
        if self.motor_running:self._stop_motor()
        self.motor_slider.setValue(1000);self.motor_verified_check.setChecked(False)

    def _start_motor(self):
        if not(self._ready() and self._imu_ready() and self.status[3] in (4,5) and self.propeller_check.isChecked() and self.output_prop_check.isChecked() and self.battery_check.isChecked()):return
        self.motor_slider.setValue(1000)
        self._command('MOTOR_START',[self.motor_choice.currentData(),1,0,0])

    def _imu_ready(self):
        status=self.live.get(120);imu=self.live.get(21)
        return bool(status and len(status)>2 and status[2] and imu and len(imu)>=6 and
                    self.imu_stamp is not None and 0<=time.monotonic()-self.imu_stamp<=.5)

    def _stop_motor(self):
        active=self.motor_running or bool(self.status and self.status[8]);self.motor_running=False;self.motor_slider.setValue(1000)
        if active and self.connected:
            # Emergency commands bypass this widget's normal in-flight request gate.
            self.action_requested.emit('command',{'command':'MOTOR_STOP','args':[0,0,0,0]})

    def _record_minimum(self):
        if not self.motor_running:return
        mask=self.motor_choice.currentData();value=self.motor_slider.value()
        for i in range(4):
            if mask&(1<<i):
                self.motor_candidate[i]=value;self.idle_boxes[i].setValue(value);self.minimum_labels[i].setText(f'Start recorded: {value} µs')
        self.configuration['motors']['candidate_min_us']=list(self.motor_candidate)
        self._set_message('Starting command recorded. Stop the motor, verify its direction, then save the idle values.')

    def _confirm_motor(self):
        if not self.motor_verified_check.isChecked() or self.motor_running:return
        mask=self.motor_choice.currentData()
        self._apply({134:self._setup_values()},lambda:self._command('MOTOR_OK',[mask,1,0,0]))

    def _arming_values(self):
        flight=list(self.configuration['flight'])
        flight[0]=self.mode_channel.currentIndex()+1;flight[4]=self.mode_low.currentIndex();flight[5]=self.mode_high.currentIndex()
        return {4:[w.value() for w in self.arming_fields],7:flight,
                112:[self.ppm_timeout.value(),self.digital_timeout.value()]}

    def _arming_matches_fc(self):
        if not hasattr(self,'mode_channel'):return False
        values=self._arming_values()
        return all(equal_values(value,self.live.get(group) or self.last_settings.get(group) or []) for group,value in values.items())

    def _save_arming(self):
        values=[w.value() for w in self.arming_fields];flight=list(self.configuration['flight'])
        flight[0]=self.mode_channel.currentIndex()+1;flight[4]=self.mode_low.currentIndex();flight[5]=self.mode_high.currentIndex()
        if flight[0] in self._setup_values()[2:6] or flight[4]==flight[5]:
            self._set_message('Flight-mode channel must be separate from the four stick channels, with different Low/High modes.',True);return
        self.configuration.update(arming=values,flight=flight,timeouts=[self.ppm_timeout.value(),self.digital_timeout.value()])
        self._apply({4:values,7:flight,112:self.configuration['timeouts']})

    def _restore_timing(self):
        defaults=default_configuration()
        self.configuration['arming']=defaults['arming'];self.configuration['timeouts']=defaults['timeouts'];self._load_arming()
        self._set_message('Default timing loaded as a draft. Save arming settings to apply it.')

    def _snapshot(self):
        self.configuration['imu']=self.sensor_panel.snapshot();self._setup_values()
        values=self._arming_values();self.configuration.update(arming=values[4],flight=values[7],timeouts=values[112])
        return deepcopy(self.configuration)

    def _finalize(self):
        if not self.save_ack.isChecked() or not self._requirements_ready():return
        self._request('finalize', {'groups': self._final_groups(),
                                   'acc_origin': self.sensor_panel.snapshot()['offsets_origin']})

    def _final_groups(self):
        # Use the exact same draft for the comparison and the final save request.
        cfg = self.configuration
        profile = cfg['pid']['profiles'][cfg['pid']['selected']]
        return {2: profile['rate'], 3: profile['angle'],
                6: list(self.sensor_panel.config['offsets']),
                132: cfg['receiver']['values'], 134: self._draft_setup_values(),
                **self._arming_values()}

    def _requirements_ready(self):
        s=self.status
        return bool(not self.reset_unverified and s and s[0] and s[5] and (s[6] or self.configuration['input_source']!='PPM') and
                    s[3] in (4,5) and s[4]==15 and self._arming_matches_fc() and not s[8] and s[2] not in (2,3,4))

    def _show_step(self,index):
        if not 0 <= index < len(self.STEP_TITLES):
            return
        if index == 9 and not self.restart_view_active:
            self._open_restart_from_review()
            return
        if self.restart_view_active and index != 9:
            return
        if index!=self.step and self.step != 9:
            self.suspend('Setup step changed')
        changed=index!=self.step
        self.step=index;self.stack.setCurrentIndex(index);self.step_label.setText('Step 10 · Optional' if index == 9 else f'Step {index+1} of 9')
        if changed:
            self.scrolls[index].verticalScrollBar().setValue(0)
        if changed and self.isVisible():focus_page(self.scrolls[index])
        if not self._loading:self._checkpoint()
        self._update_navigation()

    def advance(self):
        if not self.next_button.isEnabled():return
        if self.restart_view_active or (self.step == 8 and self.finalized_this_visit):
            self._leave_completed_setup()
            return
        if self.step==8:self._finalize();return
        target=self._resume_target() if self.step==0 else self.step+1
        if target==4 and self.configuration['input_source']!='PPM':target=5
        self._show_step(target)

    def back(self):
        if self.restart_view_active:
            receipt = self.restart_page.receipt
            same_kit = bool(receipt and self.restart_page.context[2] == receipt['kit_id'])
            if self._restart_from_review and same_kit:
                self.restart_view_active = False
                self._show_step(8)
                self._set_message('Setup complete.')
            else:
                self._leave_completed_setup()
            return
        if self.step==0:return
        target=self.step-1
        if target==4 and self.configuration['input_source']!='PPM':target=3
        self._show_step(target)

    def _tick(self):
        if self.restart_view_active:
            return
        if self.visit_active and not self.finalized_this_visit and self.connected and not self.begin_requested and not self.operation_busy and not self.external_busy:
            self.begin_requested=True
            self._request('begin',{'props_removed':self.propeller_check.isChecked()})
        now=time.monotonic()
        if self.motor_running:
            if not(self.visit_active and self.connected and self.disarmed and self.status and self.status[8] and self.step==6):
                self._stop_motor()
            elif not self.operation_busy and not self.external_busy and now-self.motor_last_tx>=.1:
                self.motor_last_tx=now
                self.action_requested.emit('command',{'command':'MOTOR_SET','args':[self.motor_last_mask,self.motor_slider.value(),0,0]})
        self._update_navigation()

    def _sensor_capture_safe(self,safe):
        return safe

    def receive_telemetry(self,values,stamp,now,identity):
        if self.restart_view_active:
            return
        if self.fc_identity is not None and identity!=self.fc_identity:
            self.rx_sticks.set_sample(None, 'idle', 'Waiting', 'New receiver connection.')
            self.rx_available = False
            self.rx_capture=None;self.rx_result=None;self.motor_running=False;self.motor_slider.setValue(1000)
            self.begin_requested=False;self.begin_confirmed=False;self.loaded_identity=None
        self.fc_identity=identity;self.live={k:v for k,v in values.items() if v is not None};self.imu_stamp=stamp
        s=self.status
        if s:
            if self.kit_id is not None and s[15]!=self.kit_id:
                self.opening_settings = None
                self.opening_kit = None
                self.review_read_session = None
                self.rx_progress.setValue(0)
                self.rx_extent.setText('Roll  ·  Pitch  ·  Throttle  ·  Yaw')
                self.rx_status.setStyleSheet('')
                self.rx_status.setText('Sweep all four axes from end to end.')
                self.orientation_check.setChecked(False);self.rx_direction_check.setChecked(False)
                self.motor_candidate=[None]*4;self.esc_response.setChecked(False);self.receiver_review_available=False
                self.last_status=None;self.last_settings={};self.begin_confirmed=False;self.begin_requested=False;self._show_step(0)
                self.propeller_check.setChecked(False);self.configuration['checks']={}
            self.kit_id=s[15];self.last_status=list(s);self.reconnect_waiting=False
            for group in (2,3,4,6,7,112,132,134):
                if self.live.get(group) is not None:self.last_settings[group]=list(self.live[group])
            if s[6] and self.live.get(134):
                saved_mapping = list(self.live[134][2:6])
                if saved_mapping == [box.currentIndex() + 1 for box in self.mapping_boxes]:
                    self.receiver_review_available = True
                    if self.rx_capture is None and self.rx_result is None and self.rx_status.text() == 'Sweep all four axes from end to end.':
                        self.rx_progress.setValue(100)
                        self.rx_extent.setText('Saved calibration')
                        self.rx_status.setText('The kit reports a verified receiver calibration.')
        safe=bool(self.connected and self.disarmed and s and s[0] and self.propeller_check.isChecked())
        self.sensor_panel.update_telemetry(self.live,stamp,now,identity,self.demo,self._sensor_capture_safe(safe))
        self.raw=self.live.get(131);self.rx_stamp=self.live.get('_raw_stamp')
        self._refresh_receiver_preview(now)
        if self.rx_capture:
            state = self.rx_capture.add(self.raw, self.rx_stamp, now, identity, safe)
            if state == 'error':
                self.rx_status.setText(self.rx_capture.error)
                self.rx_status.setStyleSheet('color:#ffafb9')
                self.rx_extent.setText('Capture stopped · retry when the signal is live')
                self.rx_progress.setValue(0)
                self.rx_capture = None
            else:
                self._capture_progress()
        rx_values=self.configuration['receiver']['values']
        for i in range(8):
            minimum=self.rx_capture.minimum[i] if self.rx_capture else None;maximum=self.rx_capture.maximum[i] if self.rx_capture else None
            for col,value in ((2,minimum if minimum is not None else rx_values[4*i]),(3,rx_values[4*i+1]),(4,maximum if maximum is not None else rx_values[4*i+2])):self.rx_table.item(i,col).setText(str(value))
        if s and not s[8] and self.motor_running:
            self.motor_running=False;self.motor_slider.setValue(1000)
        self._update_navigation()

    def _restart_navigation(self):
        # Independent inspection can start from Welcome, even with a different kit connected.
        # Previously shown setup checks and arming indicators do not represent that kit.
        if self._restart_chrome_state == self.restart_page.state:
            return
        self._restart_chrome_state = self.restart_page.state
        self.lock_note.setText('Read-only check')
        set_visual_state(self.lock_note, 'waiting')
        self.restart_open_button.hide()
        self.retry_begin.hide()
        self.message.hide()
        self.next_button.setText('Done')
        self.next_button.setEnabled(True)
        self.back_button.setEnabled(True)
        for i, control in enumerate(self.step_buttons):
            optional = i == 9
            verified = optional and self.restart_page.state == 'verified'
            error = optional and self.restart_page.state in ('error', 'mismatch')
            control.set_step_state(verified, False, error)
            control.setEnabled(optional)
            control.setChecked(optional)
            self.step_picker.model().item(i).setEnabled(optional)
            title = self.STEP_TITLES[i]
            self.step_picker.setItemText(i, f'{i + 1:02d}  {title}')
        self.step_picker.setCurrentIndex(9)
        self.step_progress.setRange(0, 10)
        self.step_progress.setValue(10)

    def _update_navigation(self,*args):
        if not hasattr(self,'next_button'):return
        if self.restart_view_active:
            self._restart_navigation()
            return
        self._refresh_change_review()
        s=self.status;ready=self._ready();props=self.propeller_check.isChecked();ppm=self.configuration['input_source']=='PPM'
        remembered=s or self.last_status
        calibration_busy=bool(s and (s[3] in (1,2) or (s[3] in (3,6) and not self._imu_ready())))
        edit_ready=ready and not calibration_busy
        locked=bool(s and s[0]);done=bool(s and s[1] and not s[0] and self.finalized_this_visit)
        self.read_current_button.setEnabled(ready and not self.motor_running)
        reset_safe=bool(ready and props and s and s[2]>0 and not s[8] and s[3]!=2
                        and not (s[3] in (3,6) and not self._imu_ready())
                        and not self.motor_running and not self.sensor_panel.active and self.rx_capture is None)
        self.reset_button.setEnabled(reset_safe and self.reset_confirm.isChecked())
        self.reset_confirm.setEnabled(not self.operation_busy)
        self.current_settings_status.setText(
            'Reset not verified. Reload the current kit settings before continuing.' if self.reset_unverified else
            'Current settings loaded.' if ready and self.loaded_identity is not None else
            'Reading kit…' if self.operation_busy else
            'Connect to load saved settings.')
        self.lock_note.setText(('DEMO · ' if self.demo else '')+(self._saved_label('SETUP SAVED') if done else
            'ARM LOCKED · props removed until finish' if locked else
            'Waiting for setup lock…' if self.connected else 'Kit offline'))
        self.retry_begin.setEnabled(self.connected and not self.operation_busy and not self.external_busy)
        if not s and self.last_status:
            self.lock_note.setText('Waiting for kit status' if self.connected else 'OFFLINE · showing last saved checks')
        complete=[bool(locked and props),False,False,bool(remembered and remembered[5]),bool(not ppm or remembered and remembered[6]),
                  bool(remembered and remembered[3] in (4,5)),bool(remembered and remembered[4]==15),self._arming_matches_fc(),done]
        current134=self.live.get(134) or self.last_settings.get(134)
        if current134:
            complete[1]=current134[0]==self.profile_keys.index(self.configuration['pid']['selected'])
            complete[2]=current134[1]==SOURCE_IDS[self.configuration['input_source']]
        set_visual_state(self.lock_note, 'armed' if done and self._live_arm_state() is True else
                         'complete' if done else 'locked' if locked else 'waiting')
        navigation_open = (props and self.begin_confirmed and locked and not self.operation_busy
                           and not self.motor_running) or self.finalized_this_visit
        for i, control in enumerate(self.step_buttons):
            skipped = i == 4 and not ppm
            if i == 9:
                enabled = self.finalized_this_visit and bool(self.restart_page.receipt)
                checked = self.restart_page.state == 'verified' and enabled
                error = enabled and self.restart_page.state in ('mismatch', 'error')
            else:
                enabled = bool((i == 0 or navigation_open) and not skipped)
                checked = complete[i] and not skipped
                error = bool(self.last_error and self._message_step == i)
            control.set_step_state(checked, skipped, error)
            control.setChecked(i == self.step)
            control.setEnabled(enabled)
            prefix = '–' if skipped else '✓' if checked else f'{i + 1:02d}'
            title = f'{prefix}  {self.STEP_TITLES[i]}'
            caption = title.replace('&', '&&')
            if control.text() != caption:
                control.setText(caption)
            if self.step_picker.itemText(i) != title:
                self.step_picker.setItemText(i, title)
            picker_item = self.step_picker.model().item(i)
            if picker_item.isEnabled() != enabled:
                picker_item.setEnabled(enabled)
        self.step_picker.setCurrentIndex(self.step)
        self.step_progress.setRange(0, 9)
        self.step_progress.setValue(self.step + 1)
        self.restart_open_button.setVisible(self.step == 8 and self.finalized_this_visit and not hasattr(self, 'scope'))
        self.restart_open_button.setEnabled(bool(self.restart_page.receipt))
        if self._shared_chrome:
            self.retry_begin.setVisible(self.connected and not self.begin_confirmed
                                        and not self.operation_busy and not self.finalized_this_visit)
        self.back_button.setEnabled(self.step>0 and not self.operation_busy)
        allowed=ready and props and not self.reset_unverified
        if self.step==0:allowed=allowed and locked
        elif self.step==1:allowed=allowed and complete[1]
        elif self.step==2:allowed=allowed and complete[2]
        elif self.step==3:allowed=allowed and complete[3]
        elif self.step==4:allowed=allowed and complete[4]
        elif self.step==5:allowed=allowed and complete[5]
        elif self.step==6:allowed=allowed and complete[6] and not self.motor_running
        elif self.step==7:allowed=allowed and complete[7]
        elif self.step==8:allowed=allowed and self._requirements_ready() and self.save_ack.isChecked()
        self.next_button.setText('Save && finish' if self.step==8 else
                                'Resume ESC calibration' if self.step==0 and self._resume_target()==5 else
                                'Use current settings' if self.step==0 else 'Next');self.next_button.setEnabled(bool(allowed))
        if self.step == 8 and self.finalized_this_visit:
            self.next_button.setText('Done')
            self.next_button.setEnabled(True)
        self.footer_note.setText('DEMO ONLY · no physical calibration or flight readiness' if self.demo else self._saved_label('Saved to kit') if done else 'Setup in progress · flight arming locked' if locked else 'Waiting for the kit to confirm its setup lock')
        for b in (self.aircraft_apply,self.input_apply,self.arming_save):b.setEnabled(edit_ready and props)
        self.sensor_save.setEnabled(edit_ready and self._imu_ready() and props and self.orientation_check.isChecked() and not self.sensor_panel.active)
        preview_now = time.monotonic()
        self._refresh_mode_test(preview_now)
        signal_expired = self.rx_available and (self.rx_stamp is None or preview_now - self.rx_stamp > MAX_TELEMETRY_AGE_S)
        if (signal_expired or (not self.connected and self.rx_sticks.signal_label.text() != 'Offline')
                or (self.connected and not ppm and self.rx_sticks.signal_label.text() != 'Inactive')):
            self._refresh_receiver_preview(preview_now)
        rx_ready=edit_ready and props and ppm and self.rx_available
        self.rx_start.setEnabled(rx_ready and self.rx_capture is None);self.rx_finish.setEnabled(rx_ready and self.rx_capture is not None)
        self.rx_save.setEnabled(rx_ready and self.rx_capture is None and (self.rx_result is not None or self.receiver_review_available) and self.rx_direction_check.isChecked())
        for c in self.rx_reverse:c.setEnabled(self.rx_capture is None and ready)
        for c in self.mapping_boxes:c.setEnabled(self.rx_capture is None and ready)
        if not ppm:
            self.rx_skip_note.setText('AP / USB uses digital channels. Continue to the next step.')
        elif self.rx_sticks.quality in ('warning', 'error'):
            self.rx_skip_note.setText(self.rx_preview.text())
        else:
            self.rx_skip_note.setText('Move the physical transmitter sticks to check their direction.')
        esc_state=s[3] if s else 0;esc_ready=edit_ready and self._imu_ready() and props and bool(s and s[5]) and (not ppm or bool(s and s[6]))
        self.esc_schedule.setEnabled(esc_ready and self.esc_compatible.isChecked() and esc_state not in (1,2))
        self.esc_verify.setEnabled(ready and self._imu_ready() and esc_state==3 and self.esc_response.isChecked())
        self.esc_skip.setEnabled(esc_ready and self.esc_skip_check.isChecked() and esc_state not in (1,2))
        names={0:'Not checked',1:'PENDING RESTART',2:'Calibrating',3:'Confirm ESC response',4:'ESC response confirmed',5:'Calibration skipped',6:'Interrupted / failed'}
        detail=names.get(esc_state,'Unknown');progress={0:0,1:10,2:50,3:90,4:100,5:100,6:0}.get(esc_state,0)
        if s and s[3]==2:
            detail='HIGH signal · calibration running' if s[2]==3 else 'LOW signal · completing calibration'
            progress=35 if s[2]==3 else 65
        elif s and s[3] in (3,6) and not self._imu_ready():
            status=self.live.get(120);samples=status[5] if status else 0
            detail=f'Signal sequence finished · waiting for automatic sensor startup ({samples}/2000 samples)' if s[3]==3 else 'Calibration interrupted · waiting for sensors before retry'
            progress=80+int(min(2000,samples)/2000*10) if s[3]==3 else 0
        elif not s:
            previous=names.get(remembered[3],'Unknown') if remembered else 'No saved result yet'
            detail='OFFLINE · last confirmed: '+previous+'. Reconnect to read the result.';progress=0
        if s and str(s[14]).startswith('IMU_STARTUP_FAILED'):
            detail='Sensor startup failed. Keep motors stopped, inspect the IMU connection and restart the kit. Saved ESC result and setup checks are retained.'
            progress=0
        self.esc_status.setText(detail+(f' · {s[14]}' if s and s[14] else ''))
        self.esc_progress.setValue(progress)
        self.esc_sequence.sync(esc_state if s else None, bool(s and str(s[14]).startswith('IMU_STARTUP_FAILED')))
        self.esc_read_status.setEnabled(self.connected and not self.operation_busy and not self.external_busy)
        motor_ready=ready and props and self._imu_ready() and bool(s and s[3] in (4,5))
        self.motor_start.setEnabled(motor_ready and not self.motor_running and self.output_prop_check.isChecked() and self.battery_check.isChecked())
        self.motor_stop.setEnabled(bool(self.connected and (self.motor_running or s and s[8])))
        self.motor_slider.setEnabled(self.motor_running and not self.finalized_this_visit);self.motor_choice.setEnabled(not self.motor_running and not self.operation_busy)
        for editor in self.idle_boxes:editor.setEnabled(not self.motor_running and ready)
        self.record_min.setEnabled(self.motor_running);self.motor_confirm.setEnabled(motor_ready and not self.motor_running and self.motor_verified_check.isChecked())
        self.motor_view.set_outputs(s[9:13] if s else None)
        tested = sum(bool(s[4] & (1 << i)) for i in range(4)) if s else 0
        self.motor_status.setText(('Test active' if s[8] else 'Test inactive') +
                                  f'  ·  {tested} / 4 verified' if s else 'Waiting for kit status')
        self.arming_guide.setText('PPM: low throttle · yaw right ARM / left DISARM' if ppm else 'AP / USB: use ARM and DISARM buttons.')
        self.arming_status.setText('Settings saved.' if complete[7] else 'Unsaved settings')
        stages = (('Aircraft', PROFILE_NAMES[self.configuration['pid']['selected']], complete[1]),
                  ('Flight input', self.configuration['input_source'], complete[2]),
                  ('Sensors', 'Verified' if s and s[5] else 'Pending', complete[3]),
                  ('Receiver', 'Skipped · digital input' if not ppm else 'Verified' if s and s[6] else 'Pending', complete[4]),
                  ('ESC', names.get(esc_state, 'Unknown'), complete[5]),
                  ('Motors', f'{tested} of 4 verified', complete[6]),
                  ('Arming settings', 'Current kit values' if complete[7] else 'Save timing & modes', complete[7]),
                  ('Storage', 'Saved and verified' if done else 'Final save required', done))
        for name, value, checked in stages:
            tone = 'done' if checked else 'pending'
            if not s:
                tone, value = 'unknown', 'Waiting for kit'
            elif name == 'ESC' and esc_state == 6:
                tone = 'error'
            elif (name == 'Receiver' and not ppm) or (name == 'ESC' and esc_state == 5):
                tone = 'skip'
            self.review_tiles[name].set_result(value, tone)
        if not done:
            if not s:
                receipt = 'Connect to read the current kit checks.'
            elif self.operation_busy and self.pending and self.pending[0] == 'finalize':
                receipt = 'Saving and verifying the stored setup…'
            elif self._requirements_ready():
                receipt = 'Kit checks ready for final save.'
            else:
                receipt = 'Complete the pending checks before saving.'
            self.fc_save_status.setText(receipt)


    def diagnostic_snapshot(self):
        return {'step':self.step+1,'stage':'complete' if self.finalized_this_visit else 'setup',
                'configuration':self._snapshot(),'setup_status':list(self.status) if self.status else None,
                'wizard_complete':bool(self.status and self.status[1] and not self.status[0]),
                'hardware_applied':bool(not self.demo and self.status and self.status[1] and not self.status[0]),
                'demo':self.demo,'motor_test_active':self.motor_running,'receiver_capture_active':self.rx_capture is not None,
                'imu_capture_active':self.sensor_panel.active,'pending_action':deepcopy(self.pending),'last_error':self.last_error,
                'reconnect_waiting':self.reconnect_waiting,'last_confirmed_setup_status':self.last_status,
                'checkpoint_error':self.checkpoint_error,'reset_unverified':self.reset_unverified}
