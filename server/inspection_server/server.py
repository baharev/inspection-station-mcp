"""An inspection station behind MCP: the AI takes photos, looks closer, records results.

The rules live here, not in the prompt: the photo the AI is sent is capped in size (the
full photo is kept for zooming), every input is checked,
a "fail" (the part is taken off the line) needs a person's yes, and everything is audit-logged.
Over the network, every request needs a secret key or a login, and a login's roles
decide which tools its user may call.

    inspection-server                 # stdio MCP server (started by a client such as Claude Code)
    inspection-server --http [--host 0.0.0.0] [--port 8000] [--tls-cert C --tls-key K]
                                      # over the network, at http(s)://<host>:<port>/mcp
    inspection-server --choose-camera [--http ...]
                                      # choose the camera in a menu (saved for later starts)

The camera and the size of its photos are always chosen by a person: once, in menus at
the first start over HTTP (or with --choose-camera), or with the settings CAMERA and
CAMERA_SIZE; see choice.py.

With --http, a browser shows what the camera sees at http(s)://<host>:<port>/live: on
the camera's own computer at http://localhost:<port>/live without a key, from other
computers with the key or a login token (role viewer). The server alone opens the
camera, so watching the live view never stops a photo from being taken.

Environment:
    CAMERA       if set, comes before the camera chosen in the menu: "fake" (the sample
                 photos) or a real camera, as scripts/check_camera.py lists them: on Linux
                 its path, such as /dev/v4l/by-id/usb-046d_0825_<serial>-video-index0;
                 on Windows and macOS (macOS not tested yet) its name or device path
    CAMERA_SIZE  if set, comes before the photo size chosen in the menu, like 1920x1080:
                 one of the sizes the camera offers, as scripts/check_camera.py lists them;
                 needed with a real camera in CAMERA
    SAMPLES_DIR  photos the fake camera serves (default: samples/)
    DATA_DIR     where photos (captures/) and logs (logs/) are kept (default: this repo)
    API_KEY      with --http: the secret key every client must send, at least 32 characters;
                 if not set, the key in ~/.config/inspection-server/api-key, which the
                 server makes on its first start (copy it to wherever Claude Code runs)
    OAUTH_ISSUER with --http, instead of a key: the login server (OAuth authorization
                 server) whose tokens are accepted, e.g. http://localhost:8080/realms/inspection
    SERVER_URL   with OAUTH_ISSUER: this server's address as clients use it, e.g.
                 http://localhost:8000/mcp; tokens must be issued for it
"""

import argparse
import asyncio
import hashlib
import hmac
import io
import json
import logging
import os
import secrets
import socket
import ssl
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit
from urllib.request import urlopen

import jwt
import uvicorn
from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.elicitation import AcceptedElicitation, ElicitationResult
from mcp.server.mcpserver import Elicit, Image, Resolve
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from PIL import Image as PILImage
from pydantic import BaseModel, Field
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, PlainTextResponse, Response

from inspection_server import choice as camera_choice
from inspection_server.camera import CameraError, FakeCamera, RealCamera

REPO = Path(__file__).resolve().parent.parent
LIVE_PAGE = Path(__file__).resolve().parent / "live.html"

MAX_PHOTO = (1280, 720)   # largest photo the AI is sent, in pixels; zooms use the full photo
ZOOM_SIZE = 1024          # longer side of an enlarged crop, in pixels
MIN_ZOOM = 0.1            # smallest crop, as a fraction of the photo's width or height
MAX_FINDINGS = 500        # characters
MIN_KEY_LENGTH = 32       # characters of the secret key
KEY_FILE = Path.home() / ".config" / "inspection-server" / "api-key"
LIVE_GAP = 60             # seconds without a frame after which a live viewer is logged again

# Who may call which tool. Logins carry their roles in the token's "roles" claim; the
# person at this computer (stdio) and the holder of the secret key may call everything.
VIEWER, INSPECTOR = "viewer", "inspector"
ALL_ROLES = [VIEWER, INSPECTOR]

