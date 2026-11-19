"""Native Welcome launcher for the Areion desktop console."""
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget,
)

from .launcher_tile import LauncherTile
from .scroll_guard import page_action_button as button
from .widgets import label


WELCOME_STYLE = """
QWidget#welcomePage QLabel {color:#18343e;}
QLabel#welcomeHeading {font-size:27px; font-weight:700; color:#152f37;}
QFrame#welcomeBrand {background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #ffffff,stop:1 #deeae8);
                     border:1px solid #b6cbca; border-radius:15px;}
QLabel#wordmark {color:#123841; font-size:32px; font-weight:800; letter-spacing:3px;}
QLabel#productName {color:#436067; font-size:15px; font-weight:500;}
QFrame#welcomeSummary {background:#fbfdfc; border:1px solid #c0d2d1; border-radius:14px;}
QFrame#splitRule {background:#d3dfdd; border:0;}
QLabel#sectionHeading {color:#15333c; font-size:19px; font-weight:700;}
QLabel#fieldName {color:#516770; font-size:12px;}
QLabel#fieldValue {color:#19363e; font-size:15px; font-weight:600;}
QLabel#eventTime {color:#456b71; font-family:"IBM Plex Mono","Menlo",monospace; font-size:12px;}
QLabel#eventMessage {color:#28444d; font-size:13px;}
QLabel#emptyEvents {color:#546d73; font-size:14px;}
QPushButton#welcomeLink {color:#1e4b52; background:#e8f1f0; border:1px solid #b7cecd;
                         border-radius:6px; padding:5px 11px; font-size:12px;}
QPushButton#welcomeLink:hover {background:#d9eae7; border-color:#79a9a4;}
QPushButton#welcomeLink:focus {border:2px solid #207c78; padding:4px 10px;}
QPushButton#welcomeLink:pressed {background:#c7dfdb;}
"""


