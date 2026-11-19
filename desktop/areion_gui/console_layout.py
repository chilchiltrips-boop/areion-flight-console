"""Compact top navigation and read-only landing/inspection pages."""
from pathlib import Path
import time
from PySide6.QtCore import Qt, QSize, QRect
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QWidget,QFrame,QLabel,QVBoxLayout,QHBoxLayout,QGridLayout,
    QStackedWidget,QLineEdit,QSpinBox,QDoubleSpinBox,QDialog,QSizePolicy,QLayout,QMenu)
from .combo_box import ConsoleComboBox
from .widgets import Card,label
from .scroll_guard import page_action_button as button,focus_page
from .link_activity import LinkActivity
from .welcome import WelcomePage
from .backend import SUPPORTED_FIRMWARE

CHROME_STYLE='''
QFrame#consoleHeader {background:#101b2a;border-bottom:1px solid #2d4056;}
QFrame#consoleHeader QLabel {font-size:12px;}
QFrame#navigationBar {background:#142131;border-bottom:1px solid #30445b;}
QFrame#navigationBar QPushButton {font-size:12px;border-radius:4px;padding:3px 7px;}
QFrame#navigationBar QComboBox {font-size:12px;border-radius:4px;padding:3px;min-height:22px;}
QPushButton#usbEndpoint {text-align:left;color:#f1f6fa;padding-left:9px;padding-right:19px;}
QMenu#usbPortMenu {background:#16283a;color:#eef5fb;border:1px solid #587087;padding:4px;}
QMenu#usbPortMenu::item {background:#16283a;color:#eef5fb;border-radius:3px;padding:7px 14px 7px 24px;}
QMenu#usbPortMenu::item:selected {background:#345873;color:white;}
QMenu#usbPortMenu::item:disabled {color:#b4c4d0;}
QMenu#usbPortMenu::separator {height:1px;background:#40576b;margin:4px;}
QPushButton#topNav {background:transparent;border:1px solid transparent;color:#9db2c9;}
QPushButton#topNav:checked {background:#244a4c;border-color:#5cddc2;color:#d8fff5;}
QPushButton#topNav:hover {background:#24394f;}
QPushButton#topNav:disabled {color:#536579;}
QFrame#sectionBar {background:#101b2a;border:1px solid #24364b;border-radius:5px;}
QFrame#sectionBar QPushButton {padding:4px 12px;border-radius:4px;font-size:12px;}
QLabel#title {font-size:23px;font-weight:700;}
QLabel#notice {padding:6px 9px;border-radius:5px;}
QFrame#card {border-radius:9px;}
'''


class NavigationLayout(QLayout):
    """Keep navigation and connection controls together; wrap only on overflow."""
    def __init__(self,parent):
        super().__init__(parent);self.items=[]
        self.setContentsMargins(10,4,10,4);self.setSpacing(8)

    def addItem(self,item):self.items.append(item)
    def count(self):return len(self.items)
    def itemAt(self,index):return self.items[index] if 0<=index<len(self.items) else None
    def takeAt(self,index):return self.items.pop(index) if 0<=index<len(self.items) else None
    def expandingDirections(self):return Qt.Orientation.Horizontal
    def hasHeightForWidth(self):return True

    def minimumSize(self):
        left,top,right,bottom=self.getContentsMargins()
        sizes=[item.minimumSize() for item in self.items]
        return QSize(max((v.width() for v in sizes),default=0)+left+right,
                     max((v.height() for v in sizes),default=0)+top+bottom)

    def sizeHint(self):
        left,top,right,bottom=self.getContentsMargins()
        sizes=[item.sizeHint() for item in self.items]
        return QSize(sum(v.width() for v in sizes)+self.spacing()+left+right,
                     max((v.height() for v in sizes),default=0)+top+bottom)

    def heightForWidth(self,width):return self._arrange(QRect(0,0,width,0),False)

    def setGeometry(self,rect):
        super().setGeometry(rect);self._arrange(rect,True)

    def _arrange(self,rect,apply):
        left,top,right,bottom=self.getContentsMargins()
        available=max(0,rect.width()-left-right)
        sizes=[item.sizeHint() for item in self.items]
        wrap=sum(v.width() for v in sizes)+self.spacing()>available
        x=rect.x()+left;y=rect.y()+top;row_height=0
        for index,(item,size) in enumerate(zip(self.items,sizes)):
            width=min(size.width(),available)
            if index and wrap:
                y+=row_height+4;row_height=0
            # The connection group stays aligned to the right in either mode.
            position=rect.x()+rect.width()-right-width if index else x
            if apply:item.setGeometry(QRect(position,y,width,size.height()))
            row_height=max(row_height,size.height())
        return y-rect.y()+row_height+bottom


