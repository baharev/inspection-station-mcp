"""Tests for the server over HTTP, with a secret key and with logins: in-process, no
network, no hardware, no login server.

    pytest -q

The HTTP app runs inside the test through an ASGI transport, so no port is opened. The
login server is replaced by a key pair made here: the tests sign their own tokens.
"""

import socket
import ssl
import time
from contextlib import asynccontextmanager
from urllib.error import URLError

import httpx2
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from PIL import Image

from inspection_camera.camera import FakeCamera
from inspection_camera.server import create_server, key_auth, oauth_auth

pytestmark = pytest.mark.anyio

KEY = "k" * 32
URL = "http://127.0.0.1:8000/mcp"   # the port is never opened


@pytest.fixture
def anyio_backend():
    return "asyncio"


ISSUER = "http://localhost:8080/realms/inspection"
LOGIN_SERVER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def make_app(tmp_path, auth):
    samples = tmp_path / "samples"
    samples.mkdir()
    Image.new("RGB", (640, 480), (220, 30, 30)).save(samples / "a.jpg")
    return create_server(FakeCamera(samples), tmp_path / "data", **auth).streamable_http_app()


@pytest.fixture
def app(tmp_path):
    return make_app(tmp_path, key_auth(KEY))


@pytest.fixture
def login_app(tmp_path):
    public_key = LOGIN_SERVER_KEY.public_key()
    return make_app(tmp_path, oauth_auth(ISSUER, URL, signing_key=lambda token: public_key))


def token(user="inspector", roles=("viewer", "inspector"), key=LOGIN_SERVER_KEY, **changes):
    """An access token as the login server would issue it, with any claim changed."""
    claims = {"iss": ISSUER, "aud": URL, "sub": f"id-of-{user}", "preferred_username": user,
              "roles": list(roles), "azp": "claude-code", "exp": int(time.time()) + 300}
    claims.update(changes)
    return {"Authorization": "Bearer " + jwt.encode(claims, key, algorithm="RS256")}


def audit_lines(tmp_path):
    return (tmp_path / "data" / "logs" / "audit.log").read_text().splitlines()


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


# --- logins (OAuth) -------------------------------------------------------------------

async def test_the_server_tells_clients_which_login_server_to_use(login_app):
    async with http(login_app) as client:
        refused = await client.post(URL, json={})
        metadata = await client.get("http://127.0.0.1:8000/.well-known/oauth-protected-resource/mcp")
    assert refused.status_code == 401
    assert "oauth-protected-resource/mcp" in refused.headers["www-authenticate"]
    assert metadata.json()["authorization_servers"] == [ISSUER]
    assert metadata.json()["resource"] == URL


@pytest.mark.parametrize("bad", [
    {"aud": "http://localhost:9000/mcp"},          # issued for another server
    {"iss": "http://localhost:8080/realms/other"},  # from another login server
    {"exp": int(time.time()) - 10},               # expired
    {"key": OTHER_KEY},                           # not signed by the login server
])
async def test_tokens_that_do_not_fit_are_refused(login_app, bad):
    async with http(login_app, token(**bad)) as client:
        response = await client.post(URL, json={})
    assert response.status_code == 401


async def test_an_inspector_records_under_their_name(login_app, tmp_path):
    async with http(login_app, token("inspector")) as client:
        async with Client(streamable_http_client(URL, http_client=client)) as mcp:
            photo = await mcp.call_tool("capture_image", {})
            image_id = photo.content[0].text.split()[1]
            result = await mcp.call_tool("record_inspection", {
                "image_id": image_id, "part_id": "tray-07", "verdict": "pass",
                "findings": "All tools present."})
    assert not result.is_error
    assert result.structured_content["recorded_by"] == "inspector"
    assert all(line.split()[1] == "inspector" for line in audit_lines(tmp_path))


async def test_a_viewer_may_look_but_not_record(login_app, tmp_path):
    async def nobody(context, params):
        pytest.fail("The viewer was asked to confirm a fail they may not record.")

    async with http(login_app, token("viewer", roles=["viewer"])) as client:
        async with Client(streamable_http_client(URL, http_client=client),
                          elicitation_callback=nobody) as mcp:
            photo = await mcp.call_tool("capture_image", {})
            image_id = photo.content[0].text.split()[1]
            for verdict in ("pass", "fail"):
                result = await mcp.call_tool("record_inspection", {
                    "image_id": image_id, "part_id": "tray-07", "verdict": verdict,
                    "findings": "Hammer missing."})
                assert result.is_error
                assert "needs the role 'inspector'" in result.content[0].text
    assert not photo.is_error
    assert "viewer REFUSED record_inspection: needs the role inspector" in audit_lines(tmp_path)[-1]


async def test_a_login_without_roles_may_do_nothing(login_app):
    async with http(login_app, token("guest", roles=[])) as client:
        async with Client(streamable_http_client(URL, http_client=client)) as mcp:
            result = await mcp.call_tool("capture_image", {})
    assert result.is_error
    assert "needs the role 'viewer'" in result.content[0].text


def test_an_unreachable_login_server_stops_the_start_with_a_message():
    with socket.socket() as s:   # a port that was free a moment ago: nothing listens there
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    with pytest.raises(SystemExit) as stop:
        oauth_auth(f"http://127.0.0.1:{port}/realms/inspection", URL)
    assert "Is the login server running" in str(stop.value.code)


def test_an_untrusted_login_server_certificate_is_named_in_the_message(monkeypatch):
    def untrusted(url, timeout):
        raise URLError(ssl.SSLCertVerificationError("certificate verify failed"))
    monkeypatch.setattr("inspection_camera.server.urlopen", untrusted)
    with pytest.raises(SystemExit) as stop:
        oauth_auth("https://localhost:8443/realms/inspection", URL)
    assert "Set SSL_CERT_FILE" in str(stop.value.code)
