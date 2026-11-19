"""Read-only transmitter check for Configuration → Input."""

import time

from PySide6.QtCore import QSignalBlocker
from PySide6.QtWidgets import QCheckBox, QDialog, QGridLayout, QHBoxLayout, QVBoxLayout

from .combo_box import ConsoleComboBox
from .health_board import COLORS
from .tx_link import MIN_SEPARATION, Verification, spare_channels
from .widgets import Card, button, label


class TxLinkPanel(Card):
    def __init__(self, owner):
        super().__init__('PPM transmitter link')
        self.owner = owner
        self.dialog = None
        self._severity = None
        row = QHBoxLayout()
        self.summary = label('Waiting for PPM input', 'muted')
        self.summary.setWordWrap(True)
        row.addWidget(self.summary)
        row.addStretch()
        self.check_button = button('Check transmitter…', self.open_check)
        row.addWidget(self.check_button)
        self.box.addLayout(row)

    def current(self):
        return self.owner._tx_link_status(time.monotonic(), self.owner._connected())

    def refresh(self, observation, profile, indication):
        summary = indication.label
        if profile:
            summary += ' · ' + ('PPM pulse loss' if profile['kind'] == 'pulse'
                                else f"CH{profile['channel']} failsafe")
        if self.summary.text() != summary:
            self.summary.setText(summary)
        if self._severity != indication.state:
            self._severity = indication.state
            face, edge, ink = COLORS[indication.state]
            self.summary.setStyleSheet(f'color:{ink}; background:{face}; border:1px solid {edge};'
                                       'border-radius:5px; padding:4px 8px; font-weight:bold;')
        if self.summary.toolTip() != indication.detail:
            self.summary.setToolTip(indication.detail)
        if self.dialog is not None and self.dialog.isVisible():
            self.dialog.refresh(observation, profile)

    def open_check(self):
        if self.dialog is None:
            self.dialog = TxLinkDialog(self)
        if not self.dialog.isVisible():
            self.dialog.begin()
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()


