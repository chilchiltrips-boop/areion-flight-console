"""Read-only geographic view. A future GNSS decoder can feed update_fix()."""
import math
from pathlib import Path
import time

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget


class _GeographicCanvas(QWidget):
    """Longitude/latitude in the same plate carrée projection as the atlas."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(120, 85)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAccessibleName('Geographic map')
        self.position = None
        self._land = None

    def set_position(self, position):
        if self.position != position:
            self.position = position
            self.update()

    def _projection(self, area):
        if self.position is None:
            scale = min(area.width() / 360., area.height() / 180.)
            return scale, 0., 0.
        latitude, longitude = self.position
        scale = max(area.width() / 36., area.height() / 30.)
        margin = area.height() / (2 * scale)
        return scale, longitude, max(-90 + margin, min(90 - margin, latitude))

    def paintEvent(self, event):
        if self._land is None:
            atlas = Path(__file__).with_name('assets') / 'world-land-110m.svg'
            self._land = QSvgRenderer(str(atlas))
        area = QRectF(self.rect())
        scale, lon, lat = self._projection(area)
        if scale <= 0:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(area, QColor('#192f3c'))
        center = area.center()
        left = center.x() - (lon + 180) * scale
        top = center.y() - (90 - lat) * scale
        world = QRectF(left, top, 360 * scale, 180 * scale)
        visible = area if self.position is not None else world
        painter.setClipRect(visible)
        painter.fillRect(visible, QColor('#203c49'))
        # Repeat neighboring copies where the viewport crosses the antimeridian.
        for shift in (-world.width(), 0., world.width()):
            copy = world.translated(shift, 0)
            if area.intersects(copy):
                self._land.render(painter, copy)
        step = 30 if self.position is None else 5
        painter.setPen(QPen(QColor(173, 207, 203, 40), 1))
        west = lon - visible.width() / (2 * scale)
        east = lon + visible.width() / (2 * scale)
        for meridian in range(math.ceil(west / step) * step, math.floor(east / step) * step + 1, step):
            x = center.x() + (meridian - lon) * scale
            painter.drawLine(QPointF(x, visible.top()), QPointF(x, visible.bottom()))
        for parallel in range(-90, 91, step):
            y = center.y() - (parallel - lat) * scale
            if visible.top() <= y <= visible.bottom():
                painter.drawLine(QPointF(visible.left(), y), QPointF(visible.right(), y))
        painter.setClipping(False)
        if self.position is not None:
            # Civil GNSS position has no implied direction of travel.
            marker = QPointF(center.x(), center.y() - (self.position[0] - lat) * scale)
            painter.setPen(QPen(QColor('#f0fffa'), 2))
            painter.setBrush(QColor('#36baa4'))
            painter.drawEllipse(marker, 6.5, 6.5)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(134, 233, 214, 175), 1.2))
            painter.drawEllipse(marker, 12, 12)
        font = QFont(self.font())
        font.setPixelSize(11)
        painter.setFont(font)
        painter.setPen(QColor('#d0e6e4'))
        painter.drawText(area.adjusted(7, 4, -7, -4),
                         Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop, 'N ↑')
        painter.end()


class GpsMapPanel(QFrame):
    """Offline atlas bound to the current FC session. All methods run on the GUI thread.

    render_status calls set_link with the current link identity and monotonic time
    even when the map is hidden. A future decoder passes actual receiver fix
    validity, WGS84 coordinates, monotonic receipt timestamp and session to
    update_fix. The present FC schema supplies no GNSS data.
    """
    MAX_FIX_AGE = 5.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('gpsMapPanel')
        self.setAccessibleName('GPS map')
        self.setStyleSheet('''
            QFrame#gpsMapPanel {background:#192f3c; border:1px solid #3b5561; border-radius:8px;}
            QFrame#gpsMapPanel QLabel {background:transparent; border:0; color:#bdcfce; font-size:11px;}
            QLabel#gpsState {color:#f0f7f6; font-weight:600; font-size:13px;}
            QLabel#gpsCoordinates {color:#8be3d0; font-weight:600;}
        ''')
        self._session = None
        self._latest_stamp = None
        self._state = ''
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)
        header = QHBoxLayout()
        self.status = QLabel()
        self.status.setObjectName('gpsState')
        self.coordinates = QLabel()
        self.coordinates.setObjectName('gpsCoordinates')
        header.addWidget(self.status)
        header.addStretch()
        header.addWidget(self.coordinates)
        layout.addLayout(header)
        self.canvas = _GeographicCanvas()
        layout.addWidget(self.canvas, 1)
        source = QLabel('Natural Earth  ·  Offline atlas')
        source.setToolTip('Natural Earth, public-domain 1:110m land outlines.')
        layout.addWidget(source)
        self._set_display(None, 'Waiting for GPS')

    def _set_display(self, position, state):
        if self.canvas.position == position and self._state == state:
            return
        self._state = state
        self.canvas.set_position(position)
        self.status.setText(state)
        text = ''
        if position is not None:
            lat, lon = position
            text = f"{abs(lat):.5f}° {'N' if lat >= 0 else 'S'}   {abs(lon):.5f}° {'E' if lon >= 0 else 'W'}"
        self.coordinates.setText(text)
        self.canvas.setAccessibleDescription(f'{state} {text}'.strip())

    def set_link(self, session, now=None):
        now = time.monotonic() if now is None else now
        if session != self._session:
            self._session = session
            self._latest_stamp = None
            self._set_display(None, 'Waiting for GPS')
        if self.canvas.position is not None and now - self._latest_stamp > self.MAX_FIX_AGE:
            self._set_display(None, 'GPS fix expired')

    def update_fix(self, latitude, longitude, *, valid, stamp, session, now=None):
        """Return True only when a current, valid position was displayed."""
        now = time.monotonic() if now is None else now
        if session is None or session != self._session:
            return False
        self.set_link(session, now)
        if type(stamp) not in (float, int) or not 0 <= stamp <= now:
            return False
        if self._latest_stamp is not None and stamp <= self._latest_stamp:
            return False
        self._latest_stamp = stamp
        if now - stamp > self.MAX_FIX_AGE:
            self._set_display(None, 'GPS fix expired')
            return False
        if (valid is not True or type(latitude) not in (float, int)
                or type(longitude) not in (float, int)
                or not -90 <= latitude <= 90 or not -180 <= longitude <= 180):
            self._set_display(None, 'No GPS fix')
            return False
        self._set_display((float(latitude), float(longitude)), 'GPS fix')
        return True
