"""Tests for the server over HTTP with a secret key: in-process, no network, no hardware.

    pytest -q

The HTTP app runs inside the test through an ASGI transport, so no port is opened.
"""

from contextlib import asynccontextmanager

import httpx2
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from PIL import Image

from inspection_camera.camera import FakeCamera
from inspection_camera.server import create_server, key_auth

pytestmark = pytest.mark.anyio

KEY = "k" * 32
URL = "http://127.0.0.1:8000/mcp"   # the port is never opened


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def app(tmp_path):
    samples = tmp_path / "samples"
    samples.mkdir()
    Image.new("RGB", (640, 480), (220, 30, 30)).save(samples / "a.jpg")
    return create_server(FakeCamera(samples), tmp_path / "data", **key_auth(KEY)).streamable_http_app()


@asynccontextmanager
async def http(app, headers=None):
    """An HTTP client talking to the app in-process, with the app's startup and shutdown."""
    async with app.router.lifespan_context(app):
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app),
                                      headers=headers) as client:
            yield client


@pytest.mark.parametrize("headers", [None, {"Authorization": "Bearer wrong"},
                                     {"Authorization": KEY}])   # no "Bearer"
async def test_requests_without_the_key_are_refused(app, headers):
    async with http(app, headers) as client:
        response = await client.post(URL, json={})
    assert response.status_code == 401


async def test_with_the_key_the_tools_work(app):
    async with http(app, {"Authorization": f"Bearer {KEY}"}) as client:
        async with Client(streamable_http_client(URL, http_client=client)) as mcp:
            result = await mcp.call_tool("capture_image", {})
    assert not result.is_error
    assert result.content[0].text.startswith("Photo ")
