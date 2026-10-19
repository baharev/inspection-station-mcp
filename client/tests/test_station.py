"""The loop between Claude and the inspection server, without the window.

Claude is replaced by a script of answers (no cost, same result every time); the
inspection server by a stand-in with the same tools (stand_in_server.py), in-process.
"""

import asyncio
import contextlib
import json
import time
from types import SimpleNamespace
from typing import Annotated

import httpx2
import pytest
from anthropic.types import Message
from mcp import Client
from mcp.server import MCPServer, request_state
from mcp.server.elicitation import ElicitationResult
from mcp.server.mcpserver import Elicit, Resolve
from pydantic import BaseModel

from inspection_client.app import result_in_words
from inspection_client.station import (
    SERVER_KEY_FILE,
    Answer,
    Done,
    KeyAuth,
    McpMessage,
    Note,
    Question,
    Station,
    ToolCall,
    ToolResult,
    live_view,
    server_client,
)
from stand_in_server import stand_in_server

pytestmark = pytest.mark.anyio

MODEL = "Claude Opus 5.5"


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
    # Read from the sentence, as Claude does: the app passes Claude no other field.
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
        steps.append(q)   # in its place among the steps, to check the order
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


def claude_proposes_a_fail():
    """Claude takes a photo and records it as a fail."""
    return ScriptedClaude(
        reply(tool("capture_image")),
        lambda request: reply(tool("record_inspection", 2, image_id=last_photo(request),
                                   part_id="tray-07", verdict="fail",
                                   findings="Hammer missing.")),
        reply(text("Done."), stop="end_turn"))


@pytest.mark.parametrize("answer, server_got", [
    (True, True), (False, False), (None, "cancel"),
], ids=["yes", "no", "closed"])
async def test_the_person_answers_the_servers_question_about_a_fail(stand_in, answer,
                                                                    server_got):
    server, answers = stand_in
    station = Station(claude_proposes_a_fail(),
                      lambda confirm: Client(server, elicitation_callback=confirm))
    steps, asked = await run(station, "Is the tray complete? Record it.", [answer])

    assert len(asked) == 1
    assert "tray-07" in asked[0].message and "FAILED" in asked[0].message
    assert asked[0].picture[:2] == b"\xff\xd8"   # the photo is shown with the question
    result = [s for s in steps if isinstance(s, ToolResult)][-1]
    assert not result.refused
    assert answers == [server_got]

    # Protocol 2026-07-28: the question comes back as the call's result, with the server's
    # sealed state; the person is asked; the call goes again with the answer and the state.
    call, asking, person, again, final = [s for s in steps
                                          if isinstance(s, (McpMessage, Question))][-5:]
    assert (call.sent, call.method) == (True, "tools/call") and "requestState" not in call.body
    assert (asking.sent, asking.method) == (False, "result")
    assert asking.body["resultType"] == "input_required"
    [(key, question)] = asking.body["inputRequests"].items()
    assert question["method"] == "elicitation/create"
    assert "tray-07" in question["params"]["message"]
    assert "sealed by the server" in asking.body["requestState"]   # shortened
    assert person is asked[0]
    assert (again.sent, again.method) == (True, "tools/call")
    assert again.body["arguments"] == call.body["arguments"]
    assert again.body["requestState"] == asking.body["requestState"]
    assert again.body["inputResponses"][key] == (
        {"action": "cancel"} if answer is None
        else {"action": "accept", "content": {"mark_failed": answer}})
    assert (final.sent, final.body["resultType"]) == (False, "complete")


async def test_over_the_older_protocol_the_server_asks_during_the_call(stand_in):
    server, answers = stand_in
    station = Station(claude_proposes_a_fail(), lambda confirm: Client(
        server, elicitation_callback=confirm, mode="legacy"))
    steps, asked = await run(station, "Is the tray complete? Record it.", [True])

    assert answers == [True]
    call, question, person, answered, final = [s for s in steps
                                               if isinstance(s, (McpMessage, Question))][-5:]
    assert (call.sent, call.method) == (True, "tools/call")
    assert (question.sent, question.method) == (False, "elicitation/create")
    assert "tray-07" in question.body["message"]
    assert person is asked[0] and person.picture[:2] == b"\xff\xd8"
    assert answered == McpMessage(True, "result",
                                  {"action": "accept", "content": {"mark_failed": True}})
    assert (final.sent, final.method) == (False, "result")
    assert final.body["structuredContent"]["fail_confirmation"] == "yes"


@pytest.mark.parametrize("answer, can_ask, line", [
    (True, True, "Recorded: part tray-07 FAIL (confirmed by a person)"),
    (False, True, "Recorded: part tray-07 UNSURE<br>The fail was not confirmed (answer: no)"),
    (None, False, "Recorded: part tray-07 UNSURE<br>The fail was not confirmed "
                  "(answer: cannot ask)"),
], ids=["yes", "no", "cannot ask"])
async def test_the_window_says_what_was_recorded(stand_in, answer, can_ask, line):
    server, _ = stand_in
    station = Station(claude_proposes_a_fail(), lambda confirm: Client(
        server, elicitation_callback=confirm if can_ask else None))
    steps, asked = await run(station, "Is the tray complete? Record it.", [answer])

    assert len(asked) == can_ask
    record = [s for s in steps if isinstance(s, ToolResult)][-1]
    assert result_in_words(record).startswith(line), result_in_words(record)


