"""Initial setup pages. Hardware erase/apply/save is deliberately not implemented."""
from __future__ import annotations

import math
from pathlib import Path
from PySide6.QtCore import Qt, QPointF, QRectF, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QStackedWidget, QScrollArea, QPushButton, QButtonGroup, QCheckBox,
    QSpinBox, QDoubleSpinBox, QLineEdit, QProgressBar)
from .combo_box import ConsoleComboBox
from .widgets import Card, label, button
from .wizard_model import DEFAULT_SELECTIONS, LAYOUTS, QUAD_X_MOTORS, read_draft, save_draft


class SetupDiagram(QWidget):
    """Scalable 2D top views drawn in Qt; no image assets or hardware side effects."""
    def __init__(self, kind, detailed=False):
        super().__init__()
        self.kind = kind
        self.detailed = detailed
        self.setMinimumHeight(250 if detailed else 95)
        self.setMaximumHeight(275 if detailed else 115)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAccessibleName('Top-view diagram: ' + kind.replace('_', ' '))

    def set_kind(self, kind):
        self.kind = kind
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        scale = min(self.width() / 520, self.height() / 290)
        p.translate((self.width() - 520 * scale) / 2, (self.height() - 290 * scale) / 2)
        p.scale(scale, scale)
        ink = '#5cddc2' if self.isEnabled() else '#627489'
        amber = '#ffad66' if self.isEnabled() else '#7b8798'

        def line(a, b, color=ink, width=6):
            p.setPen(QPen(QColor(color), width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(QPointF(*a), QPointF(*b))

        def text(rect, value, color=ink, size=16):
            p.setPen(QColor(color));p.setFont(QFont('Sans Serif', size, QFont.Weight.DemiBold))
            p.drawText(QRectF(*rect), Qt.AlignmentFlag.AlignCenter, value)

        def motor(x, y, rotation=None, coaxial=False):
            p.setPen(QPen(QColor(ink), 3));p.setBrush(QColor('#102836'))
            p.drawEllipse(QPointF(x, y), 28, 28)
            if coaxial:p.drawEllipse(QPointF(x, y), 20, 20)
            p.setBrush(QColor(ink));p.drawEllipse(QPointF(x, y), 4, 4)
            if rotation:
                sign = 1 if rotation == 'CW' else -1
                angles = [math.radians(-90 + sign * a) for a in range(0, 271, 9)]
                points = [QPointF(x + 20 * math.cos(a), y + 20 * math.sin(a)) for a in angles]
                p.setBrush(Qt.BrushStyle.NoBrush);p.setPen(QPen(QColor(amber), 3))
                p.drawPolyline(QPolygonF(points))
                end = points[-1];a = angles[-1]
                tangent = QPointF(-sign * math.sin(a), sign * math.cos(a))
                normal = QPointF(math.cos(a), math.sin(a))
                p.setBrush(QColor(amber))
                p.drawPolygon(QPolygonF([end, end - tangent * 9 + normal * 5, end - tangent * 9 - normal * 5]))
            else:
                line((x-17,y),(x+17,y),ink,4)
                line((x,y-17),(x,y+17),ink,4)

        if self.kind in ('usb', 'ap'):
            p.setPen(QPen(QColor(ink), 4));p.setBrush(QColor('#102836'))
            p.drawRoundedRect(QRectF(45, 76, 140, 98), 8, 8)
            line((35, 185), (195, 185), ink, 7)
            p.drawRoundedRect(QRectF(340, 75, 120, 110), 10, 10)
            p.drawRect(QRectF(378, 105, 44, 44))
            for y in range(90, 180, 20):
                line((330,y),(340,y),ink,3);line((460,y),(470,y),ink,3)
            if self.kind == 'usb':
                line((195,135),(330,135),amber,6)
                text((190,95,145,30),'USB',amber,18)
            else:
                p.setPen(QPen(QColor(amber), 4));p.setBrush(Qt.BrushStyle.NoBrush)
                for radius in (23,42,61):p.drawArc(QRectF(260-radius,150-radius,2*radius,2*radius),30*16,120*16)
                text((202,164,120,30),'AP Wi-Fi',amber,18)
            text((35,208,170,35),'COMPUTER',size=15)
            text((326,208,150,35),'AREION KIT',size=15)
            p.end();return
        if self.kind == 'fixed_wing':
            p.setPen(QPen(QColor(ink), 3));p.setBrush(QColor('#243b4d'))
            p.drawPolygon(QPolygonF([QPointF(x,y) for x,y in [(260,40),(280,118),(423,177),(423,192),(281,164),(278,222),(320,246),(200,246),(242,222),(239,164),(97,192),(97,177),(240,118)]]))
            p.end();return
        if self.kind == 'car':
            p.setPen(QPen(QColor(ink), 5));p.setBrush(QColor('#243b4d'))
            p.drawRoundedRect(QRectF(185,55,150,190),24,24)
            p.drawRect(QRectF(205,85,110,45));p.drawRect(QRectF(205,183,110,35))
            for x in (162,338):
                for y in (88,180):p.drawRoundedRect(QRectF(x,y,20,45),4,4)
            p.end();return

        kind = self.kind
        points = [(170,90),(350,90),(350,210),(170,210)]
        if kind == 'quad_plus':points = [(260,58),(370,150),(260,242),(150,150)]
        elif kind in ('tricopter','y6'):points = [(160,75),(360,75),(260,235)]
        elif kind in ('hexacopter','octacopter'):
            count = 6 if kind == 'hexacopter' else 8
            points = [(260+103*math.sin(2*math.pi*i/count),150-103*math.cos(2*math.pi*i/count)) for i in range(count)]
        elif kind == 'coreless':points = [(192,98),(328,98),(328,202),(192,202)]
        if kind == 'quad_h':
            line(points[0],points[3],width=10);line(points[1],points[2],width=10)
            line((170,150),(350,150),width=10)
        else:
            for pt in points:line((260,150),pt,width=9)
        p.setPen(QPen(QColor(ink), 2));p.setBrush(QColor('#263d4a'))
        p.drawRoundedRect(QRectF(239,125,42,50),8,8)
        if self.detailed:
            text((205,0,110,28),'FRONT',amber,14)
            line((260,50),(260,33),amber,3)
            line((260,33),(254,39),amber,3);line((260,33),(266,39),amber,3)
        for i, (x,y) in enumerate(points):
            rotation = QUAD_X_MOTORS[i][2] if self.detailed and kind == 'quad_x' else None
            motor(x,y,rotation,kind in ('y6','x8'))
            if kind == 'safety':
                line((x-34,y-34),(x+34,y+34),'#ff9caa',5)
            if self.detailed and kind == 'quad_x':
                name,position,direction = QUAD_X_MOTORS[i]
                tx = 1 if x < 260 else 397
                text((tx,y-27,122,30),f'{name}  {direction}',amber,16)
                text((tx,y+3,122,25),position,'#acbfd3',12)
        if self.detailed:
            caption = 'TOP VIEW · PROPELLERS REMOVED' if kind == 'safety' else 'TOP VIEW'
            text((120,261,280,28),caption,'#8da1b8',11)
        p.end()


class ChoiceCard(QPushButton):
    def __init__(self, title, caption, kind, enabled=True):
        super().__init__()
        self.setCheckable(True);self.setEnabled(enabled)
        self.setMinimumWidth(170)
        # QPushButton's native height hint ignores child layouts; reserve room
        # for the diagram and wrapped captions instead of collapsing to one row.
        self.setMinimumHeight(185)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName(title + '. ' + caption)
        layout = QVBoxLayout(self);layout.setContentsMargins(12,10,12,12);layout.setSpacing(4)
        layout.addWidget(SetupDiagram(kind))
        for value, role in ((title,'cardTitle'),(caption,'muted')):
            item = label(value,role);item.setAlignment(Qt.AlignmentFlag.AlignCenter);item.setWordWrap(True)
            item.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            if not enabled:item.setStyleSheet('color:#667b91;')
            layout.addWidget(item)


class SetupWizard(QWidget):
    connect_requested = Signal(dict)
    disconnect_requested = Signal()
    refresh_ports_requested = Signal()
    saved = Signal(str)

    STEP_TITLES = ('Remove propellers', 'Connect kit', 'Vehicle type',
                   'Drone profile', 'Frame type', 'Quad layout')

    def __init__(self, draft_path):
        super().__init__()
        self.draft_path = Path(draft_path)
        self.selections = dict(DEFAULT_SELECTIONS)
        self.step = 0
        self.last_saved = None
        self.save_error = ''
        self.connection = {}
        self.load_note = 'Initial selections are saved on this computer. Firmware setup is added in later steps.'
        try:
            self.last_saved = read_draft(self.draft_path)
            self.selections = dict(self.last_saved['selections'])
            self.load_note = 'Saved local selections restored. Confirm propeller removal again before continuing.'
        except FileNotFoundError:
            pass
        except (OSError, ValueError, TypeError) as error:
            self.load_note = f'Saved draft could not be loaded; defaults shown. {error}'
        self._build()
        self.on_enter()

    def _build(self):
        root = QVBoxLayout(self);root.setContentsMargins(0,0,0,0);root.setSpacing(10)
        head = QHBoxLayout();head.addWidget(label('Setup wizard','title'));head.addStretch()
        self.step_label = label('','pill');head.addWidget(self.step_label);root.addLayout(head)
        self.overview = label('01 Safety   /   02 Connection   /   03 Vehicle   /   04 Profile   /   05 Frame   /   06 Layout','muted')
        self.overview.setWordWrap(True);root.addWidget(self.overview)
        self.banner = label('KEEP ALL PROPELLERS REMOVED until the entire setup wizard is completed.','notice')
        self.banner.setWordWrap(True);root.addWidget(self.banner)
        self.stack = QStackedWidget();root.addWidget(self.stack,1)
        self._safety_page();self._connection_page();self._vehicle_page()
        self._profile_page();self._frame_page();self._layout_page();self._pending_page()
        self.footer_note = label('','muted');self.footer_note.setWordWrap(True);root.addWidget(self.footer_note)
        footer = QHBoxLayout();self.back_button = button('Back',self.back)
        self.next_button = button('Next',self.advance,'primary')
        footer.addWidget(self.back_button);footer.addStretch();footer.addWidget(self.next_button);root.addLayout(footer)

    def _page(self, title, subtitle):
        inner = QWidget();inner.setObjectName('base')
        box = QVBoxLayout(inner);box.setContentsMargins(0,8,8,8);box.setSpacing(12)
        box.addWidget(label(title,'cardTitle'))
        note = label(subtitle,'muted');note.setWordWrap(True);box.addWidget(note)
        scroll = QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(inner)
        self.stack.addWidget(scroll)
        return box

    def _safety_page(self):
        box = self._page('Before you begin', 'Remove every propeller from the drone before starting setup.')
        card = Card();row = QHBoxLayout();row.addWidget(SetupDiagram('safety',True),1)
        col = QVBoxLayout()
        warning = label('Motors may start unexpectedly during setup. Attached propellers can cause serious injury.','cardTitle')
        warning.setWordWrap(True);warning.setStyleSheet('color:#ffb7bd;');col.addWidget(warning)
        message = label('Keep all propellers removed throughout every setup step. Reinstall them only after the entire setup wizard is complete.','muted')
        message.setWordWrap(True);col.addWidget(message)
        col.addStretch();row.addLayout(col,1);card.box.addLayout(row);box.addWidget(card)
        self.propeller_check = QCheckBox('I confirm that ALL propellers have been removed.')
        check_asset=(Path(__file__).parent/'assets'/'check.svg').as_posix()
        self.propeller_check.setStyleSheet(f'QCheckBox::indicator:checked {{image:url("{check_asset}");}}')
        self.propeller_check.toggled.connect(self._update_navigation);box.addWidget(self.propeller_check)
        self.restore_note = label(self.load_note,'muted');self.restore_note.setWordWrap(True);box.addWidget(self.restore_note)
        box.addStretch()

    def _connection_page(self):
        box = self._page('Connect your Areion kit', 'Choose USB or AP Wi-Fi. The connection is shared with the rest of the console.')
        card = Card();row = QHBoxLayout();row.setSpacing(18)
        self.connection_diagram = SetupDiagram('usb');self.connection_diagram.setMinimumWidth(200)
        row.addWidget(self.connection_diagram,1)
        fields = QGridLayout();self.mode = ConsoleComboBox();self.mode.addItems(['USB','AP'])
        fields.addWidget(label('Connection','muted'),0,0);fields.addWidget(self.mode,0,1)
        self.connection_fields = QStackedWidget()
        usb = QWidget();ug = QGridLayout(usb);ug.setContentsMargins(0,0,0,0)
        self.port = ConsoleComboBox();self.port.setEditable(True);self.port.setMinimumWidth(210)
        self.refresh_button = button('Refresh',self.refresh_ports_requested.emit)
        ug.addWidget(label('USB port','muted'),0,0);ug.addWidget(self.port,0,1);ug.addWidget(self.refresh_button,0,2)
        self.baud = QSpinBox();self.baud.setRange(9600,2000000);self.baud.setValue(115200)
        self.startup_wait = QDoubleSpinBox();self.startup_wait.setRange(0,30);self.startup_wait.setValue(4);self.startup_wait.setSuffix(' s')
        ug.addWidget(label('Baud','muted'),1,0);ug.addWidget(self.baud,1,1)
        ug.addWidget(label('Startup wait','muted'),2,0);ug.addWidget(self.startup_wait,2,1)
        self.connection_fields.addWidget(usb)
        ap = QWidget();ag = QGridLayout(ap);ag.setContentsMargins(0,0,0,0)
        self.host = QLineEdit('192.168.4.1');self.udp_port = QSpinBox();self.udp_port.setRange(1,65535);self.udp_port.setValue(8080)
        self.ssid = QLineEdit('aerion drone')
        for i,(title,editor) in enumerate((('AP address',self.host),('UDP port',self.udp_port),('Wi-Fi name',self.ssid))):
            ag.addWidget(label(title,'muted'),i,0);ag.addWidget(editor,i,1)
        self.connection_fields.addWidget(ap);fields.addWidget(self.connection_fields,1,0,1,2)
        row.addLayout(fields,3);card.box.addLayout(row)
        self.ap_hint = label('Join aerion drone in your computer’s Wi-Fi settings using the kit Wi-Fi password.','muted')
        self.ap_hint.setWordWrap(True);card.box.addWidget(self.ap_hint)
        actions = QHBoxLayout();self.connect_button = button('Connect kit',self._request_connection,'primary')
        self.disconnect_button = button('Disconnect',self.disconnect_requested.emit)
        actions.addWidget(self.connect_button);actions.addWidget(self.disconnect_button);actions.addStretch();card.box.addLayout(actions)
        self.connection_status = label('OFFLINE · Connect the kit to continue.','muted');self.connection_status.setWordWrap(True)
        card.box.addWidget(self.connection_status);box.addWidget(card)
        erase = Card('Erase all settings', 'Firmware erase will be connected after the remaining wizard steps are built.')
        erow = QHBoxLayout();self.erase_button = button('Erase all settings',None,'danger');self.erase_button.setEnabled(False)
        self.erase_button.setStyleSheet('QPushButton#danger:disabled {background:#172230;color:#60728a;border-color:#2c3b4c;}')
        self.erase_button.setToolTip('Not available in this release. No firmware settings are erased.')
        erow.addWidget(self.erase_button);erow.addStretch();erow.addWidget(label('0% · NOT STARTED','eyebrow'));erase.box.addLayout(erow)
        self.erase_progress = QProgressBar();self.erase_progress.setRange(0,100);self.erase_progress.setValue(0);self.erase_progress.setTextVisible(False)
        erase.box.addWidget(self.erase_progress)
        self.erase_status = label('Unavailable in this release. Continue with the existing FC settings; nothing will be erased.','muted')
        self.erase_status.setWordWrap(True);erase.box.addWidget(self.erase_status);box.addWidget(erase);box.addStretch()
        self.mode.currentTextChanged.connect(self._mode_changed);self._mode_changed()

    def _choices(self, box, key, options, columns=3):
        group = QButtonGroup(self);group.setExclusive(True);grid = QGridLayout();grid.setSpacing(12)
        buttons = {}
        for i,(value,title,caption,kind,enabled) in enumerate(options):
            item = ChoiceCard(title,caption,kind,enabled)
            group.addButton(item);buttons[value] = item;grid.addWidget(item,i//columns,i%columns)
            item.setChecked(self.selections[key] == value)
            item.clicked.connect(lambda checked=False,k=key,v=value:self._choose(k,v))
        box.addLayout(grid)
        return buttons

    def _vehicle_page(self):
        box = self._page('Choose vehicle type', 'Multirotor is available now. Other vehicle types will be added later.')
        self.vehicle_buttons = self._choices(box,'vehicle_type',[
            ('multirotor','Multirotor','Available · selected by default','quad_x',True),
            ('fixed_wing','Fixed wing','Future support','fixed_wing',False),
            ('car','Car / rover','Future support','car',False)])
        box.addStretch()

    def _profile_page(self):
        box = self._page('Choose drone profile', 'The current kit uses a brushless motor and ESC profile for an F450-style drone.')
        self.profile_buttons = self._choices(box,'drone_profile',[
            ('f450_esc','F450-style · ESC','Brushless motors + separate ESCs\nCurrent kit profile','quad_x',True),
            ('coreless','Mini / micro · coreless','Non-ESC motor-driver profile\nFuture support','coreless',False)],2)
        note = label('This profile is a local setup selection. It does not change PWM, motor pins, PID values or firmware settings.','muted')
        note.setWordWrap(True);box.addWidget(note);box.addStretch()

    def _frame_page(self):
        box = self._page('Choose multirotor frame type', 'Quadcopter is supported by the current kit. Other motor counts are reserved for future support.')
        self.frame_buttons = self._choices(box,'frame_class',[
            ('quadcopter','Quadcopter','4 motors · available','quad_x',True),
            ('tricopter','Tricopter','3 motors · future','tricopter',False),
            ('hexacopter','Hexacopter','6 motors · future','hexacopter',False),
            ('octacopter','Octacopter','8 motors · future','octacopter',False),
            ('y6','Y6','3 arms / 6 motors · future','y6',False),
            ('x8','X8','4 arms / 8 motors · future','x8',False)])
        box.addStretch()

    def _layout_page(self):
        box = self._page('Choose quadcopter layout', 'Quad X matches the current kit. Quad + and Quad H can be saved as future local drafts only.')
        self.layout_buttons = self._choices(box,'frame_layout',[
            ('quad_x','Quad X','Current kit layout','quad_x',True),
            ('quad_plus','Quad +','Local draft only','quad_plus',True),
            ('quad_h','Quad H','Local draft only','quad_h',True)])
        card = Card();self.layout_diagram = SetupDiagram(self.selections['frame_layout'],True)
        card.box.addWidget(self.layout_diagram)
        self.layout_note = label('','muted');self.layout_note.setWordWrap(True);card.box.addWidget(self.layout_note)
        box.addWidget(card);box.addStretch();self._update_layout()

    def _pending_page(self):
        box = self._page('Initial selections saved', 'The next setup steps will be added here. The full setup wizard is still incomplete.')
        card = Card('Local draft saved · hardware not configured')
        self.pending_diagram = SetupDiagram(self.selections['frame_layout'],True);card.box.addWidget(self.pending_diagram)
        self.summary_label = label('','cardTitle');self.summary_label.setWordWrap(True);card.box.addWidget(self.summary_label)
        self.save_location = label('','muted');self.save_location.setWordWrap(True);self.save_location.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        card.box.addWidget(self.save_location);box.addWidget(card)
        note = label('KEEP PROPELLERS REMOVED. Firmware erase, settings apply/save and the remaining setup checks have not been performed.','notice')
        note.setWordWrap(True);box.addWidget(note);box.addStretch()

    def on_enter(self, connection_options=None):
        # Never restore or silently reuse a safety acknowledgement from an earlier visit.
        self.propeller_check.setChecked(False)
        if connection_options:
            mode = connection_options.get('mode','USB')
            self.mode.setCurrentText(mode if mode in ('USB','AP') else 'USB')
            self.port.setCurrentText(connection_options.get('port',''))
            self.baud.setValue(connection_options.get('baud',115200))
            self.startup_wait.setValue(connection_options.get('startup_wait',4))
            self.host.setText(connection_options.get('host','192.168.4.1'))
            self.udp_port.setValue(connection_options.get('udp_port',8080))
            self.ssid.setText(connection_options.get('ssid','aerion drone'))
        self._show_step(0)

    def set_ports(self, ports):
        current = self.port.currentText();self.port.clear()
        for device, description in ports:
            self.port.addItem(device);self.port.setItemData(self.port.count()-1,description,Qt.ItemDataRole.ToolTipRole)
        if current:self.port.setCurrentText(current)

    def _mode_changed(self, *args):
        ap = self.mode.currentText() == 'AP'
        self.connection_fields.setCurrentIndex(1 if ap else 0)
        self.connection_diagram.set_kind('ap' if ap else 'usb');self.ap_hint.setVisible(ap)
        if hasattr(self,'next_button'):self.set_connection_state(**self.connection)

    def _request_connection(self):
        self.connect_requested.emit({'mode':self.mode.currentText(),'port':self.port.currentText().strip(),
            'baud':self.baud.value(),'startup_wait':self.startup_wait.value(),'host':self.host.text().strip(),
            'udp_port':self.udp_port.value(),'ssid':self.ssid.text().strip()})

    def set_connection_state(self, connected=False, connecting=False, has_link=False,
                             demo=False, disarmed=False, busy=False, paths=None, detail=''):
        self.connection = dict(connected=connected,connecting=connecting,has_link=has_link,
            demo=demo,disarmed=disarmed,busy=busy,paths=paths or [],detail=detail)
        self.connect_button.setEnabled(not has_link and not connecting)
        self.disconnect_button.setEnabled(has_link or connecting)
        self.connection_fields.setEnabled(not has_link and not connecting)
        self.mode.setEnabled(not connecting)
        if connecting:message = 'CONNECTING · Waiting for verified FC replies…'
        elif not connected:message = 'OFFLINE / STALE · Connect the kit to continue.\n' + detail
        elif not self._route_ready():message = f'{self.mode.currentText()} path is not confirmed or is stale. Select the connected path, or disconnect and reconnect.'
        elif not disarmed:message = 'DISARM the kit and wait for fresh FC status before continuing.'
        elif busy:message = 'Waiting for the current control action to stop…'
        else:message = ('DEMO · NO HARDWARE · Layout preview only.' if demo else f'{self.mode.currentText()} CONNECTED · FC confirmed DISARMED.')
        self.connection_status.setText(message)
        self._update_navigation()

    def _route_ready(self):
        state = self.connection
        if not state.get('connected'):return False
        if state.get('demo'):return True
        ap = self.mode.currentText() == 'AP'
        return any(p.get('datagram') == ap and p.get('active') and p.get('confirmed')
            and p.get('last_received_age') is not None and p['last_received_age'] < .5
            for p in state.get('paths',[]))

    def _connection_ready(self):
        return bool(self._route_ready() and self.connection.get('disarmed') and not self.connection.get('busy'))

    def _choose(self, key, value):
        self.save_error = ''
        self.selections[key] = value
        if key == 'frame_layout':self._update_layout()
        self._update_navigation()

    def _update_layout(self):
        layout = self.selections['frame_layout'];self.layout_diagram.set_kind(layout)
        self.layout_note.setText('Top view: M1 front left CW · M2 front right CCW · M3 back right CW · M4 back left CCW.\nThis diagram is a setup reference; no motor output or mixer is changed.' if layout == 'quad_x' else
            f'{LAYOUTS[layout]} geometry preview only. Motor numbering, rotation and firmware mixer support are not configured. Save & Next stores a local draft only.')

    def _show_step(self, step):
        self.save_error = ''
        self.step = step;self.stack.setCurrentIndex(step)
        self.stack.currentWidget().verticalScrollBar().setValue(0)
        self.step_label.setText(f'STEP {step+1} / 6' if step < 6 else 'FURTHER STEPS PENDING')
        self._update_navigation()

    def _update_navigation(self, *args):
        if not hasattr(self,'next_button'):return
        self.back_button.setEnabled(self.step > 0)
        self.next_button.setText('Save && Next' if self.step == 5 else 'Next')
        allowed = self.propeller_check.isChecked() and self.step < 6
        if self.step == 1:allowed = allowed and self._connection_ready()
        self.next_button.setEnabled(allowed)
        self.footer_note.setText('Saved locally. Further setup steps are pending; keep propellers removed.' if self.step == 6 else
            'Save & Next stores selections on this computer. Firmware erase/apply/save will be added later.' if self.step == 5 else
            ('Propeller removal confirmed for this visit. Continue with Next.' if self.propeller_check.isChecked() else 'Confirm propeller removal to enable Next.') if self.step == 0 else
            'Connect via the selected path and disarm the kit to enable Next. Erase is not required in this release.' if self.step == 1 else
            'Choose an available option, then continue. You can return with Back.')
        if self.save_error:self.footer_note.setText(self.save_error)

    def back(self):
        if self.step > 0:self._show_step(self.step-1)

    def advance(self):
        if not self.next_button.isEnabled():return
        if self.step != 5:
            self._show_step(self.step+1);return
        try:
            self.last_saved = save_draft(self.draft_path,self.selections)
        except (OSError, ValueError, TypeError) as error:
            self.save_error = f'Could not save the local draft: {error}. Check the folder and try Save & Next again.'
            self.footer_note.setText(self.save_error)
            return
        self.pending_diagram.set_kind(self.selections['frame_layout'])
        self.summary_label.setText(f'Multirotor  /  F450-style ESC  /  Quadcopter  /  {LAYOUTS[self.selections["frame_layout"]]}')
        self.save_location.setText(f'Saved and verified on this computer:\n{self.draft_path}')
        self.restore_note.setText('Local selections saved. Every visit starts with a fresh propeller-removal confirmation.')
        self._show_step(6);self.saved.emit(str(self.draft_path))

    def diagnostic_snapshot(self):
        return {'step':self.step+1,'stage':'initial_selections','selections':dict(self.selections),
                'propellers_confirmed_this_visit':self.propeller_check.isChecked(),
                'wizard_complete':False,'hardware_applied':False,'erase_available':False,
                'local_draft_saved':self.last_saved is not None,
                'selections_match_saved':bool(self.last_saved and self.last_saved['selections']==self.selections)}
