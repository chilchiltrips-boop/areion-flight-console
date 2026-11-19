"""Primary flight display driven by the console's timestamped, read-only attitude model."""
from functools import lru_cache
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QSizePolicy

from .attitude_model import wrapped_angle
from .widgets import Horizon


CENTER = Qt.AlignmentFlag.AlignCenter
LEFT = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
NO_PEN = Qt.PenStyle.NoPen
NO_BRUSH = Qt.BrushStyle.NoBrush
INK = QColor('#102932')
WHITE = QColor('#f5fbf9')
MUTED = QColor('#a7c2c6')
GOLD = QColor('#ffdb75')


def tilt_degrees(roll, pitch):
    """Angle between body vertical and earth vertical, including inverted attitudes."""
    if roll is None or pitch is None:
        return None
    projection = math.cos(math.radians(roll)) * math.cos(math.radians(pitch))
    return math.degrees(math.acos(max(-1., min(1., projection))))


@lru_cache(maxsize=32)
def _font(size, bold=False):
    font = QFont('Sans Serif')
    font.setPixelSize(int(size))
    font.setWeight(QFont.Weight.DemiBold if bold else QFont.Weight.Normal)
    return font


@lru_cache(maxsize=64)
def _pitch_numeral(text, size):
    path = QPainterPath()
    path.addText(QPointF(0., 0.), _font(size, True), text)
    center = path.boundingRect().center()
    return path.translated(-center.x(), -center.y())


def _bank_point(center, angle, distance):
    radians = math.radians(angle)
    return center + QPointF(distance * math.sin(radians), -distance * math.cos(radians))


def _angle(value, signed=True):
    if value is None:
        return '—'
    value = 0. if abs(value) < .05 else value
    return f'{value:+.1f}°' if signed else f'{value:.1f}°'


