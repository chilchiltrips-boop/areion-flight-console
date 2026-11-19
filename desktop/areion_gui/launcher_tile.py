"""Animated, keyboard-accessible launch buttons for the Welcome workspace."""
from pathlib import Path

from PySide6.QtCore import QEvent, QEasingCurve, QPointF, QRectF, QSize, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QIcon, QKeyEvent, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QPushButton, QSizePolicy


class LauncherTile(QPushButton):
    """Paint inside a stable hit area. QPushButton owns navigation and activation."""

    def __init__(self, text, icon_key, parent=None, *, featured=False):
        super().__init__(text, parent)
        self.icon_key = icon_key
        self.featured = featured
        self.setIcon(QIcon(str(Path(__file__).with_name('assets') / f'launch-{icon_key}.svg')))
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAutoDefault(False)
        self.setAutoRepeat(False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hover = False
        self._motion = 0.0
        self._animation = QVariantAnimation(self)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animation.valueChanged.connect(self._move_face)
        self.pressed.connect(self._animate)
        self.released.connect(self._animate)

    def minimumSizeHint(self):
        return QSize(144, 150) if self.featured else QSize(80, 70)

    def sizeHint(self):
        return QSize(230, 225) if self.featured else QSize(116, 110)

    def _move_face(self, value):
        self._motion = float(value)
        self.update()

    def _animate(self):
        target = -1.0 if self.isDown() else float(self._hover and self.isEnabled())
        current = self._motion
        self._animation.stop()
        if target == current:
            return
        # Give even a brief mouse-down a visible response before the next tick.
        if self.isDown():
            current = min(current, -0.45)
            self._move_face(current)
        self._animation.setDuration(90 if self.isDown() else 140)
        self._animation.setStartValue(current)
        self._animation.setEndValue(target)
        self._animation.start()

    def enterEvent(self, event):
        super().enterEvent(event)
        self._hover = True
        self._animate()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self._hover = False
        self._animate()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._animation.stop()
        self._hover = False
        self._move_face(0)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.EnabledChange and not self.isEnabled():
            self._animation.stop()
            self._move_face(0)

    def _activation_key(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            # Outside a dialog QPushButton only activates a default button on
            # Return. Reuse its native Space press/release and cancellation rules.
            return QKeyEvent(event.type(), Qt.Key.Key_Space, event.modifiers(), ' ',
                             event.isAutoRepeat(), event.count())
        return event

    def keyPressEvent(self, event):
        key = self._activation_key(event)
        if key.key() != Qt.Key.Key_Space or not key.isAutoRepeat():
            super().keyPressEvent(key)
        if key.key() == Qt.Key.Key_Space:
            event.accept()

    def keyReleaseEvent(self, event):
        key = self._activation_key(event)
        if key.key() != Qt.Key.Key_Space or not key.isAutoRepeat():
            super().keyReleaseEvent(key)
        if key.key() == Qt.Key.Key_Space:
            event.accept()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        hover = max(0.0, self._motion)
        pressed = max(0.0, -self._motion)
        bounds = QRectF(self.rect()).adjusted(2, 3, -2, -4)
        inset = 1.6 * pressed
        face = bounds.adjusted(inset, inset, -inset, -inset)
        face.translate(0, pressed * 2 - hover * 1.5)
        radius = 13 if self.featured else 10
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(16, 29, 39, 43))
        painter.drawRoundedRect(bounds.translated(0, 2), radius, radius)

        gradient = QLinearGradient(face.topLeft(), face.bottomRight())
        if self.featured:
            gradient.setColorAt(0, QColor('#ffe584'))
            gradient.setColorAt(.6, QColor('#ffca4e'))
            gradient.setColorAt(1, QColor('#f8b538'))
            edge = QColor('#d4a541')
        else:
            gradient.setColorAt(0, QColor('#294351'))
            gradient.setColorAt(.55, QColor('#1e3442'))
            gradient.setColorAt(1, QColor('#182b37'))
            edge = QColor('#425d69')
        painter.setBrush(gradient)
        painter.setPen(QPen(edge, 1))
        painter.drawRoundedRect(face, radius, radius)
        painter.setPen(Qt.PenStyle.NoPen)
        if hover or pressed:
            overlay = QColor(255, 255, 255, round(19 * hover)) if hover else QColor(7, 24, 33, round(35 * pressed))
            painter.setBrush(overlay)
            painter.drawRoundedRect(face, radius, radius)

        if not self.isEnabled():
            painter.setOpacity(.42)
        if self.featured:
            self._paint_featured(painter, face, hover)
        else:
            self._paint_shortcut(painter, face)
        if self.hasFocus():
            painter.setOpacity(1)
            painter.setPen(QPen(QColor('#344b49' if self.featured else '#9aefe1'), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(face.adjusted(3, 3, -3, -3), radius - 2, radius - 2)
        painter.end()

    def _paint_shortcut(self, painter, face):
        font = QFont(self.font())
        font.setWeight(QFont.Weight.DemiBold)
        font.setPixelSize(max(12, min(18, font.pixelSize() if font.pixelSize() > 0 else 14)))
        painter.setFont(font)
        metrics = QFontMetricsF(font)
        side = min(face.width() * .58, face.height() - metrics.height() - 17, 72)
        group_height = side + 6 + metrics.height()
        top = face.center().y() - group_height / 2
        icon = QRectF(face.center().x() - side / 2, top, side, side)
        self.icon().paint(painter, icon.toAlignedRect())
        text = QRectF(face.left() + 4, icon.bottom() + 6, face.width() - 8, metrics.height() + 2)
        caption = metrics.elidedText(self.text(), Qt.TextElideMode.ElideRight, text.width())
        painter.setPen(QColor('#f0f7f7'))
        painter.drawText(text, Qt.AlignmentFlag.AlignCenter, caption)

    def _paint_featured(self, painter, face, hover):
        pad = min(22.0, max(13.0, face.width() * .08))
        inner = face.adjusted(pad, pad, -pad, -pad)
        title = QFont(self.font())
        title.setWeight(QFont.Weight.Bold)
        title.setPixelSize(round(max(18, min(32, inner.width() * .145, inner.height() * .14))))
        painter.setFont(title)
        metrics = QFontMetricsF(title)
        arrow_width = 20
        flags = Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom
        title_width = inner.width() - arrow_width - 6
        text_height = metrics.boundingRect(QRectF(0, 0, title_width, inner.height()), flags, self.text()).height() + 2
        caption = QRectF(inner.left(), inner.bottom() - text_height, title_width, text_height)
        art = QRectF(inner.left(), inner.top(), inner.width(), caption.top() - inner.top() - 8)
        self.icon().paint(painter, art.toAlignedRect())
        painter.setPen(QColor('#183831'))
        painter.drawText(caption, flags, self.text())
        arrow = QPointF(inner.right() - 3 + hover * 2, inner.bottom() - metrics.height() / 2)
        painter.setPen(QPen(QColor('#294a40'), 2.1, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(arrow + QPointF(-15, 0), arrow)
        painter.drawLine(arrow + QPointF(-6, -6), arrow)
        painter.drawLine(arrow + QPointF(-6, 6), arrow)
