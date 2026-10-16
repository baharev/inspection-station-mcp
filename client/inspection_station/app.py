"""The window: the camera's live view on the left, the conversation with Claude on the right.

    inspection-station [--server http://<station computer>:8000/mcp]

The camera server must be running with --http. Keys are read from files, never typed:
the camera server's key from ~/.config/inspection-camera/api-key (or API_KEY), Claude's
from ~/.config/anthropic/api-key (or ANTHROPIC_API_KEY).
"""

import argparse
import asyncio
import html
import json
import sys
import threading
import time
from urllib.parse import urlsplit, urlunsplit

import anthropic
from PySide6.QtCore import QByteArray, QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (QImage, QPixmap, QTextBlockFormat, QTextCharFormat, QTextCursor,
                           QTextDocument)
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout,
                               QLabel, QLineEdit, QMainWindow, QPushButton, QScrollArea,
                               QSplitter, QTextBrowser, QVBoxLayout, QWidget)

from .station import (CAMERA_KEY_FILE, CLAUDE_KEY_FILE, MODELS, Answer, Done, Note, Question,
                      Station, ToolCall, ToolResult, camera_client, describe, read_key)

THUMBNAIL = 240      # width of a picture in the conversation, in pixels
LIVE_GAP = 150       # pause between two live frames, in milliseconds


class Worker(QObject):
    """Runs the station in a background thread, so the window never freezes.

    The station's steps arrive as signals, which Qt delivers in the window's thread.
    """

    step = Signal(object)
    connected = Signal(str)
    confirm = Signal(object, object)   # the question, and the function that takes the answer

    def __init__(self, station: Station):
        super().__init__()
        self.station = station
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True).start()

    def run(self, coroutine) -> None:
        asyncio.run_coroutine_threadsafe(coroutine, self.loop)

    def check(self) -> None:
        async def check():
            try:
                tools = await self.station.check()
                self.connected.emit(f"Connected. The server's tools: {tools}")
            except Exception as err:
                self.connected.emit(describe(err))
        self.run(check())

    def ask(self, question: str, model: str) -> None:
        self.run(self.station.ask(question, model, self.step.emit, self.ask_person))

    async def ask_person(self, question: Question) -> bool | None:
        answered = self.loop.create_future()
        self.confirm.emit(question,
                          lambda answer: self.loop.call_soon_threadsafe(answered.set_result, answer))
        return await answered