ImageId = Annotated[str, Field(
    pattern=r"^\d{8}-\d{6}(-\d+)?$",
    description="The photo's ID, as returned by capture_image, e.g. 20261014-213005",
)]
Fraction = Annotated[float, Field(ge=0.0, le=1.0)]


class Confirmation(BaseModel):
    record: bool = Field(description="Mark this part as FAILED?")


# What the person said when asked to confirm a fail: "yes", "no", "declined" (the AI
# application turned the question down: a Decline button, or automatically where it cannot
# show questions, as in claude -p), "no answer" (closed without answering).
FailConfirmation = Literal["not asked", "yes", "no", "declined", "no answer"]


class InspectionRecord(BaseModel):
    time: str
    image_id: str
    photo_sha256: str = Field(description="The photo file's fingerprint: if the file is "
                                          "changed or replaced later, it no longer matches")
    part_id: str
    ai_verdict: Literal["pass", "fail", "unsure"] = Field(description="What the AI proposed")
    ai_findings: str = Field(description="What the AI saw, in its words")
    fail_confirmation: FailConfirmation = Field(
        description="'not asked' unless the AI proposed a fail; without a 'yes' the verdict "
                    "is unsure")
    verdict: Literal["pass", "fail", "unsure"] = Field(
        description="What was recorded: the AI's verdict, but a fail only with a person's yes")
    user: str = Field(description="Whose login the AI used: a login's user name, "
                                  "'api-key' (the secret key) or 'local' (stdio)")
    note: str = ""


