"""Read-only, software-rendered airframes for flight instruments and setup."""
from dataclasses import dataclass
from functools import lru_cache
import math
from pathlib import Path
import time

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QSizePolicy, QWidget


ASSETS = Path(__file__).parent / 'assets' / 'airframes'
POSES = {
    'level': (0, 0, 0), 'nose_up': (0, 90, 0), 'nose_down': (0, -90, 0),
    'left_side': (-90, 0, 0), 'right_side': (90, 0, 0), 'inverted': (180, 0, 0),
}
IDENTITY = (1., 0., 0., 0.)
FRONT = '__front__'


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _normal(a, b, c):
    x, y, z = (bi - ai for ai, bi in zip(a, b))
    u, v, w = (ci - ai for ai, ci in zip(a, c))
    cross = (y*w-z*v, z*u-x*w, x*v-y*u)
    length = math.sqrt(_dot(cross, cross))
    return tuple(t/length for t in cross)


@dataclass
class Mesh:
    vertices: tuple
    faces: tuple
    anchors: dict


@lru_cache(maxsize=1)
def _palette():
    shades = {}
    for line in (ASSETS / 'areion.mtl').read_text(encoding='utf8').splitlines():
        fields = line.split()
        if not fields:
            continue
        if fields[0] == 'newmtl':
            name = fields[1]
        elif fields[0] == 'Kd':
            rgb = tuple(float(v)*255 for v in fields[1:])
            shades[name] = tuple(
                QColor(*(min(255, round(c*(.69 + .42*i/15))) for c in rgb)) for i in range(16)
            )
    return shades


@lru_cache(maxsize=2)
def _mesh(key):
    vertices, faces, anchor_points = [], [], {}
    group = material = ''
    for line in (ASSETS / (key + '.obj')).read_text(encoding='utf8').splitlines():
        fields = line.split()
        if not fields:
            continue
        tag = fields[0]
        if tag == 'v':
            vertices.append(tuple(map(float, fields[1:4])))
        elif tag == 'usemtl':
            material = fields[1]
        elif tag == 'g':
            group = fields[1]
        elif tag == 'f':
            indices = tuple(int(v)-1 for v in fields[1:])
            points = [vertices[i] for i in indices]
            center = tuple(sum(axis)/len(points) for axis in zip(*points))
            faces.append((indices, _normal(*points[:3]), center, _palette()[material]))
            if group in ('M1', 'M2', 'M3', 'M4', 'nose'):
                anchor_points.setdefault(group, set()).update(indices)
    anchors = {}
    for name, indices in anchor_points.items():
        xyz = [vertices[i] for i in indices]
        anchors[FRONT if name == 'nose' else int(name[1:])] = (
            sum(p[0] for p in xyz)/len(xyz), max(p[1] for p in xyz) if name == 'nose'
            else sum(p[1] for p in xyz)/len(xyz), max(p[2] for p in xyz),
        )
    return Mesh(tuple(vertices), tuple(faces), anchors)


def _attitude(roll, pitch, yaw):
    """Body +X is right, +Y front, +Z up. Positive bank is right side down."""
    r, p, h = (math.radians(a % 360) * .5 for a in (roll, pitch, -yaw))
    cr, sr, cp, sp, ch, sh = math.cos(r), math.sin(r), math.cos(p), math.sin(p), math.cos(h), math.sin(h)
    # Yaw around world Z, pitch around X, roll around body Y.
    return (ch*cp*cr - sh*sp*sr, ch*sp*cr - sh*cp*sr,
            ch*cp*sr + sh*sp*cr, ch*sp*sr + sh*cp*cr)


def _basis(q):
    w, x, y, z = q
    return ((1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)),
            (2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)),
            (2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)))


def _blend(a, b, t):
    # Use the shorter rotation even when a sample crosses +/-180 degrees.
    if _dot(a, b) < 0:
        b = tuple(-x for x in b)
    q = tuple(x+(y-x)*t for x,y in zip(a,b))
    length = math.sqrt(_dot(q,q))
    return tuple(v/length for v in q)


