"""Native, read-only time and frequency plots for received flight telemetry."""
from bisect import bisect_left
from dataclasses import dataclass
import math
from statistics import median

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QSizePolicy,
                               QToolButton, QVBoxLayout, QWidget)


TRACE_COLORS = ('#69e2cc', '#f9ad67', '#aeb0ff', '#68c1fd',
                '#f28cb3', '#e2d46d', '#b3d794', '#c69aea')
LEFT = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
CENTER = Qt.AlignmentFlag.AlignCenter


def _num(value):
    if abs(value) < 1e-12:
        return '0'
    return f'{value:.4g}'.replace('-', '−')


def _tick_step(span, intervals):
    rough = max(1e-12, span / max(1, intervals))
    scale = 10 ** math.floor(math.log10(rough))
    for multiplier in (1., 2., 2.5, 5., 10.):
        if multiplier * scale >= rough * .999999:
            return multiplier * scale
    return 10. * scale


def _ticks(low, high, step):
    first = math.ceil(low / step - 1e-9)
    last = math.floor(high / step + 1e-9)
    return [i * step for i in range(first, last + 1)]


def _segments(points, gap):
    """Split at missing samples, time reversals or excessive sample intervals."""
    if gap is None:
        intervals = [b[0] - a[0] for a, b in zip(points, points[1:])
                     if b[0] > a[0] and a[1] is not None and b[1] is not None]
        gap = 3.5 * median(intervals) if intervals else math.inf
    pieces = []
    run = []
    for x, y in points:
        if run and (y is None or x < run[-1][0] or x - run[-1][0] > gap):
            pieces.append(run)
            run = []
        if y is not None:
            run.append((x, y))
    if run:
        pieces.append(run)
    return pieces


def _envelope(points, xmin, xmax, columns):
    """Retain first/last and actual extrema per display column in time order."""
    if len(points) <= columns * 2:
        return points
    scale = columns / (xmax - xmin)
    output = []
    start = 0
    while start < len(points):
        column = int((points[start][0] - xmin) * scale)
        stop = start + 1
        least = most = start
        while stop < len(points) and int((points[stop][0] - xmin) * scale) == column:
            if points[stop][1] < points[least][1]:
                least = stop
            if points[stop][1] > points[most][1]:
                most = stop
            stop += 1
        output.extend(points[i] for i in sorted({start, least, most, stop - 1}))
        start = stop
    return output


@dataclass
class _Trace:
    name: str
    color: str
    runs: list
    stats: tuple | None
    peak: tuple | None


def _trace(name, points, color, limits, gap):
    xmin, xmax = limits
    selected = []
    for x, y in points:
        if not math.isfinite(x) or x < xmin or x > xmax:
            continue
        selected.append((x, y if y is not None and math.isfinite(y) else None))
    runs = _segments(selected, gap)
    valid = [point for run in runs for point in run]
    if not valid:
        return _Trace(name, color, [], None, None)
    peak = max(valid, key=lambda p: p[1])
    values = [p[1] for p in valid]
    return _Trace(name, color, runs, (min(values), peak[1], math.fsum(values) / len(values)), peak)


