"""Rate and attitude editors for the flight controller's existing PID groups."""
from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtWidgets import (
    QCheckBox, QDoubleSpinBox, QGridLayout, QHBoxLayout, QLabel, QSizePolicy,
)
from zebjus_areion_link.schema import DRONE_GROUPS

from .model import pid_gain_word
from .scroll_guard import page_action_button
from .widgets import Card, SettingsCard, label


STYLE = """
QFrame#pidMatrix {background:#142a36;border:1px solid #36505d;border-radius:9px;}
QLabel#matrixTitle {color:#eff7f5;font-size:16px;font-weight:700;}
QLabel#matrixLoop {font-size:10px;color:#9ab8bd;}
QLabel#matrixAxis {color:#9fc2cc;font-size:10px;font-weight:700;letter-spacing:1px;}
QLabel#matrixTerm {font-size:12px;color:#d0e1e4;}
QLabel#matrixNote {color:#abc1c7;font-size:11px;}
QCheckBox#matrixLink {color:#bfd4d7;font-size:11px;spacing:5px;}
QCheckBox#matrixLink::indicator {width:13px;height:13px;}
QDoubleSpinBox#matrixGain {
  font-size:13px;font-weight:600;color:#edf6f4;background:#10222c;
  border:1px solid #3c5864;border-radius:4px;padding:2px 4px;min-height:19px;
}
QDoubleSpinBox#matrixGain:focus {border-color:#77dfca;}
QDoubleSpinBox#matrixGain:disabled {color:#91a8b0;background:#152931;border-color:#304854;}
QDoubleSpinBox#matrixGain::up-button,QDoubleSpinBox#matrixGain::down-button {width:14px;background:#29424e;}
QPushButton#matrixAction,QPushButton#matrixApply {
  border:1px solid #4b6672;border-radius:4px;background:#263e4a;color:#e0edee;
  padding:3px 8px;min-height:18px;font-size:11px;font-weight:600;
}
QPushButton#matrixAction:hover {background:#34515e;}
QPushButton#matrixApply {background:#a0e4d1;color:#123a33;border-color:#a0e4d1;}
QPushButton#matrixApply:hover {background:#b2f0df;}
QPushButton#matrixAction:pressed,QPushButton#matrixApply:pressed {border-color:#ecce91;}
QPushButton#matrixAction:disabled,QPushButton#matrixApply:disabled {
  background:#233843;color:#748c95;border-color:#344d59;
}
"""

CHANGED_STYLE = "QDoubleSpinBox#matrixGain:enabled {background:#392f21;border-color:#c39b51;color:#ffdd94;}"

TERMS = ('Proportional', 'Integral', 'Derivative')
STEPS = (.01, .1, .001)


class GainInput(QDoubleSpinBox):
    """Keep common gains short while accepting small fractional coefficients."""
    def textFromValue(self, value):
        text = super().textFromValue(value)
        separator = self.locale().decimalPoint()
        if separator in text:
            text = text.rstrip(self.locale().zeroDigit()).rstrip(separator)
        return text