class TxLinkDialog(QDialog):
    TITLES = ('Transmitter on', 'Transmitter off', 'Transmitter back on', 'Check complete')
    ACTIONS = ('Capture ON', 'Capture OFF', 'Capture restored link', 'Capture complete')
    PROMPTS = ('Turn on the transmitter. Keep the sticks still and the throttle low.',
               'Switch the transmitter off. Keep the receiver and kit powered.',
               'Switch the transmitter back on. Return to the same stick and switch positions.',
               'Save this check to show transmitter status for this kit.')

    def __init__(self, panel):
        super().__init__(panel.owner)
        self.panel = panel
        self.setWindowTitle('Check PPM transmitter')
        self.resize(492, 390)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)
        self.heading = label('', 'cardTitle')
        self.prompt = label('')
        self.prompt.setWordWrap(True)
        layout.addWidget(self.heading)
        layout.addWidget(self.prompt)
        card = Card()
        grid = QGridLayout()
        self.channel = ConsoleComboBox()
        self.channel.setAccessibleName('Receiver loss indication')
        self.channel.addItem('PPM pulses stop', 0)
        self.channel.currentIndexChanged.connect(self._change_method)
        grid.addWidget(label('Receiver loss indication', 'muted'), 0, 0)
        grid.addWidget(self.channel, 0, 1)
        self.live = label('Waiting for the receiver', 'cardTitle')
        self.live.setWordWrap(True)
        grid.addWidget(label('Live reading', 'muted'), 1, 0)
        grid.addWidget(self.live, 1, 1)
        card.box.addLayout(grid)
        self.method_note = label('', 'muted')
        self.method_note.setWordWrap(True)
        card.box.addWidget(self.method_note)
        layout.addWidget(card)
        self.props_removed = QCheckBox('Propellers removed. Kit disarmed.')
        self.props_removed.toggled.connect(self._props_changed)
        layout.addWidget(self.props_removed)
        self.message = label('', 'muted')
        self.message.setWordWrap(True)
        self.message.setAccessibleName('Transmitter check status')
        layout.addWidget(self.message)
        layout.addStretch()
        row = QHBoxLayout()
        self.clear_button = button('Forget saved check', self._forget)
        self.reset_button = button('Start over', self._restart)
        self.capture_button = button('Capture ON', self._capture, 'primary')
        self.save_button = button('Save check', self._save, 'primary')
        row.addWidget(self.clear_button)
        row.addWidget(self.reset_button)
        row.addStretch()
        row.addWidget(button('Close', self.reject))
        row.addWidget(self.capture_button)
        row.addWidget(self.save_button)
        layout.addLayout(row)
        self.learner = Verification()
        self.candidate = None
        self.session = None
        self._methods = None
        self._method_edited = False

    @property
    def stage(self):
        return self.learner.step

    def _new_capture(self):
        self.learner = Verification(self.channel.currentData() or None)
        self.candidate = None
        self.message.clear()

    def begin(self):
        self.session = None
        self._methods = None
        self._method_edited = False
        with QSignalBlocker(self.props_removed):
            self.props_removed.setChecked(False)
        self._new_capture()
        self._update()

    def _restart(self):
        self._new_capture()
        self._update()

    def _change_method(self):
        self._method_edited = True
        self._restart()

    def _props_changed(self, checked):
        if not checked:
            self._new_capture()
        self._update()

    def _update(self):
        obs, profile, _ = self.panel.current()
        self.refresh(obs, profile)

    def _available_methods(self, obs, profile):
        channels = tuple(spare_channels(obs))
        if self._methods == channels:
            return
        self._methods = channels
        preferred = self.channel.currentData() if self._method_edited else (
            profile['channel'] if profile else 6)
        with QSignalBlocker(self.channel):
            self.channel.clear()
            self.channel.addItem('PPM pulses stop', 0)
            for ch in channels:
                self.channel.addItem(f'CH{ch} failsafe value', ch)
            self.channel.setCurrentIndex(max(0, self.channel.findData(preferred or 0)))
        self._new_capture()

    def refresh(self, obs, profile):
        identity = (obs.session, obs.kit_id, obs.mapping, obs.mode_channel) if obs.connected else None
        suitable = obs.connected and obs.source == 0 and obs.armed is False and bool(obs.kit_id)
        if (self.session is not None and self.session != identity) or (self.stage and not suitable):
            self.begin_after_loss()
        self.session = identity
        if self.stage == 0:
            self._available_methods(obs, profile)
        self.channel.setEnabled(suitable and self.stage == 0)
        channel = self.channel.currentData()
        self.method_note.setText(
            f'Reserve CH{channel}. Keep it fixed on the radio and set its receiver failsafe at least {MIN_SEPARATION} µs away.'
            if channel else 'Use this method if switching off the transmitter stops PPM output.')
        value = obs.marker(channel) if channel else None
        reading = '—'
        if obs.pulse is False:
            reading = 'No PPM pulses'
        elif obs.pulse is True:
            reading = f'{value:.0f} µs' if value is not None else 'PPM pulses present'
        self.live.setText(reading)
        self.heading.setText(self.TITLES[self.stage] if self.stage == 3 else
                             f'{self.stage + 1} of 3  ·  {self.TITLES[self.stage]}')
        if not obs.connected:
            prompt = 'Connect the kit to check its transmitter.'
        elif obs.armed is True:
            prompt = 'Disarm the kit before checking the transmitter.'
        elif obs.source not in (0, None):
            prompt = 'Select PPM receiver and save the input on the kit.'
        elif not suitable:
            prompt = 'Waiting for kit identity, input and arming status.'
        else:
            prompt = self.PROMPTS[self.stage]
        self.prompt.setText(prompt)
        self.capture_button.setText(self.ACTIONS[self.stage])
        self.capture_button.setVisible(self.stage < 3)
        self.save_button.setVisible(self.stage == 3)
        allowed = suitable and self.props_removed.isChecked()
        self.capture_button.setEnabled(bool(allowed and self.stage < 3))
        self.save_button.setEnabled(bool(allowed and self.candidate is not None))
        self.reset_button.setVisible(self.stage > 0)
        self.clear_button.setVisible(bool(profile))
        self.clear_button.setEnabled(bool(suitable and profile))

    def begin_after_loss(self):
        with QSignalBlocker(self.props_removed):
            self.props_removed.setChecked(False)
        self._new_capture()
        self._method_edited = False
        self._methods = None

    def _capture(self):
        obs, profile, _ = self.panel.current()
        self.refresh(obs, profile)
        if not self.capture_button.isEnabled():
            return
        try:
            self.candidate = self.learner.capture(obs)
        except ValueError as error:
            self.message.setText(str(error))
        else:
            self.message.clear()
        self.refresh(obs, profile)

    def _save(self):
        self._update()
        if not self.save_button.isEnabled():
            return
        try:
            self.panel.owner.save_tx_link_profile(self.candidate)
        except (OSError, ValueError) as error:
            self.message.setText(str(error))
            return
        self.accept()
        self.panel.refresh(*self.panel.current())

    def _forget(self):
        obs, profile, _ = self.panel.current()
        if not profile or not obs.kit_id or obs.armed is not False:
            return
        try:
            self.panel.owner.clear_tx_link_profile(obs.kit_id)
        except (OSError, ValueError) as error:
            self.message.setText(str(error))
            return
        self._restart()
        self.message.setText('Saved check cleared.')
