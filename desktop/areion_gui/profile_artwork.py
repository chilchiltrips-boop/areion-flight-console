"""Scalable native 2D illustrations for setup profile and sensor-pose cards."""
from PySide6.QtCore import Qt,QPointF,QRectF
from PySide6.QtGui import QColor,QPainter,QPen,QPolygonF,QPainterPath,QFont
from PySide6.QtWidgets import QWidget

def _text(p,rect,value,size=11,color='#c8d8e8'):
    p.setPen(QColor(color));p.setFont(QFont('Sans Serif',size))
    p.drawText(QRectF(*rect),Qt.AlignmentFlag.AlignCenter,value)

def _line(p,points,color,width=2):
    path=QPainterPath(QPointF(*points[0]))
    for pt in points[1:]:path.lineTo(QPointF(*pt))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(QColor(color),width,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin))
    p.drawPath(path)

class ProfileArt(QWidget):
    """Illustrative profile art; it does not claim a model or protocol was applied."""
    def __init__(self,kind='aerion450',parent=None):
        super().__init__(parent);self.kind=kind;self.setMinimumHeight(150)
        self.setAccessibleName('Setup profile illustration')
    def set_kind(self,kind):
        self.kind=kind;self.update()
    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        scale=min(self.width()/320,self.height()/180)
        p.translate((self.width()-320*scale)/2,(self.height()-180*scale)/2);p.scale(scale,scale)
        if self.kind.startswith('pose_'):self._pose(p)
        elif self.kind.startswith('esc_'):self._esc(p)
        else:self._drone(p)
        p.end()

    def _esc(self,p):
        kind=self.kind.removeprefix('esc_')
        color={'standard50':'#7eb8ff','pwm250':'#64dbc3','oneshot':'#ffb46f'}.get(kind,'#64dbc3')
        # Power pair, three motor phase wires and a smaller receiver signal lead.
        for y,c in ((75,'#e98585'),(101,'#7d8b9a')):
            _line(p,[(12,y),(40,y),(66,85 if y==75 else 105),(80,85 if y==75 else 105)],c,5)
        for y in (63,90,117):
            _line(p,[(233,y),(258,y),(290,y-10 if y==63 else y+10 if y==117 else y)],'#d8b876',4)
            p.setPen(QPen(QColor('#546478'),1));p.setBrush(QColor('#a8b7c7'));p.drawRoundedRect(QRectF(287,y-14 if y==63 else y+6 if y==117 else y-4,18,8),3,3)
        _line(p,[(98,47),(89,28),(46,28)],'#a6c3d6',2)
        p.setBrush(QColor('#1b293a'));p.setPen(QPen(QColor('#4b657b'),1))
        p.drawRoundedRect(QRectF(24,21,24,15),3,3)
        # Broad heat-shrink outline with a contrasting faceplate.
        p.setPen(QPen(QColor(color),2));p.setBrush(QColor('#203447'))
        p.drawRoundedRect(QRectF(78,44,158,91),13 if kind!='oneshot' else 5,13 if kind!='oneshot' else 5)
        p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor('#0e1b2b'));p.drawRoundedRect(QRectF(89,54,136,71),8,8)
        for x in range(97,222,10):
            p.setPen(QPen(QColor('#2d4354'),2));p.drawLine(QPointF(x,59),QPointF(x,119))
        p.setBrush(QColor('#1d3446'));p.setPen(QPen(QColor(color),1));p.drawRoundedRect(QRectF(115,66,84,46),6,6)
        _text(p,(116,67,82,43),'ESC',23,color)
        p.setPen(QPen(QColor(color),3));p.drawLine(QPointF(91,130),QPointF(221,130))
        _text(p,(31,149,258,21),{'standard50':'STANDARD PWM','pwm250':'FAST PWM','oneshot':'ONESHOT'}.get(kind,'ESC PROFILE'),11,color)

    def _drone(self,p):
        racing=self.kind=='aerion250'
        custom=self.kind=='custom'
        color='#ffb46f' if racing else '#64dbc3' if self.kind=='stable' else '#c0a1ff' if custom else '#7eb8ff'
        pts=[(84,43),(236,43),(230,136),(90,136)] if not racing else [(106,40),(214,40),(224,140),(96,140)]
        # Landing feet and arms stay distinct for a broad utility frame and compact FPV frame.
        if not racing:
            _line(p,[(128,106),(118,152),(143,152)],'#708698',4)
            _line(p,[(192,106),(202,152),(177,152)],'#708698',4)
        for i,(x,y) in enumerate(pts):
            arm='#c77a74' if i<2 and not racing else '#53677b'
            if custom:arm=color
            p.setPen(QPen(QColor(arm),11 if not racing else 9,Qt.PenStyle.DashLine if custom else Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap))
            p.drawLine(QPointF(160,90),QPointF(x,y))
            p.setPen(QPen(QColor(color),1.5));p.setBrush(QColor('#172e40'));p.drawEllipse(QPointF(x,y),16,16)
            p.save();p.translate(x,y);p.rotate(28 if i%2==0 else -28)
            shade=QColor(color);shade.setAlpha(85);p.setBrush(shade);p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QRectF(-35,-7,70,14));p.restore()
            p.setPen(QPen(QColor('#c3d0d9'),1));p.setBrush(QColor('#283d4f'));p.drawEllipse(QPointF(x,y),5,5)
        body=QPolygonF([QPointF(140,57),QPointF(180,57),QPointF(188,113),QPointF(160,127),QPointF(132,113)]) if racing else QPolygonF([QPointF(140,62),QPointF(180,62),QPointF(194,89),QPointF(181,114),QPointF(139,114),QPointF(126,89)])
        p.setPen(QPen(QColor(color),2));p.setBrush(QColor('#223d4f'));p.drawPolygon(body)
        p.setBrush(QColor('#40566a'));p.setPen(QPen(QColor('#93aabb'),1));p.drawRoundedRect(QRectF(146,72,28,41),4,4)
        p.setPen(QPen(QColor('#172333'),5));p.drawLine(QPointF(146,85),QPointF(174,85))
        if racing:
            p.setPen(QPen(QColor(color),1));p.setBrush(QColor('#0e1b2a'));p.drawRoundedRect(QRectF(147,50,26,17),4,4)
            p.setBrush(QColor('#7bbed8'));p.drawEllipse(QPointF(160,58),5,5)
            _line(p,[(180,104),(198,124),(198,144)],'#c8a87c',2)
        else:
            p.setPen(QPen(QColor('#8fa7b6'),2));p.setBrush(QColor('#243b4d'));p.drawEllipse(QPointF(160,66),7,7)
        p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor('#ffb46f'))
        p.drawPolygon(QPolygonF([QPointF(160,19),QPointF(155,29),QPointF(165,29)]))
        _text(p,(98,157,124,20),'FRAME TEMPLATE' if custom else 'COMPACT FPV' if racing else 'UTILITY QUAD',10,color)

    def _pose(self,p):
        key=self.kind.removeprefix('pose_')
        key={'left':'left_side','right':'right_side'}.get(key,key)
        labels={'level':'FLAT / LEVEL','nose_up':'NOSE UP','nose_down':'NOSE DOWN',
                'left_side':'LEFT SIDE DOWN','right_side':'RIGHT SIDE DOWN','inverted':'UPSIDE DOWN'}
        side=key in ('left_side','right_side')
        _text(p,(20,3,280,22),'FRONT VIEW' if side else 'SIDE VIEW',10,'#89a7bc')
        # The floor is a 2D orientation cue; no hardware 3D model is drawn.
        _line(p,[(57,144),(263,144)],'#41576b',2)
        for x in range(63,262,13):_line(p,[(x,145),(x-5,151)],'#30475c',1)
        p.save();p.translate(160,88)
        angle={'level':0,'nose_up':-90,'nose_down':90,'left_side':-90,'right_side':90,'inverted':0}.get(key,0)
        p.rotate(angle)
        top=12 if key=='inverted' else -12
        p.setPen(QPen(QColor('#9bb7c7'),1.5));p.setBrush(QColor('#294759'));p.drawRoundedRect(QRectF(-60,-8,120,16),4,4)
        p.setPen(QPen(QColor('#64dbc3'),3));p.drawLine(QPointF(-53,top),QPointF(53,top))
        if side:
            _text(p,(-50,-9,20,18),'L',10,'#7eb8ff');_text(p,(30,-9,20,18),'R',10,'#ffb46f')
        else:
            p.setBrush(QColor('#ffb46f'));p.setPen(Qt.PenStyle.NoPen)
            p.drawPolygon(QPolygonF([QPointF(73,0),QPointF(59,-6),QPointF(59,6)]))
        p.restore()
        _text(p,(20,157,280,21),labels.get(key,'POSITION'),12,'#64dbc3')
