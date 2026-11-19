"""Read-only receiver measurements for the Scopes workspace."""
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
    QSizePolicy, QVBoxLayout, QWidget,
)

from .model import CHANNEL_NAMES, FLIGHT_MODES
from .flight_status import SOURCES
from .receiver_calibration import raw_channels
from .scope_data import FRESH_SECONDS, accepted_input, input_frame_fresh


DASH = '—'
TRACE = ('#62d6c1', '#72b2ed', '#f5ba77', '#d2abed', '#e9c778', '#9bcad0', '#a5c492', '#afa7dc')
STATUS_COLORS = {
    'good': ('#163f3d', '#8ae6cf'), 'waiting': ('#3a3325', '#f2cd8c'),
    'bad': ('#482d36', '#ffb0b6'), 'idle': ('#20313d', '#a5b7c5'),
}


def _setting(data, group):
    entry = data.latest.get(group)
    return entry[0] if entry else None


def _last(rows):
    return rows[-1] if rows else (None, None)


def _fresh(stamp, now):
    return stamp is not None and 0 <= now - stamp <= FRESH_SECONDS


def _last_mark(data):
    marks = data.scopes.receiver_marks
    return marks[-1] if marks else None


def _accepted(data, now):
    rows = data.scopes.rows
    status_rows = rows.get(122, ())
    stamp, status = _last(status_rows)
    if not _fresh(stamp, now):
        return (), 'waiting', 'Waiting for input status' if stamp is None else 'Input status stale'
    source = status[0]
    if source not in (0, 1, 2):
        return (), 'bad', 'Invalid input source'
    gate = accepted_input(status)
    if gate is None:
        if not status[(2, 3, 8)[source]]:
            return (), 'waiting', 'Waiting for signal'
        return (), 'waiting', 'Waiting for accepted input'
    timeout = data.scopes.input_timeouts[int(source != 0)]
    if not input_frame_fresh(status[6], stamp, now, timeout):
        return (), 'waiting', 'FC reports expired input frame'
    pulse_time, pulses = _last(rows.get(22, ()))
    if not _fresh(pulse_time, now):
        return (), 'waiting', 'Channel data stale' if pulses else 'Waiting for channels'
    record = _last_mark(data)
    if record != (data.scopes.receiver_epoch, gate[1]):
        return (), 'waiting', 'Waiting for new channels'
    count = gate[1]
    values = pulses[:count]
    if len(pulses) != 8 or any(type(v) is not int or not 900 <= v <= 2100 for v in values):
        return (), 'bad', 'Invalid channel pulse'
    return values, 'good', f'{count} channels received'


def _physical(data, now):
    stamp, sample = _last(data.scopes.rows.get(131, ()))
    if not _fresh(stamp, now):
        return (), 'waiting', 'Raw PPM stale' if sample else 'Waiting for raw PPM'
    timeout = data.scopes.input_timeouts[0]
    if not sample[9] or not input_frame_fresh(sample[10], stamp, now, timeout):
        return (), 'waiting', 'Waiting for PPM signal'
    try:
        values, count = raw_channels(sample, 4, max_age_ms=timeout)
    except ValueError:
        return (), 'bad', 'Invalid PPM frame'
    return values[:count], 'good', f'{count} channels received'