def now() -> str:
    """The time with its offset from UTC, so the hour that repeats when clocks go back is
    still clear."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def write_audit(logs: Path, who: str, text: str) -> None:
    with open(logs / "audit.log", "a", encoding="utf-8") as f:
        f.write(f"{now()} {who} {text}\n")


class LogRefusals:
    """Writes requests refused for want of a valid key or login token to the audit log.

    The SDK refuses them before any tool runs, so the tools never see them.
    """

    def __init__(self, app, logs: Path):
        self.app, self.logs = app, logs

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def send_and_log(message):
            if message["type"] == "http.response.start" and message["status"] == 401:
                sent = any(name == b"authorization" for name, _ in scope["headers"])
                address = scope["client"][0] if scope.get("client") else "an unknown address"
                write_audit(self.logs, "unknown", f"REFUSED {scope['path']} from {address}: "
                            + ("key or login token not accepted" if sent
                               else "no key or login token sent"))
            await send(message)

        await self.app(scope, receive, send_and_log)


def from_this_computer(request: Request) -> bool:
    """True for a request from this computer that also addresses it by a local name.

    The name (the Host header) keeps out web pages that make a browser here call this
    server under a name of their own (DNS rebinding). An SSH tunnel into this computer
    counts as this computer; so would a proxy running here, so put none in front.
    """
    name = urlsplit("//" + request.headers.get("host", "")).hostname
    return (request.client is not None and request.client.host in ("127.0.0.1", "::1")
            and name in ("localhost", "127.0.0.1", "::1"))


class ApiKeyVerifier:
    """Accepts one secret key, sent by the client as "Authorization: Bearer <key>"."""

    def __init__(self, key: str):
        self.key = key.encode()

    async def verify_token(self, token: str) -> AccessToken | None:
        if hmac.compare_digest(token.encode(), self.key):  # same time for every wrong key
            return AccessToken(token=token, client_id="api-key", scopes=[], subject="api-key",
                               claims={"roles": ALL_ROLES})
        return None


class JwtVerifier:
    """Accepts access tokens (JWTs) signed by the login server and issued for this server."""

    def __init__(self, issuer: str, audience: str, signing_key):
        # signing_key(token) returns the login server's public key for the token
        self.issuer, self.audience, self.signing_key = issuer, audience, signing_key

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            key = await asyncio.to_thread(self.signing_key, token)
            claims = jwt.decode(token, key, algorithms=["RS256"], issuer=self.issuer,
                                audience=self.audience, options={"require": ["exp", "sub"]})
        except jwt.PyJWTError:
            return None
        return AccessToken(token=token, client_id=claims.get("azp", ""),
                           scopes=claims.get("scope", "").split(), expires_at=claims["exp"],
                           subject=claims["sub"], claims=claims)


def create_server(camera, data_dir: str | Path = REPO, *, auth: AuthSettings | None = None,
                  token_verifier=None) -> MCPServer:
    captures = Path(data_dir) / "captures"
    logs = Path(data_dir) / "logs"
    captures.mkdir(parents=True, exist_ok=True)
    logs.mkdir(parents=True, exist_ok=True)
    inspection_log = logs / "inspections.jsonl"

    def caller() -> tuple[str, list[str]]:
        """The caller's name and roles, from the token of the current request."""
        token = get_access_token()
        if token is None:   # stdio: the person at this computer
            return "local", ALL_ROLES
        claims = token.claims or {}
        roles = claims.get("roles", [])
        # A list only: in a text such as "trainee-viewer", "viewer" would be found too.
        return (claims.get("preferred_username") or token.subject,
                roles if isinstance(roles, list) else [])

    # Never print() in a stdio server: stdout carries the protocol. Logs go to files.
    def audit(text: str) -> None:
        write_audit(logs, caller()[0], text)

    def require(role: str, tool: str) -> None:
        name, roles = caller()
        if role not in roles:
            audit(f"REFUSED {tool}: needs the role {role}")
            raise ToolError(f"{name} may not use {tool}: it needs the role '{role}'.")

    def photo_path(image_id: str) -> Path:
        path = captures / f"{image_id}.jpg"
        if not path.exists():
            raise ToolError(f"There is no photo {image_id}. Take one with capture_image.")
        return path

    def already_recorded(image_id: str) -> bool:
        if not inspection_log.exists():
            return False
        with open(inspection_log, encoding="utf-8") as f:
            return any(json.loads(line)["image_id"] == image_id for line in f)

    def check_record(image_id: str) -> None:
        photo_path(image_id)
        if already_recorded(image_id):
            audit(f"REFUSED record_inspection {image_id}: already recorded")
            raise ToolError(f"Photo {image_id} already has an inspection record. "
                            "Take a new photo to inspect the part again.")

    def as_jpeg(photo: PILImage.Image) -> bytes:
        buffer = io.BytesIO()
        photo.save(buffer, format="JPEG", quality=85)
        return buffer.getvalue()

    mcp = MCPServer(
        "inspection-server",
        instructions=(
            "One inspection station: a camera looks down at parts on a light background. "
            "Take a photo with capture_image to answer questions about what is there. "
            "If a detail is too small to judge, use zoom_image on part of the photo "
            "instead of guessing. Record results with record_inspection; recording a "
            "fail needs a human's confirmation. When unsure, say so and record 'unsure'."
        ),
        auth=auth,
        token_verifier=token_verifier,
    )

    @mcp.tool(annotations=ToolAnnotations(destructive_hint=False))
    async def capture_image() -> list:
        """Take a photo of the inspection station. Returns the photo and its ID."""
        require(VIEWER, "capture_image")
        try:
            photo = await asyncio.to_thread(camera.take)
        except CameraError as err:
            audit(f"FAILED capture_image: {err}")
            raise ToolError(str(err)) from None
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        image_id, n = stamp, 1
        while (captures / f"{image_id}.jpg").exists():
            n += 1
            image_id = f"{stamp}-{n}"
        (captures / f"{image_id}.jpg").write_bytes(as_jpeg(photo))   # full size, for zooms
        size = f"{photo.width}x{photo.height}"
        photo.thumbnail(MAX_PHOTO)  # size cap; keeps the aspect ratio
        sent = f"{photo.width}x{photo.height}"
        audit(f"capture_image {image_id} {size}")
        return [f"Photo {image_id} ({size} pixels" + (f", shown here at {sent}; zoom_image "
                f"shows parts of it at full detail)" if sent != size else ")"),
                Image(data=as_jpeg(photo), format="jpeg")]

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
    async def zoom_image(
        image_id: ImageId,
        left: Annotated[Fraction, Field(description="Left edge, 0 = left side of the photo")],
        top: Annotated[Fraction, Field(description="Top edge, 0 = top of the photo")],
        width: Annotated[Fraction, Field(description="Width, as a fraction of the photo's width")],
        height: Annotated[Fraction, Field(description="Height, as a fraction of the photo's height")],
    ) -> list:
        """Look closer: crop a rectangle of an earlier photo and return it enlarged.

        All four numbers are fractions of the photo, from 0 to 1. Example: the top-right
        quarter is left=0.5, top=0, width=0.5, height=0.5. Enlarging shows what the
        camera captured more clearly; it cannot add detail the camera did not capture.
        """
        require(VIEWER, "zoom_image")
        if width < MIN_ZOOM or height < MIN_ZOOM:
            audit(f"REFUSED zoom_image {image_id}: too small")
            raise ToolError(f"The rectangle is too small: width and height must be at least "
                            f"{MIN_ZOOM} of the photo. Smaller crops only show blur.")
        if left + width > 1 or top + height > 1:
            audit(f"REFUSED zoom_image {image_id}: outside the photo")
            raise ToolError("The rectangle reaches outside the photo: left + width and "
                            "top + height must be at most 1.")
        with PILImage.open(photo_path(image_id)) as photo:
            w, h = photo.size
            box = (round(left * w), round(top * h), round((left + width) * w),
                   round((top + height) * h))
            crop = photo.crop(box)
        scale = ZOOM_SIZE / max(crop.size)
        crop = crop.resize((round(crop.width * scale), round(crop.height * scale)),
                           PILImage.Resampling.LANCZOS)
        audit(f"zoom_image {image_id} box={box}")
        return [f"Photo {image_id}, pixels {box[0]}..{box[2]} across and {box[1]}..{box[3]} "
                f"down, enlarged {scale:.1f} times",
                Image(data=as_jpeg(crop), format="jpeg")]

    # The live view: a page (no secrets in it) that keeps asking for the latest frame.
    # With --http only; the tools above are the only way in over stdio.
    @mcp.custom_route("/live", methods=["GET"])
    async def live_page(request: Request) -> Response:
        return HTMLResponse(LIVE_PAGE.read_text(encoding="utf-8"))

    watching = {}   # viewer name: when they last got a frame

    @mcp.custom_route("/live/frame.jpg", methods=["GET"])
    async def live_frame(request: Request) -> Response:
        # The SDK checks the key or token of every request, but refuses missing ones only
        # at /mcp. Here: none is needed from this computer, one is from any other. One sent
        # and refused (expired, say) is refused here too, never taken as the person here.
        if get_access_token() is None and ("authorization" in request.headers
                                           or not from_this_computer(request)):
            return PlainTextResponse("Send the secret key or a login token.", 401,
                                     headers={"WWW-Authenticate": "Bearer"})
        name, roles = caller()
        if VIEWER not in roles:
            audit(f"REFUSED live view: needs the role {VIEWER}")
            return PlainTextResponse(f"{name} may not use the live view: "
                                     f"it needs the role '{VIEWER}'.", 403)
        last = watching.get(name)
        if last is None or time.monotonic() - last >= LIVE_GAP:
            audit("live view opened")
        watching[name] = time.monotonic()
        try:
            data = await asyncio.to_thread(lambda: as_jpeg(camera.view()))
        except CameraError as err:
            return PlainTextResponse(str(err), 503)
        headers = {"Cache-Control": "no-store"}
        if rate := camera.rate():   # for the page: how many pictures a second the camera sends
            headers["X-Camera-Rate"] = f"{rate:.1f}"
        return Response(data, media_type="image/jpeg", headers=headers)

    def confirm_fail(image_id: str, part_id: str, verdict: str, findings: str):
        # Runs before the tool body. Only a fail asks the human, and only for a valid record.
        if verdict != "fail":
            return None
        require(INSPECTOR, "record_inspection")
        check_record(image_id)
        return Elicit(f"The AI found a problem with part {part_id} (photo {image_id}): "
                      f"{findings}\n\nIf you agree, the part is marked FAILED; in a real "
                      f"plant it would be taken off the line. If not, it is marked UNSURE and "
                      f"put aside for a person to look at.", Confirmation)

    @mcp.tool(annotations=ToolAnnotations(destructive_hint=False, idempotent_hint=False))
    async def record_inspection(
        image_id: ImageId,
        part_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9-]{1,40}$",
                                      description="The part's label, e.g. tray-07")],
        verdict: Literal["pass", "fail", "unsure"],
        findings: Annotated[str, Field(min_length=1, max_length=MAX_FINDINGS,
                                       description="What was seen, in a sentence or two")],
        answer: Annotated[ElicitationResult[Confirmation], Resolve(confirm_fail)],
    ) -> InspectionRecord:
        """Add the result of an inspection to the log: one record per photo.

        Verdict pass, fail or unsure. A fail takes the part off the line, so a person must
        confirm it first; without their yes the part is recorded as unsure and put aside
        for a person to look at.
        """
        require(INSPECTOR, "record_inspection")
        check_record(image_id)
        confirmation, recorded = "not asked", verdict
        if verdict == "fail":
            if isinstance(answer, AcceptedElicitation):
                confirmation = "yes" if answer.data.record else "no"
            else:
                confirmation = "declined" if answer.action == "decline" else "no answer"
            if confirmation != "yes":
                recorded = "unsure"
        record = InspectionRecord(
            time=now(), image_id=image_id,
            photo_sha256=hashlib.sha256(photo_path(image_id).read_bytes()).hexdigest(),
            part_id=part_id, ai_verdict=verdict, ai_findings=findings,
            fail_confirmation=confirmation, verdict=recorded, user=caller()[0],
        )
        with open(inspection_log, "a", encoding="utf-8") as f:
            f.write(record.model_dump_json(exclude={"note"}) + "\n")
        audit(f"record_inspection {part_id} {recorded} {image_id} "
              f"(AI: {verdict}, fail confirmation: {confirmation})")
        if confirmation not in ("not asked", "yes"):
            record.note = (f"The fail was not confirmed (answer: {confirmation}), so part "
                           f"{part_id} was recorded as unsure: a person should look at it.")
        elif recorded == "unsure":
            record.note = f"Recorded as unsure: a person should look at part {part_id}."
        return record

    return mcp


