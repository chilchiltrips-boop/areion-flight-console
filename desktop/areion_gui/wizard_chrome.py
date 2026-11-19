"""Native controls for the setup workflow. All visual feedback is local to the GUI."""
from PySide6.QtCore import QByteArray, QEasingCurve, QPointF, QRectF, QSize, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QCursor, QFont, QPainter, QPen
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QPushButton, QSizePolicy, QWidget

STEP_NAMES = ('Safety', 'Airframe', 'Wiring', 'IMU', 'Receiver', 'ESC', 'Motors', 'Arming', 'Review', 'Restart')
STEP_ICONS = ('safety', 'frame', 'wiring', 'imu', 'receiver', 'esc', 'motor', 'lock', 'review', 'restart')
_GLYPHS = {
    'safety': '<path d="m12 3 8 3v6c0 4-4 7-8 9-4-2-8-5-8-9V6z M8.5 12l2.4 2.5 4.9-5"/>',
    'frame': '<path d="m7 7 10 10M17 7 7 17"/><circle cx="6" cy="6" r="3"/><circle cx="18" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="18" r="3"/>',
    'wiring': '<rect x="3" y="8" width="5" height="8" rx="1"/><path d="M8 12h4l4-6h4m-8 6h8m-8 0 4 6h4"/><circle cx="20" cy="6" r="1"/><circle cx="20" cy="12" r="1"/><circle cx="20" cy="18" r="1"/>',
    'imu': '<path d="m12 2 9 5v10l-9 5-9-5V7z M3 7l9 5 9-5 M12 12v10 M8 5l9 5"/>',
    'receiver': '<rect x="3" y="8" width="18" height="12" rx="4"/><path d="M6 8 4 4m14 4 2-4M7 14h4m-2-2v4"/><circle cx="16" cy="14" r="2"/>',
    'esc': '<path d="M2 15h5V6h6v12h4v-7h5"/>',
    'motor': '<circle cx="12" cy="12" r="2.5"/><path d="M10 10C4 9 4 3 8 3c3 0 5 3 5 6m1 2c4-5 10-2 8 2-1 3-6 3-8 1m-2 1c1 6-4 9-7 6-2-3 1-6 5-7"/>',
    'lock': '<rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3m-4 5v2"/>',
    'restart': '<path d="M4 10a8 8 0 1 1 1 7M4 4v6h6m1 4 2 2 4-5"/>',
    'review': '<rect x="4" y="3" width="16" height="18" rx="2"/><path d="m7 9 1.5 1.5L11 8m2 1h4M7 15l1.5 1.5L11 14m2 1h4"/>',
}


class WizardGlyph(QWidget):
    def __init__(self, name, size, light=False):
        super().__init__()
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        stroke = '#1d655b' if light else '#a6e2cd'
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
               f'stroke="{stroke}" stroke-width="1.8" stroke-linejoin="round" stroke-linecap="round">'
               + _GLYPHS[name] + '</svg>')
        self.renderer = QSvgRenderer(QByteArray(svg.encode('ascii')), self)

    def paintEvent(self, event):
        painter = QPainter(self)
        self.renderer.render(painter, QRectF(self.rect()).adjusted(1., 1., -1., -1.))


STYLE = """
QWidget#setupExperience {background:#eaf2ed;border:1px solid #bcd0c7;border-radius:12px;}
QLabel#wizardTitle {color:#143a42;font-size:24px;font-weight:700;background:transparent;}
QLabel#wizardNumber {color:#3c666a;font-size:12px;font-weight:700;background:transparent;}
QLabel#wizardLock {color:#365c63;background:#dae8e3;border:1px solid #b6ccc4;
                   border-radius:6px;font-size:11px;font-weight:600;padding:4px 7px;}
QLabel#wizardLock[state="locked"] {color:#594523;background:#f8e7b9;border-color:#dbc58d;}
QLabel#wizardLock[state="armed"] {color:#832d3b;background:#fae2e2;border-color:#d99fa3;}
QLabel#wizardLock[state="complete"] {color:#165044;background:#d4ebdf;border-color:#9ac9b8;}
QComboBox#wizardStepPicker {color:#193c43;background:#f9fcf8;border:1px solid #aabfb7;
                           padding:3px 7px;border-radius:5px;min-height:21px;}
QProgressBar#wizardProgress {border:0;border-radius:2px;background:#cedfd8;min-height:3px;max-height:3px;}
QProgressBar#wizardProgress::chunk {border-radius:2px;background:#408d7c;}
QWidget#wizardBody, QScrollArea#wizardScroll {background:#142c39;border:0;border-radius:9px;}
QLabel#wizardPageTitle {color:#f4faf6;font-size:19px;font-weight:700;background:transparent;}
QLabel#wizardMessage {font-size:12px;color:#35595f;background:transparent;}
QLabel#wizardMessage[state="error"] {color:#902f38;font-weight:600;}
QLabel#wizardMessage[state="success"] {color:#17654e;}
QWidget#setupExperience QFrame#card {background:#203c49;border:1px solid #36525d;border-radius:8px;}
QWidget#setupExperience QLabel#cardTitle {color:#eef8f5;font-size:15px;font-weight:700;}
QWidget#setupExperience QLabel#notice {color:#d6efea;background:#234750;border:1px solid #3c656b;
                                       border-radius:6px;padding:6px 9px;}
QWidget#setupExperience QLabel#muted {color:#b1cad0;}
QWidget#setupExperience QPushButton {border-radius:6px;}
QWidget#setupExperience QPushButton:hover:!disabled {border-color:#71b8aa;}
QWidget#setupExperience QPushButton:pressed:!disabled {background:#315962;border-color:#a1dcd0;}
QWidget#setupExperience QPushButton#primary, QPushButton#wizardAdvance {
    color:#25372f;background:#ffcf74;border:1px solid #dbaf56;padding:5px 12px;font-weight:700;}
QWidget#setupExperience QPushButton#primary:pressed, QPushButton#wizardAdvance:pressed {
    background:#eeb35b;border-color:#987443;}
QWidget#setupExperience QPushButton#danger:disabled {color:#b5a9af;background:#3b343c;border-color:#554851;}
QWidget#setupExperience QPushButton#primary:disabled {color:#aebebd;background:#3d5055;border-color:#4f6266;}
QPushButton#wizardAdvance:disabled {color:#6d796f;background:#d6ded4;border-color:#b9c7bb;}
QPushButton#wizardBack, QPushButton#wizardRetry {color:#254a4e;background:#f9fcf7;border:1px solid #b1c6ba;padding:5px 10px;}
QPushButton#wizardBack:disabled, QPushButton#wizardRetry:disabled {color:#82928a;background:#e4ece5;border-color:#c6d4c9;}
QLabel#wizardDirectInfo, QCheckBox#wizardDirectCheck {color:#2a4d50;background:transparent;}
"""


