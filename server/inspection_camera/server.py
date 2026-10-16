"""An inspection station behind MCP: the AI takes photos, looks closer, records results.

The rules live here, not in the prompt: photo size is capped, every input is checked,
a "fail" (the part is taken off the line) needs a person's yes, and everything is audit-logged.
Over the network, every request needs a secret key or a login, and a login's roles
decide which tools its user may call.

    inspection-camera                 # stdio MCP server (started by a client such as Claude Code)
    inspection-camera --http [--host 0.0.0.0] [--port 8000] [--tls-cert C --tls-key K]
                                      # over the network, at http(s)://<host>:<port>/mcp

With --http, a browser shows what the camera sees at http(s)://<host>:<port>/live: on
the camera's own computer at http://localhost:<port>/live without a key, from other
computers with the key or a login token (role viewer). The server alone opens the
camera, so watching the live view never stops a photo from being taken.

Environment:
    CAMERA       "fake" (default) or a real camera, as scripts/check_camera.py lists them:
                 on Linux its path, such as /dev/v4l/by-id/usb-046d_0825_<serial>-video-index0;
                 on Windows and macOS (macOS not tested yet) its name or device path
    SAMPLES_DIR  photos the fake camera serves (default: samples/)
    DATA_DIR     where photos (captures/) and logs (logs/) are kept (default: this repo)
    API_KEY      with --http: the secret key every client must send, at least 32 characters;
                 if not set, the key in ~/.config/inspection-camera/api-key, which the
                 server makes on its first start (copy it to wherever Claude Code runs)
    OAUTH_ISSUER with --http, instead of a key: the login server (OAuth authorization
                 server) whose tokens are accepted, e.g. http://localhost:8080/realms/inspection
    SERVER_URL   with OAUTH_ISSUER: this server's address as clients use it, e.g.
                 http://localhost:8000/mcp; tokens must be issued for it
"""

import argparse
import asyncio
import hmac
import io
import json
import logging
import os
import secrets
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
from starlette.requests import Request
from starlette.responses import HTMLResponse, PlainTextResponse, Response

from inspection_camera.camera import CameraError, FakeCamera, RealCamera

REPO = Path(__file__).resolve().parent.parent
LIVE_PAGE = Path(__file__).resolve().parent / "live.html"

MAX_PHOTO = (1280, 720)   # longest photo the AI is sent, in pixels
ZOOM_SIZE = 1024          # longer side of an enlarged crop, in pixels
MIN_ZOOM = 0.1            # smallest crop, as a fraction of the photo's width or height
MAX_FINDINGS = 500        # characters
MIN_KEY_LENGTH = 32       # characters of the secret key
KEY_FILE = Path.home() / ".config" / "inspection-camera" / "api-key"
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
    part_id: str
    verdict: Literal["pass", "fail", "unsure"]
    findings: str
    fail_confirmation: FailConfirmation = Field(
        description="'not asked' unless the AI proposed a fail; without a 'yes' the verdict "
                    "is unsure")
    recorded_by: str = Field(description="Who recorded it: a login's user name, "
                                         "'api-key' or 'local'")
    note: str = ""


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
        return claims.get("preferred_username") or token.subject, claims.get("roles", [])

    # Never print() in a stdio server: stdout carries the protocol. Logs go to files.
    def audit(text: str) -> None:
        with open(logs / "audit.log", "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat(timespec='seconds')} {caller()[0]} {text}\n")

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
        "inspection-camera",
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
        photo.thumbnail(MAX_PHOTO)  # size cap; keeps the aspect ratio
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        image_id, n = stamp, 1
        while (captures / f"{image_id}.jpg").exists():
            n += 1
            image_id = f"{stamp}-{n}"
        data = as_jpeg(photo)
        (captures / f"{image_id}.jpg").write_bytes(data)
        audit(f"capture_image {image_id} {photo.width}x{photo.height}")
        return [f"Photo {image_id} ({photo.width}x{photo.height} pixels)",
                Image(data=data, format="jpeg")]

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
        # at /mcp. Here: none is needed from this computer, one is from any other.
        if get_access_token() is None and not from_this_computer(request):
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
        return Response(data, media_type="image/jpeg", headers={"Cache-Control": "no-store"})

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
        confirmation = "not asked"
        if verdict == "fail":
            if isinstance(answer, AcceptedElicitation):
                confirmation = "yes" if answer.data.record else "no"
            else:
                confirmation = "declined" if answer.action == "decline" else "no answer"
            if confirmation != "yes":
                verdict = "unsure"
        record = InspectionRecord(
            time=datetime.now().isoformat(timespec="seconds"), image_id=image_id,
            part_id=part_id, verdict=verdict, findings=findings,
            fail_confirmation=confirmation, recorded_by=caller()[0],
        )
        with open(inspection_log, "a", encoding="utf-8") as f:
            f.write(record.model_dump_json(exclude={"note"}) + "\n")
        audit(f"record_inspection {part_id} {verdict} {image_id}"
              + ("" if confirmation == "not asked" else f" (fail confirmation: {confirmation})"))
        if confirmation not in ("not asked", "yes"):
            record.note = (f"The fail was not confirmed (answer: {confirmation}), so part "
                           f"{part_id} was recorded as unsure: a person should look at it.")
        elif verdict == "unsure":
            record.note = f"Recorded as unsure: a person should look at part {part_id}."
        return record

    return mcp


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


