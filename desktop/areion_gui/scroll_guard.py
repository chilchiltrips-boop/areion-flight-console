"""Keep page scrolling separate from editing configuration and control values."""
import weakref
from PySide6.QtCore import QEvent, QObject, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import (
    QApplication, QAbstractScrollArea, QAbstractSpinBox, QComboBox, QSlider, QWidget,
)
from shiboken6 import isValid


class ScrollGuard(QObject):
    """Consume editor wheels and forward them to the enclosing scroll viewport.

    Explicit typing, arrow keys, spin buttons, combo selection and slider dragging
    retain their normal Qt behavior. Popup choice lists keep their own scrolling.
    An application filter also covers lazily created pages and owned dialogs.
    """
    def __init__(self, owner):
        super().__init__(owner)
        self._owner = weakref.ref(owner)
        self._installed = False

    def eventFilter(self, watched, event):
        if event.type() != QEvent.Type.Wheel or not isinstance(watched, QWidget):
            return False
        owner = self._owner()
        if owner is None or not isValid(owner):
            return False
        ancestor = watched
        while ancestor is not None and ancestor is not owner:
            ancestor = ancestor.parent()
        if ancestor is None:
            return False
        control = watched
        while control is not None and not isinstance(control, (QAbstractSpinBox, QComboBox, QSlider)):
            if control is owner:
                return False
            control = control.parentWidget()
        if control is None:
            return False
        if isinstance(control, QComboBox):
            view = control.view()
            if view.isVisible() and (watched is view or view.isAncestorOf(watched)):
                return False

        parent = control.parentWidget()
        while parent is not None:
            if isinstance(parent, QAbstractScrollArea):
                pixels = event.pixelDelta()
                if not pixels.isNull():
                    # QScrollArea's scrollbar wheel handler can ignore a
                    # pixel-only trackpad event. Use its native pixel distance
                    # instead of rounding it into artificial wheel notches.
                    vertical = parent.verticalScrollBar()
                    horizontal = parent.horizontalScrollBar()
                    vertical.setValue(vertical.value() - pixels.y())
                    horizontal.setValue(horizontal.value() - pixels.x())
                    break
                viewport = parent.viewport()
                position = viewport.mapFromGlobal(event.globalPosition().toPoint())
                forwarded = QWheelEvent(
                    QPointF(position), event.globalPosition(), event.pixelDelta(),
                    event.angleDelta(), event.buttons(), event.modifiers(),
                    event.phase(), event.inverted(), event.source(), event.pointingDevice(),
                )
                QApplication.sendEvent(viewport, forwarded)
                break
            parent = parent.parentWidget()
        # Accept even without a scrolling parent: wheel gestures must never
        # become changes to a motor slider, PID field or connection selection.
        event.accept()
        return True


def install_scroll_guard(owner):
    """Install once for a main window and all its present/future child widgets."""
    app = QApplication.instance()
    if app is None:
        raise RuntimeError('Create QApplication before installing the scroll guard.')
    guard = getattr(owner, '_scroll_guard', None)
    if guard is None or not isValid(guard):
        guard = ScrollGuard(owner)
        owner._scroll_guard = guard
    if not guard._installed:
        app.installEventFilter(guard)
        guard._installed = True
    return guard


def remove_scroll_guard(owner):
    """Detach a closed window so it adds no overhead to other windows' events."""
    guard = getattr(owner, '_scroll_guard', None)
    if guard is None or not isValid(guard) or not guard._installed:
        return
    app = QApplication.instance()
    if app is not None and isValid(app):
        app.removeEventFilter(guard)
    guard._installed = False


def focus_page(page):
    """Start a newly selected page on its container, not an editable value."""
    if page is not None and isValid(page) and page.isVisible():
        page.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        page.setFocus(Qt.FocusReason.OtherFocusReason)


def page_action_button(text, callback=None, role=None):
    """Keep a clicked page action from moving focus when it disables itself.

    Qt otherwise advances focus to another enabled child, revealing that child
    lower down the scroll area. Run the focus handoff before the action slots,
    after mouse release / keyboard activation has already produced the click.
    No scroll positions are repeatedly restored, so users remain free to scroll
    during captures and can still reach every control with Tab.
    """
    from .widgets import button
    item = button(text, role=role)

    def prepare_action():
        parent = item.parentWidget()
        while parent is not None:
            if isinstance(parent, QAbstractScrollArea):
                focus_page(parent)
                break
            parent = parent.parentWidget()

    item.clicked.connect(prepare_action)
    if callback:
        item.clicked.connect(callback)
    return item
