"""Tests for the server over HTTP, with a secret key and with logins, and for the live
view: in-process, no network, no hardware, no login server.

    pytest -q

The HTTP app runs inside the test through an ASGI transport, so no port is opened. The
login server is replaced by a key pair made here: the tests sign their own tokens.
"""

import base64
import hashlib
import hmac
import io
import json
import socket
import ssl
import sys
import time
from contextlib import asynccontextmanager
from urllib.error import URLError

import httpx2
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from PIL import Image

from inspection_server.camera import FakeCamera
from inspection_server.server import create_server, http_app, key_auth, oauth_auth, secret_key

pytestmark = pytest.mark.anyio

KEY = "k" * 32
URL = "http://127.0.0.1:8000/mcp"   # the port is never opened
THIS_COMPUTER = ("127.0.0.1", 50000)   # where a request comes from
ELSEWHERE = ("192.0.2.5", 50000)
LIVE = "http://192.0.2.2:8000/live/frame.jpg"   # as other computers address the server


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
    return http_app(create_server(FakeCamera(samples), tmp_path / "data", **auth), tmp_path / "data")


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
              "roles": roles if isinstance(roles, str) else list(roles), "azp": "claude-code",
              "exp": int(time.time()) + 300}
    claims.update(changes)
    return {"Authorization": "Bearer " + jwt.encode(claims, key, algorithm="RS256")}


def audit_lines(tmp_path):
    return (tmp_path / "data" / "logs" / "audit.log").read_text().splitlines()


@asynccontextmanager
async def http(app, headers=None, client=THIS_COMPUTER):
    """An HTTP client talking to the app in-process, with the app's startup and shutdown."""
    async with app.router.lifespan_context(app):
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app, client=client),
                                      headers=headers) as http_client:
            yield http_client


@pytest.mark.parametrize("headers", [None, {"Authorization": "Bearer wrong"},
                                     {"Authorization": KEY}])   # no "Bearer"
async def test_requests_without_the_key_are_refused(app, headers, tmp_path):
    async with http(app, headers, client=ELSEWHERE) as client:
        response = await client.post(URL, json={})
    assert response.status_code == 401
    # Refused before any tool runs, and still in the audit log:
    reason = "no key or login token sent" if headers is None else "key or login token not accepted"
    assert [line.split(" ", 1)[1] for line in audit_lines(tmp_path)] == [
        f"unknown REFUSED /mcp from 192.0.2.5: {reason}"]


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
    assert result.structured_content["user"] == "inspector"
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


async def test_roles_sent_as_text_count_for_nothing(login_app):
    # As a list only: in the text, "viewer" would be found inside "trainee-viewer".
    async with http(login_app, token("trainee", roles="trainee-viewer-inspector")) as client:
        async with Client(streamable_http_client(URL, http_client=client)) as mcp:
            result = await mcp.call_tool("capture_image", {})
        live = await client.get("http://localhost:8000/live/frame.jpg")
    assert result.is_error and "needs the role 'viewer'" in result.content[0].text
    assert live.status_code == 403


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


def test_a_login_server_on_another_computer_needs_https():
    # Its keys decide which tokens are genuine: over plain HTTP they could be replaced.
    with pytest.raises(SystemExit) as stop:
        oauth_auth("http://192.0.2.7:8080/realms/inspection", URL)
    assert "must be reached over HTTPS" in str(stop.value.code)


def login_server_settings(monkeypatch, **settings):
    """The login server's published settings, as the server reads them at its start."""
    published = {"issuer": ISSUER, "jwks_uri": ISSUER + "/protocol/openid-connect/certs"}
    published.update(settings)
    monkeypatch.setattr("inspection_server.server.urlopen",
                        lambda url, timeout: io.BytesIO(json.dumps(published).encode()))


def test_the_login_server_must_call_itself_by_the_address_set(monkeypatch):
    login_server_settings(monkeypatch, issuer="http://localhost:8080/realms/other")
    with pytest.raises(SystemExit) as stop:
        oauth_auth(ISSUER, URL)
    assert "calls itself http://localhost:8080/realms/other" in str(stop.value.code)


