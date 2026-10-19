"""The stand-in server against the real one: the app's other tests run against the
stand-in, so it must offer what the real inspection server offers, as far as the app
depends on it (the MCP part of the list in CLAUDE.md).

Skipped unless the real server (folder server) is installed in the same environment: the
app never imports it, and its other tests never need it.
"""

import pytest
from mcp import Client
from mcp.types import ElicitResult
from PIL import Image

import stand_in_server
from inspection_client.station import SERVER_KEY_FILE
from stand_in_server import stand_in_server as make_stand_in

real = pytest.importorskip("inspection_server.server",
                           reason="the inspection server is not installed here")
cameras = pytest.importorskip("inspection_server.camera")

pytestmark = pytest.mark.anyio


@pytest.fixture
def servers(tmp_path):
    """The real server, with the fake camera serving one photo, and the stand-in."""
    (tmp_path / "photos").mkdir()
    Image.new("RGB", (640, 480)).save(tmp_path / "photos" / "part.jpg")
    return {"real": real.create_server(cameras.FakeCamera(tmp_path / "photos"), tmp_path),
            "stand-in": make_stand_in()[0]}


def fields(schema: dict | None) -> tuple[dict, set]:
    """A schema's fields with their JSON types, and the required ones: what the app relies
    on. Descriptions and limits (patterns, ranges) are the real server's own business."""
    schema = schema or {}
    return ({name: field.get("type") for name, field in schema.get("properties", {}).items()},
            set(schema.get("required", [])))


async def test_the_stand_in_has_the_real_tools_with_their_arguments_and_results(servers):
    tools = {}
    for name, server in servers.items():
        async with Client(server) as client:
            tools[name] = {tool.name: tool for tool in (await client.list_tools()).tools}
    assert set(tools["stand-in"]) == set(tools["real"])
    for name, tool in tools["stand-in"].items():
        real_tool = tools["real"][name]
        assert fields(tool.input_schema) == fields(real_tool.input_schema), name
        # The real results may hold more fields than the stand-in's; never fewer or others.
        offered, required = fields(tool.output_schema)
        real_offered, real_required = fields(real_tool.output_schema)
        assert offered.items() <= real_offered.items(), name
        assert required <= real_required, name


async def test_a_photo_and_a_refusal_say_what_claude_and_the_window_expect(servers):
    assert stand_in_server.MIN_ZOOM == real.MIN_ZOOM
    for name, server in servers.items():
        async with Client(server) as client:
            photo = await client.call_tool("capture_image", {})
            assert photo.structured_content is not None
            image_id = photo.structured_content["image_id"]
            assert photo.content[0].text.startswith(f"Photo {image_id} "), name
            result = await client.call_tool("zoom_image", {
                "image_id": image_id, "left": 0, "top": 0, "width": real.MIN_ZOOM / 2,
                "height": 0.5})
        assert result.is_error, name
        assert result.content[0].text.startswith("Error executing tool zoom_image: "), name


async def test_the_fail_question_has_the_one_yes_or_no_field(servers):
    asked = {}
    for name, server in servers.items():
        async def answer(context, params, name=name):
            asked[name] = fields(params.requested_schema)
            return ElicitResult(action="decline")

        async with Client(server, elicitation_callback=answer) as client:
            photo = await client.call_tool("capture_image", {})
            assert photo.structured_content is not None
            await client.call_tool("record_inspection", {
                "image_id": photo.structured_content["image_id"], "part_id": "tray-07",
                "verdict": "fail", "findings": "The hammer is missing."})
    assert asked["real"] == asked["stand-in"] == ({"mark_failed": "boolean"}, set())


def test_the_app_reads_the_key_file_the_server_makes():
    assert SERVER_KEY_FILE == real.KEY_FILE
