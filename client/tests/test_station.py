"""The loop between Claude and the camera server, without the window.

Claude is replaced by a script of answers (no cost, same result every time); the camera
server by a stand-in with the same tools (stand_in_server.py), in-process.
"""

import asyncio
import contextlib
import json
from typing import Annotated

import httpx2
import pytest
from anthropic.types import Message
from mcp import Client
from mcp.server import MCPServer
from mcp.server.elicitation import ElicitationResult
from mcp.server.mcpserver import Elicit, Resolve
from pydantic import BaseModel

from inspection_client.station import (CAMERA_KEY_FILE, Answer, Done, KeyAuth, McpMessage, Note,
                                        Question, Station, ToolCall, ToolResult, camera_client,
                                        live_view)
from stand_in_server import stand_in_server

pytestmark = pytest.mark.anyio

MODEL = "Claude Opus 5.5"


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def stand_in():
    return stand_in_server()


@pytest.fixture
def server(stand_in):
    return stand_in[0]


def reply(*blocks, stop="tool_use", usage=None):
    """One answer from Claude, as the API returns it."""
    return Message.model_validate({
        "id": "msg", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
        "content": list(blocks), "stop_reason": stop, "stop_sequence": None,
        "usage": usage or {"input_tokens": 1000, "output_tokens": 100}})


def text(words):
    return {"type": "text", "text": words}


def tool(name, n=1, **arguments):
    return {"type": "tool_use", "id": f"call-{n}", "name": name, "input": arguments}


class ScriptedClaude:
    """Stands in for the Claude API: gives the scripted replies in order, keeps the requests.

    A reply can also be a function of the request, for replies that name a photo's ID.
    """

    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests = []
        self.messages = self

    async def create(self, **request):
        request = json.loads(json.dumps(request, default=lambda o: o.model_dump()))
        self.requests.append(request)
        next_reply = self.replies.pop(0)
        return next_reply(request) if callable(next_reply) else next_reply


def last_photo(request):
    """The ID of the photo taken last, as the server told Claude."""
    for message in reversed(request["messages"]):
        for block in message["content"] if isinstance(message["content"], list) else []:
            if block.get("type") == "tool_result" and not block.get("is_error"):
                words = block["content"][0]["text"].split()
                if words[0] == "Photo":
                    return words[1]


async def run(station, question, answers=()):
    steps, asked = [], []
    answers = list(answers)

    async def person(q: Question):
        asked.append(q)
        return answers.pop(0)

    await station.ask(question, MODEL, steps.append, person)
    return steps, asked


async def test_claude_takes_a_photo_and_answers(server):
    claude = ScriptedClaude(
        reply({"type": "thinking", "thinking": "I need a photo.", "signature": "s"},
              tool("capture_image")),
        reply(text("The tray is empty."), stop="end_turn"))
    station = Station(claude, lambda confirm: Client(server, elicitation_callback=confirm))
    steps, _ = await run(station, "What is on the tray?")

    assert [type(s) for s in steps] == [Note, ToolCall, McpMessage, McpMessage, ToolResult,
                                        Answer, Done]
    photo = steps[4]
    assert photo.text.startswith("Photo ") and len(photo.pictures) == 1 and not photo.refused
    assert photo.pictures[0][:2] == b"\xff\xd8"   # a JPEG
    assert steps[6].problem == ""

    # the MCP messages as sent, the picture's data left out
    sent, received = steps[2], steps[3]
    assert sent == McpMessage(True, "tools/call", {"name": "capture_image", "arguments": {}})
    assert not received.sent and received.method == "result"
    caption, image = received.body["content"]
    assert caption["text"] == photo.text and image["mimeType"] == "image/jpeg"
    assert image["data"].endswith(" bytes, not shown)")

    # Claude was given the server's tools and instructions, then the photo as an image
    first, second = claude.requests
    assert {t["name"] for t in first["tools"]} == {"capture_image", "zoom_image",
                                                   "record_inspection"}
    assert "zoom_image" in first["system"] and "operator" in first["system"]
    result = second["messages"][-1]["content"][0]
    assert result["type"] == "tool_result" and result["tool_use_id"] == "call-1"
    assert [c["type"] for c in result["content"]] == ["text", "image"]


