"""Read-only setup diagrams and indicators. All device actions live in the wizard."""
from PySide6.QtCore import QEasingCurve, QPointF, QRectF, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame, QLabel, QSizePolicy, QVBoxLayout, QWidget

from .drone_scene import DroneScene

CENTER = Qt.AlignmentFlag.AlignCenter
INK = '#e1f1ee'
TEAL = '#7cdec4'
BLUE = '#94c9ed'
AMBER = '#ffcd83'
RED = '#ff9da2'
QUIET = '#90aab1'


def _font(painter, pixels, bold=False):
    font = QFont(painter.font())
    font.setPixelSize(pixels)
    font.setBold(bold)
    painter.setFont(font)


class PropellerGuide(QWidget):
    """Exploded side view of the propeller lifted off the motor shaft."""
    def __init__(self):
        super().__init__()
        self.setFixedHeight(132)
        self.setMinimumWidth(152)
        self.setAccessibleName('Propeller removal guide')
        self.setAccessibleDescription('Lift the propeller off the motor shaft. Remove all four.')

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        scale = min(self.width() / 215, self.height() / 132)
        p.translate((self.width()-215*scale)/2, (self.height()-132*scale)/2)
        p.scale(scale, scale)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor('#122c36')); p.drawRoundedRect(QRectF(0, 0, 215, 132), 11, 11)
        p.setPen(QPen(QColor('#4a6970'), 1, Qt.PenStyle.DashLine))
        p.drawLine(QPointF(103, 22), QPointF(103, 98))
        prop = QPainterPath(QPointF(103, 29))
        prop.cubicTo(76, 13, 53, 16, 28, 18)
        prop.cubicTo(38, 29, 57, 31, 101, 34)
        prop.cubicTo(119, 47, 155, 48, 181, 47)
        prop.cubicTo(162, 34, 137, 31, 103, 29)
        p.setPen(QPen(QColor(AMBER), 1.4)); p.setBrush(QColor('#815e3a')); p.drawPath(prop)
        p.setBrush(QColor('#283d45')); p.drawEllipse(QPointF(103, 31), 7, 4)
        p.setBrush(QColor('#77949a')); p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(100, 69, 6, 21), 2, 2)
        p.setPen(QPen(QColor('#91c8cc'), 1.3)); p.setBrush(QColor('#355c65'))
        p.drawRoundedRect(QRectF(76, 86, 54, 28), 6, 6)
        p.setBrush(QColor('#55848c')); p.drawEllipse(QRectF(76, 80, 54, 13))
        p.setPen(QPen(QColor('#88aab0'), 1))
        for x in range(83, 129, 8):
            p.drawLine(QPointF(x, 94), QPointF(x, 107))
        p.setPen(QPen(QColor(TEAL), 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(155, 89), QPointF(155, 59))
        p.drawPolyline([QPointF(148, 66), QPointF(155, 58), QPointF(162, 66)])
        p.end()


class EscSequence(QWidget):
    """Display the FC-reported stages in order. Move the cursor only on stage changes."""
    TITLES = ('Schedule', 'Power cycle', 'Endpoints', 'Confirm tones')
    def __init__(self):
        super().__init__()
        self.setFixedHeight(55)
        self.setMinimumWidth(240)
        self.mode = 'idle'
        self.stage = -1
        self.cursor = -1.
        self.motion = QVariantAnimation(self)
        self.motion.setDuration(180)
        self.motion.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.motion.valueChanged.connect(self._move)
        self.setAccessibleName('ESC calibration sequence')

    def _move(self, value):
        self.cursor = value
        self.update()

    def hideEvent(self, event):
        self.motion.stop()
        self.cursor = float(self.stage)
        super().hideEvent(event)

    def sync(self, code, fault=False):
        if code is None:
            stage, mode = -1, 'offline'
        elif fault or code == 6:
            stage, mode = -1, 'error'
        elif code == 5:
            stage, mode = -1, 'skipped'
        elif code == 4:
            stage, mode = 3, 'complete'
        else:
            stage, mode = {0: 0, 1: 1, 2: 2, 3: 3}.get(code, -1), 'current'
        if (mode, stage) == (self.mode, self.stage):
            return
        self.motion.stop()
        previous = self.stage
        self.mode, self.stage = mode, stage
        self.setAccessibleDescription(self.TITLES[stage] + ' · ' + mode if stage >= 0 else mode)
        if self.isVisible() and previous >= 0 and stage > previous and mode == 'current':
            self.motion.setStartValue(self.cursor); self.motion.setEndValue(float(stage)); self.motion.start()
        else:
            self.cursor = float(stage)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cell = self.width()/4
        p.setPen(QPen(QColor('#46606a'), 2))
        p.drawLine(QPointF(cell/2, 13), QPointF(self.width()-cell/2, 13))
        if self.cursor > 0:
            p.setPen(QPen(QColor(TEAL), 2))
            p.drawLine(QPointF(cell/2, 13), QPointF((self.cursor+.5)*cell, 13))
        _font(p, 11)
        for i, title in enumerate(self.TITLES):
            x = cell*(i+.5)
            active = i < self.stage or self.mode == 'complete'
            color = TEAL if active else AMBER if i == self.stage else QUIET
            p.setPen(QPen(QColor(color), 1.6))
            p.setBrush(QColor(color if active or i == self.stage else '#223f49'))
            p.drawEllipse(QPointF(x, 13), 5 if i == self.stage else 4, 5 if i == self.stage else 4)
            p.setPen(QColor(color))
            p.drawText(QRectF(i*cell, 23, cell, 25), CENTER, title)
        p.end()


class MotorOutputScene(QWidget):
    def __init__(self):
        super().__init__()
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        self.scene = DroneScene()
        self.scene.setMinimumHeight(148); self.scene.setMaximumHeight(225)
        self.scene.set_presentation()
        box.addWidget(self.scene, 1)
        self.pulses = QLabel()
        self.pulses.setObjectName('muted'); self.pulses.setWordWrap(True)
        self.pulses.setAlignment(CENTER)
        self.pulses.setToolTip('Commanded test pulses reported by the kit in microseconds.')
        box.addWidget(self.pulses)
        self.selected_mask = 1
        self.outputs = ()
        self.set_selection(1)
        self.set_outputs(None)

    def set_selection(self, mask):
        self.selected_mask = mask
        self.scene.set_motor_highlight([i+1 for i in range(4) if mask & (1 << i)])

    def set_outputs(self, outputs):
        current = tuple(outputs) if outputs is not None else None
        if current == self.outputs:
            return
        self.outputs = current
        labels = [f'M{i+1}  {current[i]:.0f}' if current is not None else f'M{i+1}  —' for i in range(4)]
        self.pulses.setText('     '.join(labels) + '  µs')


class ModeBand(QWidget):
    """Diagram of the selected low/high flight mode assignment."""
    def __init__(self):
        super().__init__()
        self.setMinimumWidth(160)
        self.setFixedHeight(53)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.mapping = None
        self.pulse = None
        self.setAccessibleName('Flight mode switch mapping')

    def set_pulse(self, pulse):
        if self.pulse != pulse:
            self.pulse = pulse
            self.update()

    def set_mapping(self, channel, low, high):
        mapping = channel, low, high
        if mapping == self.mapping:
            return
        self.mapping = mapping
        self.setAccessibleDescription(f'{channel}, below 1500 microseconds {low}, 1500 and above {high}')
        self.update()

    def paintEvent(self, event):
        if self.mapping is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        channel, low, high = self.mapping
        w = self.width()
        for i, (color, title) in enumerate(((TEAL, low), (BLUE, high))):
            rect = QRectF(i*w/2+1, 1, w/2-2, 24)
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor('#244c4c' if i == 0 else '#2b4459'))
            p.drawRoundedRect(rect, 4, 4)
            _font(p, 11, True); p.setPen(QColor(color))
            p.drawText(rect, CENTER, ('LOW   ' if i == 0 else 'HIGH   ')+title)
        if self.pulse is not None:
            fraction = max(0., min(1., (self.pulse - 1000) / 1000))
            x = 5 + (w - 10) * fraction
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor('#fff4cb'))
            p.drawPolygon([QPointF(x, 19), QPointF(x - 4, 26), QPointF(x + 4, 26)])
        p.setPen(QColor(QUIET)); _font(p, 10)
        p.drawText(QRectF(2, 28, w-4, 19), Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter, '1000 µs')
        p.drawText(QRectF(0, 28, w, 19), CENTER, f'{channel}  ·  1500 µs')
        p.drawText(QRectF(2, 28, w-4, 19), Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter, '2000 µs')
        p.end()


class ReviewTile(QFrame):
    def __init__(self, name):
        super().__init__()
        self.setObjectName('reviewTile')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(11, 8, 10, 8)
        layout.setSpacing(2)
        self.title = QLabel(name); self.title.setStyleSheet('color:#a3bdc5;background:transparent;font-size:11px;')
        self.value = QLabel('Pending'); self.value.setWordWrap(True)
        self.value.setStyleSheet('color:#e1efef;background:transparent;font-weight:600;font-size:13px;')
        layout.addWidget(self.title); layout.addWidget(self.value)
        self.current = None

    def set_result(self, value, tone):
        if (value, tone) == self.current:
            return
        if self.current is None or tone != self.current[1]:
            color = {'pending':AMBER,'done':TEAL,'unknown':QUIET,'error':RED,'skip':BLUE}[tone]
            self.setStyleSheet(f'QFrame#reviewTile {{background:#1b3541;border-left:3px solid {color};border-radius:5px;}}')
        self.current = value, tone
        self.value.setText(value)
        self.setAccessibleName(f'{self.title.text()} · {value}')
