"""The conversation in the window: MCP messages only when asked for."""

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # no screen needed

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QTextFormat
from PySide6.QtWidgets import QApplication

from inspection_station.app import Window, pretty
from inspection_station.station import Answer, McpMessage, ToolCall

app = QApplication.instance() or QApplication([])


class Worker(QObject):
    """Stands in for the worker: the same signals, no camera server, no Claude."""

    step = Signal(object)
    connected = Signal(str)
    note = Signal(str)
    confirm = Signal(object, object)
    frame = Signal(bytes)
    no_frame = Signal(str)

    def check(self):
        pass

    def watch(self, live):
        pass


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
    assert pretty({"record": True}) == '{"record": true}'   # short parts stay on one line


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
