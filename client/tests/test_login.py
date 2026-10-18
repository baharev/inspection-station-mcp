"""The app's part of the login: the browser is sent to the login page and comes back.

The login server and the browser are played by the test; the rest of the login (finding
the login server, the token, renewing it) is the MCP SDK's, tested there, and was tried
by hand with the demo login server of the camera server's repository.
"""

import time
from urllib.parse import parse_qs, urlsplit

import httpx2
import pytest

from inspection_client import login as login_module
from inspection_client.login import CALLBACK, RENEW_EARLY, BrowserLogin, LoginFailed
from inspection_client.station import CameraServerRefused, describe

pytestmark = pytest.mark.anyio

LOGIN_PAGE = ("http://login.example/auth?response_type=code&client_id=inspection-client"
              "&state=s1&scope=openid+offline_access&prompt=consent")


@pytest.fixture
def anyio_backend():
    return "asyncio"


def browser(comes_back_with: str, opened: list):
    """Opens the login page, and returns to the app with the login server's answer."""
    def open_page(url):
        opened.append(url)
        httpx2.get(f"{CALLBACK}?{comes_back_with}")
    return open_page


def login_with(answer: str, opened: list, told: list) -> BrowserLogin:
    login = BrowserLogin("http://station:8000/mcp", told.append, browser(answer, opened))
    login.auth.context.auth_server_url = "http://login.example/"   # as the camera server names it
    return login


async def test_the_browser_brings_back_the_answer():
    opened, told = [], []
    login = login_with("code=c1&state=s1&iss=http%3A%2F%2Flogin.example%2F", opened, told)
    await login.open_login_page(LOGIN_PAGE)
    answer = await login.wait_for_login()
    assert (answer.code, answer.state, answer.iss) == ("c1", "s1", "http://login.example/")

    # no scopes asked for, and the login form every time
    asked = parse_qs(urlsplit(opened[0]).query)
    assert "scope" not in asked and asked["prompt"] == ["login"]
    assert asked["client_id"] == ["inspection-client"]
    assert told == ["Log in in the browser window that opened."]


async def test_a_refused_login_is_told_in_words():
    opened, told = [], []
    login = login_with("error=access_denied&error_description=Not+allowed&state=s1", opened, told)
    await login.open_login_page(LOGIN_PAGE)
    with pytest.raises(LoginFailed) as failed:
        await login.wait_for_login()
    assert describe(failed.value) == "Not logged in: the login server said: Not allowed"
    assert not login.logged_in


async def test_no_login_page_when_the_camera_server_names_no_login_server():
    opened = []
    login = BrowserLogin("http://station:8000/mcp", print, browser("code=c1", opened))
    with pytest.raises(LoginFailed, match="without --login"):
        await login.open_login_page(LOGIN_PAGE)
    assert opened == []


def test_refusals_say_what_to_do():
    assert "--login" in describe(CameraServerRefused(401, "wants a login"))
    assert "SERVER_URL" in describe(CameraServerRefused(401, "login"))
    assert "refused the key" in describe(CameraServerRefused(401, "key"))


async def test_the_address_must_be_the_one_the_camera_server_publishes():
    login = BrowserLogin("http://127.0.0.1:8000/mcp")
    await login.same_address("http://127.0.0.1:8000/mcp", "http://127.0.0.1:8000/mcp")
    with pytest.raises(LoginFailed, match="--server http://localhost:8000/mcp"):
        await login.same_address("http://127.0.0.1:8000/mcp", "http://localhost:8000/mcp")


def servers(request: httpx2.Request) -> httpx2.Response:
    """The camera server, which wants a login, and its login server."""
    match request.url.path:
        case "/mcp" if "Authorization" in request.headers:
            return httpx2.Response(200)
        case "/mcp":
            return httpx2.Response(401, headers={"WWW-Authenticate": 'Bearer resource_metadata='
                                   '"http://station:8000/.well-known/oauth-protected-resource/mcp"'})
        case "/.well-known/oauth-protected-resource/mcp":
            return httpx2.Response(200, json={"resource": "http://station:8000/mcp",
                                              "authorization_servers": ["http://login.example/"]})
        case "/.well-known/oauth-authorization-server":
            return httpx2.Response(200, json={
                "issuer": "http://login.example/", "response_types_supported": ["code"],
                "authorization_endpoint": "http://login.example/auth",
                "token_endpoint": "http://login.example/token",
                "code_challenge_methods_supported": ["S256"]})
        case "/token":
            return httpx2.Response(200, json={"access_token": "t1", "token_type": "Bearer",
                                              "expires_in": 300, "refresh_token": "r1"})
    return httpx2.Response(404)


async def test_a_login_left_unfinished_stops_without_a_traceback(monkeypatch, caplog):
    monkeypatch.setattr(login_module, "WAIT", 0.2)
    opened = []
    login = BrowserLogin("http://station:8000/mcp", print, opened.append)  # nobody logs in
    async with httpx2.AsyncClient(auth=login.auth,
                                  transport=httpx2.MockTransport(servers)) as http:
        with pytest.raises(LoginFailed) as failed:
            await http.post("http://station:8000/mcp")
    assert len(opened) == 1
    assert describe(failed.value).startswith("Not logged in: no login within")
    assert caplog.records == []   # the window says it; nothing more in the terminal


async def test_the_token_is_renewed_before_the_camera_server_would_refuse_it():
    def logs_in(url):
        state = parse_qs(urlsplit(url).query)["state"][0]
        httpx2.get(f"{CALLBACK}?code=c1&state={state}&iss=http%3A%2F%2Flogin.example%2F")

    login = BrowserLogin("http://station:8000/mcp", print, logs_in)
    async with httpx2.AsyncClient(auth=login.auth,
                                  transport=httpx2.MockTransport(servers)) as http:
        assert (await http.post("http://station:8000/mcp")).status_code == 200
    assert login.logged_in
    left = login.auth.context.token_expiry_time - time.time()
    assert 300 - RENEW_EARLY - 5 < left <= 300 - RENEW_EARLY
