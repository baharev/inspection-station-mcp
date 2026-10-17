"""The window: the camera's live view on the left, the conversation with Claude on the right.

    inspection-station [--server http://<station computer>:8000/mcp] [--login] [--trust ca.pem]

The camera server must be running with --http. Keys are read from files, never typed:
the camera server's key from ~/.config/inspection-camera/api-key (or API_KEY), Claude's
from ~/.config/anthropic/api-key (or ANTHROPIC_API_KEY). With --login, the person logs
in through the camera server's login server in the browser instead, and the camera
server's key is not needed.
"""

import argparse
import asyncio
import html
import json
import ssl
import sys
import threading
import time
from urllib.parse import urlsplit, urlunsplit

import anthropic
from PySide6.QtCore import QObject, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (QColor, QFontDatabase, QFontMetricsF, QImage, QPixmap,
                           QTextBlockFormat, QTextCharFormat, QTextCursor, QTextDocument,
                           QTextFormat, QTextLength)
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QHBoxLayout, QLabel, QLineEdit, QMainWindow, QPushButton,
                               QScrollArea, QSplitter, QTextBrowser, QVBoxLayout, QWidget)

from .login import BrowserLogin
from .station import (CAMERA_KEY_FILE, CLAUDE_KEY_FILE, MODELS, Answer, Done, KeyAuth,
                      McpMessage, Note, Question, Station, ToolCall, ToolResult, camera_client,
                      describe, live_view, read_key)

THUMBNAIL = 240      # width of a picture in the conversation, in pixels
INDENT = 20          # Claude's work on a question is indented below it, in pixels
# The conversation keeps to one font and size: the operator and Claude in the normal
# color, Claude's work in gray, problems in red. Only MCP messages, shown on request, are
# in a code font.
GRAY = "#777"
RED = "#c22"


class Worker(QObject):
    """Runs the station in a background thread, so the window never freezes.

    The station's steps arrive as signals, which Qt delivers in the window's thread.
    """

    step = Signal(object)
    connected = Signal(str)
    note = Signal(str)                 # about the login, for the conversation
    confirm = Signal(object, object)   # the question, and the function that takes the answer
    frame = Signal(bytes)              # the live view's newest frame (JPEG)
    no_frame = Signal(str)             # why there is none

    def __init__(self, station: Station, who=lambda: ""):
        super().__init__()
        self.station = station
        self.who = who   # the user logged in, if any
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True).start()

    def run(self, coroutine) -> None:
        asyncio.run_coroutine_threadsafe(coroutine, self.loop)

    def check(self) -> None:
        async def check():
            try:
                tools = await self.station.check()
                user = f" as {self.who()}" if self.who() else ""
                self.connected.emit(f"Connected{user}. The server's tools: {tools}")
            except Exception as err:
                self.connected.emit(describe(err))
        self.run(check())

    def watch(self, live) -> None:
        """Starts the live view: live(show, tell) runs as long as the app."""
        self.run(live(self.frame.emit, self.no_frame.emit))

    def ask(self, question: str, model: str) -> None:
        self.run(self.station.ask(question, model, self.step.emit, self.ask_person))

    async def ask_person(self, question: Question) -> bool | None:
        answered = self.loop.create_future()
        self.confirm.emit(question,
                          lambda answer: self.loop.call_soon_threadsafe(answered.set_result, answer))
        return await answered