async def test_a_refusal_by_the_server_goes_back_to_claude(server):
    claude = ScriptedClaude(
        reply(tool("capture_image")),
        lambda request: reply(tool("zoom_image", 2, image_id=last_photo(request), left=0,
                                   top=0, width=0.01, height=0.01)),
        reply(text("I could not look closer."), stop="end_turn"))
    station = Station(claude, lambda confirm: Client(server, elicitation_callback=confirm))
    steps, _ = await run(station, "Look closer.")

    photo, zoom = [s for s in steps if isinstance(s, ToolResult)]
    assert "too small" in zoom.text
    assert (photo.refused, zoom.refused) == (False, True)   # shown in red in the window
    sent_back = claude.requests[2]["messages"][-1]["content"][0]
    assert sent_back.get("is_error") is True, f"Claude was told the zoom worked: {sent_back}"


@pytest.mark.parametrize("answer, server_got", [
    (True, True), (False, False), (None, "cancel"),
], ids=["yes", "no", "closed"])
async def test_the_person_answers_the_servers_question_about_a_fail(stand_in, answer,
                                                                    server_got):
    server, answers = stand_in
    claude = ScriptedClaude(
        reply(tool("capture_image")),
        lambda request: reply(tool("record_inspection", 2, image_id=last_photo(request),
                                   part_id="tray-07", verdict="fail",
                                   findings="Hammer missing.")),
        reply(text("Done."), stop="end_turn"))
    station = Station(claude, lambda confirm: Client(server, elicitation_callback=confirm))
    steps, asked = await run(station, "Is the tray complete? Record it.", [answer])

    assert len(asked) == 1
    assert "tray-07" in asked[0].message and "FAILED" in asked[0].message
    assert asked[0].picture[:2] == b"\xff\xd8"   # the photo is shown with the question
    result = [s for s in steps if isinstance(s, ToolResult)][-1]
    assert not result.refused
    assert answers == [server_got]

    # the server's question and the answer, as MCP messages within the tool call
    question, answered = [s for s in steps if isinstance(s, McpMessage)][-3:-1]
    assert question.method == "elicitation/create" and not question.sent
    assert "tray-07" in question.body["message"]
    assert answered.sent and answered.body["action"] == ("cancel" if answer is None else "accept")


async def test_the_dialog_shows_the_photo_being_recorded(server):
    """Not the conversation's first photo, nor the latest one."""
    claude = ScriptedClaude(
        reply(tool("capture_image")), reply(text("One photo."), stop="end_turn"),
        reply(tool("capture_image", 2)), reply(tool("capture_image", 3)),
        reply(tool("record_inspection", 4, image_id="p2", part_id="tray-07", verdict="fail",
                   findings="Hammer missing.")),
        reply(text("Done."), stop="end_turn"))
    station = Station(claude, lambda confirm: Client(server, elicitation_callback=confirm))
    earlier, _ = await run(station, "Take a photo.")
    steps, asked = await run(station, "Take two more and record the first of them.", [False])

    photos = {s.text.split()[1]: s.pictures[0] for s in earlier + steps
              if isinstance(s, ToolResult) and s.name == "capture_image"}
    assert list(photos) == ["p1", "p2", "p3"]
    assert [name for name, picture in photos.items() if picture == asked[0].picture] == ["p2"]


class RecordWithReason(BaseModel):
    record: bool
    reason: str


class Reason(BaseModel):
    reason: str


@pytest.mark.parametrize("asked_for", [RecordWithReason, Reason],
                         ids=["yes or no plus a reason", "only a reason"])
