"""The app's part of the login: the browser is sent to the login page and comes back.

The login server and the browser are played by the test; the rest of the login (finding
the login server, the token, renewing it) is the MCP SDK's, tested there, and was tried
by hand with the demo login server in the inspection server's folder.
"""

import socket
import time
from urllib.parse import parse_qs, urlsplit

import httpx2
import pytest

from inspection_client import login as login_module
from inspection_client.login import RENEW_EARLY, BrowserLogin, LoginFailed
from inspection_client.station import ServerRefused, server_http, describe

pytestmark = pytest.mark.anyio

LOGIN_PAGE = ("http://login.example/auth?response_type=code&client_id=inspection-client"
              "&state=s1&scope=openid+offline_access&prompt=consent")


@pytest.fixture(autouse=True)
def free_port(monkeypatch):
    """The browser comes back to a free port, so the tests run while the app is logging in
    on this computer too (on its own port)."""
    with socket.socket() as probe:
        probe.bind(("localhost", 0))
        port = probe.getsockname()[1]
    monkeypatch.setattr(login_module, "CALLBACK_PORT", port)
    monkeypatch.setattr(login_module, "CALLBACK", f"http://localhost:{port}/callback")


def browser(comes_back_with: str, opened: list):
    """Opens the login page, and returns to the app with the login server's answer."""
    def open_page(url):
        opened.append(url)
        httpx2.get(f"{login_module.CALLBACK}?{comes_back_with}")
    return open_page


def login_with(answer: str, opened: list, told: list) -> BrowserLogin:
    login = BrowserLogin("http://station:8000/mcp", told.append, browser(answer, opened))
    login.auth.context.auth_server_url = "http://login.example/"   # as the server names it
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


async def test_only_the_callback_address_brings_the_answer():
    elsewhere = []

    def open_page(url):   # another page on the same port first, then the real answer
        app = login_module.CALLBACK.removesuffix("/callback")
        elsewhere.append(httpx2.get(f"{app}/elsewhere?code=forged&state=s1").status_code)
        httpx2.get(f"{login_module.CALLBACK}?code=c1&state=s1")

    login = BrowserLogin("http://station:8000/mcp", print, open_page)
    login.auth.context.auth_server_url = "http://login.example/"
    await login.open_login_page(LOGIN_PAGE)
    assert (await login.wait_for_login()).code == "c1"
    assert elsewhere == [404]


async def test_a_refused_login_is_told_in_words():
    opened, told = [], []
    login = login_with("error=access_denied&error_description=Not+allowed&state=s1", opened, told)
    await login.open_login_page(LOGIN_PAGE)
    with pytest.raises(LoginFailed) as failed:
        await login.wait_for_login()
    assert describe(failed.value) == "Not logged in: the login server said: Not allowed"
    assert not login.logged_in


async def test_no_login_page_when_the_inspection_server_names_no_login_server():
    opened = []
    login = BrowserLogin("http://station:8000/mcp", print, browser("code=c1", opened))
    with pytest.raises(LoginFailed, match="without --login"):
        await login.open_login_page(LOGIN_PAGE)
    assert opened == []


async def test_the_address_must_be_the_one_the_inspection_server_publishes():
    login = BrowserLogin("http://127.0.0.1:8000/mcp")
    await login.same_address("http://127.0.0.1:8000/mcp", "http://127.0.0.1:8000/mcp")
    with pytest.raises(LoginFailed, match="--server http://localhost:8000/mcp"):
        await login.same_address("http://127.0.0.1:8000/mcp", "http://localhost:8000/mcp")


def servers(request: httpx2.Request, accepts_token=True) -> httpx2.Response:
    """The inspection server, which wants a login, and its login server."""
    match request.url.path:
        case "/mcp" if accepts_token and "Authorization" in request.headers:
            return httpx2.Response(200)
        case "/mcp":
            return httpx2.Response(401, headers={"WWW-Authenticate": 'Bearer resource_metadata='
                                   '"http://station:8000/.well-known/oauth-protected-resource/mcp"'})
        case "/.well-known/oauth-protected-resource/mcp":
            return httpx2.Response(200, json={"resource": "http://station:8000/mcp",
                                              "authorization_servers": ["http://login.example/"]})
        case "/.well-known/openid-configuration":   # as Keycloak: not the first place looked
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


async def test_no_login_to_an_inspection_server_known_by_another_address(monkeypatch):
    monkeypatch.setattr(login_module, "WAIT", 0.2)   # never wait for a login that may start
    opened = []
    login = BrowserLogin("http://127.0.0.1:8000/mcp", print, opened.append)
    async with httpx2.AsyncClient(auth=login.auth,
                                  transport=httpx2.MockTransport(servers)) as http:
        with pytest.raises(Exception) as failed:
            await http.post("http://127.0.0.1:8000/mcp")
    assert ("the inspection server's address is http://station:8000/mcp, not "
            "http://127.0.0.1:8000/mcp: start the app with --server http://station:8000/mcp"
            in describe(failed.value))
    assert opened == []


def logs_in(url):
    """The person logs in on the login page."""
    state = parse_qs(urlsplit(url).query)["state"][0]
    httpx2.get(f"{login_module.CALLBACK}?code=c1&state={state}&iss=http%3A%2F%2Flogin.example%2F")


async def test_the_token_is_renewed_before_the_inspection_server_would_refuse_it():
    login = BrowserLogin("http://station:8000/mcp", print, logs_in)
    async with httpx2.AsyncClient(auth=login.auth,
                                  transport=httpx2.MockTransport(servers)) as http:
        assert (await http.post("http://station:8000/mcp")).status_code == 200
    assert login.logged_in
    early = 300 - (login.auth.context.token_expiry_time - time.time())   # the token lasts 300 s
    assert early >= 20, f"The token is renewed only {early:.0f} s before it runs out."
    assert early < RENEW_EARLY + 5


async def test_the_inspection_servers_first_refusal_starts_the_login(offline):
    offline(servers)
    login = BrowserLogin("http://station:8000/mcp", print, logs_in)
    try:
        async with server_http(login.auth) as http:
            assert (await http.post("http://station:8000/mcp")).status_code == 200
    except ServerRefused as refused:
        pytest.fail(f"No login: the person was told: {describe(refused)}")
    assert login.logged_in


async def test_a_login_the_inspection_server_refuses_is_told_in_words(offline):
    offline(lambda request: servers(request, accepts_token=False))
    login = BrowserLogin("http://station:8000/mcp", print, logs_in)
    with pytest.raises(ServerRefused) as refused:
        async with server_http(login.auth) as http:
            await http.post("http://station:8000/mcp")
    assert login.logged_in, "The inspection server's refusal was final before the person logged in."
    told = describe(refused.value)
    assert "refused the login" in told and "SERVER_URL" in told, f"The person was told: {told}"