def oauth_auth(issuer: str, server_url: str, signing_key=None) -> dict:
    """Settings for create_server: every request must carry a token from the login server.

    signing_key(token) returns the public key to check a token with; by default the
    login server's published keys are used.
    """
    issuer = issuer.rstrip("/")
    if signing_key is None:
        # The login server publishes where its public keys are (OpenID Connect discovery).
        settings = f"{issuer}/.well-known/openid-configuration"
        try:
            with urlopen(settings, timeout=10) as response:
                keys = json.load(response)["jwks_uri"]
        except (OSError, ValueError, KeyError) as err:   # unreachable, refused, not JSON
            hint = ("Set SSL_CERT_FILE to the certificate authority that signed its certificate."
                    if isinstance(getattr(err, "reason", err), ssl.SSLCertVerificationError)
                    else "Is the login server running, and is OAUTH_ISSUER right?")
            sys.exit(f"Cannot read the login server's settings at {settings} ({err}). {hint}")
        signing_key = jwt.PyJWKClient(keys).get_signing_key_from_jwt
    # resource_server_url publishes, for clients such as Claude Code, which login server
    # to use. The verifier checks that a token was issued for this server (its audience).
    return {"auth": AuthSettings(issuer_url=issuer, resource_server_url=server_url,
                                 validate_token_resource=False),
            "token_verifier": JwtVerifier(issuer, server_url, signing_key)}


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
    args = parser.parse_args()

    device = os.environ.get("CAMERA", "fake")
    if device == "fake":
        camera = FakeCamera(os.environ.get("SAMPLES_DIR", REPO / "samples"))
    else:
        camera = RealCamera(device)
        try:
            camera.check()   # now, not at the first photo, so whoever starts it sees why
        except CameraError as err:
            sys.exit(str(err))
    data_dir = os.environ.get("DATA_DIR", REPO)

    if not args.http:
        create_server(camera, data_dir).run()
        return
    if issuer := os.environ.get("OAUTH_ISSUER", ""):
        if os.environ.get("API_KEY"):
            sys.exit("Set either API_KEY or OAUTH_ISSUER, not both.")
        server_url = os.environ.get("SERVER_URL") or sys.exit(
            "Set SERVER_URL to this server's address as clients use it, "
            f"e.g. http://localhost:{args.port}/mcp")
        auth = oauth_auth(issuer, server_url)
    else:
        auth = key_auth(secret_key())
    app = create_server(camera, data_dir, **auth).streamable_http_app(host=args.host)
    scheme = "https" if args.tls_cert else "http"
    listens_here = args.host in ("127.0.0.1", "localhost", "::1", "0.0.0.0", "::")
    print(f"Live view: {scheme}://{'localhost' if listens_here else args.host}:{args.port}/live",
          file=sys.stderr)
    # The live view asks for a frame five times a second; keep those out of the terminal.
    logging.getLogger("uvicorn.access").addFilter(
        lambda record: "/live/frame.jpg" not in record.getMessage())
    uvicorn.run(app, host=args.host, port=args.port,
                ssl_certfile=args.tls_cert, ssl_keyfile=args.tls_key)


if __name__ == "__main__":
    main()
