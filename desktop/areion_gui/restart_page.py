"""Read-only view of a verified setup and a later flight-controller boot."""
from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QHeaderView, QHBoxLayout, QSizePolicy, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)
from .scroll_guard import page_action_button
from .widgets import Card, label


class RestartCheckPage(QWidget):
    check_requested = Signal()
    COLORS = {'verified': '#acedd5', 'mismatch': '#ffbdc3', 'error': '#ffbdc3',
              'wrong_kit': '#ffcb97', 'reading': '#b8dce8'}

    def __init__(self):
        super().__init__()
        self.receipt = None
        self.context = None
        self._known_kit = None
        self._saved_label = ''
        self.result = None
        self.state = ''
        self._rendered = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        card = Card('Restart check')
        card.box.setSpacing(8)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        intro = label('Leave propellers off. Power-cycle the kit, then reconnect through USB or AP.', 'muted')
        intro.setWordWrap(True)
        card.box.addWidget(intro)
        self.status = label()
        self.status.setAccessibleName('Restart verification status')
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        card.box.addWidget(self.status)
        row = QHBoxLayout()
        self.kit = label('', 'muted')
        self.kit.setTextFormat(Qt.TextFormat.PlainText)
        self.kit.setWordWrap(True)
        row.addWidget(self.kit, 1)
        self.check_button = page_action_button('Check settings', self.check_requested.emit)
        row.addWidget(self.check_button)
        card.box.addLayout(row)
        layout.addWidget(card)
        self.table = QTableWidget(0, 3)
        self.table.setAccessibleName('Settings that differ after restart')
        self.table.setHorizontalHeaderLabels(('Setting', 'Saved', 'After restart'))
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setMinimumHeight(100)
        layout.addWidget(self.table, 1)
        self.set_context(None, False, None, None, False)

    def set_context(self, receipt, connected, fc_session, kit_id, busy):
        # A result belongs to one receipt, physical controller and live boot.
        key = (bool(connected), fc_session, kit_id)
        boot_changed = self.context is None or key[:2] != self.context[:2]
        different_kit = bool(kit_id and self._known_kit and kit_id != self._known_kit)
        if self.receipt != receipt:
            self._saved_label = ''
            if receipt:
                self._saved_label = 'Saved kit  ·  ' + str(receipt['kit_id'])
                try:
                    saved = datetime.fromisoformat(receipt.get('saved_at', '')).astimezone()
                    self._saved_label += '   ·   ' + saved.strftime('%d %b %Y, %H:%M %Z')
                except (TypeError, ValueError):
                    pass
            self.result = None
        if boot_changed or different_kit:
            self.result = None
        if boot_changed or not connected:
            self._known_kit = None
        if kit_id:
            self._known_kit = kit_id
        self.receipt = receipt
        self.context = key
        self.busy = bool(busy)
        self._refresh()

    def set_result(self, result):
        self.result = result if isinstance(result, dict) else None
        self._refresh()

    def _refresh(self):
        connected, boot, kit = self.context
        rows = ()
        eligible = False
        if not self.receipt:
            state, text = 'unavailable', 'A verified setup save is required for this check.'
        elif not connected:
            state, text = 'offline', 'Kit offline. Reconnect after the restart.'
        elif not kit or not boot:
            state, text = 'waiting', 'Reading kit identity and boot session…'
        elif kit != self.receipt['kit_id']:
            state, text = 'wrong_kit', 'Different kit connected. Reconnect the kit listed below.'
        elif boot == self.receipt['fc_session']:
            state, text = 'same_boot', 'Kit connected · restart not verified. Power-cycle the kit.'
        else:
            eligible = True
            if self.result:
                state = self.result.get('state', 'error')
                text = self.result.get('message', 'Read the kit settings again.')
                rows = tuple(self.result.get('changes') or ())
            else:
                state, text = 'ready', 'New boot detected. Ready to check saved settings.'
        self.state = state
        self.check_button.setEnabled(eligible and not self.busy and state != 'reading')
        kit_text = self._saved_label
        display = (state, text, kit_text, rows)
        if self._rendered == display:
            return
        self._rendered = display
        self.kit.setText(kit_text)
        self.check_button.setText('Retry check' if state in ('error', 'mismatch') else 'Check settings')
        self.status.setText(text)
        color = self.COLORS.get(state, '#efdaae')
        self.status.setStyleSheet(f'color:{color};font-size:16px;font-weight:600;')
        self.table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            for j, value in enumerate(row[:3]):
                item = QTableWidgetItem(str(value))
                item.setToolTip(str(value))
                self.table.setItem(i, j, item)
        self.table.setVisible(bool(rows))