def http_app(server: MCPServer, data_dir: str | Path = REPO, host: str = "127.0.0.1") -> Starlette:
    """The server over HTTP, with the refused requests in the audit log."""
    app = server.streamable_http_app(host=host)
    app.add_middleware(LogRefusals, logs=Path(data_dir) / "logs")
    return app


def key_auth(key: str) -> dict:
    """Settings for create_server: every request must carry the secret key."""
    # The SDK's token check needs an issuer URL; with a fixed key nobody issues tokens,
    # and without resource_server_url the URL is never published.
    return {"auth": AuthSettings(issuer_url="http://localhost", resource_server_url=None),
            "token_verifier": ApiKeyVerifier(key)}


def secret_key(path: Path = KEY_FILE) -> str:
    """The secret key: API_KEY if set, else the key in the key file, made there if missing.

    With the key in a file, the server and Claude Code read the same key, also on two
    computers (copy the file), and nobody has to type it.
    """
    if key := os.environ.get("API_KEY", "").strip():
        where = "API_KEY"
    else:
        where = str(path)
        if not path.exists():
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                # Readable by this user only (Linux and macOS):
                with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as f:
                    f.write(secrets.token_urlsafe(32) + "\n")
            except OSError as err:
                sys.exit(f"Cannot make the key file {path} ({err}). Set API_KEY instead.")
            where += " (made now)"
        key = path.read_text(encoding="utf-8").strip()
    if len(key) < MIN_KEY_LENGTH:
        sys.exit(f"The secret key in {where} is shorter than {MIN_KEY_LENGTH} characters.")
    print(f"Secret key: {where}", file=sys.stderr)
    return key


