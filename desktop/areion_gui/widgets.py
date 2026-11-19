"""Painted transmitter controls and bounded live plots; no hardware side effects."""
import math
import time
from PySide6.QtCore import Qt, QPointF, QRectF, Signal, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPainterPath, QLinearGradient, QPolygonF
from PySide6.QtWidgets import (QWidget, QFrame, QLabel, QVBoxLayout, QHBoxLayout,
                              QGridLayout, QPushButton, QDoubleSpinBox, QSpinBox, QAbstractSpinBox, QSizePolicy)
from zebjus_areion_link.schema import DRONE_GROUPS
from .combo_box import ConsoleComboBox
from .model import field_label, equal_values, FLIGHT_MODES
from .attitude_model import AttitudeModel, wrapped_angle
from .scroll_guard import page_action_button

ACCENT = '#ffad66'
TEAL = '#5cddc2'
MUTED = '#8da1b8'

def label(text='', role=None):
    item = QLabel(text)
    if role:
        item.setObjectName(role)
    return item

def button(text, callback=None, role=None):
    item = QPushButton(text)
    item.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
    item.setAutoDefault(False)
    item.setCursor(Qt.CursorShape.PointingHandCursor)
    if role:
        item.setObjectName(role)
    if callback:
        item.clicked.connect(callback)
    return item

class Card(QFrame):
    def __init__(self, title='', subtitle=''):
        super().__init__()
        self.setObjectName('card')
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(16, 14, 16, 14)
        self.box.setSpacing(10)
        if title:
            self.box.addWidget(label(title, 'cardTitle'))
        if subtitle:
            text = label(subtitle, 'muted')
            text.setWordWrap(True)
            self.box.addWidget(text)

class Metric(Card):
    def __init__(self, title, unit=''):
        super().__init__()
        self.box.setContentsMargins(14, 12, 14, 12)
        self.box.addWidget(label(title.upper(), 'eyebrow'))
        row = QHBoxLayout()
        self.value = label('—', 'metric')
        row.addWidget(self.value)
        row.addWidget(label(unit, 'muted'), alignment=Qt.AlignmentFlag.AlignBottom)
        row.addStretch()
        self.box.addLayout(row)

    def set_value(self, value, decimals=2):
        self.value.setText('—' if value is None else f'{value:.{decimals}f}')