class ConsoleLayout:
    def _build_console(self):
        base=QWidget();base.setObjectName('base');self.setCentralWidget(base)
        root=QVBoxLayout(base);root.setContentsMargins(0,0,0,0);root.setSpacing(0)
        self.header=QFrame();self.header.setObjectName('consoleHeader');self.header.setFixedHeight(42)
        top=QHBoxLayout(self.header);top.setContentsMargins(14,3,12,3);top.setSpacing(8)
        brand=label('AREION','cardTitle');brand.setStyleSheet('letter-spacing:2px;font-size:16px;');top.addWidget(brand)
        top.addWidget(label('FC A1 · Console 3.12.3','muted'));top.addStretch()
        self.route_pill=label('OFFLINE','muted');self.arm_pill=label('ARMED: UNKNOWN','muted')
        top.addWidget(self.route_pill);top.addWidget(self.arm_pill)
        self.stop_button=button('■  DISARM / STOP',lambda:self.stop('DISARM requested'),'danger')
        self.stop_button.setFixedHeight(32);self.stop_button.setStyleSheet('font-size:12px;padding:3px 12px;border-radius:4px;')
        top.addWidget(self.stop_button);root.addWidget(self.header)
        self.navigation_bar=QFrame();self.navigation_bar.setObjectName('navigationBar')
        self.navigation_layout=NavigationLayout(self.navigation_bar)
        policy=QSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Preferred);policy.setHeightForWidth(True)
        self.navigation_bar.setSizePolicy(policy)
        self.navigation_routes=QWidget();self.toolbar=QHBoxLayout(self.navigation_routes)
        self.toolbar.setContentsMargins(0,0,0,0);self.toolbar.setSpacing(2)
        self.navigation_layout.addWidget(self.navigation_routes)
        routes=[('Welcome',7,'welcome'),('Flight Data',0,'flight'),('Configuration',2,'configuration'),
                ('System',4,'system'),('Scopes',8,'scopes'),('HITL',None,'hitl'),('Firmware',9,'firmware')]
        self.nav_routes=[]
        for title,index,icon in routes:
            control=button(title,lambda checked=False,n=index:self.navigate(n) if n is not None else None,'topNav')
            control.setCheckable(True);control.setFixedHeight(34)
            control.setIcon(QIcon(str(Path(__file__).parent/'assets'/('nav-'+icon+'.svg'))));control.setIconSize(QSize(16,16))
            if index is None:
                control.setEnabled(False);control.setToolTip('Hardware-in-the-loop is unavailable.')
            self.nav.append(control);self.nav_routes.append(index);self.toolbar.addWidget(control)
        self.connection_controls=QWidget();self.connection_toolbar=QHBoxLayout(self.connection_controls)
        self.connection_toolbar.setContentsMargins(0,0,0,0);self.connection_toolbar.setSpacing(4)
        self.link_activity=LinkActivity();self.connection_toolbar.addWidget(self.link_activity)
        self.navigation_layout.addWidget(self.connection_controls)
        root.addWidget(self.navigation_bar)
        main=QVBoxLayout();main.setContentsMargins(14,10,14,8);main.setSpacing(8);root.addLayout(main,1)
        self.section_bar=QFrame();self.section_bar.setObjectName('sectionBar');sections=QHBoxLayout(self.section_bar)
        sections.setContentsMargins(6,4,6,4);sections.setSpacing(4);self.section_buttons={}
        for name,index in [('Setup',5),('Input',10),('IMU',1),('ESC / motors',6),('PID / settings',2),('Live values',4),('Connection',3)]:
            b=button(name,lambda checked=False,n=index:self.navigate(n));b.setCheckable(True);b.setFixedHeight(30)
            sections.addWidget(b);self.section_buttons[index]=b
        sections.addStretch();main.addWidget(self.section_bar)
        self.pages=QStackedWidget();main.addWidget(self.pages,1)
        # Internal route IDs remain stable for control/navigation guards.
        self._flight_page();self._imu_page();self._settings_page();self._build_connection_page();self._live_page()
        self.wizard_placeholder=QWidget();self.pages.addWidget(self.wizard_placeholder)
        self.esc_placeholder=QWidget();self.pages.addWidget(self.esc_placeholder)
        self._welcome_page();self._scopes_page();self._firmware_page();self._input_page()
        self.receiver_placeholder=QWidget();self.pages.addWidget(self.receiver_placeholder)
        # These are the same connection widgets used by the existing backend.
        self.transport.setFixedSize(90,32);self.connection_toolbar.addWidget(self.transport)
        self.endpoint_button=button('Choose port',role='usbEndpoint')
        self.endpoint_button.setFixedHeight(32)
        arrow=(Path(__file__).parent/'assets'/'down.svg').as_posix()
        self.endpoint_button.setStyleSheet(
            f'QPushButton::menu-indicator {{image:url("{arrow}");width:12px;height:8px;'
            'subcontrol-position:right center;subcontrol-origin:padding;right:5px;}')
        self.port_menu=QMenu(self.endpoint_button)
        self.port_menu.setObjectName('usbPortMenu')
        self.port_menu.setToolTipsVisible(True)
        self.port_menu.aboutToShow.connect(self._open_usb_menu)
        self.port_menu.triggered.connect(self._port_menu_triggered)
        self.endpoint_button.clicked.connect(self._edit_ap_endpoint)
        self.connection_toolbar.addWidget(self.endpoint_button)
        self.connect_button.setFixedSize(86,32);self.connection_toolbar.addWidget(self.connect_button)
        self.disconnect_button.setText('×');self.disconnect_button.setToolTip('Disconnect the kit')
        self.disconnect_button.setAccessibleName('Disconnect the kit');self.disconnect_button.setFixedSize(30,32);self.connection_toolbar.addWidget(self.disconnect_button)
        self.transport.currentTextChanged.connect(self._sync_endpoint)
        self.port.currentTextChanged.connect(self._sync_endpoint);self.host.textChanged.connect(self._sync_endpoint)
        self.udp_port.valueChanged.connect(self._sync_endpoint)
        self._sync_endpoint()
        self.side_state=QLabel(self);self.side_state.hide() # status API retained without a sidebar
        self.notice=label(self.last_notice,'notice');self.notice.setWordWrap(True);main.addWidget(self.notice)
        self.navigate(7,initial=True)

    def _sync_endpoint(self,*args):
        mode=self.transport.currentText();port=self.port.currentText().strip();host=self.host.text().strip()
        ap_only=mode=='AP'
        menu=None if ap_only else self.port_menu
        if self.endpoint_button.menu() is not menu:
            self.endpoint_button.setMenu(menu)
        address=f'{host}:{self.udp_port.value()}'
        text=address if ap_only else port or 'USB ports'
        self.endpoint_button.ensurePolished()
        metrics=self.endpoint_button.fontMetrics()
        full_width=metrics.horizontalAdvance(text)+40
        width=max(108,min(430,full_width))
        self.endpoint_button.setFixedWidth(width)
        # A very long by-id path retains both its prefix and connector suffix.
        # The menu and tooltip expose the full path.
        caption=metrics.elidedText(text,Qt.TextElideMode.ElideMiddle,width-36) if full_width>width else text
        self.endpoint_button.setText(caption.replace('&','&&'))
        title='Edit AP address' if ap_only else 'Choose USB port'
        details=[title]
        if not ap_only and port:
            details.append(port)
            if port==getattr(self,'_preferred_usb_port',''):
                details.append('Last connected USB port')
        if mode!='USB':
            details.append(address)
        self.endpoint_button.setAccessibleName(title)
        self.endpoint_button.setAccessibleDescription(text)
        self.endpoint_button.setToolTip('\n'.join(details))
        if self.port_menu.isVisible():
            self._update_open_usb_menu()

    def _edit_ap_endpoint(self):
        if self.transport.currentText()=='AP':
            self.show_connection_settings()

    def _open_usb_menu(self):
        self.port_menu.clear()
        self._menu_devices={}
        self._empty_ports=self.port_menu.addAction('No USB ports detected')
        self._empty_ports.setEnabled(False)
        self._port_separator=self.port_menu.addSeparator()
        self._port_settings=self.port_menu.addAction('Connection settings…')
        self._update_open_usb_menu()
        self.refresh_ports()

    def _update_open_usb_menu(self):
        devices=dict(self._wizard_ports)
        selected=self.port.currentText().strip()
        preferred=getattr(self,'_preferred_usb_port','')
        for path in (*devices,selected):
            if not path or path in self._menu_devices:
                continue
            action=self.port_menu.addAction(path.replace('&','&&'))
            action.setData(path)
            action.setCheckable(True)
            self.port_menu.insertAction(self._port_separator,action)
            self._menu_devices[path]=action
        self._empty_ports.setVisible(not self._menu_devices)
        # Preserve existing row positions while the menu is open. Unplugging a
        # device disables its row; a newly discovered device gets its own row.
        for path,action in self._menu_devices.items():
            present=path in devices
            action.setEnabled(present)
            action.setChecked(path==selected)
            suffix='  ·  Last connected' if path==preferred else ''
            if not present:
                suffix+='  ·  Unavailable'
            action.setText(path.replace('&','&&')+suffix)
            action.setToolTip('\n'.join(part for part in (path,devices.get(path)) if part))

    def _port_menu_triggered(self,action):
        if action is self._port_settings:
            self.show_connection_settings()
        elif action.isEnabled() and action.data():
            self.select_usb_port(action.data())

    def show_connection_settings(self):
        self.connection_dialog.show();self.connection_dialog.raise_();self.connection_dialog.activateWindow()
        focus_page(self.connection_dialog)

    def _build_connection_page(self):
        box=self.page('Connection','')
        self.transport=ConsoleComboBox();self.transport.addItems(['USB','AP','USB + AP'])
        self.port=ConsoleComboBox();self.port.setEditable(True);self.port.setMinimumWidth(240)
        self.baud=QSpinBox();self.baud.setRange(9600,2000000);self.baud.setValue(115200)
        self.wait=QDoubleSpinBox();self.wait.setRange(0,30);self.wait.setValue(4);self.wait.setSuffix(' s')
        self.host=QLineEdit('192.168.4.1');self.udp_port=QSpinBox();self.udp_port.setRange(1,65535);self.udp_port.setValue(8080)
        self.ssid=QLineEdit('aerion drone')
        self.connect_button=button('Connect',self.connect_fc,'primary');self.disconnect_button=button('Disconnect',self.disconnect)
        self.connection_dialog=QDialog(self);self.connection_dialog.setWindowTitle('Areion FC A1 · connection settings');self.connection_dialog.resize(650,470)
        layout=QVBoxLayout(self.connection_dialog);layout.setContentsMargins(20,16,20,16)
        layout.addWidget(label('Connection settings','cardTitle'))
        grid=QGridLayout()
        for i,(name,widget) in enumerate([('USB port',self.port),('Baud',self.baud),('USB startup wait',self.wait),('AP address',self.host),('UDP port',self.udp_port),('Wi-Fi network',self.ssid)]):
            grid.addWidget(label(name,'muted'),i,0);grid.addWidget(widget,i,1)
        layout.addLayout(grid)
        hint=label('Join aerion drone using the kit Wi-Fi password.','muted');hint.setWordWrap(True);layout.addWidget(hint)
        row=QHBoxLayout();row.addWidget(button('Refresh USB',self.refresh_ports));row.addWidget(button('Check Wi-Fi',self.check_wifi));row.addStretch()
        row.addWidget(button('Done',self.connection_dialog.accept));layout.addLayout(row)
        state=Card('Kit communication')
        self.connection_detail=label('OFFLINE · No connection opened.','cardTitle');self.connection_detail.setWordWrap(True);state.box.addWidget(self.connection_detail)
        self.wifi_detail=label('Wi-Fi association: not checked','muted');self.wifi_detail.setWordWrap(True);state.box.addWidget(self.wifi_detail)
        self.paths_detail=label('','muted');self.paths_detail.setWordWrap(True);state.box.addWidget(self.paths_detail)
        state.box.addWidget(button('Edit connection',self.show_connection_settings));box.addWidget(state);box.addStretch()

    def _welcome_page(self):
        self.welcome = WelcomePage(self.navigate, self.show_connection_settings,
                                   self._open_imu_calibration, self._open_event_log, self.open_restart_check)
        self.welcome.set_restart_available(bool(self._restart_receipt))
        self.log_view.textChanged.connect(
            lambda: self.welcome.update_activity(self.log_view.document()))
        self.pages.addWidget(self.welcome)

    def _open_event_log(self):
        self.navigate(4)
        self.live_tabs.setCurrentWidget(self.log_view)

    def _open_imu_calibration(self):
        self.navigate(1);self.imu_tabs.setCurrentIndex(1)

    def _scopes_page(self):
        # Hold the route until a user first opens the instrument workspace.
        self._scope_workspace = None
        self._scope_placeholder = QWidget()
        self.pages.addWidget(self._scope_placeholder)

    @property
    def scopes_page(self):
        if self._scope_workspace is None:
            from .scopes_page import ScopesPage
            page = ScopesPage()
            page.export_requested.connect(self.export_csv)
            index = self.pages.indexOf(self._scope_placeholder)
            self.pages.removeWidget(self._scope_placeholder)
            self._scope_placeholder.deleteLater()
            self.pages.insertWidget(index, page)
            self._scope_workspace = page
        return self._scope_workspace

    def _firmware_page(self):
        box=self.page('Firmware','')
        card=Card('Version information');self.firmware_info=label('Connect to read the kit firmware.','cardTitle');self.firmware_info.setWordWrap(True);card.box.addWidget(self.firmware_info)
        versions=' / '.join(sorted(SUPPORTED_FIRMWARE))
        card.box.addWidget(label(f'Console 3.12.3 · Compatible firmware: {versions}','muted'))
        guide=label('Upload with Arduino IDE. Disconnect LiPo before flashing.','muted');guide.setWordWrap(True);card.box.addWidget(guide)
        self.flash_button=button('Flash · unavailable',lambda:None);self.flash_button.setEnabled(False);self.flash_button.setToolTip('This desktop has no verified firmware uploader.');card.box.addWidget(self.flash_button)
        card.box.addWidget(button('Copy diagnostics',self.copy_diagnostics));box.addWidget(card);box.addStretch()

    def _input_page(self):
        box=self.page('Input','')
        card=Card('Control source');row=QHBoxLayout();self.config_source=ConsoleComboBox()
        for text,value in [('PPM receiver',0),('USB channels',2),('AP Wi-Fi channels',1)]:self.config_source.addItem(text,value)
        row.addWidget(self.config_source);self.config_source_apply=button('Save input',self._save_config_source,'primary');row.addWidget(self.config_source_apply);row.addStretch();card.box.addLayout(row)
        self.config_input_state=label('Connect to read input.','muted');card.box.addWidget(self.config_input_state)
        text=label('PPM needs receiver calibration. Saving input does not arm.','muted');text.setWordWrap(True);card.box.addWidget(text)
        actions=QHBoxLayout();actions.addWidget(button('Calibrate PPM',lambda:self.navigate(11)));actions.addWidget(button('New receiver',lambda:self.navigate(5)));card.box.addLayout(actions);box.addWidget(card)
        from .tx_link_panel import TxLinkPanel
        self.tx_link_panel = TxLinkPanel(self)
        box.addWidget(self.tx_link_panel)
        modes=Card('Flight mode & timing')
        modes.box.addWidget(button('Edit settings',lambda:self.navigate(2)));box.addWidget(modes);box.addStretch()

    def _save_config_source(self):
        self.source_box.setCurrentIndex(self.source_box.findData(self.config_source.currentData()));self.select_source()

    def _sync_navigation(self,index):
        config=index in (1,2,5,6,10,11);system=index in (3,4)
        for route,control in zip(self.nav_routes,self.nav):
            control.setChecked((route==2 and config) or (route==4 and system) or (route not in (2,4) and route==index))
        self.section_bar.setVisible(config or system)
        for route,control in self.section_buttons.items():
            control.setVisible((config and route in (1,2,5,6,10)) or (system and route in (3,4)))
            control.setChecked(route==index or (route==10 and index==11))

    def _render_console(self,now,connected,status,setup):
        paths=self.link.transport_status if self.link else []
        demo=bool(self.link and getattr(self.link,'demo',False))
        identity=(id(self.link),self.link.fc_session) if self.link else None
        self.link_activity.refresh(paths,identity,now,connected,demo)
        routes=[]
        if connected and not demo:
            routes=sorted({'AP' if p.get('datagram') else 'USB' for p in paths
                if p.get('active') and p.get('confirmed') and p.get('last_received_age') is not None and p['last_received_age']<.5},reverse=True)
            self.route_pill.setText(' + '.join(routes)+' LINK' if routes else 'LINK STALE')
            self.route_pill.setStyleSheet('color:#5cddc2;' if routes else 'color:#f5b459;')
        else:self.route_pill.setStyleSheet('color:#8da1b8;' if demo else 'color:#ff9caa;')
        self.config_source_apply.setEnabled(self.source_apply.isEnabled());self.config_input_state.setText(self.input_state.text())
        if self.pages.currentIndex()==7:
            self.welcome.set_restart_available(bool(self._restart_receipt))
            self.welcome.update_status(connected and not demo, self.connecting, routes, setup,
                                       self.data.values(125), self.data.values(134))
        if self.pages.currentIndex()==9:
            device=self.data.values(125) if connected else None
            compatibility=('Simulated firmware; no hardware version verified.' if demo else
                'Compatible with this console.' if device and device[0] in SUPPORTED_FIRMWARE else
                'Version mismatch. Check the matching main/library.')
            self.firmware_info.setText(('DEMO · simulated kit\n' if demo else '')+
                (f'FC firmware: {device[0]}\n'+compatibility if device else
                 'OFFLINE · installed firmware not verified.'))