class LiveView(QLabel):
    """What the camera sees right now; the worker brings each new frame."""

    def __init__(self):
        super().__init__("Waiting for the camera…")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(320, 180)
        self.setStyleSheet("background: #222; color: #ccc;")
        self.frame = None

    def show_jpeg(self, data: bytes) -> None:
        self.frame = QPixmap()
        self.frame.loadFromData(data)
        self.show_frame()

    def show_problem(self, text: str) -> None:
        self.frame = None
        self.setText(f"No live view: {text}\n(trying again)")

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
        self.room = (parent.screen() if parent else QApplication.primaryScreen()).availableGeometry()
        layout = QVBoxLayout(self)
        message = QLabel(question.message)
        message.setWordWrap(True)
        message.setStyleSheet("font-size: 14pt;")
        layout.addWidget(message)
        if question.picture:
            picture = QLabel()
            pixmap = QPixmap()
            pixmap.loadFromData(question.picture)
            # The whole dialog fits on the screen, above the taskbar: the picture gets
            # the room the text and the buttons leave.
            fit = QSize(min(800, self.room.width() - 100), self.room.height() - 300)
            picture.setPixmap(pixmap.scaled(fit.boundedTo(pixmap.size()),
                                            Qt.AspectRatioMode.KeepAspectRatio,
                                            Qt.TransformationMode.SmoothTransformation))
            layout.addWidget(picture)
        buttons = QDialogButtonBox()
        yes = buttons.addButton("Yes, mark it as failed", QDialogButtonBox.ButtonRole.YesRole)
        no = buttons.addButton("No, put it aside", QDialogButtonBox.ButtonRole.NoRole)
        # Enter never scraps a part by accident: "No" stays the default wherever the
        # keyboard focus is (Qt otherwise moves the default along with the focus), and
        # it gets the focus once the dialog shows.
        for button in yes, no:
            button.setAutoDefault(False)
        no.setDefault(True)
        QTimer.singleShot(0, no.setFocus)
        buttons.clicked.connect(lambda button: self.done(1 if button is not no else 2))
        layout.addWidget(buttons)
        self.place()

    def place(self) -> None:
        """Centered on the screen at its final size. Qt would center it over the window
        at a smaller size, and on Windows the dialog then grew down under the taskbar."""
        self.adjustSize()
        title = 40   # room for the title bar, which has no height until the dialog shows
        self.move(self.room.left() + max(0, (self.room.width() - self.width()) // 2),
                  self.room.top() + max(0, (self.room.height() - self.height() - title) // 2))

    def showEvent(self, event) -> None:
        super().showEvent(event)
        QTimer.singleShot(300, self.keep_on_screen)   # once the window has its frame

    def keep_on_screen(self) -> None:
        """If the dialog is still partly off the screen or under the taskbar, moves it
        onto the screen, as little as needed."""
        room = self.room
        frame = self.frameGeometry()
        x = max(room.left(), min(frame.left(), room.right() + 1 - frame.width()))
        y = max(room.top(), min(frame.top(), room.bottom() + 1 - frame.height()))
        if (x, y) != (frame.left(), frame.top()):
            self.move(x, y)

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
    def __init__(self, worker: Worker, server_url: str, live):
        super().__init__()
        self.worker = worker
        self.server_url = server_url
        self.pictures = []
        self.entries = []   # everything shown in the conversation, to show it again
        self.after_mcp = False   # the last thing shown is an MCP message, with its line below
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
        self.show_mcp = QCheckBox("Show MCP messages")
        self.show_mcp.setToolTip("Also show the messages between this app and the camera "
                                 "server, as the Model Context Protocol sends them")
        self.show_mcp.toggled.connect(self.show_again)
        self.cost = QLabel()

        asking = QHBoxLayout()
        asking.addWidget(self.question)
        asking.addWidget(self.ask_button)
        below = QHBoxLayout()
        below.addWidget(self.new_button)
        below.addWidget(QLabel("Model:"))
        below.addWidget(self.model)
        below.addWidget(self.show_mcp)
        below.addStretch()
        below.addWidget(self.cost)
        right = QWidget()
        column = QVBoxLayout(right)
        column.addWidget(self.conversation)
        column.addLayout(asking)
        column.addLayout(below)

        live_view = LiveView()
        splitter = QSplitter()
        splitter.addWidget(live_view)
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
        worker.note.connect(lambda text: self.add(gray(html.escape(text))))
        worker.confirm.connect(self.confirm)
        worker.frame.connect(live_view.show_jpeg)
        worker.no_frame.connect(live_view.show_problem)
        worker.check()
        worker.watch(live)

    # --- asking -------------------------------------------------------------------

    def ask(self) -> None:
        question = self.question.text().strip()
        if not question or not self.ask_button.isEnabled():
            return
        self.question.clear()
        self.set_working(True)
        self.add(f"<b>Me:</b> {html.escape(question)}")
        self.worker.ask(question, self.model.currentText())

    def new_conversation(self) -> None:
        self.worker.station.new_conversation()
        self.conversation.clear()
        self.after_mcp = False
        self.pictures.clear()
        self.entries.clear()
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
                self.add(gray(paragraphs(text)), indent=True)
            case Answer(text):
                self.add(text, kind="answer")
            case ToolCall():
                self.add(gray(f"▸ {html.escape(in_words(step))}"), indent=True)
            case McpMessage():
                self.add(mcp_message(step), kind="mcp")
            case ToolResult(refused=True):
                reason = step.text.removeprefix(f"Error executing tool {step.name}: ")
                self.add(red(f"Refused by the server: {html.escape(reason)}"), indent=True)
            case ToolResult() if step.pictures:   # the text is for Claude: the picture shows it
                self.add("".join(self.thumbnail(p) for p in step.pictures), indent=True)
            case ToolResult():
                self.add(gray(result_in_words(step)), indent=True)
            case Done(cost, problem):
                self.conversation_cost += cost
                if problem:
                    self.add(red(html.escape(problem)), indent=True)
                self.add(gray(f"{'Stopped after' if problem else 'Answered in'} "
                              f"{time.monotonic() - self.started:.0f} s, cost "
                              f"{dollars(cost)}") + "<hr>", indent=True)
                self.cost.setText(f"Conversation so far: {dollars(self.conversation_cost)}")
                self.set_working(False, problem)
                self.question.setFocus()

    def thumbnail(self, data: bytes) -> str:
        name = f"picture:{len(self.pictures)}"
        self.pictures.append(data)
        self.add_picture(name, data)
        return f"<a href='{name}'><img src='{name}' width='{THUMBNAIL}'></a> "

    def add_picture(self, name: str, data: bytes) -> None:
        self.conversation.document().addResource(
            QTextDocument.ResourceType.ImageResource, QUrl(name), QImage.fromData(data))

    def open_picture(self, url: QUrl) -> None:
        n = int(url.toString().split(":")[1])
        picture_window(self, self.pictures[n], f"Picture {n + 1}")

    def add(self, content: str, kind: str = "html", indent: bool = False) -> None:
        """Adds a paragraph: html, Claude's answer (Markdown) or an MCP message (html)."""
        self.entries.append((content, kind, indent))
        self.show_entry(content, kind, indent)
        self.scroll_down()

    def show_entry(self, content: str, kind: str, indent: bool) -> None:
        if kind == "mcp":
            if self.show_mcp.isChecked():
                self.show_mcp_message(content)
            return
        self.after_mcp = False
        cursor = self.conversation.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        block = QTextBlockFormat()
        block.setLeftMargin(INDENT if indent else 0)
        cursor.insertBlock(block, QTextCharFormat())   # not the previous format
        if kind == "answer":
            cursor.insertHtml("<b>Claude:</b> ")
            cursor.insertMarkdown(content)
        else:
            cursor.insertHtml(content)

    def show_mcp_message(self, text: str) -> None:
        """An MCP message in a code font, each line a paragraph of its own, so that a
        line too long for the window stays indented where it wraps."""
        code = QTextCharFormat()
        code.setFontFamilies([QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
                              .family()])
        code.setForeground(QColor(GRAY))
        font = self.conversation.font()
        font.setFamilies(code.fontFamilies())
        space = QFontMetricsF(font).horizontalAdvance(" ")
        cursor = self.conversation.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        if not self.after_mcp:   # between two messages, one line is enough
            self.add_line(cursor)
        for line in text.split("\n"):
            text = line.lstrip(" ")
            block = QTextBlockFormat()
            block.setLeftMargin(INDENT + space * (len(line) - len(text)))
            cursor.insertBlock(block, code)
            cursor.insertText(text, code)
        self.add_line(cursor)
        self.after_mcp = True

    @staticmethod
    def add_line(cursor: QTextCursor) -> None:
        """A thin gray line across the conversation, to mark where an MCP message starts
        and ends."""
        line = QTextBlockFormat()
        line.setLeftMargin(INDENT)
        line.setProperty(QTextFormat.Property.BlockTrailingHorizontalRulerWidth,
                         QTextLength(QTextLength.Type.PercentageLength, 100))
        line.setBackground(QColor(GRAY))
        cursor.insertBlock(line, QTextCharFormat())

    def show_again(self) -> None:
        """Shows the whole conversation again, with or without the MCP messages."""
        self.conversation.clear()
        self.after_mcp = False
        for n, data in enumerate(self.pictures):
            self.add_picture(f"picture:{n}", data)
        for entry in self.entries:
            self.show_entry(*entry)
        self.scroll_down()

    def scroll_down(self) -> None:
        bar = self.conversation.verticalScrollBar()
        bar.setValue(bar.maximum())


def gray(fragment: str) -> str:
    return f"<span style='color:{GRAY}'>{fragment}</span>"


def red(fragment: str) -> str:
    return f"<span style='color:{RED}'>{fragment}</span>"


def mcp_message(message: McpMessage) -> str:
    """An MCP message as text, laid out over several lines: → from this app to the
    server, ← back."""
    return f"{'→' if message.sent else '←'} {message.method} {pretty(message.body)}"


SHORT = 60   # a part of a message this long or shorter stays on one line


def pretty(value, depth: int = 0) -> str:
    """JSON, indented. A text that holds JSON of its own, such as an inspection record,
    is shown as that JSON, indented too, instead of as one string full of escapes."""
    if isinstance(value, str) and (inner := json_inside(value)) is not None:
        return "(JSON sent as a string) " + pretty(inner, depth)
    if not isinstance(value, (dict, list)) or not value:
        return json.dumps(value, ensure_ascii=False)
    one_line = json.dumps(value, ensure_ascii=False)
    if len(one_line) <= SHORT and not holds_json(value):
        return one_line
    pad = "  " * (depth + 1)
    if isinstance(value, dict):
        parts = [f"{pad}{json.dumps(k, ensure_ascii=False)}: {pretty(v, depth + 1)}"
                 for k, v in value.items()]
        start, end = "{", "}"
    else:
        parts = [f"{pad}{pretty(v, depth + 1)}" for v in value]
        start, end = "[", "]"
    return start + "\n" + ",\n".join(parts) + "\n" + "  " * depth + end


def json_inside(text: str):
    """The JSON object or list a text holds, or None."""
    if text.strip()[:1] not in ("{", "["):
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


def holds_json(value) -> bool:
    if isinstance(value, str):
        return json_inside(value) is not None
    parts = value.values() if isinstance(value, dict) else value if isinstance(value, list) else []
    return any(holds_json(part) for part in parts)


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
    parser.add_argument("--login", action="store_true",
                        help="log in through the camera server's login server, in the "
                             "browser, instead of sending the camera server's key")
    parser.add_argument("--trust", metavar="CA_FILE",
                        help="for HTTPS with private certificates: also trust the certificate "
                             "authority in this file, such as the demo's certs/ca.pem")
    args = parser.parse_args()

    verify = True
    if args.trust:
        verify = ssl.create_default_context()
        try:
            verify.load_verify_locations(args.trust)
        except (OSError, ssl.SSLError) as err:
            sys.exit(f"Cannot read the certificate authority {args.trust}: {err}")
    login = BrowserLogin(args.server) if args.login else None
    auth = login.auth if login else KeyAuth(read_key("API_KEY", CAMERA_KEY_FILE))
    claude = anthropic.AsyncAnthropic(api_key=read_key("ANTHROPIC_API_KEY", CLAUDE_KEY_FILE))
    station = Station(claude, lambda confirm: camera_client(args.server, auth, confirm, verify))
    ready = (lambda: login.logged_in) if login else (lambda: True)
    live = lambda show, tell: live_view(live_url(args.server), auth, show, tell, verify, ready)

    app = QApplication(sys.argv)
    app.setApplicationName("Inspection station")
    worker = Worker(station, login.who if login else lambda: "")
    if login:
        login.tell = worker.note.emit
    window = Window(worker, args.server, live)
    room = window.screen().availableSize()
    if window.width() + 40 > room.width() or window.height() + 80 > room.height():
        window.showMaximized()   # a small screen: Windows would let it run under the taskbar
    else:
        window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