class BrandMark(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName('brandMark')
        self.setAccessibleName('Areion logo')
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.mark = QPixmap(str(Path(__file__).with_name('assets') / 'areion-mark.png'))

    def paintEvent(self, event):
        if self.mark.isNull():
            return
        area = QRectF(self.rect()).adjusted(4, 5, -4, -2)
        size = self.mark.deviceIndependentSize()
        size.scale(area.size(), Qt.AspectRatioMode.KeepAspectRatio)
        target = QRectF(QPointF(), size)
        target.moveCenter(area.center())
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawPixmap(target, self.mark, QRectF(self.mark.rect()))


class EventMessage(QLabel):
    """Keep long serial and SDK messages from setting a minimum window width."""

    def __init__(self):
        super().__init__()
        self.setObjectName('eventMessage')
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.full_text = ''

    def set_message(self, message):
        self.full_text = message
        self.setToolTip(message)
        self.setAccessibleName(message)
        self._fit()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()

    def _fit(self):
        self.setText(self.fontMetrics().elidedText(
            self.full_text, Qt.TextElideMode.ElideRight, self.contentsRect().width()))


class WelcomePage(QWidget):
    def __init__(self, navigate, connection_settings, open_imu, open_log, open_restart=None):
        super().__init__()
        self.setObjectName('welcomePage')
        self.setStyleSheet(WELCOME_STYLE)
        self._last_status = None
        self._last_events = None
        self._open_restart = open_restart
        self.restart_button = None

        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(22, 18, 22, 20)
        self.body.setSpacing(16)
        heading = label('Welcome', 'welcomeHeading')
        self.body.addWidget(heading)

        launch = QGridLayout()
        launch.setSpacing(10)
        launch.setRowStretch(0, 1)
        launch.setRowStretch(1, 1)
        for column, stretch in enumerate((21, 13, 13, 13, 24)):
            launch.setColumnStretch(column, stretch)
        self.body.addLayout(launch, 6)

        brand = QFrame()
        brand.setObjectName('welcomeBrand')
        brand_layout = QVBoxLayout(brand)
        brand_layout.setContentsMargins(12, 12, 12, 18)
        brand_layout.setSpacing(2)
        self.brand_mark = BrandMark()
        brand_layout.addWidget(self.brand_mark, 1)
        wordmark = label('AREION', 'wordmark')
        wordmark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand_layout.addWidget(wordmark)
        product = label('Flight Console', 'productName')
        product.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand_layout.addWidget(product)
        launch.addWidget(brand, 0, 0, 2, 1)

        self.flight_button = LauncherTile('Flight Data', 'flight')
        self.input_button = LauncherTile('Flight input', 'input')
        self.imu_button = LauncherTile('IMU', 'imu')
        self.esc_button = LauncherTile('ESC / motors', 'esc')
        self.pid_button = LauncherTile('PID settings', 'pid')
        self.scopes_button = LauncherTile('Scopes', 'scopes')
        self.setup_button = LauncherTile('Vehicle setup wizard', 'wizard', featured=True)
        self.imu_button.setAccessibleName('IMU calibration')
        self.esc_button.setAccessibleName('ESC and motor calibration')
        tools = (
            (self.flight_button, lambda: navigate(0)), (self.input_button, lambda: navigate(10)),
            (self.imu_button, open_imu), (self.esc_button, lambda: navigate(6)),
            (self.pid_button, lambda: navigate(2)), (self.scopes_button, lambda: navigate(8)),
        )
        for index, (tile, activate) in enumerate(tools):
            launch.addWidget(tile, index // 3, 1 + index % 3)
            tile.clicked.connect(activate)
        launch.addWidget(self.setup_button, 0, 4, 2, 1)
        self.setup_button.clicked.connect(lambda: navigate(5))

        summary = QFrame()
        summary.setObjectName('welcomeSummary')
        self.body.addWidget(summary, 5)
        summary_row = QHBoxLayout(summary)
        summary_row.setContentsMargins(20, 18, 20, 18)
        summary_row.setSpacing(20)
        controller_panel = QWidget()
        controller_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        summary_row.addWidget(controller_panel, 1)
        controller = QVBoxLayout(controller_panel)
        controller.setContentsMargins(0, 0, 0, 0)
        controller.setSpacing(8)
        controller_title = QHBoxLayout()
        controller_title.addWidget(label('Flight controller', 'sectionHeading'))
        controller_title.addStretch()
        self.connection = label('Offline', 'connectionState')
        self.connection.setAccessibleName('Connection status')
        controller_title.addWidget(self.connection)
        controller.addLayout(controller_title)

        self.values = {}
        fields = QGridLayout()
        fields.setContentsMargins(0, 5, 0, 4)
        fields.setSpacing(9)
        for i, field in enumerate(('Telemetry link', 'Firmware', 'Setup', 'Configured input')):
            metric = QVBoxLayout()
            metric.setSpacing(2)
            metric.addWidget(label(field, 'fieldName'))
            value = label('—', 'fieldValue')
            value.setAccessibleName(field)
            metric.addWidget(value)
            fields.addLayout(metric, i // 2, i % 2)
            self.values[field] = value
        fields.setColumnStretch(0, 1)
        fields.setColumnStretch(1, 1)
        controller.addLayout(fields, 1)
        self.settings_button = button('Connection settings', connection_settings, 'welcomeLink')
        self.kit_actions = QHBoxLayout()
        self.kit_actions.addWidget(self.settings_button)
        self.kit_actions.addStretch()
        controller.addLayout(self.kit_actions)

        rule = QFrame()
        rule.setObjectName('splitRule')
        rule.setFixedWidth(1)
        summary_row.addWidget(rule)
        activity_panel = QWidget()
        activity_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        summary_row.addWidget(activity_panel, 1)
        activity = QVBoxLayout(activity_panel)
        activity.setContentsMargins(0, 0, 0, 0)
        activity.setSpacing(8)
        activity.addWidget(label('Session activity', 'sectionHeading'))
        self.empty_activity = label('No events this session', 'emptyEvents')
        activity.addWidget(self.empty_activity, 1)
        self.event_rows = []
        for _ in range(3):
            row = QHBoxLayout()
            row.setSpacing(12)
            stamp = label('', 'eventTime')
            message = EventMessage()
            row.addWidget(stamp)
            row.addWidget(message, 1)
            activity.addLayout(row)
            self.event_rows.append((stamp, message))
        activity.addStretch(1)
        self.event_button = button('Open event log', open_log, 'welcomeLink')
        activity.addWidget(self.event_button, alignment=Qt.AlignmentFlag.AlignLeft)
        self.update_activity(None)
        self.update_status(False, False, (), None, None, None)

    def set_restart_available(self, available):
        if available and self.restart_button is None and self._open_restart:
            self.restart_button = button('Verify last setup', self._open_restart, 'welcomeLink')
            self.kit_actions.insertWidget(1, self.restart_button)
        if self.restart_button is not None:
            self.restart_button.setVisible(available)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        compact = self.width() < 960 or self.height() < 555
        horizontal = 16 if compact else min(52, max(22, self.width() // 38))
        vertical = 12 if compact else min(36, max(18, self.height() // 30))
        self.body.setContentsMargins(horizontal, vertical, horizontal, vertical)
        self.body.setSpacing(10 if compact else min(22, self.height() // 36))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(.5, .5, -.5, -.5)
        shape = QPainterPath()
        shape.addRoundedRect(rect, 14, 14)
        wash = QLinearGradient(rect.topLeft(), rect.bottomRight())
        wash.setColorAt(0, QColor('#f1f5ee'))
        wash.setColorAt(.52, QColor('#e3eeec'))
        wash.setColorAt(1, QColor('#dbe8e9'))
        painter.fillPath(shape, wash)
        painter.setClipPath(shape)
        # Low-contrast wing contours decorate the canvas around the launcher.
        painter.setPen(QPen(QColor('#cfdfdc'), 1.3))
        w, h = self.width(), self.height()
        for offset in (0, 18, 36, 54):
            painter.drawPolyline([QPointF(.55*w+offset, -.08*h), QPointF(.85*w+offset, .25*h),
                                  QPointF(.74*w+offset, .25*h), QPointF(w+offset, .62*h)])

    def update_activity(self, document):
        # Read only three trailing log lines, even if the history is full.
        entries = []
        block = document.lastBlock() if document else None
        while block is not None and block.isValid() and len(entries) < 3:
            line = block.text().strip()
            if line:
                timestamp, space, message = line.partition('  ')
                if not space or not (len(timestamp) == 8 and timestamp[2:3] == ':'):
                    timestamp, message = '', line
                entries.append((timestamp, message))
            block = block.previous()
        if entries == self._last_events:
            return
        self._last_events = entries
        self.empty_activity.setVisible(not entries)
        for index, (stamp, message) in enumerate(self.event_rows):
            active = index < len(entries)
            stamp.setVisible(active)
            message.setVisible(active)
            if active:
                stamp.setText(entries[index][0])
                message.set_message(entries[index][1])

    def update_status(self, connected, connecting, routes, setup, firmware, config):
        live = bool(connected and routes)
        complete = bool(live and setup and setup[1] and not setup[0])
        if live:
            state, fg, bg = 'Connected', '#105a46', '#d9efe4'
        elif connecting:
            state, fg, bg = 'Connecting…', '#744600', '#fff0c7'
        elif connected:
            state, fg, bg = 'Link stale', '#794400', '#ffebc8'
        else:
            state, fg, bg = 'Offline', '#435b62', '#e4eceb'
        setup_text = 'Saved' if complete else 'In progress' if setup and setup[0] else 'Incomplete'
        display = (
            ' + '.join(routes) if live else '—',
            str(firmware[0]) if live and firmware else '—',
            setup_text if live and setup else '—',
            {0: 'PPM', 1: 'AP', 2: 'USB'}.get(config[1], '—') if live and config else '—',
        )
        key = (state, display, complete)
        if key == self._last_status:
            return
        self._last_status = key
        self.connection.setText(state)
        self.connection.setStyleSheet(
            f'color:{fg}; background:{bg}; border-radius:8px; padding:3px 9px; font-weight:600;')
        for widget, text in zip(self.values.values(), display):
            widget.setText(text)
        self.setup_button.setText('Edit setup' if complete else 'Vehicle setup wizard')