class PrimaryFlightDisplay(Horizon):
    """Moving horizon and relative yaw tape with independent FC status readback."""
    def __init__(self):
        super().__init__()
        self.setMinimumSize(258, 191)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.animation.setInterval(33)
        self.armed = None
        self.mode = ''
        self.reason = ''
        self.setAccessibleName('Primary flight display')
        self.setToolTip('Roll and pitch are the kit’s filtered attitude. Tilt is the angle from upright. '
                        'Relative yaw is integrated from the gyro and can drift.')

    @property
    def tilt(self):
        return tilt_degrees(self.roll, self.pitch)

    def set_flight_state(self, armed, mode='', reason=''):
        state = (armed if type(armed) is bool else None, mode, reason)
        if (self.armed, self.mode, self.reason) != state:
            self.armed, self.mode, self.reason = state
            self.setAccessibleDescription(' · '.join(filter(None, (self.arm_text, mode, reason))))
            self.update()

    @property
    def arm_text(self):
        if self.armed is None:
            return 'ARM —'
        return 'ARMED' if self.armed else 'DISARMED'

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())
        clip = QPainterPath()
        clip.addRoundedRect(rect, 8., 8.)
        p.setClipPath(clip)
        compact = rect.height() < 305
        tape_height = 32. if compact else 41.
        state_height = 31. if compact else 38.
        value_height = 37. if compact else 51.
        field = rect.adjusted(0., tape_height, 0., -(state_height + value_height))
        self._draw_tape(p, QRectF(0., 0., rect.width(), tape_height))
        p.save()
        p.setClipRect(field, Qt.ClipOperation.IntersectClip)
        center = QPointF(field.center().x(), field.top() + field.height() * .55)
        if self.display_roll is None or self.display_pitch is None:
            self._draw_standby(p, field, center)
        else:
            self._draw_world(p, field, center)
            self._draw_bank_scale(p, field, center)
            self._draw_aircraft(p, center, field)
        p.restore()
        self._draw_state(p, QRectF(0., field.bottom(), rect.width(), state_height))
        self._draw_angles(p, QRectF(0., rect.bottom() - value_height, rect.width(), value_height))

    def _draw_tape(self, p, rect):
        p.fillRect(rect, QColor('#102c36'))
        tag_width = 66. if rect.width() > 375. else 52.
        p.setFont(_font(10, True))
        p.setPen(MUTED)
        p.drawText(QRectF(8., 1., tag_width - 8., rect.height() - 2.), LEFT, 'REL YAW')
        p.setPen(QPen(QColor('#38515a'), 1.))
        p.drawLine(QPointF(tag_width, 7.), QPointF(tag_width, rect.bottom() - 7.))
        yaw = self.display_yaw
        cx = rect.center().x()
        if yaw is not None:
            pixels_per_degree = max(2.3, min(7., rect.width() / 92.))
            left = math.floor((yaw + (tag_width + 5. - cx) / pixels_per_degree) / 5.) * 5
            right = math.ceil((yaw + (rect.right() - cx) / pixels_per_degree) / 5.) * 5
            p.save()
            p.setClipRect(rect.adjusted(tag_width + 5., 0., -3., 0.), Qt.ClipOperation.IntersectClip)
            for tick in range(left, right + 1, 5):
                x = cx + (tick - yaw) * pixels_per_degree
                major = tick % 10 == 0
                p.setPen(QPen(QColor('#a2bec3'), 1.))
                p.drawLine(QPointF(x, rect.bottom() - 1.), QPointF(x, rect.bottom() - (6. if major else 3.)))
                if major and abs(x - cx) > 42.:
                    value = int(wrapped_angle(tick))
                    label = f'{value:+d}' if value else '0'
                    p.setFont(_font(11))
                    p.drawText(QRectF(x - 17., 0., 34., rect.height() - 7.), CENTER, label)
            p.restore()
        badge = QRectF(cx - 33., 3., 66., rect.height() - 10.)
        p.setPen(QPen(QColor('#627e80'), 1.))
        p.setBrush(QColor('#203f48'))
        p.drawRoundedRect(badge, 4., 4.)
        p.setFont(_font(14, True))
        p.setPen(GOLD if yaw is not None else MUTED)
        p.drawText(badge, CENTER, _angle(yaw))
        p.setBrush(GOLD if yaw is not None else QColor('#6f8b91'))
        p.setPen(NO_PEN)
        p.drawPolygon(QPolygonF([QPointF(cx - 4., badge.bottom()), QPointF(cx + 4., badge.bottom()),
                                 QPointF(cx, rect.bottom() - 2.)]))

    def _draw_world(self, p, field, center):
        scale = max(2.4, min(8., field.height() / 48.))
        # Bound the translation for all finite telemetry, even outside physical pitch limits.
        span = math.hypot(field.width(), field.height()) + 2.
        offset = max(-span, min(span, self.display_pitch * scale))
        p.save()
        p.translate(center)
        p.rotate(-self.display_roll)
        sky = QLinearGradient(0., offset - field.height() * .8, 0., offset)
        sky.setColorAt(0., QColor('#24608a'))
        sky.setColorAt(.65, QColor('#4e9ebd'))
        sky.setColorAt(1., QColor('#82c3ce'))
        ground = QLinearGradient(0., offset, 0., offset + field.height() * .95)
        ground.setColorAt(0., QColor('#a58b57'))
        ground.setColorAt(.54, QColor('#806a45'))
        ground.setColorAt(1., QColor('#4d4939'))
        p.fillRect(QRectF(-span, -span, 2. * span, span + offset), sky)
        p.fillRect(QRectF(-span, offset, 2. * span, span - offset), ground)
        p.setPen(QPen(QColor('#f7f0c6'), 2.))
        p.drawLine(QPointF(-span, offset), QPointF(span, offset))
        p.restore()

        p.save()
        p.translate(center)
        p.rotate(-self.display_roll)
        width = max(23., min(46., field.width() * .077))
        numeral_size = 12 if field.height() < 200. else 14
        bank_radius = min(field.height() * .43, field.width() * .39)
        rotation = math.radians(-self.display_roll)
        cos_roll, sin_roll = math.cos(rotation), math.sin(rotation)
        def clear_of_bank(x, y, margin=2.):
            dx, dy = x * cos_roll - y * sin_roll, x * sin_roll + y * cos_roll
            inside_field = field.top() + margin < center.y() + dy < field.bottom() - margin
            under_bank = dy >= -abs(dx) * .47 or math.hypot(dx, dy) < bank_radius - 7. - margin
            return inside_field and under_bank

        for degree in range(-90, 91, 5):
            if not degree:
                continue
            y = (self.display_pitch - degree) * scale
            if abs(y) > min(span, field.height() * .63):
                continue
            major = degree % 10 == 0
            half = width if major else width * .42
            line = QPainterPath()
            for sign in (-1., 1.):
                if not (clear_of_bank(sign * 5., y) and clear_of_bank(sign * half, y)):
                    continue
                line.moveTo(sign * 5., y)
                line.lineTo(sign * half, y)
                if major:
                    line.lineTo(sign * half, y + (3. if degree > 0 else -3.))
            style = Qt.PenStyle.SolidLine if degree > 0 else Qt.PenStyle.DashLine
            p.setPen(QPen(QColor(28, 48, 52, 105), 3., style))
            p.setBrush(NO_BRUSH)
            p.drawPath(line)
            p.setPen(QPen(WHITE, 1.4, style))
            p.drawPath(line)
            if major:
                numeral = _pitch_numeral(f'{degree:+d}', numeral_size)
                bounds = numeral.boundingRect().adjusted(-2., -2., 2., 2.)
                for side in (-1., 1.):
                    label_x = side * (half + 18.)
                    box = bounds.translated(label_x, y)
                    corners = (box.topLeft(), box.topRight(), box.bottomLeft(), box.bottomRight(), box.center())
                    if not all(clear_of_bank(corner.x(), corner.y(), 3.) for corner in corners):
                        continue
                    p.save()
                    p.translate(label_x, y)
                    p.setPen(QPen(QColor('#2b474e'), 1.2))
                    p.setBrush(WHITE)
                    # Outline behind the white fill retains the full thickness of small numerals.
                    p.drawPath(numeral)
                    p.fillPath(numeral, WHITE)
                    p.restore()
        p.restore()

    @staticmethod
    def _contrast_text(p, box, text):
        # A small dark underprint keeps white scale markings legible on the bright horizon.
        p.setPen(QColor('#304a4c'))
        p.drawText(box.translated(.7, .9), CENTER, text)
        p.setPen(WHITE)
        p.drawText(box, CENTER, text)

    def _draw_bank_scale(self, p, field, center):
        radius = min(field.height() * .43, field.width() * .39)
        point = lambda angle, distance: _bank_point(center, angle, distance)
        arc = QPainterPath(point(-60., radius))
        for angle in range(-58, 61, 2):
            arc.lineTo(point(angle, radius))
        p.setBrush(NO_BRUSH)
        p.setPen(QPen(QColor(26, 49, 54, 110), 3.))
        p.drawPath(arc)
        p.setPen(QPen(QColor('#d8eee9'), 1.))
        p.drawPath(arc)
        dense = radius >= 103.
        p.setFont(_font(10 if radius < 95. else 11, True))
        for angle in (-60, -45, -30, -20, -10, 0, 10, 20, 30, 45, 60):
            major = angle in (-60, -30, 0, 30, 60)
            p.setPen(QPen(WHITE, 2. if major else 1.3))
            p.drawLine(point(angle, radius), point(angle, radius - (7. if major else 4.)))
            if major or dense:
                label_center = point(angle, radius + 9.)
                label = str(abs(angle)) + ('°' if angle == 0 else '')
                self._contrast_text(p, QRectF(label_center.x()-13.,label_center.y()-7.,26.,14.), label)
        # Bank is read in the aircraft frame; a positive right bank moves the index right.
        # Beyond the ±60° arc the numeric roll remains available, without pegging an index.
        if abs(self.display_roll) <= 60.:
            p.save()
            p.translate(center)
            p.rotate(self.display_roll)
            p.setBrush(GOLD)
            p.setPen(QPen(INK, 1.1))
            apex = -radius + 1.
            p.drawPolygon(QPolygonF([QPointF(0., apex), QPointF(5., apex + 9.), QPointF(-5., apex + 9.)]))
            p.restore()

    @staticmethod
    def _draw_aircraft(p, center, field):
        width = max(42., min(83., field.width() * .14))
        path = QPainterPath()
        path.moveTo(-width, 0.)
        path.lineTo(-width * .45, 0.)
        path.lineTo(-width * .36, 4.)
        path.moveTo(width, 0.)
        path.lineTo(width * .45, 0.)
        path.lineTo(width * .36, 4.)
        path.moveTo(-12., 5.)
        path.lineTo(0., -2.)
        path.lineTo(12., 5.)
        p.save()
        p.translate(center)
        p.setBrush(NO_BRUSH)
        for color, stroke in ((INK, 5.4), (GOLD, 3.1)):
            p.setPen(QPen(color, stroke, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                          Qt.PenJoinStyle.RoundJoin))
            p.drawPath(path)
        p.restore()

    def _draw_standby(self, p, field, center):
        gradient = QLinearGradient(field.topLeft(), field.bottomLeft())
        gradient.setColorAt(0., QColor('#203f4c'))
        gradient.setColorAt(1., QColor('#17323d'))
        p.fillRect(field, gradient)
        radius = min(field.height() * .44, field.width() * .35)
        for angle in (-60, -45, -30, -20, -10, 0, 10, 20, 30, 45, 60):
            p.setPen(QPen(QColor('#52717c'), 1.4))
            p.drawLine(_bank_point(center, angle, radius), _bank_point(center, angle, radius - 5.))
        box = QRectF(field.left() + 8., field.center().y() - 14., field.width() - 16., 28.)
        p.setFont(_font(15 if field.height() < 185. else 18, True))
        p.setPen(QColor('#d8e6e5'))
        p.drawText(box, CENTER, 'Waiting for live IMU')
        # No artificial level line, aircraft symbol, or zero-degree reading while offline.

    def _draw_state(self, p, rect):
        p.fillRect(rect, QColor('#102c36'))
        if self.armed is None:
            light, dark = QColor('#c2d0d1'), QColor('#344d56')
        elif self.armed:
            light, dark = QColor('#ffe09c'), QColor('#604727')
        else:
            light, dark = QColor('#a4ebd1'), QColor('#234c48')
        compact = rect.width() < 430.
        padding = 7. if compact else 12.
        arm_box = QRectF(padding, rect.top() + 4., 82. if compact else 105., rect.height() - 8.)
        p.setPen(NO_PEN)
        p.setBrush(dark)
        p.drawRoundedRect(arm_box, 4., 4.)
        p.setPen(light)
        p.setFont(_font(12 if compact else 15, True))
        p.drawText(arm_box, CENTER, self.arm_text)
        right = rect.width() - padding
        if self.mode and self.mode != '—':
            p.setFont(_font(10 if compact else 11, True))
            mode_width = min(rect.width() * .26, p.fontMetrics().horizontalAdvance(self.mode) + 16.)
            mode_box = QRectF(right - mode_width, rect.top() + 6., mode_width, rect.height() - 12.)
            p.setPen(QPen(QColor('#49646c'), 1.))
            p.setBrush(NO_BRUSH)
            p.drawRoundedRect(mode_box, 4., 4.)
            p.setPen(QColor('#d6e7e5'))
            p.drawText(mode_box, CENTER, p.fontMetrics().elidedText(self.mode, Qt.TextElideMode.ElideRight, int(mode_width - 5)))
            right = mode_box.left() - 5.
        reason_box = QRectF(arm_box.right() + 8., rect.top(), max(0., right - arm_box.right() - 8.), rect.height())
        p.setPen(MUTED)
        p.setFont(_font(11 if compact else 12))
        p.drawText(reason_box, LEFT, p.fontMetrics().elidedText(self.reason, Qt.TextElideMode.ElideRight, int(reason_box.width())))

    def _draw_angles(self, p, rect):
        p.fillRect(rect, QColor('#193a44'))
        cell_width = rect.width() / 3.
        compact = rect.height() < 45.
        for i, (label, value) in enumerate((('ROLL', self.roll), ('PITCH', self.pitch), ('TILT', self.tilt))):
            x = i * cell_width
            if i:
                p.setPen(QPen(QColor('#3c5a61'), 1.))
                p.drawLine(QPointF(x, rect.top() + 7.), QPointF(x, rect.bottom() - 7.))
            if compact:
                p.setFont(_font(9, True))
                label_width = p.fontMetrics().horizontalAdvance(label)
                p.setFont(_font(15, True))
                value_text = _angle(value, signed=i < 2)
                value_width = p.fontMetrics().horizontalAdvance(value_text)
                left = x + max(2., (cell_width - label_width - value_width - 6.) / 2.)
                p.setFont(_font(9, True))
                p.setPen(MUTED)
                p.drawText(QRectF(left, rect.top(), label_width + 1., rect.height()), LEFT, label)
                p.setFont(_font(15, True))
                p.setPen(WHITE)
                p.drawText(QRectF(left + label_width + 6., rect.top(), value_width + 2., rect.height()), LEFT, value_text)
            else:
                p.setFont(_font(10, True))
                p.setPen(MUTED)
                p.drawText(QRectF(x, rect.top() + 3., cell_width, 16.), CENTER, label)
                p.setFont(_font(21, True))
                p.setPen(WHITE)
                p.drawText(QRectF(x, rect.top() + 16., cell_width, rect.height() - 17.), CENTER, _angle(value, signed=i < 2))