class PidMatrixCard(SettingsCard):
    """Expose the SettingsCard contract while editing gains in wire order."""
    def __init__(self, group, title=None, subtitle='', persist_on_apply=True):
        if group not in (2, 3):
            raise ValueError('Choose rate or attitude PID.')
        Card.__init__(self)
        self.setObjectName('pidMatrix')
        self.setStyleSheet(STYLE)
        self.box.setContentsMargins(12, 10, 12, 9)
        self.box.setSpacing(6)
        self.group = group
        self.persist_on_apply = persist_on_apply
        self.active = None
        self.loaded = self.busy = self.allowed = self.can_read = False
        self.axes = ('Roll', 'Pitch', 'Yaw') if group == 2 else ('Roll', 'Pitch')
        self.setAccessibleName('Rate PID' if group == 2 else 'Attitude PID')
        self.defaults = [field['default'] for field in DRONE_GROUPS[group]['fields']]
        self._had_active = False
        self._has_fc_readback = False
        # Preserve untouched controller floats at their original precision.
        self._source = list(self.defaults)
        self._displayed_source = list(self.defaults)

        heading = QHBoxLayout()
        heading.setSpacing(6)
        stripe = QLabel()
        stripe.setFixedSize(3, 18)
        stripe.setStyleSheet('background:' + ('#7cddc0' if group == 2 else '#8dbfe8') + ';border-radius:1px;')
        heading.addWidget(stripe)
        heading.addWidget(label(title or self.accessibleName(), 'matrixTitle'))
        heading.addWidget(label(subtitle or ('Inner loop' if group == 2 else 'Outer loop'), 'matrixLoop'))
        heading.addStretch()
        self.link_check = QCheckBox('Link roll/pitch')
        self.link_check.setObjectName('matrixLink')
        self.link_check.setToolTip('Apply the next roll or pitch edit to both axes in that row.')
        heading.addWidget(self.link_check)
        self.box.addLayout(heading)

        self.gain_grid = QGridLayout()
        self.gain_grid.setHorizontalSpacing(6)
        self.gain_grid.setVerticalSpacing(4)
        for col, axis in enumerate(self.axes, 1):
            axis_label = label(axis.upper(), 'matrixAxis')
            axis_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.gain_grid.addWidget(axis_label, 0, col)
            self.gain_grid.setColumnStretch(col, 1)
        for row, name in enumerate(TERMS, 1):
            self.gain_grid.addWidget(label(name[0] + '   ' + name, 'matrixTerm'), row, 0)
        self.inputs = []
        for field in DRONE_GROUPS[group]['fields']:
            index = field['index']
            row, col = divmod(index, len(self.axes))
            item = GainInput()
            item.setObjectName('matrixGain')
            item.setAccessibleName(f'{self.accessibleName()} {self.axes[col]} {TERMS[row]}')
            item.setDecimals(7)
            item.setRange(field['min'], field['max'])
            item.setSingleStep(STEPS[row])
            item.setKeyboardTracking(False)
            item.setAlignment(Qt.AlignmentFlag.AlignCenter)
            item.setValue(field['default'])
            item.setMinimumWidth(55)
            item.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            item.setProperty('gainIndex', index)
            item.valueChanged.connect(self._gain_edited)
            self.inputs.append(item)
            self.gain_grid.addWidget(item, row + 1, col + 1)
        self.box.addLayout(self.gain_grid)

        actions = QHBoxLayout()
        actions.setSpacing(4)
        self.buttons = {}
        for key, text in (('read', 'Read FC'), ('stored', 'Read saved')):
            self.buttons[key] = self._action(key, text)
            actions.addWidget(self.buttons[key])
        self.revert_button = page_action_button('Revert', self._revert, 'matrixAction')
        self.revert_button.setToolTip('Restore this editor to the last confirmed active gains.')
        actions.addWidget(self.revert_button)
        actions.addStretch()
        self.buttons['apply'] = self._action('apply', 'Apply to FC')
        actions.addWidget(self.buttons['apply'])
        self.box.addLayout(actions)
        self.note = label('Firmware defaults · awaiting FC read', 'matrixNote')
        self.note.setTextFormat(Qt.TextFormat.PlainText)
        self.note.setWordWrap(True)
        self.box.addWidget(self.note)
        self.refresh()

    def _action(self, action, title):
        role = 'matrixApply' if action == 'apply' else 'matrixAction'
        item = page_action_button(title, self._action_clicked, role)
        item.setProperty('gainAction', action)
        return item

    def _action_clicked(self):
        self._request(self.sender().property('gainAction'))

    def values(self):
        # Reading another axis must never round a gain the user didn't edit.
        return [original if editor.value() == displayed else editor.value()
                for editor, original, displayed in zip(self.inputs, self._source, self._displayed_source)]

    def _load(self, values):
        self._source = list(values)
        for item, value in zip(self.inputs, values):
            with QSignalBlocker(item):
                item.setValue(value)
        self._displayed_source = [item.value() for item in self.inputs]

    def _changed(self):
        if not self.loaded or self.active is None:
            return [False] * len(self.inputs)
        # The controller stores float32 gains. Compare at that boundary.
        return [pid_gain_word(v) != pid_gain_word(baseline)
                for v, baseline in zip(self.values(), self.active)]

    def _gain_edited(self):
        index = self.sender().property('gainIndex')
        row, col = divmod(index, len(self.axes))
        if self.link_check.isChecked() and self.link_check.isEnabled() and col < 2:
            peer = row * len(self.axes) + 1 - col
            linked = self.values()[index]
            with QSignalBlocker(self.inputs[peer]):
                self.inputs[peer].setValue(linked)
            self._source[peer] = linked
            self._displayed_source[peer] = self.inputs[peer].value()
        if self.loaded and self.active is not None:
            changed = sum(self._changed())
            self.note.setText(('1 edited gain' if changed == 1 else f'{changed} edited gains')
                              if changed else 'Matches last FC readback')
        self.refresh()

    def _revert(self):
        if self.loaded and self.active is not None and not self.busy:
            self._load(self.active)
            self.note.setText('Matches last FC readback')
            self.refresh()

    def refresh(self):
        lost_readback = self._had_active or (self._has_fc_readback and not self.can_read)
        if lost_readback and self.active is None and not self.loaded:
            self._has_fc_readback = False
            self._load(self.defaults)
            self.link_check.setChecked(False)
            self.note.setText('Firmware defaults · awaiting FC read')
        self._had_active = self.active is not None
        writable = self.allowed and self.loaded and not self.busy
        self.link_check.setEnabled(writable)
        self.buttons['read'].setEnabled(self.can_read and not self.busy)
        self.buttons['stored'].setEnabled(self.can_read and not self.busy)
        self.buttons['apply'].setEnabled(writable)
        changed = self._changed()
        self.revert_button.setEnabled(any(changed) and not self.busy)
        for index, item in enumerate(self.inputs):
            item.setEnabled(writable)
            if item.property('changed') != changed[index]:
                item.setProperty('changed', changed[index])
                item.setStyleSheet(CHANGED_STYLE if changed[index] else '')
            if changed[index]:
                hint = f'{item.accessibleName()} · last FC readback {self.active[index]:.9g}'
            else:
                hint = item.accessibleName()
            if item.toolTip() != hint:
                item.setToolTip(hint)

    def finish(self, action, values=None, error=None):
        self.busy = False
        if error:
            self.note.setText(str(error))
        else:
            if action != 'stored':
                self.active = list(values)
                self.loaded = True
            self._load(values)
            self._has_fc_readback = True
            messages = {'read': 'Loaded from FC', 'stored': 'Saved copy · not applied',
                        'apply': 'Active gains verified', 'save': 'SAVED · verified'}
            self.note.setText(messages[action])
        self.refresh()
