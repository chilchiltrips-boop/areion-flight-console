"""Direct IMU/ESC maintenance pages using the existing guarded calibration engine.

Opening a page only monitors. Explicit Begin acquires the firmware setup lock;
Finish verifies current stored settings without replaying unrelated UI drafts.
"""
from copy import deepcopy
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout
from .widgets import label
from .scroll_guard import page_action_button as button
from .wizard_extended import ExtendedSetupWizard
from .model import equal_values


class CalibrationPage(ExtendedSetupWizard):
    def __init__(self,draft_path,scope):
        if scope not in ('imu','esc','receiver'):raise ValueError('Choose IMU, ESC or receiver calibration')
        self.scope=scope;self.session_requested=False;self._direct_built=False
        super().__init__(draft_path)
        self._direct_built=True
        self._show_step({'imu':3,'esc':5,'receiver':4}[scope])
        self._update_navigation()

    def _build(self):
        # Share tested capture/motor/ESC actions and telemetry with setup. The
        # setup-only forms stay hidden; no wizard navigation is exposed here.
        super()._build()
        title=self.title_label
        title.setText({'imu':'IMU calibration','esc':'ESC calibration','receiver':'PPM receiver calibration'}[self.scope])
        self.step_label.hide();self.nav_area.hide()
        for control in self.step_buttons:control.hide()
        self.back_button.hide();self.retry_begin.hide()
        self.next_button.clicked.disconnect(self.advance)
        self.next_button.clicked.connect(self._finish_calibration)
        controls=QHBoxLayout()
        controls.addWidget(self.propeller_check,1)
        self.propeller_check.toggled.connect(self._props_changed)
        self.begin_button=button('Begin calibration',self.begin_calibration,'primary')
        controls.addWidget(self.begin_button)
        self.propeller_check.setObjectName('wizardDirectCheck')
        self.layout().insertLayout(self.layout().indexOf(self.stack),controls)
        self.save_ack.setText('Checks reviewed · props off · motors stopped.')
        self.save_ack.setObjectName('wizardDirectCheck')
        self.layout().insertWidget(self.layout().count()-1,self.save_ack)
        self.direct_tabs={}
        if self.scope=='receiver':
            receiver_note=label('Requires saved PPM input.','notice')
            receiver_note.setWordWrap(True);self.scrolls[4].widget().layout().insertWidget(2,receiver_note)
        if self.scope=='esc':
            tabs=QHBoxLayout()
            for step,text in ((5,'ESC endpoints'),(6,'Motor verification')):
                control=button(text,lambda checked=False,n=step:self._show_step(n))
                control.setCheckable(True);self.direct_tabs[step]=control;tabs.addWidget(control)
            tabs.addStretch();self.layout().insertLayout(self.layout().indexOf(self.stack),tabs)
            sounds=label('ESC controls its own tones.','muted')
            sounds.setWordWrap(True);self.scrolls[5].widget().layout().insertWidget(2,sounds)
        self.message.setText('Connect kit · remove props.')

    def _show_step(self,index):
        home={'imu':3,'esc':5,'receiver':4}[self.scope]
        if index not in {'imu':(3,),'esc':(5,6),'receiver':(4,)}[self.scope]:index=home
        super()._show_step(index)

    def on_enter(self,connection_options=None):
        # Base handles connection options and clears session confirmations.
        # Disable its automatic BEGIN: monitoring must never mutate the kit.
        super().on_enter(connection_options)
        self.visit_active=False;self.session_requested=False
        self._show_step({'imu':3,'esc':5,'receiver':4}[self.scope])
        self._set_message('')
        self._update_navigation()

    def _props_changed(self,checked):
        if not checked:self.suspend('Propeller-removal confirmation withdrawn')

    def begin_calibration(self):
        if not self.begin_button.isEnabled():return
        self.session_requested=True;self.visit_active=True;self.finalized_this_visit=False
        self.begin_requested=True
        self._request('begin',{'props_removed':True})

    def _request(self,action,payload,after=None):
        if action=='read' and self.connected and not (self.status and self.status[0]):
            if self.operation_busy:return False
            self.operation_busy=True;self.pending=(action,deepcopy(payload));self.after_action=after
            self._set_message('Reading current kit settings…');self._update_navigation()
            self.action_requested.emit(action,payload);return True
        if action=='begin':
            if not self.session_requested or not self.propeller_check.isChecked():return False
        elif action!='read' and not self.session_requested:
            self._set_message('Begin calibration before changing kit settings.',True);return False
        return super()._request(action,payload,after)

    def _tick(self):
        # Continue an already started motor lease, but never acquire a lock or
        # replay a calibration automatically after reconnect/navigation.
        if not self.isVisible() and not self.motor_running:return
        requested=self.begin_requested
        self.begin_requested=True
        try:super()._tick()
        finally:self.begin_requested=requested

    def _stop_motor(self):
        pending_start=bool(self.pending and self.pending[0]=='command' and
                           self.pending[1].get('command')=='MOTOR_START')
        if pending_start and self.connected:
            self.motor_running=False;self.motor_slider.setValue(1000)
            self.action_requested.emit('command',{'command':'MOTOR_STOP','args':[0,0,0,0]})
        else:super()._stop_motor()

    def suspend(self,reason='Calibration paused',request_stop=True):
        pending_start=bool(self.pending and self.pending[0]=='command' and
                           self.pending[1].get('command')=='MOTOR_START')
        super().suspend(reason,request_stop)
        if pending_start and request_stop:self._stop_motor()

    def _ready(self):
        return self.session_requested and super()._ready()

    def _sensor_capture_safe(self,safe):
        # Compute permission once before the shared panel renders. Previously
        # it rendered safe first, then unsafe, toggling capture buttons twice.
        return bool(safe and self.session_requested and self.isVisible())

    def action_finished(self,result,error):
        super().action_finished(result,error)
        if result and not error and result.get('complete',True):
            if result.get('action')=='finalize' and self.finalized_this_visit:
                self.session_requested=False;self.visit_active=False
                self._set_message('Calibration saved.')
            elif result.get('action')=='read':
                self._set_message('Kit settings loaded.')
        self._update_navigation()

    def _finish_ready(self):
        s=self.status
        return bool(self._ready() and self.propeller_check.isChecked() and self.loaded_identity==self.fc_identity
                    and s and s[5] and (s[6] or self.configuration['input_source']!='PPM')
                    and s[3] in (4,5) and s[4]==15 and not s[8]
                    and not self.sensor_panel.active and not self.motor_running and self.rx_capture is None
                    and self._imu_ready() and self.live.get(6) is not None
                    and equal_values(self.sensor_panel.snapshot()['offsets'],self.live[6])
                    and (self.scope!='esc' or (self.live.get(134) is not None and
                        [widget.value() for widget in self.idle_boxes]==self.live[134][7:11]))
                    and (self.scope!='receiver' or self._receiver_changes_saved()))

    def _receiver_changes_saved(self):
        values=list(self.configuration['receiver']['values'])
        for i,widget in enumerate(self.rx_reverse):values[4*i+3]=int(widget.isChecked())
        setup=self.live.get(134)
        return bool(setup and self.live.get(132) and equal_values(values,self.live[132])
                    and [widget.currentIndex()+1 for widget in self.mapping_boxes]==setup[2:6])

    def _finish_calibration(self):
        if not self.save_ack.isChecked() or not self._finish_ready():return
        # Every setting must already be saved by its own explicit calibration
        # button. Finalize only verifies FC state, never hidden profile drafts.
        self._request('finalize',{'groups':{}})

    def _update_navigation(self,*args):
        super()._update_navigation(*args)
        if not self._direct_built:return
        s=self.status;locked=bool(s and s[0]);complete=bool(s and s[1] and not s[0])
        busy=bool(s and (s[8] or s[3] in (1,2) or (s[3] in (3,6) and not self._imu_ready())))
        source_ready=self.scope!='receiver' or bool(self.live.get(134) and self.live[134][1]==0)
        self.begin_button.setEnabled(bool(self.connected and self.disarmed and s and not busy
            and source_ready
            and self.propeller_check.isChecked() and not self.operation_busy and not self.external_busy
            and not (self.session_requested and self.begin_confirmed)))
        self.begin_button.setText('Resume calibration' if locked else 'Begin calibration')
        # The unlocked monitoring path is read-only. Once setup is locked,
        # the shared request handler also requires confirmed disarmed state.
        read_state_allowed=not locked or self.disarmed
        self.sensor_panel.set_read_available(self.connected and read_state_allowed
            and not self.operation_busy and not self.external_busy)
        self.next_button.setText('Finish calibration')
        self.next_button.setEnabled(self._finish_ready() and self.save_ack.isChecked())
        for step,control in self.direct_tabs.items():
            control.setChecked(self.step==step);control.setEnabled(not self.operation_busy and not self.motor_running)
        self.lock_note.setText(('DEMO · ' if self.demo else '')+(
            'ARM LOCKED · calibration in progress' if locked else
            self._saved_label('CALIBRATION SAVED') if self.finalized_this_visit and complete else
            'MONITORING · calibration not started' if self.connected else
            'OFFLINE · reconnect kit'))
        if self.finalized_this_visit and complete:
            self.footer_note.setText(self._saved_label('Saved and verified'))
        elif self.session_requested and self.begin_confirmed:
            if self._finish_ready():text='Checks ready · finish calibration.'
            elif self.scope=='esc' and s and s[3] in (4,5) and s[4]!=15:
                text='Verify all four motors.'
            elif s and (not s[5] or (not s[6] and self.configuration['input_source']=='PPM')):
                text='Sensor / receiver check pending.'
            else:text='Calibration incomplete · ARM locked.'
            self.footer_note.setText(text)
        else:self.footer_note.setText('' if source_ready else 'Select PPM in setup first.')
        self.next_button.setToolTip(self.footer_note.text())