class Joystick(QWidget):
    moved = Signal(float, float, bool)

    def __init__(self, left=False, light=False):
        super().__init__()
        self.left = left
        self.light = light
        self.x, self.y = 0., -1. if left else 0.
        self.held = False
        self.available = True
        self._painted_state = None
        self.setMinimumSize(116, 108)
        self.setAccessibleName('Throttle and yaw stick' if left else 'Pitch and roll stick')
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setToolTip('Drag to control. Throttle holds; yaw returns to center.' if left else 'Drag to control. Both axes return to center on release.')

    def geometry_values(self):
        return QPointF(self.width() / 2, self.height() / 2), min(self.width(), self.height()) / 2 - 29

    def sync(self, x, y):
        self.available = x is not None and y is not None
        if self.available:
            self.x, self.y = max(-1., min(1., x)), max(-1., min(1., y))
        if self._painted_state != (self.available, self.x, self.y, self.held):
            self.update()

    def paintEvent(self, event):
        self._painted_state = (self.available, self.x, self.y, self.held)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        center, radius = self.geometry_values()
        travel = radius * .70
        bezel = radius + 21
        accent = QColor('#ffc571' if self.left else '#85e6d7')
        p.translate(center)

        metal = QLinearGradient(-bezel, -bezel, bezel, bezel)
        metal.setColorAt(0, QColor('#70828a' if self.light else '#526b76'))
        metal.setColorAt(.46, QColor('#213844'))
        metal.setColorAt(1, QColor('#112330'))
        p.setPen(QPen(QColor('#69828a'), .8))
        p.setBrush(metal)
        p.drawEllipse(QPointF(), bezel, bezel)
        p.setPen(QPen(QColor('#223b48'), 1))
        p.setBrush(QColor('#112733'))
        p.drawEllipse(QPointF(), bezel - 3, bezel - 3)

        inner = bezel - 11
        p.setBrush(QColor('#0b1e29'))
        p.setPen(QPen(QColor('#314955'), 1))
        p.drawEllipse(QPointF(), inner, inner)
        p.setPen(QPen(QColor('#253f4a'), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(), radius * .74, radius * .74)
        for i in range(32):
            cardinal = i % 8 == 0
            color = accent if cardinal and self.available else QColor('#627a84')
            p.setPen(QPen(color, 2 if cardinal else 1))
            theta = i * math.tau / 32
            direction = QPointF(math.sin(theta), -math.cos(theta))
            p.drawLine(direction * (inner + (1 if cardinal else 3)), direction * (bezel - 5))

        p.setPen(QPen(QColor('#41606d'), 1))
        p.drawLine(QPointF(-inner, 0), QPointF(inner, 0))
        p.drawLine(QPointF(0, -inner), QPointF(0, inner))
        p.setPen(QPen(QColor('#63808a'), 1))
        for frac in (-1, -.5, .5, 1):
            d = frac * travel
            p.drawLine(QPointF(d, -2), QPointF(d, 2))
            p.drawLine(QPointF(-2, d), QPointF(2, d))

        if not self.available:
            font = QFont(self.font())
            font.setPixelSize(round(min(12, max(9, bezel * .18))))
            font.setWeight(QFont.Weight.DemiBold)
            p.setFont(font)
            text = 'NO INPUT'
            width = p.fontMetrics().horizontalAdvance(text) + 12
            plaque = QRectF(-width / 2, -9, width, 18)
            p.setPen(QPen(QColor('#45606c'), 1))
            p.setBrush(QColor('#122b36'))
            p.drawRoundedRect(plaque, 4, 4)
            p.setPen(QColor('#c8d9dc'))
            p.drawText(plaque, Qt.AlignmentFlag.AlignCenter, text)
            return

        # Show square X/Y travel even at diagonals; the mouse uses the same travel.
        tip = QPointF(self.x * travel, -self.y * travel)
        grip = min(20, max(9, radius * .30))
        p.setPen(QPen(QColor('#58717a'), max(3, grip * .32), Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(), tip)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 85))
        p.drawEllipse(tip + QPointF(0, 2.5), grip + 1.5, grip + 1.5)
        cap = QLinearGradient(tip - QPointF(0, grip), tip + QPointF(0, grip))
        cap.setColorAt(0, QColor('#5d7d87'))
        cap.setColorAt(.55, QColor('#324d58'))
        cap.setColorAt(1, QColor('#233b48'))
        p.setPen(QPen(accent if self.held else QColor('#90a8ae'), 2 if self.held else 1.1))
        p.setBrush(cap)
        p.drawEllipse(tip, grip, grip)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(accent)
        p.drawEllipse(tip, grip * .27, grip * .27)

    def _move(self, point):
        c, r = self.geometry_values()
        travel = r * .70
        self.x = max(-1., min(1., (point.x() - c.x()) / travel))
        self.y = max(-1., min(1., (c.y() - point.y()) / travel))
        self.moved.emit(self.x, self.y, True)
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.held = True
            self._move(event.position())

    def mouseMoveEvent(self, event):
        if self.held and event.buttons() & Qt.MouseButton.LeftButton:
            self._move(event.position())
        elif self.held:
            self.held=False;self.x=0.
            if not self.left:self.y=0.
            self.moved.emit(self.x,self.y,False);self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.held = False
            self.x = 0.
            if not self.left:
                self.y = 0.
            self.moved.emit(self.x, self.y, False)
            self.update()

