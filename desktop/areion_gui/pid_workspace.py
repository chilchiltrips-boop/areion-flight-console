"""Native tuning workspace for Areion's angle and rate controllers."""
import math
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QSizePolicy, QSlider, QTabBar, QVBoxLayout, QWidget,
)

from .combo_box import ConsoleComboBox
from .pid_matrix import PidMatrixCard
from .pid_response import PidResponse
from .widgets import Card, SettingsCard


STYLE = """
QFrame#pidWorkspace {background:#e6eeea;border:1px solid #b9c9c1;border-radius:12px;}
QLabel#pidHeading {color:#143c42;font-size:22px;font-weight:700;}
QLabel#pidGlyph {background:#234a50;border-radius:7px;}
QFrame#pidBar {background:#203642;border:1px solid #294450;border-radius:7px;}
QLabel#pidReceipt {font-size:11px;font-weight:600;color:#b7d9df;}
QCheckBox#pidBench {font-size:11px;color:#e2eff0;spacing:6px;}
QCheckBox#pidBench::indicator {width:13px;height:13px;}
QTabBar#pidTabs::tab {background:transparent;color:#435e60;border:1px solid transparent;
    border-radius:5px;padding:5px 12px;font-size:12px;font-weight:600;}
QTabBar#pidTabs::tab:hover {background:#d0e0d9;}
QTabBar#pidTabs::tab:selected {background:#24574f;color:#f0faf4;border-color:#24574f;}
QFrame#stickCard {background:#172a36;border-radius:10px;border:1px solid #304858;}
QLabel#stickTitle {font-size:16px;font-weight:700;color:#e1f0ed;}
QLabel#stickHint {font-size:11px;color:#a6bfc3;}
QLabel#stickValue {font-size:17px;font-weight:700;color:#8be5c9;}
QLabel#stickPulse {font-size:12px;font-weight:600;color:#dbe9ea;}
QComboBox#stickChoice {min-height:19px;padding:2px 7px;font-size:11px;background:#203846;}
QFrame#stickCard QSlider::groove:horizontal {background:#394f5a;height:4px;}
QFrame#stickCard QSlider::sub-page:horizontal {background:#63b99c;}
QFrame#stickCard QSlider::handle:horizontal {width:12px;margin:-5px 0;background:#a4e9c9;border:1px solid #3a6e65;}
"""


class ActivePanelStack(QWidget):
    """Let only the visible settings panel contribute to the scroll area height."""
    def __init__(self):
        super().__init__()
        self.panels = QVBoxLayout(self)
        self.panels.setContentsMargins(0, 0, 0, 0)
        self.panels.setSpacing(0)
        self._index = 0

    def addWidget(self, widget):
        index = self.panels.count()
        self.panels.addWidget(widget)
        widget.setVisible(index == self._index)

    def setCurrentIndex(self, index):
        self.currentWidget().hide()
        self._index = index
        self.currentWidget().show()

    def currentWidget(self):
        return self.panels.itemAt(self._index).widget()

    def currentIndex(self):
        return self._index