def test_the_login_servers_keys_from_another_computer_need_https(monkeypatch):
    login_server_settings(monkeypatch, jwks_uri="http://192.0.2.7/certs")
    with pytest.raises(SystemExit) as stop:
        oauth_auth(ISSUER, URL)
    assert "publishes its keys at http://192.0.2.7/certs" in str(stop.value.code)


def test_a_login_server_that_fits_is_used(monkeypatch):
    login_server_settings(monkeypatch)
    assert oauth_auth(ISSUER + "/", URL)["token_verifier"].issuer == ISSUER


def test_an_untrusted_login_server_certificate_is_named_in_the_message(monkeypatch):
    def untrusted(url, timeout):
        raise URLError(ssl.SSLCertVerificationError("certificate verify failed"))
    monkeypatch.setattr("inspection_server.server.urlopen", untrusted)
    with pytest.raises(SystemExit) as stop:
        oauth_auth("https://localhost:8443/realms/inspection", URL)
    assert "Set SSL_CERT_FILE" in str(stop.value.code)


# --- forged and tampered tokens -------------------------------------------------------
# Through the server's own way of finding the login server's key: its published key list,
# looked up by the key's name (kid) in the token. Only the network is replaced.

KID = "login-server-key"
KEYS_URL = ISSUER + "/protocol/openid-connect/certs"
ATTACKER_KEYS = "https://attacker.example/certs"


def b64(data) -> str:
    data = data if isinstance(data, bytes) else json.dumps(data).encode()
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def published_key(key, kid=KID) -> dict:
    return json.loads(RSAAlgorithm.to_jwk(key.public_key())) | {"kid": kid, "use": "sig",
                                                                "alg": "RS256"}


def claims(**changes) -> dict:
    """What the login server would say about an inspector, with claims changed (None: left out)."""
    fair = {"iss": ISSUER, "aud": URL, "sub": "id-of-mallory", "preferred_username": "mallory",
            "roles": ["viewer", "inspector"], "exp": int(time.time()) + 300}
    return {name: value for name, value in (fair | changes).items() if value is not None}


def signed(the_claims=None, key=LOGIN_SERVER_KEY, algorithm="RS256", **header) -> str:
    header = {"kid": KID} | header
    return jwt.encode(the_claims or claims(), key, algorithm=algorithm,
                      headers={name: value for name, value in header.items() if value is not None})


def unsigned(header, the_claims, signature=b"") -> str:
    return f"{b64(header)}.{b64(the_claims)}.{b64(signature) if signature else ''}"


def hmac_signed(secret: bytes) -> str:
    """Signed as if the login server's public key were a shared password (key confusion)."""
    content = f"{b64({'alg': 'HS256', 'kid': KID})}.{b64(claims())}"
    return f"{content}.{b64(hmac.new(secret, content.encode(), hashlib.sha256).digest())}"


def edited(token: str, the_claims) -> str:
    header, _, signature = token.split(".")
    return f"{header}.{b64(the_claims)}.{signature}"


PUBLIC_PEM = LOGIN_SERVER_KEY.public_key().public_bytes(
    serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)