class LiveView(QLabel):
    """What the camera sees right now: asks the server for a new frame as soon as one arrives."""

    def __init__(self, url: str, key: str):
        super().__init__("Waiting for the camera…")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(320, 180)
        self.setStyleSheet("background: #222; color: #ccc;")
        self.frame = None
        self.request = QNetworkRequest(QUrl(url))
        self.request.setRawHeader(b"Authorization", f"Bearer {key}".encode())
        self.network = QNetworkAccessManager(self)
        self.network.finished.connect(self.arrived)
        QTimer.singleShot(0, self.fetch)

    def fetch(self) -> None:
        self.network.get(self.request)

    def arrived(self, reply: QNetworkReply) -> None:
        data = reply.readAll()
        if reply.error() == QNetworkReply.NetworkError.NoError:
            self.frame = QPixmap()
            self.frame.loadFromData(data)
            self.show_frame()
            QTimer.singleShot(LIVE_GAP, self.fetch)
        else:
            self.frame = None
            text = bytes(data).decode(errors="replace").strip() or reply.errorString()
            self.setText(f"No live view: {text}\n(trying again)")
            QTimer.singleShot(2000, self.fetch)
        reply.deleteLater()

    def show_frame(self) -> None:
        if self.frame and not self.frame.isNull():
            self.setPixmap(self.frame.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                             Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.show_frame()


def picture_window(parent, data: bytes, title: str) -> None:
    """A picture at full size, in a window of its own."""
    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    label = QLabel()
    pixmap = QPixmap()
    pixmap.loadFromData(data)
    label.setPixmap(pixmap)
    scroll = QScrollArea()
    scroll.setWidget(label)
    layout = QVBoxLayout(dialog)
    layout.addWidget(scroll)
    screen = parent.screen().availableSize()
    dialog.resize(min(pixmap.width() + 40, screen.width() - 80),
                  min(pixmap.height() + 40, screen.height() - 80))
    dialog.show()


class ConfirmDialog(QDialog):
    """The camera server asks the person; the answer goes back to the server unchanged."""

    def __init__(self, parent, question: Question):
        super().__init__(parent)
        self.setWindowTitle("The camera server asks you")
        layout = QVBoxLayout(self)
        message = QLabel(question.message)
        message.setWordWrap(True)
        message.setStyleSheet("font-size: 14pt;")
        layout.addWidget(message)
        if question.picture:
            picture = QLabel()
            pixmap = QPixmap()
            pixmap.loadFromData(question.picture)
            picture.setPixmap(pixmap.scaledToWidth(min(pixmap.width(), 800),
                                                   Qt.TransformationMode.SmoothTransformation))
            layout.addWidget(picture)
        buttons = QDialogButtonBox()
        buttons.addButton("Yes, mark it as failed", QDialogButtonBox.ButtonRole.YesRole)
        no = buttons.addButton("No, put it aside", QDialogButtonBox.ButtonRole.NoRole)
        no.setDefault(True)   # Enter never scraps a part by accident
        buttons.clicked.connect(lambda button: self.done(1 if button is not no else 2))
        layout.addWidget(buttons)

    @staticmethod
    def ask(parent, question: Question) -> bool | None:
        """Yes, no, or None when the dialog was closed without an answer."""
        return {1: True, 2: False}.get(ConfirmDialog(parent, question).exec())


def in_words(call: ToolCall) -> str:
    """What Claude asked the server to do, in plain words."""
    a = call.arguments
    percent = lambda x: f"{round(float(x) * 100)} %"
    try:
        match call.name:
            case "capture_image":
                return "Taking a photo"
            case "zoom_image":
                return (f"Looking closer at photo {a['image_id']}: from {percent(a['left'])} to "
                        f"{percent(a['left'] + a['width'])} across, from {percent(a['top'])} to "
                        f"{percent(a['top'] + a['height'])} down")
            case "record_inspection":
                return (f"Recording part {a['part_id']} as {a['verdict'].upper()}: "
                        f"{a['findings']}")
    except (KeyError, TypeError, ValueError):
        pass
    return f"Calling {call.name}"


class Window(QMainWindow):
    def __init__(self, worker: Worker, server_url: str, live_url: str, camera_key: str):
        super().__init__()
        self.worker = worker
        self.server_url = server_url
        self.pictures = []
        self.conversation_cost = 0.0
        self.started = 0.0
        self.setWindowTitle("Inspection station")

        self.conversation = QTextBrowser()
        self.conversation.setOpenLinks(False)
        self.conversation.anchorClicked.connect(self.open_picture)
        self.question = QLineEdit()
        self.question.setPlaceholderText("Ask about what the camera sees, e.g. "
                                         "“Is the tray complete?”")
        self.question.returnPressed.connect(self.ask)
        self.ask_button = QPushButton("Ask")
        self.ask_button.clicked.connect(self.ask)
        self.new_button = QPushButton("New conversation")
        self.new_button.clicked.connect(self.new_conversation)
        self.model = QComboBox()
        self.model.addItems(MODELS)
        self.cost = QLabel()

        asking = QHBoxLayout()
        asking.addWidget(self.question)
        asking.addWidget(self.ask_button)
        below = QHBoxLayout()
        below.addWidget(self.new_button)
        below.addWidget(QLabel("Model:"))
        below.addWidget(self.model)
        below.addStretch()
        below.addWidget(self.cost)
        right = QWidget()
        column = QVBoxLayout(right)
        column.addWidget(self.conversation)
        column.addLayout(asking)
        column.addLayout(below)

        splitter = QSplitter()
        splitter.addWidget(LiveView(live_url, camera_key))
        splitter.addWidget(right)
        splitter.setSizes([700, 600])
        self.setCentralWidget(splitter)
        self.resize(1400, 820)

        self.status = QLabel(f"Connecting to {server_url} …")
        self.statusBar().addWidget(self.status)
        self.clock = QTimer(self)
        self.clock.timeout.connect(self.tick)

        worker.connected.connect(lambda text: self.status.setText(f"{server_url}: {text}"))
        worker.step.connect(self.show_step)
        worker.confirm.connect(self.confirm)
        worker.check()

    # --- asking -------------------------------------------------------------------

    def ask(self) -> None:
        question = self.question.text().strip()
        if not question or not self.ask_button.isEnabled():
            return
        self.question.clear()
        self.set_working(True)
        self.add(f"<p><b>You:</b> {html.escape(question)}</p>")
        self.worker.ask(question, self.model.currentText())

    def new_conversation(self) -> None:
        self.worker.station.new_conversation()
        self.conversation.clear()
        self.pictures.clear()
        self.conversation_cost = 0.0
        self.cost.setText("")

    def set_working(self, working: bool, problem: str = "") -> None:
        for widget in (self.ask_button, self.new_button, self.model):
            widget.setEnabled(not working)
        if working:
            self.started = time.monotonic()
            self.clock.start(1000)
            self.tick()
        else:
            self.clock.stop()
            self.status.setText(f"{self.server_url}: {problem or 'ready'}")

    def tick(self) -> None:
        self.status.setText(f"Claude is working… {time.monotonic() - self.started:.0f} s")

    def confirm(self, question: Question, answer) -> None:
        QApplication.alert(self)
        answer(ConfirmDialog.ask(self, question))

    # --- the conversation -----------------------------------------------------------

    def show_step(self, step) -> None:
        match step:
            case Note(text):
                self.add(f"<p style='color:#777'><i>{paragraphs(text)}</i></p>")
            case Answer(text):
                self.add_markdown(text)
            case ToolCall():
                self.add(f"<p style='color:#2a6'>▸ {html.escape(in_words(step))}<br>"
                         f"<span style='color:#999; font-size:small'>{step.name} "
                         f"{html.escape(json.dumps(step.arguments))}</span></p>")
            case ToolResult(refused=True):
                self.add(f"<p style='color:#c22'>Refused by the server: "
                         f"{html.escape(step.text)}</p>")
            case ToolResult():
                self.add(f"<p style='color:#555; font-size:small'>{result_in_words(step)}</p>")
                if step.pictures:
                    self.add("".join(self.thumbnail(p) for p in step.pictures))
            case Done(cost, problem):
                self.conversation_cost += cost
                if problem:
                    self.add(f"<p style='color:#c22'>{html.escape(problem)}</p>")
                self.add(f"<p style='color:#999; font-size:small'>"
                         f"{'Stopped after' if problem else 'Answered in'} "
                         f"{time.monotonic() - self.started:.0f} s, cost {dollars(cost)}</p><hr>")
                self.cost.setText(f"This question: {dollars(cost)} · conversation: "
                                  f"{dollars(self.conversation_cost)}")
                self.set_working(False, problem)
                self.question.setFocus()

    def thumbnail(self, data: bytes) -> str:
        name = f"picture:{len(self.pictures)}"
        self.pictures.append(data)
        self.conversation.document().addResource(
            QTextDocument.ResourceType.ImageResource, QUrl(name), QImage.fromData(data))
        return f"<a href='{name}'><img src='{name}' width='{THUMBNAIL}'></a> "

    def open_picture(self, url: QUrl) -> None:
        n = int(url.toString().split(":")[1])
        picture_window(self, self.pictures[n], f"Picture {n + 1}")

    def add(self, fragment: str) -> None:
        cursor = self.conversation.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertBlock(QTextBlockFormat(), QTextCharFormat())   # not the previous format
        cursor.insertHtml(fragment)
        self.scroll_down()

    def add_markdown(self, text: str) -> None:
        cursor = self.conversation.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertBlock(QTextBlockFormat(), QTextCharFormat())
        cursor.insertHtml("<b>Claude:</b> ")
        cursor.insertMarkdown(text)
        self.scroll_down()

    def scroll_down(self) -> None:
        bar = self.conversation.verticalScrollBar()
        bar.setValue(bar.maximum())


def dollars(amount: float) -> str:
    return "under $0.01" if 0 < amount < 0.01 else f"${amount:.2f}"


def paragraphs(text: str) -> str:
    return "<br>".join(html.escape(line) for line in text.splitlines())


def result_in_words(result: ToolResult) -> str:
    if result.name == "record_inspection":
        try:
            record = json.loads(result.text)
            confirmed = record.get("fail_confirmation") == "yes"
            who = " (confirmed by a person)" if confirmed else ""
            note = f"<br>{html.escape(record['note'])}" if record.get("note") else ""
            return f"Recorded: part {html.escape(record['part_id'])} " \
                   f"{html.escape(record['verdict']).upper()}{who}{note}"
        except (ValueError, KeyError, TypeError):
            pass
    return paragraphs(result.text)


def live_url(server_url: str) -> str:
    """The live view's frame address, on the same server: …/mcp becomes …/live/frame.jpg."""
    parts = urlsplit(server_url)
    path = parts.path.removesuffix("/").removesuffix("/mcp")
    return urlunsplit(parts._replace(path=f"{path}/live/frame.jpg", query="", fragment=""))


def main() -> None:
    parser = argparse.ArgumentParser(description="The inspection station's window: Claude "
                                     "answers questions with the camera server's tools.")
    parser.add_argument("--server", default="http://localhost:8000/mcp",
                        help="the camera server's address (default: %(default)s)")
    args = parser.parse_args()

    camera_key = read_key("API_KEY", CAMERA_KEY_FILE)
    claude = anthropic.AsyncAnthropic(api_key=read_key("ANTHROPIC_API_KEY", CLAUDE_KEY_FILE))
    station = Station(claude, lambda confirm: camera_client(args.server, camera_key, confirm))

    app = QApplication(sys.argv)
    app.setApplicationName("Inspection station")
    window = Window(Worker(station), args.server, live_url(args.server), camera_key)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
