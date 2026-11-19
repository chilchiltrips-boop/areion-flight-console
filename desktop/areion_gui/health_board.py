"""Read-only status lamps for the Flight Data instrument panel."""
from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget,
)

from .flight_status import Health


# Face, outline, lettering. Status is also written on each lamp for readers
# who cannot distinguish the colors. Orange uses dark ink for contrast.
COLORS = {
    'green': ('#117239', '#58ac72', '#ffffff'),
    'amber': ('#eb8b23', '#ffb85a', '#251407'),
    'red':   ('#b22e3b', '#f0747e', '#ffffff'),
    'gray':  ('#313b44', '#52616b', '#c9d1d5'),
}
SEVERITY = {'green': 'OK', 'amber': 'Warning', 'red': 'Error', 'gray': 'Inactive'}

ROWS = (
    ('Flight', (('ARM', 'Arming'), ('MODE', 'Mode'), ('IMU', 'I²C / IMU'), ('OUTPUT', 'Output'))),
    ('Inputs', (('INPUT', 'Input'), ('PPM', 'PPM'), ('AP', 'AP'), ('USB', 'USB'))),
    ('System', (('TELEMETRY', 'Telemetry'), ('LOOP', 'Loop'), ('CONFIG', 'Config'), ('STORAGE', 'Storage'))),
)
EMPTY = Health('gray', '—', 'Waiting for flight controller status.')


def _fit_font(widget, text, size, width, bold):
    font = QFont(widget.font())
    font.setWeight(QFont.Weight.Bold if bold else QFont.Weight.Medium)
    font.setPixelSize(size)
    while size > 8 and QFontMetricsF(font).horizontalAdvance(text) > width:
        size -= 1
        font.setPixelSize(size)
    return font


class HealthTile(QWidget):
    """A full-face indicator, deliberately without an action or checked state."""
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.title = title.upper()
        self.setMinimumSize(49, 34)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.health = None
        self.set_health(EMPTY)

    def sizeHint(self):
        return QSize(100, 56)

    def set_health(self, health):
        if self.health == health:
            return
        self.health = health
        self.setAccessibleName(f'{self.title}, {SEVERITY[health.state]}, {health.label}')
        self.setAccessibleDescription(health.detail)
        self.setToolTip(health.detail)
        self.update()

    def paintEvent(self, event):
        paint = QPainter(self)
        paint.setRenderHint(QPainter.RenderHint.Antialiasing)
        face, edge, ink = COLORS[self.health.state]
        bounds = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        paint.setBrush(QColor(face))
        paint.setPen(QPen(QColor(edge), 1.5))
        paint.drawRoundedRect(bounds, 5., 5.)
        bounds.adjust(4, 1, -4, -1)
        # Scale both lines with the actual lamp. Long state names fit even when
        # the transmitter and the model share a small laptop window.
        h, w = bounds.height(), bounds.width()
        title_size = min(20, max(11, round(h * .33)))
        value_size = min(14, max(10, round(h * .245)))
        title_font = _fit_font(self, self.title, title_size, w, True)
        value_font = _fit_font(self, self.health.label, value_size, w, False)
        title_height = QFontMetricsF(title_font).height()
        value_height = QFontMetricsF(value_font).height()
        top = bounds.center().y() - (title_height + value_height) / 2.
        paint.setPen(QColor(ink))
        paint.setFont(title_font)
        paint.drawText(QRectF(bounds.left(), top, w, title_height), Qt.AlignmentFlag.AlignCenter, self.title)
        paint.setFont(value_font)
        paint.drawText(QRectF(bounds.left(), top + title_height, w, value_height),
                       Qt.AlignmentFlag.AlignCenter, self.health.label)


class _RowLabel(QWidget):
    def __init__(self, name):
        super().__init__()
        self.name = name.upper()
        self.setAccessibleName(name)
        self.setFixedWidth(16)

    def paintEvent(self, event):
        paint = QPainter(self)
        paint.translate(self.width() / 2., self.height() / 2.)
        paint.rotate(-90.)
        paint.setPen(QColor('#b1c4c8'))
        paint.setFont(_fit_font(self, self.name, 10, self.height() - 4, True))
        paint.drawText(QRectF(-self.height()/2., -self.width()/2., self.height(), self.width()),
                       Qt.AlignmentFlag.AlignCenter, self.name)


class SystemHealthBoard(QFrame):
    """Twelve FC-reported indicators, with one tile per signal."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('systemHealthBoard')
        self.setAccessibleName('System health')
        self.setStyleSheet(
            'QFrame#systemHealthBoard {background:#17262c; border:1px solid #3d5156; border-radius:8px;}'
            'QLabel#healthBoardTitle {color:#edf5f2; background:transparent; font-size:16px; font-weight:700;}'
            'QLabel#healthLegend {color:#cdd9d9; background:transparent; font-size:10px;}'
        )
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        box = QVBoxLayout(self)
        box.setContentsMargins(8, 6, 8, 8)
        box.setSpacing(5)
        header = QHBoxLayout()
        header.setSpacing(5)
        header.addWidget(QLabel('System health', objectName='healthBoardTitle'))
        header.addStretch()
        self.legend = QLabel(objectName='healthLegend')
        self.legend.setTextFormat(Qt.TextFormat.RichText)
        self.legend.setText('&nbsp;&nbsp;'.join(
            f'<span style="color:{COLORS[key][1]}">●</span>&nbsp;{name}' for key, name in SEVERITY.items()))
        self.legend.setAccessibleName('Status colors: green OK, orange warning, red error, gray inactive.')
        header.addWidget(self.legend)
        box.addLayout(header)
        grid = QGridLayout()
        grid.setHorizontalSpacing(4)
        grid.setVerticalSpacing(4)
        self.tiles = {}
        for row, (label, fields) in enumerate(ROWS):
            grid.addWidget(_RowLabel(label), row, 0)
            for column, (key, title) in enumerate(fields, 1):
                self.tiles[key] = tile = HealthTile(title)
                grid.addWidget(tile, row, column)
                grid.setColumnStretch(column, 1)
            grid.setRowStretch(row, 1)
        box.addLayout(grid, 1)

    def set_health(self, health_by_key):
        for key, tile in self.tiles.items():
            tile.set_health(health_by_key.get(key, EMPTY))
