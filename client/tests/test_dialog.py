"""The fail confirmation: pressing Enter must never mark a part as failed."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # no screen needed

from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

from inspection_station.app import ConfirmDialog
from inspection_station.station import Question

app = QApplication.instance() or QApplication([])


def answer_with_enter(move_focus_to: str | None = None) -> int:
    """1 for yes, 2 for no, as the dialog ends."""
    dialog = ConfirmDialog(None, Question("The AI found a problem with part tray-01.", None))

    def press():
        if move_focus_to:
            next(b for b in dialog.findChildren(QPushButton)
                 if b.text().startswith(move_focus_to)).setFocus()
        QTest.keyClick(dialog.focusWidget(), Qt.Key.Key_Return)
    QTimer.singleShot(50, press)
    QTimer.singleShot(2000, dialog.reject)   # never hang: closed unanswered is 0
    return dialog.exec()


def test_enter_puts_the_part_aside():
    assert answer_with_enter() == 2


def test_enter_puts_the_part_aside_even_with_the_focus_on_yes():
    assert answer_with_enter(move_focus_to="Yes") == 2