class PulseTrack(QWidget):
    """Non-interactive pulse gauge. The tip always marks the displayed sample."""
    def __init__(self, channel, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(95)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.value = None
        self.marks = None
        self.mode = None
        self.color = QColor(TRACE[channel])
        self.setAccessibleName(f'Channel {channel+1} pulse')
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def set_sample(self, value, marks, mode):
        if (self.value, self.marks, self.mode) == (value, marks, mode):
            return
        self.value, self.marks, self.mode = value, marks, mode
        self.setAccessibleDescription(f'{value} microseconds' if value is not None else 'No sample')
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        left, right, cy = 5., self.width() - 5., self.height()/2
        def x(pulse):
            return left + (right-left) * min(1., max(0., (pulse-900.)/1200.))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor('#2b414e'))
        p.drawRoundedRect(QRectF(left, cy-4., right-left, 8.), 4., 4.)
        if self.mode is not None:
            split = x(1500)
            p.setBrush(QColor('#2d6475'))
            p.drawRoundedRect(QRectF(left,cy-4.,split-left,8.),3.,3.)
            p.setBrush(QColor('#76613c'))
            p.drawRoundedRect(QRectF(split,cy-4.,right-split,8.),3.,3.)
        elif self.value is not None:
            color = QColor(self.color)
            color.setAlpha(150)
            p.setBrush(color)
            p.drawRoundedRect(QRectF(left, cy-3., x(self.value)-left, 6.),3.,3.)
        p.setPen(QPen(QColor('#9bb0bb'),1))
        for mark in self.marks or (1000, 1500, 2000):
            px = round(x(mark))
            p.drawLine(px,round(cy-5),px,round(cy+5))
        if self.value is not None:
            pos = x(self.value)
            p.setPen(QPen(QColor('#10242e'), 3.))
            p.setBrush(self.color)
            p.drawEllipse(QRectF(pos-5.,cy-6.,10.,12.))
        p.end()


def _label(text, role):
    w = QLabel(text)
    w.setObjectName(role)
    w.setTextFormat(Qt.TextFormat.PlainText)
    return w