class DroneScene(QWidget):
    """Propeller-free Quad X view. Only catalog mode accepts camera-orbit input."""

    def __init__(self, profile='areion450', parent=None):
        super().__init__(parent)
        self.setMinimumSize(116, 98)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.mode = None
        self.valid = True
        self.guide_face = None
        self._show_yaw_reference = False
        self._pose = self._target = IDENTITY
        self._motors = frozenset()
        self._azimuth, self._elevation = 31., 33.
        self._drag = None
        self._reveal = 0.
        self._clock = time.monotonic()
        self.animation = QTimer(self)
        self.animation.setInterval(33)
        self.animation.timeout.connect(self._animate)
        self.profile = None
        self.set_profile(profile)
        self.setAccessibleName('3D Quad X airframe')
        self.set_presentation()

    def sizeHint(self):
        return QSize(265, 164)

    def set_profile(self, key):
        name = 'areion250' if str(key).lower() in ('aerion250', 'areion250') else 'areion450'
        if self.profile != name:
            if self.profile is not None and self.mode == 'presentation' and self.isVisible():
                self._reveal = 10.
                self._clock = time.monotonic()
                self.animation.start()
            self.profile, self.mesh = name, _mesh(name)
            self.update()

    def _change_mode(self, mode):
        if self.mode == mode:
            return
        self._reveal = 0.
        self._azimuth, self._elevation = 31., 33.
        self._drag = None
        self.mode = mode
        selectable = mode == 'presentation'
        self.setCursor(Qt.CursorShape.OpenHandCursor if selectable else Qt.CursorShape.ArrowCursor)

    def set_presentation(self):
        self._change_mode('presentation')
        self.guide_face = None
        self.setToolTip('Drag to orbit the airframe. Double-click to restore the view.')
        self.setAccessibleDescription('Airframe profile. Front is marked F.')
        self._target_pose(IDENTITY)

    def set_guide_pose(self, face):
        aliases = {'flat': 'level', 'left': 'left_side', 'right': 'right_side', 'upside_down': 'inverted'}
        face = aliases.get(face, face)
        if face not in POSES:
            raise ValueError(f'Unknown calibration pose: {face}')
        self._change_mode('guide')
        self.guide_face = face
        self.setAccessibleDescription('Target position: ' + face.replace('_', ' '))
        self.setToolTip('Guide position. F indicates the front of the frame.')
        self._target_pose(_attitude(*POSES[face]))

    def set_live_pose(self, roll, pitch, yaw=None, *, snap=False):
        new_mode = self.mode != 'live'
        self._change_mode('live')
        self.guide_face = None
        good = all(type(v) in (int, float) and math.isfinite(v) for v in (roll, pitch))
        if not good:
            if self.valid or new_mode:
                self.valid = False
                self.animation.stop()
                self.setAccessibleDescription('Waiting for live IMU readings')
                self.update()
            return
        heading = yaw if type(yaw) in (int,float) and math.isfinite(yaw) else 0.
        if new_mode or not self.valid:
            self.setToolTip('Measured attitude. F indicates the front of the frame.')
            self.setAccessibleDescription('Measured frame orientation')
        self._target_pose(_attitude(roll, pitch, heading), snap=snap or new_mode or not self.valid)

    def set_yaw_reference(self, visible):
        """Show the fixed relative-zero direction on the floor of the live view."""
        if visible != self._show_yaw_reference:
            self._show_yaw_reference = visible
            self.update()

    def set_motor_highlight(self, ids):
        if isinstance(ids, int):
            ids = (ids,)
        motors = frozenset(n for n in ids if n in (1, 2, 3, 4))
        if self._motors != motors:
            self._motors = motors
            self.update()

    def _target_pose(self, target, snap=False):
        was_valid = self.valid
        self.valid = True
        if was_valid and self._target == target and not snap:
            return
        self._target = target
        if snap or not was_valid or not self.isVisible():
            self._pose = target
            self.animation.stop()
            self.update()
        elif 1-abs(_dot(self._pose,target)) > 0.0000005:
            if not self.animation.isActive():
                self._clock = time.monotonic()
                self.animation.start()
        else:
            self._pose = target
            self.update()

    def _animate(self):
        now = time.monotonic()
        dt = max(0., min(.12, now-self._clock))
        self._clock = now
        lag = .07 if self.mode == 'live' else .12
        self._pose = _blend(self._pose, self._target, 1-math.exp(-dt/lag))
        self._reveal *= math.exp(-dt/.11)
        if self._reveal < .08:
            self._reveal = 0.
        if 1-abs(_dot(self._pose,self._target)) < .000001 and self._reveal == 0.:
            self._pose = self._target
            self.animation.stop()
        self.update()

    def hideEvent(self, event):
        self.animation.stop()
        self._drag = None
        self._reveal = 0.
        self._pose = self._target
        super().hideEvent(event)

    def mousePressEvent(self, event):
        if self.mode == 'presentation' and event.button() == Qt.MouseButton.LeftButton:
            self._drag = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag is not None:
            delta = event.position() - self._drag
            self._drag = event.position()
            self._azimuth = (self._azimuth + delta.x() * .6) % 360
            self._elevation = max(-75., min(80., self._elevation + delta.y()*.5))
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._drag is not None:
            self._drag = None
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if self.mode == 'presentation' and event.button() == Qt.MouseButton.LeftButton:
            self._azimuth, self._elevation = 31., 33.
            self.update()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())
        clip = QPainterPath()
        clip.addRoundedRect(rect, 7., 7.)
        p.setClipPath(clip)
        background = QLinearGradient(rect.topLeft(), rect.bottomRight())
        background.setColorAt(0., QColor('#234853'))
        background.setColorAt(.75, QColor('#142e3c'))
        background.setColorAt(1., QColor('#172d39'))
        p.fillRect(rect, background)
        center = QPointF(rect.width()*.5, rect.height()*.50)
        # Fixed geometry scale across poses makes a captured attitude easy to compare.
        scale = min(rect.width()*.402, rect.height()*.392)
        az,el = math.radians(self._azimuth + self._reveal),math.radians(self._elevation)
        ca,sa,ce,se = math.cos(az),math.sin(az),math.cos(el),math.sin(el)
        right = ca,sa,0.
        up = -sa*se,ca*se,ce
        camera = sa*ce,-ca*ce,se
        floor_center = center + QPointF(0, scale*.32)
        p.setPen(QPen(QColor(123,183,186,26), 1.))
        for offset in (-1.2,-.8,-.4,0.,.4,.8,1.2):
            for x1,y1,x2,y2 in ((offset,-1.2,offset,1.2),(-1.2,offset,1.2,offset)):
                p.drawLine(floor_center + QPointF(scale*(x1*ca+y1*sa),scale*(x1*sa-y1*ca)*se),
                           floor_center + QPointF(scale*(x2*ca+y2*sa),scale*(x2*sa-y2*ca)*se))
        if not self.valid:
            p.setPen(QColor('#c7dcdc'))
            p.drawText(rect,Qt.AlignmentFlag.AlignCenter,'Waiting for IMU')
            return
        if self._show_yaw_reference and self.mode == 'live':
            # The live camera is fixed. Place the zero mark at the edge of the
            # floor grid so it stays clear of the model's moving front marker.
            distance = min((rect.width()*.5-14.)/sa, (floor_center.y()-15.)/(ca*se))
            tip = floor_center + QPointF(distance*sa, -distance*ca*se)
            p.setPen(QPen(QColor('#83b4ba'), 1., Qt.PenStyle.DashLine))
            p.drawLine(floor_center, tip)
            font = QFont()
            font.setPixelSize(10)
            p.setFont(font)
            p.setPen(QColor('#b5d2d6'))
            p.drawText(QRectF(tip.x()-12,tip.y()-14,24,13),Qt.AlignmentFlag.AlignCenter,'0°')
        matrix = _basis(self._pose)
        columns = tuple(zip(*matrix))
        right, up, camera, light = [tuple(_dot(axis, col) for col in columns)
            for axis in (right, up, camera, (-.38,-.37,.85))]
        cx, cy = center.x(), center.y()
        def project(point):
            x,y,z = point
            return QPointF(cx+scale*(right[0]*x+right[1]*y+right[2]*z),
                           cy-scale*(up[0]*x+up[1]*y+up[2]*z))
        points = tuple(project(v) for v in self.mesh.vertices)
        faces = []
        for indices,normal,fc,shades in self.mesh.faces:
            nx,ny,nz = normal
            if nx*camera[0]+ny*camera[1]+nz*camera[2] < .005:
                continue
            depth = fc[0]*camera[0]+fc[1]*camera[1]+fc[2]*camera[2]
            shade = max(0,min(15,round(8+7*(nx*light[0]+ny*light[1]+nz*light[2]))))
            faces.append((depth, indices, shades[shade]))
        faces.sort(key=lambda face:face[0])
        p.setPen(QPen(QColor(17,37,44,125), .55, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        for _, indices, color in faces:
            p.setBrush(color)
            p.drawPolygon(QPolygonF([points[i] for i in indices]))
        font = QFont()
        font.setPixelSize(10 if rect.height() >= 135 else 9)
        font.setBold(True)
        p.setFont(font)
        for n in sorted(self._motors):
            pos = project(self.mesh.anchors[n])
            p.setPen(QPen(QColor('#ffcf77'),1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(pos,scale*.15,scale*.15)
            badge = QRectF(pos.x()-11,pos.y()-10,22,16)
            p.setBrush(QColor('#f4c678'))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(badge,3,3)
            p.setPen(QColor('#1b343b'))
            p.drawText(badge,Qt.AlignmentFlag.AlignCenter,f'M{n}')
        front = project(self.mesh.anchors[FRONT])
        guide = project((0.,.61,.29))
        if math.hypot(guide.x()-front.x(),guide.y()-front.y()) < 14.:
            guide += QPointF(12.,-7.)
        p.setPen(QPen(QColor('#9ee7d5'),1.1))
        p.drawLine(front, guide)
        p.setBrush(QColor('#1e474c'))
        p.drawEllipse(guide,7.5,7.5)
        p.setPen(QColor('#c0ffeb'))
        p.drawText(QRectF(guide.x()-8,guide.y()-8,16,16),Qt.AlignmentFlag.AlignCenter,'F')
