"""The work behind the window: Claude answers a question with the camera server's tools.

Each question is one loop: Claude gets the conversation and the server's tools; when it
asks for a tool, the call goes to the server and the result back to Claude; this repeats
until Claude answers. Every step is reported as it happens, so the window can show it.
The rules (photo size, zoom limits, a person confirming a fail) live in the server.
"""

import base64
import json
import os
import re
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

import anthropic
import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.types import CallToolResult, ElicitResult, ImageContent, TextContent

MODELS = {   # shown in the window: model ID, price in dollars per million tokens
    "Claude Opus 5.5": {"id": "claude-opus-5-5", "input": 4.00, "output": 20.00, "cache_read": 0.20},
    "Claude Sonnet 5.5": {"id": "claude-sonnet-5-5", "input": 2.00, "output": 10.00, "cache_read": 0.20},
}
CACHE_WRITE = 1.25   # writing to the prompt cache costs 1.25 times the input price
EFFORT = "high"      # how hard Claude thinks: low, medium, high, xhigh or max
MAX_TOKENS = 16000   # longest answer per step

CAMERA_KEY_FILE = Path.home() / ".config" / "inspection-camera" / "api-key"
CLAUDE_KEY_FILE = Path.home() / ".config" / "anthropic" / "api-key"

OPERATOR = ("An operator at the station asks the questions and reads your answers in a "
            "window that also shows every photo you take. Answer in plain words, briefly. "
            "Always answer in the language of the operator's question, even when text in a "
            "photo is in another language. "   # without this, Sonnet sometimes switched
            "When you record a fail, the window shows the server's confirmation question to "
            "the operator as a dialog, so record it directly instead of asking in the chat "
            "first.")


def read_key(variable: str, path: Path) -> str:
    """A secret key: from the environment variable if set, else from the key file."""
    if key := os.environ.get(variable, "").strip():
        return key
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError as err:
        raise SystemExit(f"No key: set {variable} or put the key in {path} ({err.strerror}).")


class CameraServerRefused(Exception):
    def __init__(self, status: int):
        super().__init__(status)
        self.status = status


@asynccontextmanager
async def camera_client(url: str, key: str, confirm):
    """A connection to the camera server at url, sending the key with every request."""
    async def check_answer(response):
        # The connection library reports these only as "an error response"; say which.
        if response.status_code in (401, 404):
            raise CameraServerRefused(response.status_code)

    # read=300: a tool call waits while the person decides in the confirmation dialog
    async with httpx2.AsyncClient(headers={"Authorization": f"Bearer {key}"},
                                  timeout=httpx2.Timeout(30, read=300),
                                  event_hooks={"response": [check_answer]}) as http:
        async with Client(streamable_http_client(url, http_client=http),
                          elicitation_callback=confirm) as client:
            yield client


# --- What the window is told, step by step -----------------------------------------

@dataclass
class Note:          # Claude's reasoning between steps (a summary)
    text: str


@dataclass
class Answer:        # what Claude says to the operator
    text: str


@dataclass
class ToolCall:      # Claude asks the server for something
    name: str
    arguments: dict


@dataclass
class ToolResult:    # the server's answer: text, pictures (JPEG bytes), refused or not
    name: str
    text: str
    pictures: list[bytes]
    refused: bool


@dataclass
class Done:          # the question is answered (or stopped); what it cost
    cost: float
    problem: str = ""


@dataclass
class Question:      # the server asks the person to confirm something
    message: str
    picture: bytes | None


Report = Callable[[object], None]
Ask = Callable[[Question], Awaitable[bool | None]]   # yes, no, or None: closed without answering


