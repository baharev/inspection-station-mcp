"""Logging in to the inspection server, in the browser, instead of sending its key.

The inspection server names its login server (an OAuth authorization server). The MCP SDK's
OAuthClientProvider finds it, sends the person to its login page, exchanges the answer
for a token, sends the token with every request, and renews it before it runs out. This
module adds what the SDK leaves to the application: opening the browser, receiving the
login server's answer on this computer, and keeping the token. The app is registered at
the login server in advance, as the client "inspection-client" (the demo login server in
the inspection server's folder has it), the way an administrator registers each
application that may connect; nothing is registered automatically.

The token is kept in memory only: every start of the app logs in again.
"""

import asyncio
import base64
import json
import logging
import time
import webbrowser
from html import escape
from urllib.parse import parse_qs, parse_qsl, urlencode, urlsplit, urlunsplit

from mcp.client.auth import AuthorizationCodeResult, OAuthClientProvider, TokenStorage
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken

CLIENT_ID = "inspection-client"
CALLBACK_PORT = 33419   # the login server sends the browser back here, to this computer
CALLBACK = f"http://localhost:{CALLBACK_PORT}/callback"
WAIT = 300              # seconds the app waits for the login in the browser
RENEW_EARLY = 30        # seconds before a token runs out that the app renews it

PAGE = """<!doctype html><meta charset="utf-8"><title>Inspection client</title>
<body style="font: 16px sans-serif; margin: 3em"><p>{}</p></body>"""


class LoginFailed(Exception):
    pass


# The SDK logs every failed login with its traceback, then passes the error on to the
# window, which says in words what went wrong: keep the traceback out of the terminal.
logging.getLogger("mcp.client.auth.oauth2").addFilter(
    lambda record: record.getMessage() != "OAuth flow error")


class BrowserLogin(TokenStorage):
    """Logs in through the browser when the inspection server asks for a login.

    auth is what the connections to the inspection server send their requests through.
    tell(text) reports to the window: that the browser waits, and who logged in.
    """

    def __init__(self, server_url: str, tell=print, open_page=webbrowser.open):
        self.tell = tell
        self.open_page = open_page
        self.tokens = None
        self.client = OAuthClientInformationFull(client_id=CLIENT_ID, redirect_uris=[CALLBACK],
                                                 token_endpoint_auth_method="none")
        self.answer = None      # the login server's answer, while the login page is open
        self.listener = None    # where the browser brings it
        self.auth = OAuthClientProvider(
            server_url,
            OAuthClientMetadata(client_name="Inspection client", redirect_uris=[CALLBACK],
                                token_endpoint_auth_method="none"),
            self, redirect_handler=self.open_login_page, callback_handler=self.wait_for_login,
            validate_resource_url=self.same_address)

    @property
    def logged_in(self) -> bool:
        return self.tokens is not None

    def who(self) -> str:
        """The user name in the token (read, not checked: the inspection server checks it)."""
        try:
            payload = self.tokens.access_token.split(".")[1]
            claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
            return claims.get("preferred_username") or claims.get("sub", "")
        except (AttributeError, IndexError, ValueError):
            return ""

    # --- what the SDK stores here ---------------------------------------------------

    async def get_tokens(self) -> OAuthToken | None:
        return self.tokens

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self.tokens = tokens
        if tokens.expires_in:
            # The SDK counts a token's lifetime from when it arrives, the login server from
            # when it issued it: just before the SDK renews it, the inspection server would
            # already refuse it, and the SDK answers a refusal with a new login. So: early.
            self.auth.context.token_expiry_time = time.time() + tokens.expires_in - RENEW_EARLY
        if self.answer is not None:   # a login, not a renewal
            self.answer = None
            self.tell(f"Logged in as {self.who() or 'an unnamed user'}.")

    async def get_client_info(self) -> OAuthClientInformationFull:
        return self.client

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        self.client = client_info

    # --- the login in the browser ---------------------------------------------------

    async def same_address(self, server_url: str, published: str | None) -> None:
        """The inspection server's address as it publishes it must be the one the app uses:
        its tokens are issued for that address only."""
        if published and published.rstrip("/") != server_url.rstrip("/"):
            raise LoginFailed(f"the inspection server's address is {published}, not {server_url}: "
                              f"start the app with --server {published}")

    async def open_login_page(self, url: str) -> None:
        if self.auth.context.auth_server_url is None:
            # Without a login server named, the SDK would guess one on the inspection server.
            raise LoginFailed("the inspection server names no login server; it probably uses "
                              "its key: start the app without --login.")
        # The inspection server needs no scopes (it reads roles from the token), and names
        # none; the SDK then asks for every scope the login server offers, which it refuses
        # for an app not given them. So: no scopes. And the login form every time, so each
        # start of the app is a choice of user, not the browser's last one.
        address = urlsplit(url)
        query = {name: value for name, value in parse_qsl(address.query)
                 if name not in ("scope", "prompt")}
        url = urlunsplit(address._replace(query=urlencode(query | {"prompt": "login"})))
        try:
            self.listener = await asyncio.start_server(self.receive, "localhost", CALLBACK_PORT)
        except OSError as err:
            raise LoginFailed(f"port {CALLBACK_PORT} on this computer is busy "
                              f"({err.strerror}); is the app running twice?")
        self.answer = asyncio.get_running_loop().create_future()
        self.tell("Log in in the browser window that opened.")
        await asyncio.to_thread(self.open_page, url)

    async def wait_for_login(self) -> AuthorizationCodeResult:
        try:
            async with asyncio.timeout(WAIT):
                return await self.answer
        except BaseException as err:
            # Forget the old token, so that no other request starts a login of its own.
            self.answer = self.tokens = None
            self.auth.context.clear_tokens()
            if isinstance(err, TimeoutError):
                raise LoginFailed(f"no login within {WAIT // 60} minutes.")
            raise
        finally:
            self.listener.close()

    async def receive(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """The browser, sent back by the login server with the answer in the address."""
        try:
            request = (await reader.readline()).decode("latin-1").split()
            while (await reader.readline()).strip():   # the headers, not needed
                pass
            address = urlsplit(request[1]) if len(request) == 3 else None
            if (address is None or address.path != "/callback" or self.answer is None
                    or self.answer.done()):
                writer.write(b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n")
                return
            answer = {name: values[0] for name, values in parse_qs(address.query).items()}
            if "code" in answer:
                self.answer.set_result(AuthorizationCodeResult(
                    code=answer["code"], state=answer.get("state"), iss=answer.get("iss")))
                text = "Logged in. You can close this tab and go back to the app."
            else:
                why = answer.get("error_description") or answer.get("error") or "no answer"
                self.answer.set_exception(LoginFailed(f"the login server said: {why}"))
                text = f"The login did not work: {why}"
            body = PAGE.format(escape(text)).encode()
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\n"
                         b"Content-Length: %d\r\nConnection: close\r\n\r\n%s" % (len(body), body))
        finally:
            await writer.drain()
            writer.close()
