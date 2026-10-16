"""The fail confirmation: Enter never marks a part as failed, and it fits on the screen."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # no screen needed

from PySide6.QtCore import QBuffer, QByteArray, Qt, QTimer
from PySide6.QtGui import QImage
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


def test_the_dialog_fits_on_a_small_screen():
    """Its photo shrinks so that the text and the buttons stay on the screen."""
    room = app.primaryScreen().availableSize()
    image = QImage(1280, 720, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.gray)
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QBuffer.OpenModeFlag.WriteOnly)
    image.save(buffer, "JPEG")
    dialog = ConfirmDialog(None, Question("The AI found a problem with part tray-01.",
                                          bytes(data)))
    size = dialog.sizeHint()
    assert size.width() <= room.width() and size.height() + 40 <= room.height()
    place = app.primaryScreen().availableGeometry()
    assert place.top() <= dialog.y() and dialog.y() + dialog.height() + 40 <= place.bottom() + 1
    dialog.show()
    dialog.move(0, room.height() - 50)   # where Windows may put it: under the taskbar
    dialog.keep_on_screen()
    assert app.primaryScreen().availableGeometry().contains(dialog.frameGeometry())
    dialog.close()