class Horizon(QWidget):
    def __init__(self):
        super().__init__()
        self.model = AttitudeModel()
        self.roll = self.pitch = self.yaw = None
        self.display_roll = self.display_pitch = self.display_yaw = None
        self._frame_at = time.monotonic()
        self.setMinimumSize(230, 210)
        self.setAccessibleName('Live roll, pitch and relative yaw instrument')
        self.setToolTip('Yaw is integrated from the gyroscope since this continuous connection. It may drift and is not a compass heading.')
        self.animation = QTimer(self);self.animation.setInterval(16)
        self.animation.timeout.connect(self._animate);self.animation.start()

    def set_angles(self, roll, pitch):
        # Compatibility for a roll/pitch-only caller: never invent yaw data.
        now = time.monotonic()
        if roll is None or pitch is None:
            self.model.invalidate()
        else:
            self.model.update([0.,0.,0.,0.,0.,1.,roll,pitch,roll,pitch],now,now,'angles')
            self.model.yaw = self.model.yaw_rate = None
        self._sync_targets()

    def update_telemetry(self, imu, stamp, now, identity, valid=True):
        new_reference = identity != self.model.identity or self.model.stamp is None
        if type(stamp) in (int,float) and self.model.stamp is not None:
            new_reference |= stamp-self.model.stamp>self.model.MAX_GAP
        self.model.update(imu,stamp,now,identity,valid)
        if new_reference:self.display_roll=self.display_pitch=self.display_yaw=None
        self._sync_targets()

    def reset_yaw(self):
        self.model.reset_yaw();self.yaw=self.model.yaw;self.display_yaw=self.yaw
        self.update()

    def _sync_targets(self):
        self.roll,self.pitch,self.yaw=self.model.roll,self.model.pitch,self.model.yaw
        if not self.model.valid:
            self.display_roll=self.display_pitch=self.display_yaw=None
        elif self.display_roll is None:
            self.display_roll,self.display_pitch=self.roll,self.pitch
            self.display_yaw=self.yaw
        if self.yaw is None:self.display_yaw=None
        elif self.display_yaw is None:self.display_yaw=self.yaw
        self.update()

    def _animate(self):
        now=time.monotonic();dt=max(0.,min(.1,now-self._frame_at));self._frame_at=now
        if self.model.stamp is not None and now-self.model.stamp>self.model.MAX_AGE:
            self.model.invalidate();self._sync_targets();return
        if self.roll is None:return
        amount=1.-math.exp(-dt/.075)
        for name,angular in (('roll',True),('pitch',False),('yaw',True)):
            target=getattr(self,name);current=getattr(self,'display_'+name)
            if target is None or current is None:continue
            delta=wrapped_angle(target-current) if angular else target-current
            value=current+amount*delta
            setattr(self,'display_'+name,wrapped_angle(value) if angular else value)
        if self.isVisible():self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0, 0, self.width(), self.height())
        clip = QPainterPath(); clip.addRoundedRect(rect, 12, 12)
        p.setClipPath(clip)
        p.fillRect(rect, QColor('#0a1421'))
        if self.display_roll is None:
            p.setPen(QColor(MUTED));p.setFont(QFont('Sans Serif',10))
            p.drawText(rect.adjusted(10,10,-10,-10), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                       'WAITING FOR LIVE IMU\nRoll · Pitch · Relative yaw')
            return
        header,footer=39.,42.
        flight=QRectF(0,header,rect.width(),max(80.,rect.height()-header-footer))
        c=flight.center();scale=max(1.3,min(3.,flight.height()/65.))
        p.save();p.setClipRect(flight);p.translate(c);p.rotate(-self.display_roll)
        offset=self.display_pitch*scale
        sky=QLinearGradient(0,-500,0,offset);sky.setColorAt(0,QColor('#16374d'));sky.setColorAt(1,QColor('#28739b'))
        ground=QLinearGradient(0,offset,0,500);ground.setColorAt(0,QColor('#795c3c'));ground.setColorAt(1,QColor('#382e27'))
        p.fillRect(QRectF(-1800,-1800+offset,3600,1800),sky)
        p.fillRect(QRectF(-1800,offset,3600,1800),ground)
        p.setPen(QPen(QColor('#f6ebcf'),2));p.drawLine(QPointF(-1800,offset),QPointF(1800,offset))
        p.setFont(QFont('Sans Serif', 9))
        for degree in range(-80,81,5):
            if degree==0:continue
            y=offset-degree*scale;major=degree%10==0;half=33 if major else 16
            p.setPen(QPen(QColor('#e2eef1'),1,Qt.PenStyle.SolidLine if degree>0 else Qt.PenStyle.DashLine))
            p.drawLine(QPointF(-half,y),QPointF(half,y))
            if major:
                p.drawText(QRectF(half+5,y-8,24,16),Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,str(abs(degree)))
                p.drawText(QRectF(-half-29,y-8,24,16),Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,str(abs(degree)))
        p.restore()
        # Fixed bank scale; pointer rotates around the actual horizon centre.
        radius=min(flight.height()*.47,rect.width()*.36)
        p.save();p.setClipRect(flight)
        for bank in (-60,-45,-30,-20,-10,0,10,20,30,45,60):
            angle=math.radians(bank);start=c+QPointF(math.sin(angle)*radius,-math.cos(angle)*radius)
            length=9 if bank%30==0 else 5
            end=c+QPointF(math.sin(angle)*(radius-length),-math.cos(angle)*(radius-length))
            p.setPen(QPen(QColor('#f3f4e9'),2 if bank==0 else 1));p.drawLine(start,end)
        p.translate(c);p.rotate(-self.display_roll)
        p.setBrush(QColor(ACCENT));p.setPen(Qt.PenStyle.NoPen)
        p.drawPolygon(QPolygonF([QPointF(0,-radius+11),QPointF(-5,-radius+20),QPointF(5,-radius+20)]));p.restore()
        p.setPen(QPen(QColor('#101926'),5));p.drawLine(c+QPointF(-61,0),c+QPointF(-16,0));p.drawLine(c+QPointF(16,0),c+QPointF(61,0))
        p.setPen(QPen(QColor(ACCENT),3));p.drawLine(c+QPointF(-61,0),c+QPointF(-16,0));p.drawLine(c+QPointF(16,0),c+QPointF(61,0));p.drawEllipse(c,4,4)
        # Relative heading tape intentionally omits N/E/S/W compass labels.
        p.fillRect(QRectF(0,0,rect.width(),header),QColor('#102236'))
        p.setFont(QFont('Sans Serif',8));p.setPen(QColor('#9cb5ca'))
        p.drawText(QRectF(8,3,rect.width()-16,14),Qt.AlignmentFlag.AlignLeft,'RELATIVE YAW · GYRO')
        if self.display_yaw is not None:
            pixels=rect.width()/100.;centre=rect.width()/2.;yaw=self.display_yaw
            for relative in range(-60,61,10):
                degree=10*math.floor(yaw/10)+relative;x=centre+wrapped_angle(degree-yaw)*pixels
                if 10<x<rect.width()-10:
                    p.setPen(QColor('#b4ccdf'));p.drawLine(QPointF(x,34),QPointF(x,39))
                    p.drawText(QRectF(x-16,18,32,15),Qt.AlignmentFlag.AlignCenter,f'{wrapped_angle(degree):.0f}')
            p.setBrush(QColor(ACCENT));p.setPen(Qt.PenStyle.NoPen)
            p.drawPolygon(QPolygonF([QPointF(centre,38),QPointF(centre-4,32),QPointF(centre+4,32)]))
        else:
            p.drawText(QRectF(8,18,rect.width()-16,18),Qt.AlignmentFlag.AlignCenter,'UNAVAILABLE')
        p.fillRect(QRectF(0,rect.height()-footer,rect.width(),footer),QColor('#101b29'))
        p.setPen(QColor('#f0f4f8'));p.setFont(QFont('Monospace',9))
        p.drawText(QRectF(5,rect.height()-footer+3,rect.width()-10,18),Qt.AlignmentFlag.AlignCenter,
                   f'ROLL {self.roll:+.1f}°   PITCH {self.pitch:+.1f}°')
        p.setFont(QFont('Sans Serif',8));p.setPen(QColor('#9cb5ca'))
        yaw_text=f'YAW {self.yaw:+.1f}° · relative / may drift' if self.yaw is not None else 'Relative yaw unavailable'
        p.drawText(QRectF(5,rect.height()-20,rect.width()-10,17),Qt.AlignmentFlag.AlignCenter,yaw_text)