async def test_a_question_that_is_not_yes_or_no_is_declined_without_asking_the_person(asked_for):
    server, got = MCPServer("asks more"), []

    def ask_more(part_id: str):
        return Elicit(f"Part {part_id}: mark it FAILED, and why?", asked_for)

    @server.tool()
    async def record_inspection(
        part_id: str, answer: Annotated[ElicitationResult[asked_for], Resolve(ask_more)],
    ) -> str:
        got.append(answer.action)
        return f"Recorded part {part_id}."

    claude = ScriptedClaude(reply(tool("record_inspection", part_id="tray-07")),
                            reply(text("Done."), stop="end_turn"))
    station = Station(claude, lambda confirm: Client(server, elicitation_callback=confirm))
    _, asked = await run(station, "Record it.", [True])
    assert asked == [], "The person was asked a question that is not a plain yes or no."
    assert got == ["decline"]


async def test_cost_counts_every_step(server):
    usage = {"input_tokens": 1_000_000, "output_tokens": 100_000}
    claude = ScriptedClaude(
        reply(tool("capture_image"), usage=usage | {"cache_creation_input_tokens": 1_000_000}),
        reply(text("Done."), stop="end_turn", usage=usage | {"cache_read_input_tokens": 1_000_000}))
    station = Station(claude, lambda confirm: Client(server, elicitation_callback=confirm))
    steps, _ = await run(station, "Photo?")
    # each step $4 input + $2 output; then $5 for cache writes, $0.20 for cache reads
    assert steps[-1].cost == pytest.approx(11.00 + 6.20)


async def test_after_a_failure_the_question_is_dropped(server):
    def unreachable(confirm):
        raise ConnectionError("no route")

    station = Station(ScriptedClaude(), unreachable)
    station.messages = [{"role": "user", "content": "Earlier"},
                        {"role": "assistant", "content": [text("Earlier answer")]}]
    steps, _ = await run(station, "Photo?")
    assert "cannot be reached" in steps[-1].problem
    assert [m["role"] for m in station.messages] == ["user", "assistant"]


FRAME = b"\xff\xd8 a frame"


@pytest.fixture
def camera_server(offline):
    """Every HTTP request goes to a stand-in for the live view; the requests it got."""
    got = []

    def answer(request):
        got.append(request)
        if request.headers.get("Authorization") != "Bearer k1":
            return httpx2.Response(401, text="No key or login token sent.")
        return httpx2.Response(200, content=FRAME)

    offline(answer)
    return got


async def watch(ready=lambda: True):
    """The live view, until it shows a frame or says why it cannot."""
    shown, told = [], []
    live = asyncio.create_task(live_view("http://station:8000/live/frame.jpg", KeyAuth("k1"),
                                         shown.append, told.append, ready=ready))
    async with asyncio.timeout(5):
        while not shown and not told:
            await asyncio.sleep(0.01)
    live.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await live
    return shown, told


async def test_the_live_view_sends_the_key(camera_server):
    shown, told = await watch()
    assert told == []
    assert shown[0] == FRAME


async def test_the_live_view_waits_for_the_login(camera_server):
    shown, told = await watch(ready=lambda: False)
    assert camera_server == [], ("The live view asked for a frame before the person logged in, "
                                 "which starts a login of its own.")
    assert told == ["Waiting for the login…"]


KEY_REFUSED = {"WWW-Authenticate": 'Bearer error="invalid_token"'}
LOGIN_WANTED = {"WWW-Authenticate": 'Bearer error="invalid_token", resource_metadata='
                '"http://station:8000/.well-known/oauth-protected-resource/mcp"'}


@pytest.mark.parametrize("status, headers, told", [
    (404, {}, ["There is no camera server at this address", "ends in /mcp"]),
    (401, KEY_REFUSED, ["refused the key", str(CAMERA_KEY_FILE)]),
    (401, LOGIN_WANTED, ["takes logins, not its key", "--login"]),
], ids=["nothing at the address", "key refused", "logins wanted"])
async def test_errors_are_told_in_words_a_person_can_act_on(offline, status, headers, told):
    offline(lambda request: httpx2.Response(status, headers=headers))
    station = Station(ScriptedClaude(), lambda confirm: camera_client(
        "http://station:8000/mcp", KeyAuth("k1"), confirm))
    steps, _ = await run(station, "Photo?")
    problem = steps[-1].problem
    assert all(words in problem for words in told), f"The person was told: {problem}"