class ScopeCanvas(QWidget):
    def __init__(self, plot):
        super().__init__(plot)
        self.plot = plot
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(59)
        self._rect = QRectF()
        self._ylimits = (0., 1.)
        self._paths = {}
        self._geometry_key = None
        self._pointer = None
        self._hover = None
        self.setAccessibleName(plot.title + ' trace area')

    def invalidate(self):
        self._geometry_key = None
        self.update()

    def _map(self, x, y):
        xmin, xmax = self.plot.x_range
        ymin, ymax = self._ylimits
        r = self._rect
        return QPointF(r.left() + (x-xmin)/(xmax-xmin)*r.width(),
                       r.bottom() - (y-ymin)/(ymax-ymin)*r.height())

    def _scale(self, traces, target):
        if self.plot.y_range is not None:
            low, high = self.plot.y_range
            return (low, high), _tick_step(high-low, target)
        stats = [trace.stats for trace in traces if trace.stats is not None]
        if not stats:
            return (0., 1.), .5
        low, high = min(s[0] for s in stats), max(s[1] for s in stats)
        if low == high:
            radius = max(abs(low)*.025, .05)
            low, high = low - radius, high + radius
        pad = (high-low) * .055
        if self.plot.spectrum and low >= 0:
            low = 0.
        else:
            low -= pad
        high += pad
        step = _tick_step(high-low, target)
        return (math.floor(low/step)*step, math.ceil(high/step)*step), step

    def _prepare(self):
        plot = self.plot
        key = (plot.version, self.width(), self.height(), self.font())
        if key == self._geometry_key:
            return
        self._geometry_key = key
        traces = [t for t in plot.traces if t.name not in plot.hidden_traces]
        self._ylimits, ystep = self._scale(traces, max(2, min(6, (self.height()-24)//26)))
        self._yticks = _ticks(*self._ylimits, ystep)
        tickfont = QFont(self.font())
        tickfont.setPixelSize(10)
        fm = QFontMetricsF(tickfont)
        left = max(30., max((fm.horizontalAdvance(_num(t)) for t in self._yticks), default=0.)+9)
        left = min(left, self.width()*.29)
        self._rect = QRectF(left, 9, max(1., self.width()-left-17), max(1., self.height()-31))
        xmin, xmax = plot.x_range
        self._paths = {}
        ymin, ymax = self._ylimits
        left, bottom = self._rect.left(), self._rect.bottom()
        xscale = self._rect.width() / (xmax-xmin)
        yscale = self._rect.height() / (ymax-ymin)
        for trace in traces:
            path, dots = QPainterPath(), []
            for run in trace.runs:
                if len(run) == 1:
                    dots.append(self._map(*run[0]))
                else:
                    samples = _envelope(run, xmin, xmax, max(1, int(self._rect.width())))
                    x, y = samples[0]
                    path.moveTo(left + (x-xmin)*xscale, bottom - (y-ymin)*yscale)
                    for x, y in samples[1:]:
                        path.lineTo(left + (x-xmin)*xscale, bottom - (y-ymin)*yscale)
            self._paths[trace.name] = path, dots
        self._find_hover()

    def _find_hover(self):
        self._hover = None
        if self._pointer is None or not self._rect.contains(self._pointer):
            return
        xmin, xmax = self.plot.x_range
        x = xmin + (self._pointer.x()-self._rect.left()) / self._rect.width()*(xmax-xmin)
        nearest = math.inf
        for t in self.plot.traces:
            if t.name in self.plot.hidden_traces:
                continue
            for run in t.runs:
                if not run:
                    continue
                # A cursor within a recording gap must not acquire a distant sample.
                margin = 8.*(xmax-xmin)/self._rect.width()
                if x < run[0][0]-margin or x > run[-1][0]+margin:
                    continue
                i = bisect_left(run, (x, -math.inf))
                candidates = run[max(0,i-1):i+1]
                if not candidates:
                    continue
                point = min(candidates, key=lambda p: abs(p[0]-x))
                pos = self._map(*point)
                distance = abs(pos.y()-self._pointer.y()) + abs(pos.x()-self._pointer.x())
                if distance < nearest:
                    nearest = distance
                    self._hover = t, point, pos

    def mouseMoveEvent(self, event):
        self._pointer = event.position()
        self._prepare()
        self._find_hover()
        self.plot.refresh_inspector()
        self.update()

    def leaveEvent(self, event):
        self._pointer = self._hover = None
        self.plot.refresh_inspector()
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        self._prepare()
        plot = self.plot
        r = self._rect
        p = QPainter(self)
        font = QFont(self.font()); font.setPixelSize(10); p.setFont(font)
        p.fillRect(r, QColor('#10232d'))
        xmin, xmax = plot.x_range
        ymin, ymax = self._ylimits
        xstep = _tick_step(xmax-xmin, max(2, min(7, int(r.width()/55))))
        xlow, xhigh = xmin-plot.x_origin, xmax-plot.x_origin
        xticks = _ticks(xlow, xhigh, xstep)
        has_visible_samples = any(t.runs for t in plot.traces if t.name in self._paths)
        p.setPen(QPen(QColor('#203d48'), 1, Qt.PenStyle.DotLine))
        for xtick in xticks:
            at = self._map(xtick+plot.x_origin, ymin).x()
            p.drawLine(QPointF(at,r.top()), QPointF(at,r.bottom()))
        for ytick in self._yticks:
            ypos = self._map(xmin,ytick).y()
            p.setPen(QPen(QColor('#42606c' if ytick == 0 else '#26414d'), 1))
            p.drawLine(QPointF(r.left(),ypos), QPointF(r.right(),ypos))
            if has_visible_samples or plot.y_range is not None:
                p.setPen(QColor('#a2b9c4'))
                p.drawText(QRectF(0,ypos-8,r.left()-5,16), RIGHT, _num(ytick))
        p.setPen(QColor('#a2b9c4'))
        show_x_labels = not plot.spectrum or has_visible_samples
        for xtick in xticks if show_x_labels else ():
            at = self._map(xtick+plot.x_origin,ymin).x()
            text = _num(xtick)
            p.drawText(QRectF(at-25,r.bottom()+2,50,16), CENTER, text)

        p.save()
        p.setClipRect(r.adjusted(-1,-1,1,1))
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        live = plot.state.lower().startswith('live')
        for trace in plot.traces:
            if trace.name not in self._paths or not trace.runs:
                continue
            path, dots = self._paths[trace.name]
            color = QColor(trace.color)
            if plot.state.lower() in ('stale','offline','lost'):
                color.setAlpha(165)
            glow = QColor(color); glow.setAlpha(25)
            if plot._pulse_name == trace.name and plot._pulse.state() == QVariantAnimation.State.Running:
                glow.setAlpha(round(35 * float(plot._pulse.currentValue())))
                p.setPen(QPen(glow, 3.)); p.drawPath(path)
            p.setPen(QPen(color, 1., Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                          Qt.PenJoinStyle.RoundJoin))
            p.drawPath(path)
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(color)
            for dot in dots:
                p.drawEllipse(dot, 1.7, 1.7)
            if live and not plot.spectrum:
                tip = self._map(*trace.runs[-1][-1])
                p.setBrush(glow); p.drawEllipse(tip, 4.7, 4.7)
                p.setBrush(color); p.drawEllipse(tip, 2.1, 2.1)
            p.setBrush(Qt.BrushStyle.NoBrush)
        if self._hover is not None:
            trace, point, pos = self._hover
            p.setPen(QPen(QColor('#a9bdc7'), 1, Qt.PenStyle.DashLine))
            p.drawLine(QPointF(pos.x(),r.top()),QPointF(pos.x(),r.bottom()))
            p.drawLine(QPointF(r.left(),pos.y()),QPointF(r.right(),pos.y()))
            p.setPen(QPen(QColor(trace.color),2)); p.setBrush(QColor('#10232d')); p.drawEllipse(pos,4.,4.)
        p.restore()

        if not has_visible_samples:
            p.setPen(QColor('#b5cbd5'))
            message = 'Select a trace' if plot.traces and all(t.name in plot.hidden_traces for t in plot.traces) else (plot.detail or 'Waiting for samples')
            p.drawText(r.adjusted(8,3,-8,-3), CENTER | Qt.TextFlag.TextWordWrap, message)
        p.end()


class ScopePlot(QFrame):
    """An inspectable chart. Series and scale are replaced by the telemetry view."""
    def __init__(self, title, unit, *, spectrum=False, parent=None):
        super().__init__(parent)
        self.title, self.unit, self.spectrum = title, unit, spectrum
        self.traces = []
        self.x_range, self.y_range, self.x_origin = (0.,1.), None, 1.
        self.state, self.detail = 'Waiting', ''
        self.hidden_traces = set()
        self.buttons = {}
        self._preferred = None
        self.version = 0
        self._pulse_name = None
        self._pulse = QVariantAnimation(self)
        self._pulse.setDuration(170)
        self._pulse.setStartValue(1.)
        self._pulse.setEndValue(0.)
        self.setObjectName('scopeChart')
        self.setAccessibleName(title)
        self.setStyleSheet("""
            QFrame#scopeChart {background:#152c37;border:1px solid #35505b;border-radius:9px;}
            QFrame#scopeChart QLabel {background:transparent;border:none;padding:0;}
            QLabel#chartTitle {color:#ecf5f4;font-size:14px;font-weight:700;}
            QLabel#chartUnit, QLabel#chartInspector {color:#b4c9d1;font-size:10px;}
            QToolButton {font-size:11px;min-height:15px;padding:0px 5px;border-radius:4px;}
            QToolButton:focus {border:1px solid #e4efec;}
        """)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumWidth(180)
        outer = QVBoxLayout(self); outer.setContentsMargins(9,6,9,5); outer.setSpacing(2)
        header = QHBoxLayout(); header.setSpacing(7)
        title_lbl = QLabel(title); title_lbl.setObjectName('chartTitle')
        header.addWidget(title_lbl)
        self.unit_label = QLabel(unit); self.unit_label.setObjectName('chartUnit')
        header.addWidget(self.unit_label)
        header.addStretch()
        self.badge = QLabel(); header.addWidget(self.badge)
        outer.addLayout(header)
        self.legend = QHBoxLayout(); self.legend.setContentsMargins(0,0,0,0); self.legend.setSpacing(4)
        self.legend.addStretch(); outer.addLayout(self.legend)
        self.canvas = ScopeCanvas(self); outer.addWidget(self.canvas, 1)
        self._pulse.valueChanged.connect(lambda _: self.canvas.update())
        self.inspector = QLabel(); self.inspector.setObjectName('chartInspector')
        self.inspector.setMinimumWidth(1)
        self.inspector.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        footer = QHBoxLayout()
        footer.addWidget(self.inspector, 1)
        x_axis = QLabel('Frequency (Hz)' if spectrum else 'Time (s)')
        x_axis.setObjectName('chartUnit')
        footer.addWidget(x_axis)
        outer.addLayout(footer)
        self.set_data({}, (0.,1.), state='Waiting')

    def minimumSizeHint(self):
        return QSize(180, 132)

    def _legends(self, names):
        if list(self.buttons) == names:
            return
        for b in self.buttons.values():
            self.legend.removeWidget(b)
            b.hide()
            b.deleteLater()
        self.buttons = {}
        for i,name in enumerate(names):
            b = QToolButton(); b.setText(name); b.setAutoRaise(False)
            b.setCheckable(True); b.setChecked(name not in self.hidden_traces)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setAccessibleName('Show '+name+' trace')
            color = TRACE_COLORS[i % len(TRACE_COLORS)]
            b.setStyleSheet(f"""
                QToolButton {{color:#9aaeb8;background:#1b303b;border:1px solid #354a55;}}
                QToolButton:checked {{color:{color};background:#203943;border:1px solid #40616b;}}
                QToolButton:hover {{background:#304e59;}}
                QToolButton:pressed {{background:#10252f;}}
                QToolButton:focus {{border:1px solid #deeeea;}}
            """)
            b.toggled.connect(lambda checked, n=name: self._toggle(n,checked))
            self.legend.insertWidget(i,b); self.buttons[name] = b

    def _toggle(self, name, checked):
        if checked:
            self.hidden_traces.discard(name)
            self._preferred = name
            if self.isVisible():
                self._pulse.stop()
                self._pulse_name = name
                self._pulse.start()
        else:
            self.hidden_traces.add(name)
        self.version += 1
        self.canvas.invalidate()
        self.canvas._prepare()
        self.refresh_inspector()

    def set_data(self, series, x_range, *, state='Live', detail='', gap=None, y_range=None, x_origin=None):
        xmin, xmax = x_range
        if not (math.isfinite(xmin) and math.isfinite(xmax) and xmax > xmin):
            raise ValueError('Chart range must be finite and increasing.')
        if y_range is not None:
            lo, hi = y_range
            if not (math.isfinite(lo) and math.isfinite(hi) and hi > lo):
                raise ValueError('Chart vertical range must be finite and increasing.')
        names = list(series)
        self._legends(names)
        self.x_range, self.y_range = (xmin,xmax), y_range
        self.x_origin = (0. if self.spectrum else xmax) if x_origin is None else x_origin
        self.state, self.detail = state, detail
        self.traces = [_trace(name, list(series[name]), TRACE_COLORS[i%len(TRACE_COLORS)], self.x_range,gap)
                       for i,name in enumerate(names)]
        self.version += 1
        self.canvas.invalidate()
        self._update_badge()
        for trace in self.traces:
            tooltip = trace.name
            if trace.stats:
                low, high, avg = trace.stats
                tooltip += f'  ·  Min {_num(low)}  ·  Max {_num(high)}  ·  Mean {_num(avg)} {self.unit}'
            b = self.buttons[trace.name]
            if b.toolTip() != tooltip:
                b.setToolTip(tooltip)
        self.badge.setToolTip(self.detail)
        if self.canvas._pointer is not None:
            self.canvas._prepare()
        self.refresh_inspector()

    def _update_badge(self):
        text = self.state.upper()
        if self.badge.text() == text:
            return
        self.badge.setText(text)
        color = '#91ebcc' if text.startswith('LIVE') else '#ffcd92' if text in ('STALE','LOST') else '#acbfc9'
        self.badge.setStyleSheet(f'color:{color};font-size:9px;font-weight:700;')

    def refresh_inspector(self):
        trace = None
        hover = self.canvas._hover if self.canvas._pointer is not None else None
        if hover is not None:
            trace = hover[0]
        available = [t for t in self.traces if t.name not in self.hidden_traces and t.stats]
        if trace is None:
            trace = next((t for t in available if t.name == self._preferred), next(iter(available),None))
        if trace is None:
            value = ''
        elif hover is not None:
            x, y = hover[1]
            value = f'{trace.name}   {_num(x-self.x_origin)} {"Hz" if self.spectrum else "s"}   ·   {_num(y)} {self.unit}'
        else:
            low, high, avg = trace.stats
            if self.spectrum:
                value = f'{trace.name}    Peak {_num(trace.peak[0])} Hz    ·    {_num(trace.peak[1])} {self.unit}'
            else:
                value = f'{trace.name}    Min {_num(low)}    Max {_num(high)}    Mean {_num(avg)} {self.unit}'
        if self.inspector.text() != value:
            self.inspector.setText(value)

    def hideEvent(self, event):
        self._pulse.stop()
        self.canvas._pointer = self.canvas._hover = None
        super().hideEvent(event)
