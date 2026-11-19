"""Readable popup lists for the console's light and dark input controls."""
from pathlib import Path

from PySide6.QtWidgets import QComboBox, QStyledItemDelegate


_LIGHT_ARROW = (Path(__file__).parent / 'assets' / 'down-dark.svg').as_posix()


class ConsoleComboBox(QComboBox):
    def __init__(self, parent=None, *, light=False, **kwargs):
        super().__init__(parent, **kwargs)
        if light:
            surface, ink = '#f8fcfa', '#16353b'
            highlight, selected_ink = '#17635c', '#ffffff'
            disabled_bg, disabled_ink = '#e6edea', '#51635d'
            border = '#88a9a2'
        else:
            surface, ink = '#172b3b', '#f2f7fb'
            highlight, selected_ink = '#365c71', '#ffffff'
            disabled_bg, disabled_ink = '#243440', '#adbbc5'
            border = '#567184'

        # Qt's default menu delegate can use the collapsed button's foreground
        # for every menu row, even when the view advertises a different palette.
        view = self.view()
        self.setItemDelegate(QStyledItemDelegate(view))
        view.setStyleSheet(f"""
            QAbstractItemView {{
                background:{surface}; color:{ink}; border:1px solid {border};
                selection-background-color:{highlight}; selection-color:{selected_ink}; outline:0;
            }}
            QAbstractItemView::item {{
                background:{surface}; color:{ink}; border:0; min-height:22px; padding:3px 8px;
            }}
            QAbstractItemView::item:selected, QAbstractItemView::item:hover {{
                background:{highlight}; color:{selected_ink};
            }}
            QAbstractItemView::item:disabled {{
                background:{disabled_bg}; color:{disabled_ink};
            }}
        """)
        state_style = f"""
            QComboBox {{combobox-popup:0; selection-color:{selected_ink}; selection-background-color:{highlight};}}
            QComboBox:disabled {{color:{disabled_ink};background:{disabled_bg};}}
            QComboBox QLineEdit:disabled {{color:{disabled_ink};background:{disabled_bg};}}
        """
        if light:
            state_style += f"""
                QComboBox:focus, QComboBox:on {{border-color:{highlight};}}
                QComboBox::down-arrow {{image:url("{_LIGHT_ARROW}");width:12px;height:8px;}}
            """
        self.setStyleSheet(state_style)

    def showPopup(self):
        # The hidden popup can cache row positions before the stylesheet and
        # system font arrive. Relayout on opening so every hit box fits its row.
        self.view().ensurePolished()
        self.view().doItemsLayout()
        super().showPopup()