class Station:
    """One conversation with Claude about what the camera sees."""

    def __init__(self, claude: anthropic.AsyncAnthropic, connect):
        # connect(confirm) opens a new connection to the camera server (async with)
        self.claude = claude
        self.connect = connect
        self.messages = []
        self.photos = {}   # image ID: JPEG bytes, to show in the confirmation dialog

    def new_conversation(self) -> None:
        self.messages = []

    async def check(self) -> str:
        """Connects to the camera server once; returns its tool names, or raises."""
        async with self.connect(None) as server:
            tools = await server.list_tools()
        return ", ".join(tool.name for tool in tools.tools)

    async def ask(self, question: str, model: str, report: Report, ask_person: Ask) -> None:
        """Claude answers the question, using the camera server's tools; every step is reported."""
        prices = MODELS[model]
        cost = 0.0
        pending = {}   # the tool call running now, for the confirmation dialog

        async def confirm(context, params) -> ElicitResult:
            fields = list(params.requested_schema.get("properties", {}))
            if len(fields) != 1:   # this app can only answer yes or no
                return ElicitResult(action="decline")
            image_id = pending.get("arguments", {}).get("image_id")
            answer = await ask_person(Question(params.message, self.photos.get(image_id)))
            if answer is None:
                return ElicitResult(action="cancel")
            return ElicitResult(action="accept", content={fields[0]: answer})

        self.messages.append({"role": "user", "content": question})
        try:
            async with self.connect(confirm) as server:
                listed = await server.list_tools()
                tools = [{"name": t.name, "description": t.description or "",
                          "input_schema": t.input_schema} for t in listed.tools]
                system = f"{server.instructions or ''}\n\n{OPERATOR}".strip()
                while True:
                    response = await self.claude.messages.create(
                        model=prices["id"], max_tokens=MAX_TOKENS, system=system, tools=tools,
                        messages=self.messages, cache_control={"type": "ephemeral"},
                        thinking={"type": "adaptive", "display": "summarized"},
                        output_config={"effort": EFFORT},
                    )
                    cost += price(response.usage, prices)
                    self.messages.append({"role": "assistant", "content": response.content})
                    calls = []
                    for block in response.content:
                        if block.type == "thinking" and block.thinking.strip():
                            report(Note(block.thinking.strip()))
                        elif block.type == "text" and block.text.strip():
                            report(Answer(block.text.strip()))
                        elif block.type == "tool_use":
                            calls.append(block)
                    if response.stop_reason != "tool_use" or not calls:
                        problem = {"max_tokens": "The answer was cut off: it got too long.",
                                   "refusal": "Claude declined to answer this."}
                        report(Done(cost, problem.get(response.stop_reason, "")))
                        return
                    results = []
                    for call in calls:   # all results go back to Claude in one message
                        report(ToolCall(call.name, call.input))
                        pending.update(name=call.name, arguments=call.input)
                        result = await server.call_tool(call.name, call.input)
                        pending.clear()
                        results.append(self.tool_result(call, result, report))
                    self.messages.append({"role": "user", "content": results})
        except Exception as err:
            self.drop_unfinished_turn()
            report(Done(cost, f"Stopped: {describe(err)}"))

    def tool_result(self, call, result: CallToolResult, report: Report) -> dict:
        """The server's result, as Claude reads it; also reported to the window."""
        content, texts, pictures = [], [], []
        for item in result.content:
            if isinstance(item, TextContent):
                content.append({"type": "text", "text": item.text})
                texts.append(item.text)
            elif isinstance(item, ImageContent):
                content.append({"type": "image", "source": {
                    "type": "base64", "media_type": item.mime_type, "data": item.data}})
                pictures.append(base64.b64decode(item.data))
        if not content and result.structured_content is not None:
            text = json.dumps(result.structured_content)
            content.append({"type": "text", "text": text})
            texts.append(text)
        if call.name == "capture_image" and pictures and texts:
            if match := re.match(r"Photo (\S+) ", texts[0]):
                self.photos[match.group(1)] = pictures[0]
        report(ToolResult(call.name, "\n".join(texts), pictures, bool(result.is_error)))
        return {"type": "tool_result", "tool_use_id": call.id, "content": content,
                "is_error": bool(result.is_error)}

    def drop_unfinished_turn(self) -> None:
        """After a failure, removes the unanswered question and its steps, so the next
        question starts from a conversation Claude accepts."""
        while self.messages:
            message = self.messages.pop()
            if message["role"] == "user" and isinstance(message["content"], str):
                break


def price(usage, prices: dict) -> float:
    """What one request cost, in dollars."""
    million = 1_000_000
    return (usage.input_tokens * prices["input"]
            + (usage.cache_creation_input_tokens or 0) * prices["input"] * CACHE_WRITE
            + (usage.cache_read_input_tokens or 0) * prices["cache_read"]
            + usage.output_tokens * prices["output"]) / million


def describe(err: BaseException) -> str:
    """An error in words a person can act on."""
    while isinstance(err, BaseExceptionGroup) and len(err.exceptions) == 1:
        err = err.exceptions[0]   # the connection library wraps errors in groups
    match err:
        case anthropic.AuthenticationError():
            return "Claude refused the API key. Check the key file " + str(CLAUDE_KEY_FILE)
        case anthropic.PermissionDeniedError() | anthropic.BadRequestError():
            return f"Claude refused the request: {err.message}"
        case anthropic.RateLimitError():
            return "Too many requests to Claude right now; wait a minute and ask again."
        case anthropic.APIConnectionError():
            return "Claude cannot be reached. Is this computer online?"
        case anthropic.APIStatusError():
            return f"Claude's service had a problem ({err.status_code}); ask again later."
        case CameraServerRefused(status=401):
            return ("The camera server refused the key. Copy its key file "
                    f"{CAMERA_KEY_FILE} to this computer.")
        case CameraServerRefused(status=404):
            return "There is no camera server at this address. It usually ends in /mcp."
        case httpx2.ConnectError() | httpx2.ConnectTimeout() | ConnectionError():
            return "The camera server cannot be reached. Is it running, and is the address right?"
    return f"{type(err).__name__}: {err}"