class ScopeReceiver(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('scopeReceiver')
        self.setStyleSheet("""
        QFrame#scopeReceiver {background:#152b37;border:1px solid #35505c;border-radius:10px;}
        QFrame#scopeReceiver QLabel {background:transparent;color:#dce7ea;}
        QLabel#rxSource {font-size:12px;font-weight:700;color:#d8ecea;}
        QLabel#rxHead {font-size:11px;font-weight:600;color:#a2bdc7;}
        QLabel#rxChannel,QLabel#rxValue {font-size:13px;font-weight:650;}
        QLabel#rxRole,QLabel#rxEndpoint {font-size:12px;}
        QLabel#rxDetail {font-size:11px;color:#abc2c9;}
        QPushButton#rxChoice {color:#c5d3d9;background:#203743;border:1px solid #3c5662;
                              border-radius:5px;padding:4px 10px;font-weight:600;}
        QPushButton#rxChoice:checked {color:#c1f3e5;background:#294b4c;border-color:#60b5a7;}
        QPushButton#rxChoice:focus {border:1px solid #f3c78f;}
        QPushButton#rxChoice:pressed {background:#385e60;}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15,10,15,10)
        layout.setSpacing(5)
        head = QHBoxLayout()
        head.setSpacing(6)
        self.choices = QButtonGroup(self)
        self.accepted_button = self._button('Accepted input', head)
        self.raw_button = self._button('Raw PPM',head)
        self.accepted_button.setChecked(True)
        head.addStretch()
        self.source_label = _label('Source —','rxSource')
        self.status_label = _label('Offline','rxStatus')
        head.addWidget(self.source_label)
        head.addSpacing(4)
        head.addWidget(self.status_label)
        layout.addLayout(head)
        self.grid = QGridLayout()
        self.grid.setContentsMargins(0,0,0,0)
        self.grid.setHorizontalSpacing(10)
        self.grid.setVerticalSpacing(0)
        self.grid.setColumnStretch(2,1)
        self.headers = []
        for i,text in enumerate(('Slot','Function','Channel value','Pulse (µs)','Min','Centre','Max','Direction')):
            lab=_label(text,'rxHead')
            self.headers.append(lab)
            self.grid.addWidget(lab, 0, i)
        self.grid.setRowMinimumHeight(0,23)
        self.labels = []
        self.bars = []
        self._last = None
        self._status_key = None
        for i in range(8):
            channel=_label(f'CH{i+1}','rxChannel')
            role=_label(DASH,'rxRole')
            bar=PulseTrack(i)
            reading=_label(DASH,'rxValue')
            reading.setMinimumWidth(53)
            cells=[channel,role,bar,reading]+[_label(DASH,'rxEndpoint') for _ in range(4)]
            for col,widget in enumerate(cells):
                self.grid.addWidget(widget,i+1,col)
            self.grid.setRowMinimumHeight(i+1,24)
            self.labels.append(cells)
            self.bars.append(bar)
        layout.addLayout(self.grid,1)
        self.detail = _label('Waiting for telemetry.','rxDetail')
        self.detail.setWordWrap(True)
        layout.addWidget(self.detail)
        self.choices.buttonClicked.connect(self._view_changed)
        self._show_columns(False)
        self._set_status('idle','Offline')

    def _button(self, text, layout):
        widget=QPushButton(text)
        widget.setObjectName('rxChoice')
        widget.setCheckable(True)
        widget.setCursor(Qt.CursorShape.PointingHandCursor)
        widget.setAutoDefault(False)
        self.choices.addButton(widget)
        layout.addWidget(widget)
        return widget

    def _set_status(self, state, message):
        if self._status_key == (state,message):
            return
        self._status_key = state,message
        back, color = STATUS_COLORS[state]
        self.status_label.setStyleSheet(f'background:{back};color:{color};padding:3px 7px;border-radius:4px;font-size:11px;font-weight:650;')
        self.status_label.setText(message)

    def _show_columns(self, raw):
        self.headers[0].setText('Input' if raw else 'Slot')
        self.headers[2].setText('Physical pulse' if raw else 'Accepted pulse')
        for col in range(4,8):
            self.headers[col].setVisible(raw)
            for row in self.labels: row[col].setVisible(raw)

    def _view_changed(self):
        self._show_columns(self.raw_button.isChecked())
        if self._last:
            self.refresh(*self._last)

    def refresh(self, data, now, connected, frozen=False):
        self._last = (data, now, connected, frozen)
        raw = self.raw_button.isChecked()
        stamp, status = _last(data.scopes.rows.get(122, ()))
        selected = status[0] if _fresh(stamp, now) and connected else None
        self.source_label.setText('Selected  '+(SOURCES[selected] if selected in (0,1,2) else DASH))
        if not connected:
            values, state, message = (), 'idle', 'Offline'
        elif raw:
            values, state, message = _physical(data, now)
        else:
            values, state, message = _accepted(data, now)
        self._set_status(state,'Held · '+message if frozen else message)
        config = _setting(data, 134)
        axes = config[2:6] if config else ()
        calibration = _setting(data, 132)
        flight = _setting(data, 7)
        mode_slot = flight[0] if flight else None
        for i,row in enumerate(self.labels):
            channel = i+1
            if raw:
                function = CHANNEL_NAMES[axes.index(channel)] if channel in axes else ('Auxiliary' if axes else DASH)
            else:
                function = CHANNEL_NAMES[i]
                if i < 4 and selected == 0 and axes:
                    function += f'  ·  CH{axes[i]}'
            value = values[i] if i < len(values) else None
            # The FC reads PPM mode from physical pulses. Logical slots 1–4 can be remapped.
            mode = None
            if channel == mode_slot and (raw or selected in (1,2) or (selected == 0 and channel>=5)):
                function = 'Flight mode'
                if value is not None:
                    mode = FLIGHT_MODES[flight[4 if value < 1500 else 5]]
                else:
                    mode = DASH
            marks = None
            if raw and calibration:
                low, centre, high, reverse = calibration[4*i:4*i+4]
                marks = (low, centre, high)
                endpoint_texts = (str(low),str(centre),str(high),'Reversed' if reverse else 'Normal')
            else:
                endpoint_texts = (DASH,)*4
            row[1].setText(function)
            row[2].set_sample(value, marks, mode)
            row[3].setText(str(value) if value is not None else DASH)
            if mode and mode != DASH:
                row[1].setText(f'Mode · {mode}')
            for widget, text in zip(row[4:], endpoint_texts):
                widget.setText(text)
        self.detail.setText('Physical receiver channels · kit calibration in µs. Raw PPM streams during setup.' if raw
                            else 'Accepted controls from the flight controller · pulse scale 900–2100 µs.')