async def test_an_answer_too_late_is_told_in_words_and_nothing_is_recorded(stand_in,
                                                                         monkeypatch):
    server, answers = stand_in
    station = Station(claude_proposes_a_fail(),
                      lambda confirm: Client(server, elicitation_callback=confirm))
    steps, real_time = [], time.time

    async def two_hours_later(question):
        # the clock the SDK checks the sealed question's age with
        later = SimpleNamespace(time=lambda: real_time() + 7200)
        monkeypatch.setattr(request_state, "time", later)
        return True

    await station.ask("Is the tray complete? Record it.", MODEL, steps.append, two_hours_later)
    assert "came too late" in steps[-1].problem and "Nothing was recorded" in steps[-1].problem
    assert answers == []
    assert station.messages == []   # the question dropped, so the next one starts clean


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


async def test_the_dialog_shows_the_photo_not_a_zoom_of_it(server):
    """A zoom names the photo it was cut from in the same field as a photo does."""
    claude = ScriptedClaude(
        reply(tool("capture_image"), tool("capture_image", 2)),
        reply(tool("zoom_image", 3, image_id="p1", left=0, top=0, width=0.5, height=0.5)),
        reply(tool("record_inspection", 4, image_id="p1", part_id="tray-07", verdict="fail",
                   findings="Hammer missing.")),
        reply(text("Done."), stop="end_turn"))
    station = Station(claude, lambda confirm: Client(server, elicitation_callback=confirm))
    steps, asked = await run(station, "Take two photos, look closer, record the first.",
                             [False])

    first, second, zoom = [s.pictures[0] for s in steps
                           if isinstance(s, ToolResult) and s.pictures]
    assert len({first, second, zoom}) == 3
    assert asked[0].picture == first, (
        "the zoom" if asked[0].picture == zoom else "not the photo recorded")


class MarkFailedWithReason(BaseModel):
    mark_failed: bool
    reason: str


class Reason(BaseModel):
    reason: str


class Record(BaseModel):   # a yes or no, but not the field this app knows
    record: bool


@pytest.mark.parametrize("asked_for", [MarkFailedWithReason, Reason, Record],
                         ids=["yes or no plus a reason", "only a reason", "another yes or no"])
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
    assert asked == [], "The person was asked a question that is not the yes or no it knows."
    assert got == ["decline"]


async def test_a_new_conversation_forgets_the_photos_too(server):
    claude = ScriptedClaude(reply(tool("capture_image")), reply(text("A tray."), stop="end_turn"))
    station = Station(claude, lambda confirm: Client(server, elicitation_callback=confirm))
    await run(station, "What is on the table?")
    assert list(station.photos) == ["p1"]
    station.new_conversation()
    assert station.messages == [] and station.photos == {}


async def test_cost_counts_every_step(server):
    usage = {"input_tokens": 1_000_000, "output_tokens": 100_000}
    claude = ScriptedClaude(
        reply(tool("capture_image"), usage=usage | {"cache_creation_input_tokens": 1_000_000}),
        reply(text("Done."), stop="end_turn", usage=usage | {"cache_read_input_tokens": 1_000_000}))
    station = Station(claude, lambda confirm: Client(server, elicitation_callback=confirm))
    steps, _ = await run(station, "Photo?")
    # each step $4 input + $2 output; then $5 for cache writes, $0.20 for cache reads
    assert steps[-1].cost == pytest.approx(11.00 + 6.20)


