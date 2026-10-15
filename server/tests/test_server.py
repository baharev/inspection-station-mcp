"""Tests for the inspection server: in-process, against a fake camera, no hardware.

    pytest -q

The test photos are drawn by the code below (left half red, right half blue), so they
contain nothing private and the zoom can be checked by color.
"""

import base64
import io
import json

import pytest
from mcp import Client
from mcp.types import ElicitResult
from PIL import Image

from inspection_camera.camera import FakeCamera
from inspection_camera.server import create_server

pytestmark = pytest.mark.anyio

RED, BLUE = (220, 30, 30), (30, 30, 220)


@pytest.fixture
def anyio_backend():
    return "asyncio"


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

    "yes" or "no": they answer it; "decline": they refuse to answer; "cancel": they close
    the dialog.
    """
    asked = []

    async def callback(context, params):
        asked.append(params.message)
        if answer in ("yes", "no"):
            return ElicitResult(action="accept", content={"record": answer == "yes"})
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
    return result.content[0].text.split()[1]   # "Photo <id> (...)"


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


# --- capture_image -----------------------------------------------------------------

async def test_capture_returns_a_capped_photo_and_saves_it(server, tmp_path):
    async with Client(server) as client:
        result = await client.call_tool("capture_image", {})
    assert not result.is_error
    image_id = result.content[0].text.split()[1]
    assert decode(result).size == (1280, 720)          # 1600x900 capped, shape kept
    assert (tmp_path / "data" / "captures" / f"{image_id}.jpg").exists()
    assert f"capture_image {image_id} 1280x720" in log_lines(tmp_path, "audit.log")[0]


async def test_fake_camera_serves_the_photos_in_turn(server):
    async with Client(server) as client:
        sizes = [decode(await client.call_tool("capture_image", {})).size for _ in range(3)]
    assert sizes == [(1280, 720), (640, 480), (1280, 720)]


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


@pytest.mark.parametrize("box, reason", [
    ({"left": 0.5, "top": 0.5, "width": 0.05, "height": 0.2}, "too small"),
    ({"left": 0.8, "top": 0.0, "width": 0.4, "height": 0.4}, "outside the photo"),
])
async def test_zoom_refuses_bad_rectangles(server, box, reason):
    async with Client(server) as client:
        image_id = await take_photo(client)
        result = await client.call_tool("zoom_image", {"image_id": image_id, **box})
    assert result.is_error and reason in result.content[0].text


async def test_zoom_refuses_numbers_outside_0_to_1(server):
    async with Client(server) as client:
        image_id = await take_photo(client)
        result = await client.call_tool("zoom_image", {
            "image_id": image_id, "left": -0.5, "top": 0, "width": 0.5, "height": 0.5})
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
    assert json.loads(line) | {"time": None} == {
        "time": None, "image_id": image_id, "part_id": "tray-07", "verdict": "pass",
        "findings": "All three tools present.", "confirmed_by_human": False,
        "recorded_by": "local"}


async def test_unsure_is_recorded_and_says_a_person_should_look(server):
    async with Client(server, elicitation_callback=nobody()) as client:
        image_id = await take_photo(client)
        result = await client.call_tool("record_inspection", record(image_id, "unsure"))
    assert not result.is_error
    assert "a person should look" in result.structured_content["note"]


# --- record_inspection: a fail needs a human's yes ---------------------------------

async def test_fail_is_recorded_when_the_human_says_yes(server, tmp_path):
    operator = human("yes")
    async with Client(server, elicitation_callback=operator) as client:
        image_id = await take_photo(client)
        result = await client.call_tool(
            "record_inspection", record(image_id, "fail", findings="Pack torn at the top."))
    assert not result.is_error
    assert result.structured_content["confirmed_by_human"] is True
    assert "tray-07 as FAILED" in operator.asked[0] and "torn" in operator.asked[0]
    assert len(log_lines(tmp_path, "inspections.jsonl")) == 1
    assert "(confirmed by human)" in log_lines(tmp_path, "audit.log")[-1]


@pytest.mark.parametrize("answer, how", [
    ("no", "said no"), ("decline", "decline"), ("cancel", "cancel"),
], ids=["says no", "refuses to answer", "closes the dialog"])
async def test_fail_is_not_recorded_without_a_yes(server, tmp_path, answer, how):
    async with Client(server, elicitation_callback=human(answer)) as client:
        image_id = await take_photo(client)
        result = await client.call_tool("record_inspection", record(image_id, "fail"))
    assert result.is_error
    assert log_lines(tmp_path, "inspections.jsonl") == []
    assert f"fail not confirmed ({how}) tray-07" in log_lines(tmp_path, "audit.log")[-1]


async def test_human_is_not_asked_about_an_invalid_fail(server):
    async with Client(server, elicitation_callback=nobody()) as client:
        result = await client.call_tool("record_inspection", record("20200101-000000", "fail"))
    assert result.is_error and "no photo" in result.content[0].text


# --- record_inspection: inputs are checked -----------------------------------------

async def test_one_record_per_photo(server, tmp_path):
    async with Client(server, elicitation_callback=nobody()) as client:
        image_id = await take_photo(client)
        await client.call_tool("record_inspection", record(image_id, "pass"))
        result = await client.call_tool("record_inspection", record(image_id, "fail"))
    assert result.is_error and "already has an inspection record" in result.content[0].text
    assert len(log_lines(tmp_path, "inspections.jsonl")) == 1


@pytest.mark.parametrize("change", [
    {"image_id": "../../etc/passwd"},
    {"part_id": "tray 07; rm -rf"},
    {"part_id": "x" * 41},
    {"verdict": "scrap"},
    {"findings": ""},
    {"findings": "x" * 501},
])
async def test_bad_inputs_are_refused(server, tmp_path, change):
    async with Client(server, elicitation_callback=nobody()) as client:
        image_id = await take_photo(client)
        result = await client.call_tool("record_inspection", record(image_id) | change)
    assert result.is_error
    assert log_lines(tmp_path, "inspections.jsonl") == []