def secure_or_local(url: str) -> bool:
    """True for an https:// address, or any address on this computer.

    The login server's public keys decide which tokens are genuine: fetched over plain
    HTTP from another computer, anyone on the network between could swap in their own.
    """
    address = urlsplit(url)
    return address.scheme == "https" or address.hostname in ("localhost", "127.0.0.1", "::1")


def oauth_auth(issuer: str, server_url: str, signing_key=None) -> dict:
    """Settings for create_server: every request must carry a token from the login server.

    signing_key(token) returns the public key to check a token with; by default the
    login server's published keys are used.
    """
    issuer = issuer.rstrip("/")
    if not secure_or_local(issuer):
        sys.exit(f"The login server {issuer} must be reached over HTTPS (https://), or run "
                 "on this computer (localhost): over plain HTTP, anyone on the network could "
                 "replace its keys and log in as anyone.")
    if signing_key is None:
        # The login server publishes where its public keys are (OpenID Connect discovery).
        settings = f"{issuer}/.well-known/openid-configuration"
        try:
            with urlopen(settings, timeout=10) as response:
                published = json.load(response)
            keys, named = published["jwks_uri"], published["issuer"]
        except (OSError, ValueError, KeyError) as err:   # unreachable, refused, not JSON
            hint = ("Set SSL_CERT_FILE to the certificate authority that signed its certificate."
                    if isinstance(getattr(err, "reason", err), ssl.SSLCertVerificationError)
                    else "Is the login server running, and is OAUTH_ISSUER right?")
            sys.exit(f"Cannot read the login server's settings at {settings} ({err}). {hint}")
        if named.rstrip("/") != issuer:
            sys.exit(f"The login server at {issuer} calls itself {named}: set OAUTH_ISSUER "
                     "to the address it names.")
        if not secure_or_local(keys):
            sys.exit(f"The login server publishes its keys at {keys}, over plain HTTP from "
                     "another computer: anyone on the network could replace them.")
        signing_key = jwt.PyJWKClient(keys).get_signing_key_from_jwt
    # resource_server_url publishes, for clients such as Claude Code, which login server
    # to use. The verifier checks that a token was issued for this server (its audience).
    return {"auth": AuthSettings(issuer_url=issuer, resource_server_url=server_url,
                                 validate_token_resource=False),
            "token_verifier": JwtVerifier(issuer, server_url, signing_key)}


