"""Native two-dimensional fixed signal map and motor preview for Areion FC A1."""
from PySide6.QtCore import Qt,QPointF,QRectF
from PySide6.QtGui import QColor,QPainter,QPen,QFont,QPolygonF,QPainterPath
from PySide6.QtWidgets import QWidget
from .wizard_model import QUAD_X_MOTORS

COLORS=['#64dbc3','#7eb8ff','#ffb46f','#c0a1ff']

def text(p,x,y,w,h,value,size=13,color='#d7e5f4'):
    p.setPen(QColor(color));p.setFont(QFont('Sans Serif',size))
    p.drawText(QRectF(x,y,w,h),Qt.AlignmentFlag.AlignCenter,value)

class WiringView(QWidget):
    """Fixed role-to-pin signal map; graphical connector positions are schematic."""
    def __init__(self):
        super().__init__();self.focus=0;self.pins=('D0','D1','D2','D3')
        self.setMinimumHeight(390)
        self.setAccessibleName('Areion FC A1 fixed output, PPM receiver and IMU connection map')
    def set_focus(self,index):
        self.focus=index if index in range(6) else 0;self.update()
    @staticmethod
    def _line(p,points,color,width=2):
        path=QPainterPath(QPointF(*points[0]))
        for point in points[1:]:path.lineTo(QPointF(*point))
        p.setPen(QPen(QColor(color),width,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin))
        p.setBrush(Qt.BrushStyle.NoBrush);p.drawPath(path)
    def paintEvent(self,event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        s = min(self.width()/720, self.height()/190)
        p.translate((self.width()-720*s)/2, (self.height()-190*s)/2)
        p.scale(s, s)
        def caption(box, value, size=12, ink='#dcecea', bold=False):
            font = QFont(p.font()); font.setPixelSize(size); font.setBold(bold)
            p.setFont(font); p.setPen(QColor(ink))
            p.drawText(QRectF(*box), Qt.AlignmentFlag.AlignCenter, value)
        def block(box, fill, edge, radius=5):
            p.setPen(QPen(QColor(edge), 1.1)); p.setBrush(QColor(fill))
            p.drawRoundedRect(QRectF(*box), radius, radius)

        # Schematic: each pad label is a fixed signal role on the assembled PCB.
        block((152, 8, 233, 174), '#163a35', '#639082', 9)
        caption((157, 13, 217, 20), 'Areion FC A1', 15, '#bdedda', True)
        for x in (160, 377):
            for y in (16, 174):
                p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor('#92afa2'))
                p.drawEllipse(QPointF(x,y), 2,2)

        rx = '#8bd8ff' if self.focus == 4 else '#a0b6c4'
        block((3, 42, 112, 38), '#143448', rx)
        self._line(p, [(12,42),(12,27),(9,22)], rx, 2)
        caption((6, 45, 106, 30), 'PPM receiver', 13, rx, True)
        self._line(p, [(115,61),(153,61)],rx,3 if self.focus==4 else 1.5)
        caption((154,43,104,18), 'PPM  D10', 12, rx, True)
        caption((154,61,104,15), 'GPIO 18', 10, rx)
        imu = '#ffce85' if self.focus == 5 else '#b7c0b9'
        block((3, 105, 112, 52), '#2d3638', imu)
        caption((7,107,104,19), 'IMU', 13, imu, True)
        caption((7,130,104,18), 'SDA / SCL', 11, imu)
        for y, word in ((125,'SDA  D4 / 22'),(149,'SCL  D5 / 23')):
            self._line(p,[(115,y),(153,y)],imu,3 if self.focus==5 else 1.4)
            caption((154,y-10,108,20),word,11,imu,True)
        caption((0,162,142,17),'Common signal ground',10,'#b1c5ce')

        for i, (name,position,rotation) in enumerate(QUAD_X_MOTORS):
            y = 45+34*i
            active = self.focus == i
            color = COLORS[i] if active else '#a8bec5'
            block((267,y-11,111,22),'#12322f',color)
            caption((268,y-10,109,20),f'OUT {i+1}  ·  D{i}',12,color,True)
            self._line(p,[(379,y),(416,y)],color,2.7 if active else 1.3)
            block((416,y-13,68,26),'#233e48',color)
            caption((417,y-11,66,22),f'ESC {i+1}',12,color,True)
            for dy in (-4,0,4):
                self._line(p,[(484,y+dy),(518,y+dy)],color,1.3)
            p.setPen(QPen(QColor(color),1.6)); p.setBrush(QColor('#162e38'))
            p.drawEllipse(QPointF(532,y),14,14)
            caption((518,y-12,28,24),name,12,color,True)
            caption((551,y-12,159,24),f'{position}  ·  {rotation}',13,color,active)
        p.end()

class MotorView(QWidget):
    def __init__(self):
        super().__init__();self.setMinimumHeight(285);self.outputs=[1000]*4;self.selected=None;self.phase=0.
    def set_state(self,outputs,selected,phase):
        self.outputs=list(outputs);self.selected=selected;self.phase=phase;self.update()
    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        s=min(self.width()/540,self.height()/350);p.translate((self.width()-540*s)/2,(self.height()-350*s)/2);p.scale(s,s)
        pts=[(140,90),(400,90),(400,235),(140,235)]
        text(p,210,2,120,30,'FRONT ↑',15,'#ffb46f')
        p.setPen(QPen(QColor('#3a5368'),18,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap))
        for x,y in pts:p.drawLine(QPointF(270,172),QPointF(x,y))
        p.setPen(QPen(QColor('#5cddc2'),2));p.setBrush(QColor('#223f4c'));p.drawRoundedRect(QRectF(246,144,48,56),9,9)
        for i,((x,y),(name,_,rot)) in enumerate(zip(pts,QUAD_X_MOTORS)):
            color=COLORS[i] if self.selected is None or self.selected==i else '#45566a'
            p.setPen(QPen(QColor(color),2));p.setBrush(QColor('#122739'));p.drawEllipse(QPointF(x,y),49,49)
            if self.outputs[i]>1000:
                p.save();p.translate(x,y);p.rotate(self.phase*(1 if rot=='CW' else -1))
                c=QColor(color);c.setAlpha(65);p.setPen(Qt.PenStyle.NoPen);p.setBrush(c)
                p.drawEllipse(QRectF(-43,-12,86,24));p.drawEllipse(QRectF(-12,-43,24,86));p.restore()
            text(p,x-44,y-27,88,30,name,19,color);text(p,x-46,y+4,92,24,rot,12,color)
            text(p,x-80,y+54,160,28,f'{self.outputs[i]} µs',14,color)
        text(p,110,328,320,22,'COMMAND OUTPUT · NOT MEASURED RPM',11,'#ffb46f');p.end()