FORGED = {
    "no signature, algorithm none": unsigned({"alg": "none", "kid": KID}, claims()),
    "no signature, algorithm None": unsigned({"alg": "None", "kid": KID}, claims()),
    "algorithm NONE with a signature": unsigned({"alg": "NONE", "kid": KID}, claims(), b"x"),
    "public key as an HMAC password": hmac_signed(PUBLIC_PEM),
    "public key's modulus as an HMAC password": hmac_signed(
        published_key(LOGIN_SERVER_KEY)["n"].encode()),
    "attacker's key under its own name": signed(key=OTHER_KEY, kid="attacker"),
    "attacker's key under the login server's key name": signed(key=OTHER_KEY),
    "attacker's key inside the token": signed(key=OTHER_KEY, jwk=published_key(OTHER_KEY)),
    "attacker's key list named in the token (jku)": signed(key=OTHER_KEY, jku=ATTACKER_KEYS),
    "attacker's key list named in the token (x5u)": signed(key=OTHER_KEY, x5u=ATTACKER_KEYS),
    "attacker's own login server": signed(claims(iss="https://attacker.example/realms/x"),
                                          key=OTHER_KEY, kid="attacker"),
    "another issuer": signed(claims(iss="http://localhost:8080/realms/other")),
    "the issuer with a slash added": signed(claims(iss=ISSUER + "/")),
    "issued for another server": signed(claims(aud="http://localhost:9000/mcp")),
    "issued for no server": signed(claims(aud=None)),
    "expired": signed(claims(exp=int(time.time()) - 10)),
    "no expiry": signed(claims(exp=None)),
    "no user": signed(claims(sub=None)),
    "not valid yet": signed(claims(nbf=int(time.time()) + 600)),
    "issued in the future": signed(claims(iat=int(time.time()) + 600)),
    "another algorithm, RS512": signed(algorithm="RS512"),
    "another algorithm, PS256": signed(algorithm="PS256"),
    "no key name": signed(kid=None),
    "signature removed": signed().rsplit(".", 1)[0] + ".",
    "claims edited after signing": edited(signed(claims(roles=["viewer"])), claims()),
    "not a token": "not.a.token",
}


@pytest.fixture
def published_login_app(tmp_path, monkeypatch):
    """The server with logins, finding the login server's keys as it does in use.

    Returns the app and the addresses it fetched keys from.
    """
    fetched = []

    class Network:   # stands in for the connection to the login server
        def open(self, request, timeout):
            fetched.append(request.full_url)
            return io.BytesIO(json.dumps({"keys": [published_key(LOGIN_SERVER_KEY)]}).encode())

    login_server_settings(monkeypatch, jwks_uri=KEYS_URL)
    monkeypatch.setattr("jwt.jwks_client.urllib.request.build_opener", lambda *handlers: Network())
    return make_app(tmp_path, oauth_auth(ISSUER, URL)), fetched


@pytest.mark.parametrize("forged", FORGED.values(), ids=FORGED.keys())
async def test_forged_and_tampered_tokens_are_refused(published_login_app, forged, tmp_path):
    app, fetched = published_login_app
    headers = {"Authorization": f"Bearer {forged}"}
    async with http(app, headers, client=ELSEWHERE) as client:
        response = await client.post(URL, json={})
        live = await client.get(LIVE, headers=headers)
    assert response.status_code == 401 and live.status_code == 401
    assert set(fetched) <= {KEYS_URL}   # never the attacker's keys
    assert [line.split(" ", 1)[1] for line in audit_lines(tmp_path)] == [
        f"unknown REFUSED {path} from 192.0.2.5: key or login token not accepted"
        for path in ("/mcp", "/live/frame.jpg")]


@pytest.mark.parametrize("fair", [signed(), signed(claims(aud=["account", URL]))],
                         ids=["for this server", "for several servers, this one among them"])
async def test_a_token_from_the_login_server_is_accepted(published_login_app, fair):
    app, fetched = published_login_app
    async with http(app, {"Authorization": f"Bearer {fair}"}, client=ELSEWHERE) as client:
        live = await client.get(LIVE)
    assert live.status_code == 200
    assert fetched == [KEYS_URL]


# --- the live view --------------------------------------------------------------------


async def test_the_live_page_is_served_to_anyone(app):
    async with http(app, client=ELSEWHERE) as client:
        response = await client.get("http://192.0.2.2:8000/live")
    assert response.status_code == 200
    assert "/live/frame.jpg" in response.text   # the page fetches the frames, with the key


async def test_this_computer_sees_the_live_view_without_a_key(app, tmp_path):
    async with http(app) as client:
        for name in ("localhost", "127.0.0.1", "[::1]"):
            response = await client.get(f"http://{name}:8000/live/frame.jpg")
            assert response.status_code == 200
            assert response.headers["content-type"] == "image/jpeg"
    assert Image.open(io.BytesIO(response.content)).size == (640, 480)
    # Logged once, not for every frame:
    assert [line.split(" ", 1)[1] for line in audit_lines(tmp_path)] == ["local live view opened"]


