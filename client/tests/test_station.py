"""The loop between Claude and the camera server, without the window.

Claude is replaced by a script of answers (no cost, same result every time); the camera
server is the real one, in-process, with its fake camera.
"""

import json

import pytest
from anthropic.types import Message
from mcp import Client
from PIL import Image

from inspection_camera.camera import FakeCamera
from inspection_camera.server import create_server
from inspection_station.station import (Answer, CameraServerRefused, Done, Note, Question,
                                        Station, ToolCall, ToolResult, describe)

pytestmark = pytest.mark.anyio

MODEL = "Claude Opus 5.5"


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def server(tmp_path):
    samples = tmp_path / "samples"
    samples.mkdir()
    Image.new("RGB", (1280, 720), (200, 200, 200)).save(samples / "a.jpg")
    return create_server(FakeCamera(samples), tmp_path / "data")


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
            if block.get("type") == "tool_result" and not block["is_error"]:
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

    assert [type(s) for s in steps] == [Note, ToolCall, ToolResult, Answer, Done]
    photo = steps[2]
    assert photo.text.startswith("Photo ") and len(photo.pictures) == 1 and not photo.refused
    assert photo.pictures[0][:2] == b"\xff\xd8"   # a JPEG
    assert steps[4].problem == ""

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

    refused = [s for s in steps if isinstance(s, ToolResult) and s.refused]
    assert len(refused) == 1 and "too small" in refused[0].text
    assert claude.requests[2]["messages"][-1]["content"][0]["is_error"] is True


@pytest.mark.parametrize("answer, verdict, confirmation", [
    (True, "fail", "yes"), (False, "unsure", "no"), (None, "unsure", "no answer"),
], ids=["yes", "no", "closed"])
async def test_a_fail_needs_the_persons_yes_else_it_is_unsure(server, tmp_path, answer,
                                                              verdict, confirmation):
    claude = ScriptedClaude(
        reply(tool("capture_image")),
        lambda request: reply(tool("record_inspection", 2, image_id=last_photo(request),
                                   part_id="tray-07", verdict="fail",
                                   findings="Hammer missing.")),
        reply(text("Done."), stop="end_turn"))
    station = Station(claude, lambda confirm: Client(server, elicitation_callback=confirm))
    steps, asked = await run(station, "Is the tray complete? Record it.", [answer])

    assert len(asked) == 1
    assert "part tray-07" in asked[0].message and "FAILED" in asked[0].message
    assert asked[0].picture[:2] == b"\xff\xd8"   # the photo is shown with the question
    result = [s for s in steps if isinstance(s, ToolResult)][-1]
    assert not result.refused
    [line] = (tmp_path / "data" / "logs" / "inspections.jsonl").read_text().splitlines()
    assert json.loads(line)["verdict"] == verdict
    assert json.loads(line)["fail_confirmation"] == confirmation


async def test_cost_counts_every_step(server):
    usage = {"input_tokens": 1_000_000, "output_tokens": 100_000,
             "cache_read_input_tokens": 1_000_000, "cache_creation_input_tokens": 0}
    claude = ScriptedClaude(reply(tool("capture_image"), usage=usage),
                            reply(text("Done."), stop="end_turn", usage=usage))
    station = Station(claude, lambda confirm: Client(server, elicitation_callback=confirm))
    steps, _ = await run(station, "Photo?")
    # per step: $4 input + $2 output + $0.20 cache reads
    assert steps[-1].cost == pytest.approx(2 * 6.20)


async def test_after_a_failure_the_question_is_dropped(server):
    def unreachable(confirm):
        raise ConnectionError("no route")

    station = Station(ScriptedClaude(), unreachable)
    station.messages = [{"role": "user", "content": "Earlier"},
                        {"role": "assistant", "content": [text("Earlier answer")]}]
    steps, _ = await run(station, "Photo?")
    assert "cannot be reached" in steps[-1].problem
    assert [m["role"] for m in station.messages] == ["user", "assistant"]


def test_errors_are_told_in_words_a_person_can_act_on():
    wrapped = ExceptionGroup("", [ExceptionGroup("", [CameraServerRefused(401)])])
    assert "refused the key" in describe(wrapped)
    assert "ends in /mcp" in describe(CameraServerRefused(404))
