"""The fail confirmation: the button clicked is the answer, Enter never marks a part as
failed, and the dialog fits on the screen."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # no screen needed

from PySide6.QtCore import QBuffer, QByteArray, Qt, QTimer
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

from inspection_client.app import ConfirmDialog
from inspection_client.station import Question

app = QApplication.instance() or QApplication([])


def answer_with_enter(move_focus_to: str | None = None) -> str:
    """What the dialog's answer means for the part."""
    dialog = ConfirmDialog(None, Question("The AI found a problem with part tray-01.", None))

    def press():
        if move_focus_to:
            next(b for b in dialog.findChildren(QPushButton)
                 if b.text().startswith(move_focus_to)).setFocus()
        QTest.keyClick(dialog.focusWidget(), Qt.Key.Key_Return)
    QTimer.singleShot(50, press)
    QTimer.singleShot(2000, dialog.reject)   # never hang
    return {1: "marked FAILED", 2: "put aside"}.get(dialog.exec(), "closed unanswered")


def test_enter_puts_the_part_aside():
    assert answer_with_enter() == "put aside"


def test_enter_puts_the_part_aside_even_with_the_focus_on_yes():
    assert answer_with_enter(move_focus_to="Yes") == "put aside"


@pytest.mark.parametrize("button, answer", [("Yes", True), ("No", False), (None, None)],
                         ids=["yes", "no", "closed"])
def test_the_button_clicked_is_the_answer_passed_on(button, answer):
    def click():
        dialog = app.activeModalWidget()
        if button:
            next(b for b in dialog.findChildren(QPushButton)
                 if b.text().startswith(button)).click()
        else:
            dialog.reject()   # closed with the window's X or Escape
    QTimer.singleShot(50, click)
    QTimer.singleShot(2000, lambda: app.activeModalWidget() and app.activeModalWidget().reject())
    assert ConfirmDialog.ask(None, Question("Part tray-01: mark it FAILED?", None)) is answer


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
