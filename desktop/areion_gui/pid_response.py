"""Read the controller's actual loop response at telemetry packet times."""
from bisect import bisect_right

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QTabBar, QVBoxLayout, QWidget

from .scope_data import FRESH_SECONDS, group_state, time_series
from .scope_plot import ScopePlot


WINDOW_SECONDS = 10.
AXES = ('Roll', 'Pitch', 'Yaw')


def _target_period(points, statuses, start, now, active):
    """Split a target trace at any period where the FC skips its calculation."""
    stamps = []
    periods = []
    current = None
    for stamp, row in statuses:
        if stamp < start - FRESH_SECONDS or stamp > now:
            continue
        if active(row):
            if current is None or stamp - stamps[-1] > FRESH_SECONDS:
                current = stamp
        else:
            current = None
        stamps.append(stamp)
        periods.append(current)

    def period_at(stamp):
        idx = bisect_right(stamps, stamp) - 1
        if idx >= 0 and stamp - stamps[idx] <= FRESH_SECONDS:
            return periods[idx]
        return None

    points_in_mode = []
    previous_period = None
    for stamp, value in points:
        period = period_at(stamp)
        if previous_period is not None and period is not None and period != previous_period:
            points_in_mode.append((stamp, None))
        points_in_mode.append((stamp, value if period is not None else None))
        previous_period = period
    active_period = period_at(now)
    target_current = active_period is not None and previous_period == active_period
    return tuple(points_in_mode), target_current


def _selector(title, items):
    tabs = QTabBar()
    tabs.setObjectName('pidResponseTabs')
    tabs.setAccessibleName(title)
    tabs.setExpanding(False)
    tabs.setDrawBase(False)
    tabs.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    for item in items:
        tabs.addTab(item)
    return tabs


class PidResponse(QWidget):
    """A passive chart. The main window provides a validated session and clock."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('pidResponse')
        self.setAccessibleName('PID tracking response')
        self.setStyleSheet("""
            QTabBar#pidResponseTabs::tab {background:#19333f;color:#c4d5db;
                border:1px solid #35525d;border-radius:4px;padding:3px 8px;
                font-size:11px;font-weight:600;margin-right:2px;}
            QTabBar#pidResponseTabs::tab:selected {background:#21625c;color:#ebfff7;border-color:#51a996;}
            QTabBar#pidResponseTabs::tab:hover {border-color:#7eb7ac;}
            QTabBar#pidResponseTabs::tab:disabled {background:#223039;color:#83929b;}
        """)
        self._data = None
        self._identity = None
        self._now = 0.
        self._since = float('-inf')
        self._connected = False
        self._draw_key = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)
        controls = QHBoxLayout()
        controls.setSpacing(3)
        self.loop_tabs = _selector('Controller loop', ('Rate', 'Angle'))
        self.axis_tabs = _selector('Response axis', AXES)
        controls.addWidget(self.loop_tabs)
        controls.addStretch()
        controls.addWidget(self.axis_tabs)
        outer.addLayout(controls)
        self.plot = ScopePlot('Tracking response', '°/s · 10 s')
        self.plot.setMinimumHeight(130)
        outer.addWidget(self.plot, 1)
        self.loop_tabs.currentChanged.connect(self._select_loop)
        self.axis_tabs.currentChanged.connect(self._select_axis)

    def _select_loop(self, index):
        angle = index == 1
        self.axis_tabs.blockSignals(True)
        if angle and self.axis_tabs.currentIndex() == 2:
            self.axis_tabs.setCurrentIndex(0)
        self.axis_tabs.setTabEnabled(2, not angle)
        self.axis_tabs.blockSignals(False)
        self._select_axis()

    def _select_axis(self, *_):
        self._draw_key = None
        if self.isVisible():
            self._render()

    def showEvent(self, event):
        super().showEvent(event)
        self._render()

    def refresh(self, data, now, connected, identity=None):
        if data is not self._data:
            self._since = float('-inf')
        elif connected and data is not None and (not self._connected or identity != self._identity):
            # A caller can reuse a model on reconnection. Fence off its earlier kit.
            self._since = now
        self._data, self._now = data, now
        self._connected = bool(connected and data is not None)
        self._identity = identity
        if self.isVisible():
            self._render()

    def _render(self):
        angle = self.loop_tabs.currentIndex() == 1
        axis = self.axis_tabs.currentIndex()
        now, data = self._now, self._data
        start = max(now - WINDOW_SECONDS, self._since)
        measured = 'Kalman' if angle else 'Measured'
        group_ids = (21, 23, 120, 130)
        if self._connected:
            states = []
            for group in group_ids:
                latest = data.scopes.latest(group)
                states.append(group_state(data, group, now) if latest and latest[0] >= start else 'Waiting')
            revisions = tuple(data.scopes.revisions[group] for group in group_ids)
        else:
            states = ['Offline'] * len(group_ids)
            revisions = ()
        draw_key = (id(data), self._identity, self._connected, self._since, angle, axis, revisions,
                    tuple(states), int(now * 10) if self._connected else None)
        if draw_key == self._draw_key:
            return
        self._draw_key = draw_key
        unit = '°' if angle else '°/s'
        self.plot.unit = unit
        self.plot.unit_label.setText(f'{unit} · {WINDOW_SECONDS:.0f} s')
        curves = {measured: (), 'Target': ()}
        measured_state, target_state, mode_state, setup_state = states
        detail = 'Connect the kit to see its response'
        if self._connected:
            seconds = now - start
            curves.update(time_series(data, 21, {measured: (8 if angle else 0) + axis}, now, seconds))
            curves.update(time_series(data, 23, {'Target': (10 if angle else 7) + axis}, now, seconds))
            detail = 'Waiting for telemetry'
            # The firmware returns early during setup or when its IMU is unavailable.
            # In RATE mode it still publishes the last ANGLE setpoint in group 23.
            modes = ((t, row) for t, row in data.scopes.rows[120] if t >= self._since)
            setup = ((t, row) for t, row in data.scopes.rows[130] if t >= self._since)
            def loop_ready(row):
                return row[2] and row[4] > 0 and row[5] > 0 and (not angle or row[1])
            targets, mode_confirmed = _target_period(curves['Target'], modes, start, now, loop_ready)
            curves['Target'], setup_confirmed = _target_period(targets, setup, start, now, lambda row: not row[0])
            if setup_state == 'Live' and data.scopes.latest(130)[1][0]:
                target_state, detail = 'Setup lock', 'Setup has paused the control loop'
            elif mode_state != 'Live':
                target_state = mode_state
            elif setup_state != 'Live':
                target_state = setup_state
            elif not loop_ready(data.scopes.latest(120)[1]):
                target_state = 'Rate mode' if angle and not data.scopes.latest(120)[1][1] else 'Invalid'
            elif target_state == 'Live' and not (mode_confirmed and setup_confirmed):
                target_state = 'Waiting'
        state = next((s for s in ('Offline', 'Setup lock', 'Invalid', 'Stale', 'Rate mode', 'Waiting')
                      if s in (measured_state, target_state)), 'Live')
        self.plot.set_data(curves, (now - WINDOW_SECONDS, now), state=state, detail=detail)
        for name, channel_state in ((measured, measured_state), ('Target', target_state)):
            samples = curves[name]
            value = samples[-1][1] if samples and channel_state == 'Live' else None
            text = '—' if value is None else f'{value:+.1f}'
            self.plot.buttons[name].setText(f'{name}  {text}')