def set_visual_state(widget, state):
    if widget.property('state') == state:
        return
    widget.setProperty('state', state)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


class StepButton(QPushButton):
    """A real keyboard-accessible button with its verification state painted independently."""
    def __init__(self, index, title, parent=None):
        super().__init__(parent)
        self.index = index
        self.short_title = STEP_NAMES[index]
        self.state = 'pending'
        self.title = title
        self.setCheckable(True)
        self.setAutoDefault(False)
        self.setAccessibleName(f'Step {index + 1}, {title}')
        self.setAccessibleDescription('Pending')
        self.setToolTip(f'{title} · Pending')
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(34)

    def sizeHint(self):
        return QSize(88, 34)

    def minimumSizeHint(self):
        return QSize(52, 34)

    def set_step_state(self, complete, skipped, error):
        state = 'error' if error else 'skipped' if skipped else 'verified' if complete else 'pending'
        if state != self.state:
            self.state = state
            self.setAccessibleDescription(state.capitalize())
            self.setToolTip(f'{self.title} · {state.capitalize()}')
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        current = self.isChecked()
        if current:
            background, border, ink, disk, symbol = '#174a4b', '#174a4b', '#f3faf6', '#c5f0d9', '#164c48'
        elif self.isEnabled():
            background = '#d8e9df' if self.underMouse() else '#f4f8f2'
            border, ink, disk, symbol = '#b9cfc3', '#2b5053', '#dae8e0', '#355d59'
        else:
            background, border, ink, disk, symbol = '#e8efea', '#cddad0', '#627a71', '#dae4dd', '#677e72'
        if self.isDown():
            background = '#255b56' if current else '#c4dfd0'
        if self.state == 'verified' and not current:
            disk, symbol = '#c5e7d4', '#24694e'
        elif self.state == 'error':
            disk, symbol = '#f7ccd0', '#8f3542'
        painter.setPen(QPen(QColor('#f4b94c' if self.hasFocus() else border), 1.8 if self.hasFocus() else 1))
        painter.setBrush(QColor(background))
        painter.drawRoundedRect(rect, 6, 6)
        font = QFont(self.font())
        font.setPixelSize(12)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        title_width = painter.fontMetrics().horizontalAdvance(self.short_title)
        start = max(4., (rect.width() - title_width - 24.) / 2.)
        yc = rect.center().y()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(disk))
        painter.drawEllipse(QPointF(start + 9, yc), 9, 9)
        painter.setPen(QColor(symbol))
        glyph = {'verified': '✓', 'error': '!', 'skipped': '–'}.get(self.state, str(self.index + 1))
        painter.drawText(QRectF(start, yc - 10, 18, 20), Qt.AlignmentFlag.AlignCenter, glyph)
        painter.setPen(QColor(ink))
        painter.drawText(QRectF(start + 23, 0, rect.width() - start - 23, rect.height()),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.short_title)


class PressWave(QWidget):
    """Brief local ink feedback. The child accepts neither focus nor pointer input."""
    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setGeometry(parent.rect())
        point = parent.mapFromGlobal(QCursor.pos())
        self.origin = QPointF(point if parent.rect().contains(point) else parent.rect().center())
        self.phase = 0.
        self.motion = QVariantAnimation(self)
        self.motion.setStartValue(0.)
        self.motion.setEndValue(1.)
        self.motion.setDuration(210)
        self.motion.setEasingCurve(QEasingCurve.Type.OutQuad)
        self.motion.valueChanged.connect(self._set_phase)
        self.motion.finished.connect(self.deleteLater)
        self.show()
        self.motion.start()

    def _set_phase(self, phase):
        self.phase = phase
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        radius = (self.width() + self.height()) * self.phase
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(130, 223, 198, round((1. - self.phase) * 50.)))
        painter.drawEllipse(self.origin, radius, radius)


def install_action_feedback(owner):
    for item in owner.findChildren(QPushButton):
        item.pressed.connect(lambda b=item: PressWave(b) if b.isVisible() else None)