def network_address() -> str | None:
    """This computer's address on its network, as other computers reach it, if it has one."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))   # sends nothing: only picks the network to use
            return s.getsockname()[0]
    except OSError:
        return None


def next_steps(host: str, port: int, scheme: str, key_file: bool,
               address: str | None = None, mcp_url: str | None = None) -> list[str]:
    """What the server prints at its start over HTTP: where to find it, how to connect.

    key_file: clients use the key file (not API_KEY, not logins), so the Claude Code
    command can read the key from it. address: this computer's address on its network.
    mcp_url: the server's address as set for logins (SERVER_URL), if any.
    """
    lines = []
    if host in ("127.0.0.1", "localhost", "::1"):
        here, there = "localhost", None
        lines.append("Only this computer can connect. To let other computers in, "
                     "start with --host 0.0.0.0 too.")
    elif host in ("0.0.0.0", "::"):
        here, there = "localhost", address or "<this computer's address>"
    else:
        here = there = host
    lines.append(f"Live view: {scheme}://{here}:{port}/live")
    if there and there != here:
        lines.append(f"           {scheme}://{there}:{port}/live from other computers, "
                     "with the secret key or a login")
    url = mcp_url or f"{scheme}://{there or here}:{port}/mcp"
    lines.append(f"MCP address: {url}")
    if key_file:   # the commands read the key from the key file, so nobody types it
        read_key = {"Linux, macOS:": "$(cat ~/.config/inspection-server/api-key)",
                    "PowerShell:": "$(Get-Content $HOME\\.config\\inspection-server\\api-key)"}
        lines.append("To connect Claude Code, run this once in the folder where you use it"
                     + (" (on another computer, copy the key file there first):" if there else ":"))
        lines += [f"  {shell:14}claude mcp add -s local --transport http inspection-server {url} "
                  f'--header "Authorization: Bearer {key}"' for shell, key in read_key.items()]
    if there and scheme == "http":
        lines.append("Warning: other computers connect over plain HTTP, so anyone on the network "
                     "can read the key or login tokens on the way. Fine on a network you trust; "
                     "elsewhere, use HTTPS (--tls-cert and --tls-key).")
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description="The inspection station as an MCP server.")
    parser.add_argument("--http", action="store_true",
                        help="serve over the network instead of stdio, with the secret key "
                             f"in {KEY_FILE} (made if missing) or API_KEY, or with logins "
                             "(OAUTH_ISSUER and SERVER_URL)")
    parser.add_argument("--host", default="127.0.0.1",
                        help="address to listen on (default: this computer only; "
                             "0.0.0.0: every network it is on)")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--tls-cert", help="with --http: certificate file, for HTTPS")
    parser.add_argument("--tls-key", help="with --http: the certificate's private key file")
    parser.add_argument("--choose-camera", action="store_true",
                        help="choose the camera and its photo size in menus, also if they "
                             "were chosen before (the choice is saved for later starts)")
    args = parser.parse_args()

    # The menu needs a person at a terminal. Over stdio, the terminal carries the protocol:
    # there, the menu is shown only with --choose-camera, and the server then stops.
    choice = camera_choice.for_start(
        args.choose_camera, can_ask=sys.stdin.isatty() and (args.http or args.choose_camera))
    if choice.device == camera_choice.FAKE:
        camera = FakeCamera(os.environ.get("SAMPLES_DIR", REPO / "samples"))
    else:
        camera = RealCamera(choice.device, choice.size)
        try:
            camera.check()   # now, not at the first photo, so whoever starts it sees why
        except CameraError as err:
            if choice.source == camera_choice.FROM_CAMERA:
                sys.exit(str(err))
            sys.exit(f"The camera chosen earlier, {choice.name}, cannot be found. Is it "
                     f"plugged in? Or choose another: {camera_choice.CHOOSE}")
    data_dir = os.environ.get("DATA_DIR", REPO)

    if args.choose_camera and not args.http:
        return   # chosen and saved: Claude Code starts the server with it from now on
    if not args.http:
        create_server(camera, data_dir).run()
        return
    print(choice.describe(), file=sys.stderr)
    server_url = None
    if issuer := os.environ.get("OAUTH_ISSUER", ""):
        if os.environ.get("API_KEY"):
            sys.exit("Set either API_KEY or OAUTH_ISSUER, not both.")
        server_url = os.environ.get("SERVER_URL") or sys.exit(
            "Set SERVER_URL to this server's address as clients use it, "
            f"e.g. http://localhost:{args.port}/mcp")
        auth = oauth_auth(issuer, server_url)
    else:
        auth = key_auth(secret_key())
    app = http_app(create_server(camera, data_dir, **auth), data_dir, args.host)
    for line in next_steps(args.host, args.port, "https" if args.tls_cert else "http",
                           key_file=not issuer and not os.environ.get("API_KEY", "").strip(),
                           address=network_address(), mcp_url=server_url):
        print(line, file=sys.stderr)
    # The live view asks for a frame five times a second; keep those out of the terminal.
    logging.getLogger("uvicorn.access").addFilter(
        lambda record: "/live/frame.jpg" not in record.getMessage())
    uvicorn.run(app, host=args.host, port=args.port,
                ssl_certfile=args.tls_cert, ssl_keyfile=args.tls_key)


if __name__ == "__main__":
    main()