def accepted_by_claude(messages) -> str:
    """What the API would refuse in this conversation, or "" if nothing."""
    if [m["role"] for m in messages] != ["user", "assistant"] * (len(messages) // 2) + ["user"]:
        return f"roles out of turn: {[m['role'] for m in messages]}"
    for asked, answered in zip(messages[1::2], messages[2::2], strict=True):
        calls = [b["id"] for b in asked["content"] if b["type"] == "tool_use"]
        results = [b["tool_use_id"] for b in answered["content"]
                   if isinstance(b, dict) and b["type"] == "tool_result"]
        if calls != results:
            return f"tool calls {calls} answered by {results}"
    return ""


@pytest.mark.parametrize("unfinished", [
    reply(text("The tray holds"), tool("capture_image", 3), stop="max_tokens"),
    reply(text("I cannot help with that."), stop="refusal"),
    reply(text("Let me take a photo."), stop="tool_use"),   # but no call
], ids=["cut off", "refusal", "tool_use without a call"])
async def test_an_unfinished_answer_leaves_a_conversation_claude_accepts(server, unfinished):
    claude = ScriptedClaude(
        reply(tool("capture_image")), reply(text("A tray."), stop="end_turn"),
        reply(tool("capture_image", 2)), unfinished,
        reply(text("The tray is complete."), stop="end_turn"))
    station = Station(claude, lambda confirm: Client(server, elicitation_callback=confirm))
    await run(station, "What is on the table?")
    steps, _ = await run(station, "Is the tray complete?")
    assert "ask again" in steps[-1].problem
    await run(station, "Is the tray complete?")

    sent = claude.requests[-1]["messages"]
    assert accepted_by_claude(sent) == "", accepted_by_claude(sent)
    assert [m["content"] for m in sent if isinstance(m["content"], str)] == [
        "What is on the table?", "Is the tray complete?"]   # the unfinished one left out


async def test_claude_may_make_at_most_25_tool_calls_for_one_question(server):
    many = [reply(tool("capture_image", n)) for n in range(1, 27)]   # the 26th not made
    claude = ScriptedClaude(*many, reply(text("Fine."), stop="end_turn"))
    station = Station(claude, lambda confirm: Client(server, elicitation_callback=confirm))
    steps, _ = await run(station, "Take photos until you are sure.")

    assert len([s for s in steps if isinstance(s, ToolCall)]) == 25
    assert "more than 25 tool calls" in steps[-1].problem
    await run(station, "Then just say fine.")
    sent = claude.requests[-1]["messages"]
    assert accepted_by_claude(sent) == "", accepted_by_claude(sent)
    assert sent == [{"role": "user", "content": "Then just say fine."}]


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
def inspection_server(offline):
    """Every HTTP request goes to a stand-in for the live view; the requests it got."""
    got = []

    def answer(request):
        got.append(request)
        if request.headers.get("Authorization") != "Bearer k1":
            return httpx2.Response(401, text="No key or login token sent.")
        return httpx2.Response(200, content=FRAME)

    offline(answer)
    return got


LIVE = "http://station:8000/live/frame.jpg"


async def watch(ready=lambda: True, key="k1"):
    """The live view, until it shows a frame, says why it cannot, or stops asking; and
    why it stopped (None if it did not)."""
    shown, told = [], []
    live = asyncio.create_task(live_view(LIVE, KeyAuth(key), shown.append, told.append,
                                         ready=ready))
    async with asyncio.timeout(5):
        while not shown and not told and not live.done():
            await asyncio.sleep(0.01)
    if live.done():
        return shown, told, live.result()
    live.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await live
    return shown, told, None


async def test_the_live_view_sends_the_key(inspection_server):
    shown, told, stopped = await watch()
    assert stopped is None and told == [], f"No frame: {stopped or told}"
    assert shown[0] == FRAME


async def test_the_live_view_waits_for_the_login(inspection_server):
    shown, told, _ = await watch(ready=lambda: False)
    assert inspection_server == [], ("The live view asked for a frame before the person logged in, "
                                 "which starts a login of its own.")
    assert told == ["Waiting for the login…"]


async def test_the_live_view_stops_asking_once_the_key_is_refused(inspection_server):
    """Each refusal is a line in the server's audit log: no asking again every 2 s."""
    shown, told, stopped = await watch(key="k2")
    assert stopped is not None, f"The live view kept asking after: {told}"
    assert "refused the key" in stopped and str(SERVER_KEY_FILE) in stopped
    assert len(inspection_server) == 1 and shown == []


async def test_the_live_view_stops_asking_once_the_person_may_not_use_it(offline):
    refused = "viewer2 may not use the live view: it needs the role 'viewer'."
    offline(lambda request: httpx2.Response(403, text=refused))
    shown, told, stopped = await watch()
    assert stopped == refused, f"The live view kept asking after: {told}"


async def test_the_live_view_goes_on_after_a_problem_with_the_camera(offline):
    answers = [httpx2.Response(503, text="The camera returned no picture."),
               httpx2.Response(200, content=FRAME)]
    offline(lambda request: answers.pop(0))
    shown, told = [], []
    live = asyncio.create_task(live_view(LIVE, KeyAuth("k1"), shown.append, told.append))
    async with asyncio.timeout(5):
        while not shown and not live.done():
            await asyncio.sleep(0.01)
    assert not live.done(), f"The live view stopped: {live.result()}"
    live.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await live
    assert told == ["The camera returned no picture."] and shown == [FRAME]


KEY_REFUSED = {"WWW-Authenticate": 'Bearer error="invalid_token"'}
LOGIN_WANTED = {"WWW-Authenticate": 'Bearer error="invalid_token", resource_metadata='
                '"http://station:8000/.well-known/oauth-protected-resource/mcp"'}


@pytest.mark.parametrize("status, headers, told", [
    (404, {}, ["There is no inspection server at this address", "ends in /mcp"]),
    (401, KEY_REFUSED, ["refused the key", str(SERVER_KEY_FILE)]),
    (401, LOGIN_WANTED, ["takes logins, not its key", "--login"]),
], ids=["nothing at the address", "key refused", "logins wanted"])
async def test_errors_are_told_in_words_a_person_can_act_on(offline, status, headers, told):
    offline(lambda request: httpx2.Response(status, headers=headers))
    station = Station(ScriptedClaude(), lambda confirm: server_client(
        "http://station:8000/mcp", KeyAuth("k1"), confirm))
    steps, _ = await run(station, "Photo?")
    problem = steps[-1].problem
    assert all(words in problem for words in told), f"The person was told: {problem}"
