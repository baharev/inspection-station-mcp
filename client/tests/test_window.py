"""The window: MCP messages in the conversation only when asked for, pictures and links,
the person's answer to a fail question, and the live view once the server has refused it
or comes back."""

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # no screen needed

import pytest
from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QTextFormat
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from inspection_client.app import ConfirmDialog, LiveView, Window, pretty
from inspection_client.station import Answer, McpMessage, Question, ToolCall, ToolResult
from stand_in_server import photo

app = QApplication.instance() or QApplication([])


class Worker(QObject):
    """Stands in for the worker: the same signals, no inspection server, no Claude."""

    step = Signal(object)
    connected = Signal(str)
    note = Signal(str)
    confirm = Signal(object, object)
    frame = Signal(bytes)
    no_frame = Signal(str)
    live_stopped = Signal(str)

    def __init__(self):
        super().__init__()
        self.watched = 0   # how often the live view was started
        self.checked = 0   # how often the connection was checked

    def check(self):
        self.checked += 1

    def watch(self, live):
        self.watched += 1


def test_mcp_messages_show_only_when_the_box_is_ticked():
    worker = Worker()
    window = Window(worker, "http://localhost:8000/mcp", None)
    worker.step.emit(ToolCall("capture_image", {}))
    worker.step.emit(McpMessage(True, "tools/call", {"name": "capture_image", "arguments": {}}))
    worker.step.emit(Answer("The tray is empty."))
    shown = window.conversation.toPlainText

    assert "Taking a photo" in shown() and "Claude: The tray is empty." in shown()
    assert "tools/call" not in shown()
    window.show_mcp.setChecked(True)   # earlier messages appear too, in their place
    assert shown().index("Taking a photo") < shown().index("tools/call") < shown().index("Claude:")
    window.show_mcp.setChecked(False)
    assert "tools/call" not in shown() and "The tray is empty." in shown()


def test_an_mcp_message_is_laid_out_and_keeps_every_value():
    """Indented over several lines; a text that holds JSON shows that JSON, not escapes."""
    record = {"part_id": "tray-07", "verdict": "fail",
              "findings": "The hammer is missing; a table knife lies in its slot."}
    body = {"content": [{"type": "text", "text": json.dumps(record, indent=1)}],
            "isError": False}
    shown = pretty(body)
    assert "\\n" not in shown and '\\"' not in shown   # no escapes
    assert shown.splitlines()[0] == "{" and '    "type": "text",' in shown
    assert '"text": (JSON sent as a string) {' in shown
    for key, value in record.items():
        assert f'"{key}": {json.dumps(value)}' in shown
    assert pretty({"mark_failed": True}) == '{"mark_failed": true}'   # short parts stay on one line


def test_a_thin_line_marks_where_each_mcp_message_starts_and_ends():
    """Two messages in a row share the line between them; none without the checkbox."""
    worker = Worker()
    window = Window(worker, "http://localhost:8000/mcp", None)
    worker.step.emit(McpMessage(True, "tools/call", {"name": "capture_image", "arguments": {}}))
    worker.step.emit(McpMessage(False, "result", {"content": [], "isError": False}))
    worker.step.emit(Answer("The tray is empty."))

    def lines():
        block, n = window.conversation.document().begin(), 0
        while block.isValid():
            n += block.blockFormat().hasProperty(
                QTextFormat.Property.BlockTrailingHorizontalRulerWidth)
            block = block.next()
        return n

    assert lines() == 0
    window.show_mcp.setChecked(True)
    assert lines() == 3


def test_a_stopped_live_view_says_why_and_starts_again_when_clicked():
    worker = Worker()
    window = Window(worker, "http://localhost:8000/mcp", None)
    live = window.findChild(LiveView)
    QTest.mouseClick(live, Qt.MouseButton.LeftButton)
    assert worker.watched == 1, "A click started a second live view while one was running."

    worker.live_stopped.emit("The inspection server refused the key.")
    assert "refused the key" in live.text() and "Click here to try again" in live.text()
    QTest.mouseClick(live, Qt.MouseButton.LeftButton)
    assert worker.watched == 2
    assert "refused" not in live.text()
    QTest.mouseClick(live, Qt.MouseButton.LeftButton)
    assert worker.watched == 2, "A second click started the live view twice."


def test_the_status_line_is_checked_again_when_the_live_view_is_back():
    # A question refused by the server leaves its reason in the status line; once the
    # live view shows pictures again, the connection is checked and the line updated.
    worker = Worker()
    window = Window(worker, "http://localhost:8000/mcp", None)
    worker.frame.emit(photo())
    assert worker.checked == 1, "Checked again without a problem first."
    worker.no_frame.emit("The inspection server cannot be reached.")
    worker.frame.emit(photo())
    worker.frame.emit(photo())
    assert worker.checked == 2
    worker.live_stopped.emit("The inspection server refused the key.")
    QTest.mouseClick(window.findChild(LiveView), Qt.MouseButton.LeftButton)
    worker.frame.emit(photo())
    assert worker.checked == 3


@pytest.mark.parametrize("said, line", [
    (True, "My answer to the server's question: Yes, mark it as failed"),
    (False, "My answer to the server's question: No, put it aside"),
    (None, "My answer to the server's question: closed without answering")])
def test_the_persons_answer_to_the_fail_question_shows_in_the_conversation(monkeypatch, said,
                                                                         line):
    monkeypatch.setattr(ConfirmDialog, "ask", staticmethod(lambda parent, question: said))
    worker = Worker()
    window = Window(worker, "http://localhost:8000/mcp", None)
    answers = []
    worker.confirm.emit(Question("Mark part tray-02 as FAILED?", None), answers.append)
    assert answers == [said]
    assert line in window.conversation.toPlainText()


def test_a_click_on_a_picture_opens_it_and_other_links_are_left_alone():
    worker = Worker()
    window = Window(worker, "http://localhost:8000/mcp", None)
    worker.step.emit(ToolResult("capture_image", "Photo p1", [photo()], False))
    worker.step.emit(Answer("See [the guide](https://example.com/guide)."))

    window.open_picture(QUrl("https://example.com/guide"))   # nothing happens
    assert window.findChildren(QDialog) == []
    window.open_picture(QUrl("picture:0"))
    [opened] = window.findChildren(QDialog)
    assert opened.windowTitle() == "Picture 1"
    opened.close()
