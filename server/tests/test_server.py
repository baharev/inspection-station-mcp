"""Tests for the inspection server: in-process, against a fake camera, no hardware.

    pytest -q

The test photos are drawn by the code below (left half red, right half blue), so they
contain nothing private and the zoom can be checked by color.
"""

import base64
import hashlib
import io
import json
import time
from datetime import datetime
from importlib.metadata import version

import pytest
from mcp import Client, MCPError
from mcp.server import request_state
from mcp.types import ElicitResult
from PIL import Image

from inspection_server.camera import FakeCamera
from inspection_server.server import ANSWER_TIME, MAX_PHOTO, create_server

pytestmark = pytest.mark.anyio

RED, BLUE = (220, 30, 30), (30, 30, 220)


def draw_photo(path, size=(1600, 900)):
    photo = Image.new("RGB", size, RED)
    photo.paste(BLUE, (size[0] // 2, 0, size[0], size[1]))
    photo.save(path)


@pytest.fixture
def server(tmp_path):
    samples = tmp_path / "samples"
    samples.mkdir()
    draw_photo(samples / "a.jpg")
    draw_photo(samples / "b.jpg", size=(640, 480))
    return create_server(FakeCamera(samples), tmp_path / "data")


def human(answer: str):
    """A stand-in for the person who answers the question.

    "yes" or "no": they answer it; "untouched": they accept without ticking the box;
    "decline": they refuse to answer; "cancel": they close the dialog.
    """
    asked = []

    async def callback(context, params):
        asked.append(params)
        if answer in ("yes", "no"):
            return ElicitResult(action="accept", content={"mark_failed": answer == "yes"})
        if answer == "untouched":
            return ElicitResult(action="accept", content={})
        return ElicitResult(action=answer)

    callback.asked = asked
    return callback


def nobody():
    """For calls that must not ask anyone: fails the test if a question arrives."""
    async def callback(context, params):
        pytest.fail(f"A human was asked, but should not have been: {params.message}")
    return callback


def decode(result) -> Image.Image:
    image = next(c for c in result.content if c.type == "image")
    return Image.open(io.BytesIO(base64.b64decode(image.data)))


async def take_photo(client) -> str:
    result = await client.call_tool("capture_image", {})
    assert not result.is_error
    return result.structured_content["image_id"]


def record(image_id, verdict="pass", part_id="tray-07", findings="All three tools present."):
    return {"image_id": image_id, "part_id": part_id, "verdict": verdict, "findings": findings}


def log_lines(tmp_path, name):
    path = tmp_path / "data" / "logs" / name
    return path.read_text().splitlines() if path.exists() else []


# --- the tools as the AI sees them ---------------------------------------------------

async def test_tools_are_listed_with_hints(server):
    async with Client(server) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    assert set(tools) == {"capture_image", "zoom_image", "record_inspection"}
    assert tools["capture_image"].annotations.read_only_hint is not True   # it saves a file
    assert tools["capture_image"].annotations.destructive_hint is False
    assert tools["zoom_image"].annotations.read_only_hint is True
    # The human's answer is filled in by the server, so the AI cannot supply it:
    assert "answer" not in tools["record_inspection"].input_schema["properties"]


async def test_the_server_names_its_version(server):
    async with Client(server) as client:
        await client.list_tools()
        assert client.server_info.version == version("inspection-mcp-server")


async def test_photos_and_zooms_name_the_photo_in_a_field_too(server, tmp_path):
    # For programs: the ID and sizes as fields, so nobody reads them out of the sentence.
    async with Client(server) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        photo = await client.call_tool("capture_image", {})
        image_id = photo.structured_content["image_id"]
        zoom = await client.call_tool("zoom_image", {
            "image_id": image_id, "left": 0.5, "top": 0, "width": 0.25, "height": 0.5})
    assert tools["capture_image"].output_schema["required"] == ["image_id", "width", "height"]
    assert tools["zoom_image"].output_schema["required"] == ["image_id", "width", "height", "box",
                                                             "scale"]
    with Image.open(tmp_path / "data" / "captures" / f"{image_id}.jpg") as kept:
        assert photo.structured_content == {"image_id": image_id, "width": kept.width,
                                            "height": kept.height}
    assert zoom.structured_content == {"image_id": image_id, "width": 1600, "height": 900,
                                       "box": [800, 0, 1200, 450], "scale": 2.28}
    # Claude Code gives the AI the fields instead of the sentence: what the sentence says
    # about the size sent is in the tool's description, so the AI learns it either way.
    assert "at most 1280x720" in tools["capture_image"].description
    assert MAX_PHOTO == (1280, 720)
    # The sentence and the picture stay, for the AI and for clients that ignore the fields:
    for result in (photo, zoom):
        assert [c.type for c in result.content] == ["text", "image"]
        assert result.content[0].text.startswith(f"Photo {image_id}")


# --- capture_image -----------------------------------------------------------------

async def test_capture_sends_a_capped_photo_and_keeps_the_full_one(server, tmp_path):
    async with Client(server) as client:
        result = await client.call_tool("capture_image", {})
    assert not result.is_error
    image_id = result.structured_content["image_id"]
    assert decode(result).size == (1280, 720)          # 1600x900 capped, shape kept
    assert "(1600x900 pixels, shown here at 1280x720;" in result.content[0].text
    with Image.open(tmp_path / "data" / "captures" / f"{image_id}.jpg") as kept:
        assert kept.size == (1600, 900)                # the zoom's source: every pixel
    assert f"capture_image {image_id} 1600x900" in log_lines(tmp_path, "audit.log")[0]


async def test_fake_camera_serves_the_photos_in_turn(server):
    async with Client(server) as client:
        sizes = [decode(await client.call_tool("capture_image", {})).size for _ in range(3)]
    assert sizes == [(1280, 720), (640, 480), (1280, 720)]


async def test_a_photo_that_fits_says_only_its_size(server):
    async with Client(server) as client:
        await client.call_tool("capture_image", {})
        result = await client.call_tool("capture_image", {})
    assert result.content[0].text.endswith("(640x480 pixels)")


async def test_two_photos_in_the_same_second_get_different_ids(server):
    async with Client(server) as client:
        ids = [await take_photo(client) for _ in range(3)]
    assert len(set(ids)) == 3


async def test_camera_without_photos_gives_a_readable_error(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    async with Client(create_server(FakeCamera(empty), tmp_path / "data")) as client:
        result = await client.call_tool("capture_image", {})
    assert result.is_error and "no photos" in result.content[0].text


# --- zoom_image --------------------------------------------------------------------

async def test_zoom_returns_the_chosen_region_enlarged(server):
    async with Client(server) as client:
        image_id = await take_photo(client)
        result = await client.call_tool("zoom_image", {
            "image_id": image_id, "left": 0.6, "top": 0.25, "width": 0.3, "height": 0.5})
    assert not result.is_error
    crop = decode(result)
    assert max(crop.size) == 1024
    r, g, b = crop.convert("RGB").getpixel((crop.width // 2, crop.height // 2))
    assert b > 150 and r < 100                        # the right half of the photo is blue
    assert "pixels 960..1440 across and 225..675 down" in result.content[0].text   # full size
    assert result.content[0].text.endswith("enlarged 2.1 times")   # 480 pixels to 1024


async def test_a_zoom_on_a_large_rectangle_says_so_and_keeps_the_photos_detail(server):
    async with Client(server) as client:
        image_id = await take_photo(client)   # 1600x900, sent at 1280x720
        result = await client.call_tool("zoom_image", {
            "image_id": image_id, "left": 0, "top": 0, "width": 1, "height": 1})
    assert decode(result).size == (1280, 720)   # never less than the photo sent showed
    assert result.content[0].text.endswith(
        "shown at 80% of full size: a smaller rectangle shows more detail")


@pytest.mark.parametrize("box, reason", [
    ({"left": 0.5, "top": 0.5, "width": 0.05, "height": 0.2}, "too small"),
    ({"left": 0.2, "top": 0.5, "width": 0.6, "height": 0.05}, "too small"),
    ({"left": 0.8, "top": 0.0, "width": 0.4, "height": 0.4}, "outside the photo"),
    ({"left": 0.0, "top": 0.8, "width": 0.4, "height": 0.4}, "outside the photo"),
], ids=["too narrow", "too short", "past the right side", "past the bottom"])
async def test_zoom_refuses_bad_rectangles(server, tmp_path, box, reason):
    async with Client(server) as client:
        image_id = await take_photo(client)
        result = await client.call_tool("zoom_image", {"image_id": image_id, **box})
    assert reason in result.content[0].text
    assert result.is_error
    assert log_lines(tmp_path, "audit.log")[-1].endswith(f"REFUSED zoom_image {image_id}: {reason}")


async def test_zoom_takes_the_smallest_rectangle_right_up_to_the_corner(server):
    # One tenth of the photo's width and height is allowed, and so is touching its edges.
    async with Client(server) as client:
        image_id = await take_photo(client)
        result = await client.call_tool("zoom_image", {
            "image_id": image_id, "left": 0.9, "top": 0.9, "width": 0.1, "height": 0.1})
    assert "pixels 1440..1600 across and 810..900 down" in result.content[0].text
    assert not result.is_error


async def test_zoom_refuses_numbers_outside_0_to_1(server):
    async with Client(server) as client:
        image_id = await take_photo(client)
        result = await client.call_tool("zoom_image", {
            "image_id": image_id, "left": -0.5, "top": 0, "width": 0.5, "height": 0.5})
    assert "left\n  Input should be greater than or equal to 0" in result.content[0].text
    assert result.is_error


async def test_zoom_refuses_an_unknown_photo(server):
    async with Client(server) as client:
        result = await client.call_tool("zoom_image", {
            "image_id": "20200101-000000", "left": 0, "top": 0, "width": 0.5, "height": 0.5})
    assert result.is_error and "no photo" in result.content[0].text


# --- record_inspection: pass and unsure --------------------------------------------

async def test_pass_is_recorded_without_asking_anyone(server, tmp_path):
    async with Client(server, elicitation_callback=nobody()) as client:
        image_id = await take_photo(client)
        result = await client.call_tool("record_inspection", record(image_id))
    assert not result.is_error
    assert result.structured_content["verdict"] == "pass"
    [line] = log_lines(tmp_path, "inspections.jsonl")
    assert json.loads(line) | {"time": None, "photo_sha256": None} == {
        "time": None, "image_id": image_id, "photo_sha256": None, "part_id": "tray-07",
        "ai_verdict": "pass", "ai_findings": "All three tools present.",
        "fail_confirmation": "not asked", "verdict": "pass", "user": "local"}
    assert log_lines(tmp_path, "audit.log")[-1].endswith(
        f"local record_inspection tray-07 pass {image_id} (AI: pass, fail confirmation: not asked)")


async def test_a_record_holds_the_fingerprint_of_its_photo(server, tmp_path):
    async with Client(server, elicitation_callback=nobody()) as client:
        image_id = await take_photo(client)
        await client.call_tool("record_inspection", record(image_id))
    photo = (tmp_path / "data" / "captures" / f"{image_id}.jpg").read_bytes()
    [line] = log_lines(tmp_path, "inspections.jsonl")
    assert json.loads(line)["photo_sha256"] == hashlib.sha256(photo).hexdigest()


async def test_the_photo_and_its_record_have_the_same_fingerprint(server, tmp_path):
    # Taken when the photo is saved, so a record can be checked against what was taken.
    async with Client(server, elicitation_callback=nobody()) as client:
        image_id = await take_photo(client)
        await client.call_tool("record_inspection", record(image_id))
    photo = (tmp_path / "data" / "captures" / f"{image_id}.jpg").read_bytes()
    [line] = log_lines(tmp_path, "inspections.jsonl")
    assert log_lines(tmp_path, "audit.log")[0].endswith(
        f"capture_image {image_id} 1600x900 sha256={hashlib.sha256(photo).hexdigest()}")
    assert json.loads(line)["photo_sha256"] == hashlib.sha256(photo).hexdigest()


async def test_times_carry_their_offset_from_utc(server, tmp_path):
    # Without it, the hour that repeats when clocks go back could not be told apart.
    async with Client(server, elicitation_callback=nobody()) as client:
        image_id = await take_photo(client)
        await client.call_tool("record_inspection", record(image_id))
    [line] = log_lines(tmp_path, "inspections.jsonl")
    audit = log_lines(tmp_path, "audit.log")
    for stamp in (json.loads(line)["time"], *(entry.split()[0] for entry in audit)):
        assert datetime.fromisoformat(stamp).utcoffset() is not None, stamp


async def test_unsure_is_recorded_and_says_a_person_should_look(server):
    async with Client(server, elicitation_callback=nobody()) as client:
        image_id = await take_photo(client)
        result = await client.call_tool("record_inspection", record(image_id, "unsure"))
    assert not result.is_error
    assert "a person should look" in result.structured_content["note"]


# --- record_inspection: a fail needs a person's yes, else it is unsure -------------

async def test_fail_is_recorded_when_the_human_says_yes(server, tmp_path):
    operator = human("yes")
    async with Client(server, elicitation_callback=operator) as client:
        image_id = await take_photo(client)
        result = await client.call_tool(
            "record_inspection", record(image_id, "fail", findings="Pack torn at the top."))
    assert not result.is_error
    assert result.structured_content["verdict"] == "fail"
    assert result.structured_content["fail_confirmation"] == "yes"
    [question] = operator.asked
    assert "part tray-07" in question.message and "torn" in question.message
    assert "FAILED" in question.message and "UNSURE" in question.message
    # A box that reads as what ticking it does, unticked unless the person ticks it:
    assert question.requested_schema["properties"] == {"mark_failed": {
        "type": "boolean", "title": "Mark this part as FAILED", "default": False,
        "description": "Yes: the part is marked FAILED. No: it is marked UNSURE, "
                       "for a person to look at."}}
    assert len(log_lines(tmp_path, "inspections.jsonl")) == 1
    assert f"tray-07 fail {image_id} (AI: fail, fail confirmation: yes)" \
        in log_lines(tmp_path, "audit.log")[-1]


@pytest.mark.parametrize("answer, confirmation", [
    ("no", "no"), ("untouched", "no"), ("decline", "declined"), ("cancel", "no answer"),
], ids=["says no", "leaves the box unticked", "refuses to answer", "closes the dialog"])
async def test_fail_without_a_yes_is_recorded_as_unsure(server, tmp_path, answer,
                                                         confirmation):
    async with Client(server, elicitation_callback=human(answer)) as client:
        image_id = await take_photo(client)
        result = await client.call_tool("record_inspection", record(image_id, "fail"))
    assert not result.is_error
    assert "a person should look" in result.structured_content["note"]
    [line] = log_lines(tmp_path, "inspections.jsonl")
    assert json.loads(line)["ai_verdict"] == "fail"   # what the AI proposed stays on record
    assert json.loads(line)["verdict"] == "unsure"
    assert json.loads(line)["fail_confirmation"] == confirmation
    assert f"tray-07 unsure {image_id} (AI: fail, fail confirmation: {confirmation})" \
        in log_lines(tmp_path, "audit.log")[-1]


async def test_human_is_not_asked_about_an_invalid_fail(server):
    async with Client(server, elicitation_callback=nobody()) as client:
        result = await client.call_tool("record_inspection", record("20200101-000000", "fail"))
    assert result.is_error and "no photo" in result.content[0].text


ASKING = "fail proposed, asking the person"


@pytest.mark.parametrize("mode", ["auto", "legacy"], ids=["protocol 2026-07-28", "older protocol"])
async def test_asking_the_person_is_logged_once(server, tmp_path, mode):
    # In the newer protocol, the question and its answer are two calls of the tool.
    async with Client(server, mode=mode, elicitation_callback=human("yes")) as client:
        image_id = await take_photo(client)
        await client.call_tool("record_inspection", record(image_id, "fail"))
    *_, asking, recorded = log_lines(tmp_path, "audit.log")
    assert asking.endswith(f"local record_inspection tray-07 {image_id}: {ASKING}")
    assert f"tray-07 fail {image_id}" in recorded
    assert sum(ASKING in line for line in log_lines(tmp_path, "audit.log")) == 1


@pytest.mark.parametrize("mode", ["auto", "legacy"], ids=["protocol 2026-07-28", "older protocol"])
async def test_a_fail_from_an_application_that_cannot_ask_is_recorded_as_unsure(
        server, tmp_path, mode):
    async with Client(server, mode=mode) as client:   # no way to show a question
        image_id = await take_photo(client)
        result = await client.call_tool("record_inspection", record(image_id, "fail"))
    assert not result.is_error
    assert "answer: cannot ask" in result.structured_content["note"]
    [line] = log_lines(tmp_path, "inspections.jsonl")
    assert json.loads(line)["ai_verdict"] == "fail"
    assert json.loads(line)["verdict"] == "unsure"
    assert json.loads(line)["fail_confirmation"] == "cannot ask"
    assert not any(ASKING in line for line in log_lines(tmp_path, "audit.log"))


def later(monkeypatch, seconds):
    """Moves the clock that the SDK checks the question's lifetime against."""
    class Clock:
        @staticmethod
        def time():
            return time.time() + seconds
    monkeypatch.setattr(request_state, "time", Clock)


def answering_after(seconds, monkeypatch):
    """The person who says yes, but only after the given time."""
    async def callback(context, params):
        later(monkeypatch, seconds)
        return ElicitResult(action="accept", content={"mark_failed": True})
    return callback


async def test_an_answer_within_the_hour_is_recorded(server, monkeypatch):
    async with Client(server, elicitation_callback=answering_after(ANSWER_TIME - 60,
                                                                   monkeypatch)) as client:
        image_id = await take_photo(client)
        result = await client.call_tool("record_inspection", record(image_id, "fail"))
    assert result.structured_content["verdict"] == "fail"


async def test_an_answer_after_the_hour_is_refused_but_the_question_is_logged(
        server, tmp_path, monkeypatch):
    async with Client(server, elicitation_callback=answering_after(ANSWER_TIME + 60,
                                                                   monkeypatch)) as client:
        image_id = await take_photo(client)
        with pytest.raises(MCPError, match="Invalid or expired requestState"):
            await client.call_tool("record_inspection", record(image_id, "fail"))
    assert log_lines(tmp_path, "inspections.jsonl") == []
    assert log_lines(tmp_path, "audit.log")[-1].endswith(f"tray-07 {image_id}: {ASKING}")


async def test_a_restarted_server_refuses_the_answer_but_the_question_is_logged(tmp_path):
    samples = tmp_path / "samples"
    samples.mkdir()
    draw_photo(samples / "a.jpg")
    before, after = (create_server(FakeCamera(samples), tmp_path / "data") for _ in range(2))
    async with Client(before, elicitation_callback=human("yes")) as client:
        image_id = await take_photo(client)
        # The first half of the call: the server asks, and the call ends there.
        question = await client.session.call_tool(
            "record_inspection", record(image_id, "fail"), allow_input_required=True)
    [key] = question.input_requests
    async with Client(after, elicitation_callback=human("yes")) as client:
        with pytest.raises(MCPError, match="Invalid or expired requestState"):
            await client.session.call_tool(
                "record_inspection", record(image_id, "fail"),
                input_responses={key: ElicitResult(action="accept", content={"mark_failed": True})},
                request_state=question.request_state)
    assert log_lines(tmp_path, "inspections.jsonl") == []
    assert log_lines(tmp_path, "audit.log")[-1].endswith(f"tray-07 {image_id}: {ASKING}")


# --- record_inspection: inputs are checked -----------------------------------------

async def test_one_record_per_photo(server, tmp_path):
    async with Client(server, elicitation_callback=nobody()) as client:
        image_id = await take_photo(client)
        await client.call_tool("record_inspection", record(image_id, "pass"))
        result = await client.call_tool("record_inspection", record(image_id, "unsure"))
        assert "already has an inspection record" in result.content[0].text
        # A fail is refused too, before anyone is asked to confirm it:
        result = await client.call_tool("record_inspection", record(image_id, "fail"))
    assert "already has an inspection record" in result.content[0].text
    assert result.is_error
    assert len(log_lines(tmp_path, "inspections.jsonl")) == 1
    assert log_lines(tmp_path, "audit.log")[-1].endswith(
        f"REFUSED record_inspection {image_id}: already recorded")


async def test_a_line_cut_short_in_the_records_does_not_stop_recording(server, tmp_path):
    # As after a power cut while a record was written: the last line ends half way.
    async with Client(server, elicitation_callback=nobody()) as client:
        first, second, third = [await take_photo(client) for _ in range(3)]
        await client.call_tool("record_inspection", record(first))
        log = tmp_path / "data" / "logs" / "inspections.jsonl"
        log.write_text(log.read_text()[:-40])
        result = await client.call_tool("record_inspection", record(second, part_id="tray-08"))
        assert not result.is_error
        await client.call_tool("record_inspection", record(third, part_id="tray-09"))
        again = await client.call_tool("record_inspection", record(second, part_id="tray-08"))
    assert "already has an inspection record" in again.content[0].text   # still one per photo
    _, *records = log_lines(tmp_path, "inspections.jsonl")
    assert [json.loads(line)["part_id"] for line in records] == ["tray-08", "tray-09"]
    warnings = [line for line in log_lines(tmp_path, "audit.log") if "WARNING" in line]
    assert len(warnings) == 1   # once, not at every record
    assert warnings[0].endswith("WARNING inspections.jsonl: line 1 cannot be read, "
                                "so it is skipped when looking for earlier records")


@pytest.mark.parametrize("change, refusal", [
    ({"image_id": "../../etc/passwd"}, "String should match pattern"),
    ({"part_id": "tray 07; rm -rf"}, "String should match pattern"),
    ({"part_id": "x" * 41}, "String should match pattern"),
    ({"verdict": "scrap"}, "Input should be 'pass', 'fail' or 'unsure'"),
    ({"findings": ""}, "String should have at least 1 character"),
    ({"findings": "x" * 501}, "String should have at most 500 characters"),
], ids=["photo ID that is a path", "part ID with spaces", "part ID too long", "unknown verdict",
        "no findings", "findings too long"])
async def test_bad_inputs_are_refused(server, tmp_path, change, refusal):
    async with Client(server, elicitation_callback=nobody()) as client:
        image_id = await take_photo(client)
        result = await client.call_tool("record_inspection", record(image_id) | change)
    [name] = change
    assert f"{name}\n  {refusal}" in result.content[0].text   # refused for its shape
    assert result.is_error
    assert log_lines(tmp_path, "inspections.jsonl") == []