class StickGraph(QWidget):
    """Plot draft and, when loaded, current FC responses on identical axes."""
    def __init__(self):
        super().__init__()
        self.scale = .1
        self.baseline = None
        self.unit = '°'
        self.pulse = 1500
        self.setMinimumSize(200, 116)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAccessibleName('Stick input versus target')

    def sizeHint(self):
        return QSize(360, 170)

    def set_response(self, scale, baseline, unit, pulse):
        values = (scale, baseline, unit, pulse)
        if values == (self.scale, self.baseline, self.unit, self.pulse):
            return
        self.scale, self.baseline, self.unit, self.pulse = values
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor('#0f202b'))
        p.drawRoundedRect(QRectF(self.rect()), 6, 6)
        x0, x1 = 57., self.width() - 23.
        top, base = 15., self.height() - 24.
        ymax = max(10., math.ceil(max(self.scale, self.baseline or 0.) * 500 / 10) * 10)
        mid = (top + base) / 2
        def pixel(pulse, scale):
            return QPointF(x0 + (pulse-1000) / 1000 * (x1-x0),
                           mid - (pulse-1500) * scale / ymax * (base-top) / 2)
        font = QFont(self.font())
        font.setPixelSize(10)
        p.setFont(font)
        for i in range(5):
            y = top + i * (base-top) / 4
            p.setPen(QPen(QColor('#405866' if i == 2 else '#233a46'), 1))
            p.drawLine(QPointF(x0, y), QPointF(x1, y))
            if i % 2 == 0:
                p.setPen(QColor('#bdd0d2'))
                value = (1-i/2)*ymax
                text = f'{value:+.0f}{self.unit}' if value else f'0{self.unit}'
                p.drawText(QRectF(0, y-8, x0-7, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, text)
        for pulse in (1000,1250,1500,1750,2000):
            x = pixel(pulse, 0).x()
            p.setPen(QPen(QColor('#405866' if pulse == 1500 else '#233a46'), 1))
            p.drawLine(QPointF(x,top), QPointF(x,base))
            if pulse in (1000,1500,2000):
                p.setPen(QColor('#bdd0d2'))
                p.drawText(QRectF(x-20,base+2,40,17), Qt.AlignmentFlag.AlignCenter, str(pulse))
        if self.baseline is not None and not math.isclose(self.scale,self.baseline,abs_tol=.000001):
            p.setPen(QPen(QColor('#f6ca7f'), 1.8, Qt.PenStyle.DashLine))
            p.drawLine(pixel(1000,self.baseline), pixel(2000,self.baseline))
        p.setPen(QPen(QColor('#81e7c4'), 2.3))
        p.drawLine(pixel(1000,self.scale), pixel(2000,self.scale))
        point = pixel(self.pulse,self.scale)
        p.setPen(QPen(QColor('#5d9385'), 1, Qt.PenStyle.DotLine))
        p.drawLine(point, QPointF(point.x(),base))
        p.setPen(QPen(QColor('#a3f2d7'), 1.5))
        p.setBrush(QColor('#133d38'))
        p.drawEllipse(point,4.4,4.4)
        p.end()


class StickPreview(QFrame):
    CHOICES = (('Angle · Roll / Pitch',1,'°'), ('Rate · Roll / Pitch',2,'°/s'),
               ('Yaw rate',3,'°/s'))

    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self.setObjectName('stickCard')
        box = QVBoxLayout(self)
        box.setContentsMargins(13,10,13,10)
        box.setSpacing(6)
        row = QHBoxLayout()
        row.addWidget(QLabel('Stick preview',objectName='stickTitle'))
        row.addStretch()
        self.axis = ConsoleComboBox(objectName='stickChoice')
        self.axis.setAccessibleName('Stick response axis and flight mode')
        self.axis.addItems([name for name, _, _ in self.CHOICES])
        row.addWidget(self.axis)
        box.addLayout(row)
        self.graph = StickGraph()
        box.addWidget(self.graph,1)
        details = QHBoxLayout()
        self.pulse_label = QLabel(objectName='stickPulse')
        self.target_label = QLabel(objectName='stickValue')
        details.addWidget(self.pulse_label)
        details.addStretch()
        details.addWidget(self.target_label)
        box.addLayout(details)
        self.pulse = QSlider(Qt.Orientation.Horizontal)
        self.pulse.setRange(1000,2000)
        self.pulse.setValue(1500)
        self.pulse.setPageStep(50)
        self.pulse.setAccessibleName('Local preview pulse, microseconds')
        self.pulse.setToolTip('Explore a receiver pulse locally.')
        box.addWidget(self.pulse)
        self.caption = QLabel(objectName='stickHint')
        self.caption.setWordWrap(True)
        box.addWidget(self.caption)
        self.axis.currentIndexChanged.connect(self.refresh)
        self.pulse.valueChanged.connect(self.refresh)
        for editor in settings.inputs[1:4]:
            editor.valueChanged.connect(self.refresh)
        self.refresh()

    def refresh(self, *_):
        _, index, unit = self.CHOICES[self.axis.currentIndex()]
        scale, pulse = self.settings.inputs[index].value(), self.pulse.value()
        baseline = self.settings.active[index] if self.settings.loaded and self.settings.active else None
        self.graph.set_response(scale,baseline,unit,pulse)
        target = (pulse - 1500) * scale
        self.pulse_label.setText(f'{pulse} µs')
        self.target_label.setText(f'{target:+.1f}{unit}' if target else f'0{unit}')
        detail = 'Editor values · local preview'
        if baseline is not None and not math.isclose(scale,baseline,abs_tol=.000001):
            detail = 'Solid · editor     Dashed · active FC'
        self.caption.setText(detail)


class PidWorkspace(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName('pidWorkspace')
        self.setStyleSheet(STYLE)
        main = QVBoxLayout(self)
        main.setContentsMargins(12,8,12,10)
        main.setSpacing(6)
        header = QHBoxLayout()
        header.setSpacing(8)
        glyph = QLabel(objectName='pidGlyph')
        glyph.setFixedSize(31,31)
        glyph.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon = Path(__file__).parent / 'assets' / 'launch-pid.svg'
        glyph.setPixmap(QIcon(str(icon)).pixmap(QSize(24,24)))
        header.addWidget(glyph)
        header.addWidget(QLabel('PID tuning',objectName='pidHeading'))
        header.addStretch()
        self.tabs = QTabBar(objectName='pidTabs')
        self.tabs.setAccessibleName('Tuning views')
        self.tabs.setExpanding(False)
        self.tabs.setDrawBase(False)
        for title in ('Gain tuning','Stick response','Receiver && arming'):
            self.tabs.addTab(title)
        header.addWidget(self.tabs)
        main.addLayout(header)

        status = QFrame(objectName='pidBar')
        bar = QHBoxLayout(status)
        bar.setContentsMargins(10,5,10,5)
        self.pid_state = QLabel('PID · Status unavailable',objectName='pidReceipt')
        self.pid_state.setWordWrap(True)
        self.pid_state.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Preferred)
        bar.addWidget(self.pid_state,1)
        self.bench = QCheckBox('Secured on tripod · allow live tuning',objectName='pidBench')
        self.bench.setToolTip('Enable live PID tuning while secured. The kit saves pending gains after disarm.')
        self.bench.setAccessibleName('Aircraft secured on tripod · enable live PID tuning')
        bar.addWidget(self.bench)
        main.addWidget(status)
        self.stack = ActivePanelStack()
        main.addWidget(self.stack,1)
        self.cards = {2: PidMatrixCard(2), 3: PidMatrixCard(3)}
        self.cards.update({g: SettingsCard(g,title) for g,title in
                           ((7,'Flight mode & stick response'),(112,'Receiver timeouts'),(4,'Arming settings'))})

        tuning = QWidget()
        gains = QGridLayout(tuning)
        gains.setContentsMargins(0,0,0,0)
        gains.setHorizontalSpacing(9)
        gains.setVerticalSpacing(7)
        gains.addWidget(self.cards[2],0,0)
        gains.addWidget(self.cards[3],0,1)
        gains.setColumnStretch(0,1)
        gains.setColumnStretch(1,1)
        self.response = PidResponse()
        self.gain_plots = QHBoxLayout()
        self.gain_plots.setSpacing(8)
        self.gain_plots.addWidget(self.response,2)
        gains.addLayout(self.gain_plots,1,0,1,2)
        gains.setRowStretch(1,1)
        self.stack.addWidget(tuning)

        stick = QWidget()
        stick_col = QVBoxLayout(stick)
        stick_col.setContentsMargins(0,0,0,0)
        self.stick_panels = QHBoxLayout()
        self.stick_panels.addWidget(self.cards[7],5)
        self.stick_curve = StickPreview(self.cards[7])
        self.stick_panels.addWidget(self.stick_curve,4)
        stick_col.addLayout(self.stick_panels)
        stick_col.addStretch()
        self.stack.addWidget(stick)

        hardware = QWidget()
        hardware_col = QVBoxLayout(hardware)
        hardware_col.setContentsMargins(0,0,0,0)
        self.aux_panels = QHBoxLayout()
        self.aux_panels.addWidget(self.cards[4],6)
        device_col = QVBoxLayout()
        device_col.addWidget(self.cards[112])
        board = Card('Board configuration')
        self.board = QLabel('Board offline',objectName='muted')
        self.board.setWordWrap(True)
        board.box.addWidget(self.board)
        device_col.addWidget(board)
        device_col.addStretch()
        self.aux_panels.addLayout(device_col,4)
        hardware_col.addLayout(self.aux_panels)
        hardware_col.addStretch()
        self.stack.addWidget(hardware)
        self.tabs.currentChanged.connect(self._change_tab)

    def _place_curve(self):
        # The two views share the editor preview, pulse position and axis.
        # Narrow tuning screens give their available height to the live trace.
        show_with_gains = self.tabs.currentIndex() == 0 and self.width() >= 1100
        target = self.gain_plots if show_with_gains else self.stick_panels
        if target.indexOf(self.stick_curve) >= 0:
            return
        previous = self.stick_panels if show_with_gains else self.gain_plots
        previous.removeWidget(self.stick_curve)
        target.addWidget(self.stick_curve, 1 if show_with_gains else 4)
        self.stick_curve.show()
        self.stick_curve.refresh()

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self, 'aux_panels'):
            direction = QHBoxLayout.Direction
            self.aux_panels.setDirection(direction.LeftToRight if self.width() >= 820 else direction.TopToBottom)
            self.stick_panels.setDirection(direction.LeftToRight if self.width() >= 810 else direction.TopToBottom)
            self._place_curve()

    def _change_tab(self,index):
        self._place_curve()
        self.stack.setCurrentIndex(index)
        self.stack.updateGeometry()
        self.layout().invalidate()
        self.updateGeometry()
        if index == 1:
            self.stick_curve.refresh()

    def refresh(self, data, now, connected, identity=None):
        if not self.isVisible():
            return
        # Deliver session transitions even when another tuning view is active.
        # The response panel itself defers hidden chart work.
        self.response.refresh(data,now,connected,identity)
        if self.stick_curve.isVisible():
            self.stick_curve.refresh()
        if not connected:
            self.board.setText('Board offline')