async def test_a_refused_token_is_refused_on_this_computer_too(login_app, tmp_path):
    # An app here that sends a token is that login, not the person at this computer: an
    # expired token must not turn it into "local".
    async with http(login_app) as client:
        response = await client.get("http://localhost:8000/live/frame.jpg",
                                    headers=token("viewer", exp=int(time.time()) - 10))
    assert response.status_code == 401
    assert [line.split(" ", 1)[1] for line in audit_lines(tmp_path)] == [
        "unknown REFUSED /live/frame.jpg from 127.0.0.1: key or login token not accepted"]


@pytest.mark.parametrize("headers", [None, {"Authorization": "Bearer wrong"}])
async def test_other_computers_need_the_key_for_the_live_view(app, headers):
    async with http(app, headers, client=ELSEWHERE) as client:
        response = await client.get(LIVE)
    assert response.status_code == 401


async def test_other_computers_see_the_live_view_with_the_key(app, tmp_path):
    async with http(app, {"Authorization": f"Bearer {KEY}"}, client=ELSEWHERE) as client:
        response = await client.get(LIVE)
    assert response.status_code == 200
    assert "api-key live view opened" in audit_lines(tmp_path)[0]


async def test_a_web_page_cannot_reach_the_live_view_under_its_own_name(app):
    # DNS rebinding: a web site points its own name at this computer, and the browser
    # here calls the server under that name. The server sees the name and refuses.
    async with http(app) as client:
        response = await client.get("http://camera-thief.example:8000/live/frame.jpg")
    assert response.status_code == 401


async def test_a_login_needs_the_viewer_role_for_the_live_view(login_app, tmp_path):
    async with http(login_app, client=ELSEWHERE) as client:
        viewer = await client.get(LIVE, headers=token("viewer", roles=["viewer"]))
        guest = await client.get(LIVE, headers=token("guest", roles=[]))
    assert viewer.status_code == 200
    assert guest.status_code == 403 and "needs the role 'viewer'" in guest.text
    assert "guest REFUSED live view: needs the role viewer" in audit_lines(tmp_path)[-1]


async def test_a_camera_failure_is_shown_on_the_live_page(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    app = http_app(create_server(FakeCamera(empty), tmp_path / "data", **key_auth(KEY)),
                   tmp_path / "data")
    async with http(app) as client:
        response = await client.get("http://localhost:8000/live/frame.jpg")
    assert response.status_code == 503 and "no photos" in response.text


# --- the secret key -------------------------------------------------------------------

def test_the_first_start_makes_the_key_file_and_later_starts_reuse_it(tmp_path, monkeypatch):
    monkeypatch.delenv("API_KEY", raising=False)
    path = tmp_path / "config" / "api-key"
    key = secret_key(path)
    assert len(key) >= 32 and path.read_text().strip() == key
    if sys.platform != "win32":
        assert path.stat().st_mode & 0o777 == 0o600   # readable by this user only
    assert secret_key(path) == key


def test_a_key_file_written_by_hand_is_read_without_its_line_end(tmp_path, monkeypatch):
    monkeypatch.delenv("API_KEY", raising=False)
    path = tmp_path / "api-key"
    path.write_text("x" * 43 + "\n")
    assert secret_key(path) == "x" * 43


def test_api_key_wins_over_the_key_file(tmp_path, monkeypatch):
    monkeypatch.setenv("API_KEY", "y" * 40)
    path = tmp_path / "api-key"
    assert secret_key(path) == "y" * 40
    assert not path.exists()


def test_a_short_key_stops_the_start(tmp_path, monkeypatch):
    monkeypatch.setenv("API_KEY", "short")
    with pytest.raises(SystemExit) as stop:
        secret_key(tmp_path / "api-key")
    assert "shorter than 32 characters" in str(stop.value.code)