class Plot(QWidget):
    def __init__(self, title='', colors=(TEAL, ACCENT, '#8cabff')):
        super().__init__()
        self.title, self.colors = title, colors
        self.series = []
        self.names = []
        self.setMinimumHeight(170)

    def set_series(self, series, names):
        self.series, self.names = [list(s) for s in series], names
        self.update()

    def paintEvent(self, event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        box=QRectF(48, 30, max(1,self.width()-65), max(1,self.height()-62))
        p.fillRect(self.rect(),QColor('#101926'))
        p.setFont(QFont('Sans Serif',9));p.setPen(QColor(MUTED))
        p.drawText(QPointF(10,17),self.title)
        now=time.monotonic();start=now-15
        data=[[(t,v) for t,v in s if t>=start] for s in self.series]
        nums=[v for s in data for _,v in s]
        low,high=(min(nums),max(nums)) if nums else (-1,1)
        pad=max(.05,(high-low)*.15);low-=pad;high+=pad
        for i in range(5):
            y=box.top()+i*box.height()/4
            p.setPen(QPen(QColor('#233145'),1));p.drawLine(QPointF(box.left(),y),QPointF(box.right(),y))
            p.setPen(QColor(MUTED));p.drawText(QRectF(0,y-8,43,16),Qt.AlignmentFlag.AlignRight,f'{high-(high-low)*i/4:.2g}')
        for i, series in enumerate(data):
            path=QPainterPath()
            for j,(t,value) in enumerate(series):
                point=QPointF(box.left()+(t-start)/15*box.width(),box.bottom()-(value-low)/(high-low)*box.height())
                if j==0:path.moveTo(point)
                else:path.lineTo(point)
            p.setPen(QPen(QColor(self.colors[i%len(self.colors)]),2));p.drawPath(path)
        x=48
        for i,name in enumerate(self.names):
            p.setPen(QColor(self.colors[i%len(self.colors)]));p.drawText(QPointF(x,self.height()-9),name);x+=max(90,len(name)*8)
        if not nums:
            p.setPen(QColor(MUTED));p.drawText(box,Qt.AlignmentFlag.AlignCenter,'No recent samples')

class ChoiceInput(ConsoleComboBox):
    """Integer-valued choices with the same readback API as a numeric field."""
    def __init__(self, choices):
        super().__init__()
        for value, text in choices:
            self.addItem(text, value)

    def value(self):
        return self.currentData()

    def setValue(self, value):
        index = self.findData(value)
        if index < 0:
            raise ValueError('Unknown settings choice')
        self.setCurrentIndex(index)

class SettingsCard(Card):
    requested = Signal(int, str, object)

    def __init__(self, group, title, subtitle='', persist_on_apply=False):
        super().__init__(title,subtitle)
        self.persist_on_apply=persist_on_apply
        self.group=group;self.active=None;self.loaded=False;self.allowed=False;self.can_read=False;self.busy=False
        self.inputs=[];grid=QGridLayout();grid.setHorizontalSpacing(16)
        for index,field in enumerate(DRONE_GROUPS[group]['fields']):
            if group==7 and index in (0,4,5):
                choices = [(n,f'CH{n}'+(' · AUX' if n>=5 else ' · stick axis')) for n in range(1,9)] if index==0 else list(FLIGHT_MODES.items())
                item=ChoiceInput(choices);item.setValue(field['default'])
                item.currentIndexChanged.connect(self._edited)
            else:
                item=QSpinBox() if field['type']=='int' else QDoubleSpinBox()
                if isinstance(item,QDoubleSpinBox):
                    item.setDecimals(5);item.setSingleStep(.01)
                item.setRange(field['min'],field['max']);item.setValue(field['default'])
                item.setKeyboardTracking(False);item.valueChanged.connect(self._edited)
            item.setMinimumWidth(90)
            columns=2 if group==3 else 3
            position={0:0,4:1,5:2,1:3,2:4,3:5}[index] if group==7 else index
            column=position%columns;row=(position//columns)*2
            title={0:'Flight mode channel',4:'Low · below 1500',5:'High · 1500 and above'}.get(index,field_label(field['name'])) if group==7 else field_label(field['name'])
            grid.addWidget(label(title,'muted'),row,column)
            grid.addWidget(item,row+1,column);self.inputs.append(item)
        self.box.addLayout(grid)
        row=QHBoxLayout();self.buttons={}
        actions=[('read','Read FC'),('stored','Read saved'),('apply','Apply to FC')] if persist_on_apply else [('read','Read FC'),('stored','Read saved'),('apply','Apply'),('save','Save to FC')]
        for action,text in actions:
            b=page_action_button(text,lambda checked=False,a=action:self._request(a),'primary' if action=='apply' else None)
            row.addWidget(b);self.buttons[action]=b
        row.addStretch()
        self.box.addLayout(row)
        self.note=label('Not loaded','muted');self.note.setWordWrap(True);self.box.addWidget(self.note)
        self.refresh()

    def values(self):
        return [widget.value() for widget in self.inputs]

    def refresh(self):
        dirty=self.active is not None and not equal_values(self.values(),self.active)
        for action,b in self.buttons.items():
            b.setEnabled(not self.busy and ((action in ('read','stored') and self.can_read) or
                         (action in ('apply','save') and self.allowed and self.loaded and not (action=='save' and dirty))))
        for item in self.inputs:item.setEnabled(self.allowed and not self.busy)

    def _edited(self):
        if self.loaded:
            self.note.setText('Unsaved changes' if not equal_values(self.values(),self.active) else 'Matches FC')
        self.refresh()

    def _request(self,action):
        self.busy=True;self.note.setText('Waiting for FC…');self.refresh()
        self.requested.emit(self.group,action,self.values())

    def finish(self, action, values=None, error=None):
        self.busy=False
        if error:
            self.note.setText(str(error));self.refresh();return
        if action!='stored':self.active=list(values);self.loaded=True
        for widget,value in zip(self.inputs,values):
            widget.blockSignals(True);widget.setValue(value);widget.blockSignals(False)
        self.note.setText({'read':'Loaded from FC', 'stored':'Saved copy · not applied',
                           'apply':'APPLIED · not saved',
                           'save':'SAVED · verified'}[action])
        self.refresh()
