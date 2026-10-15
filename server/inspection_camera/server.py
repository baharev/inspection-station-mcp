"""An inspection station behind MCP: the AI takes photos, looks closer, records results.

The rules live here, not in the prompt: photo size is capped, every input is checked,
a "fail" (the part gets scrapped) needs a human's yes, and everything is audit-logged.
Over the network, every request needs a secret key or a login, and a login's roles
decide which tools its user may call.

    inspection-camera                 # stdio MCP server (started by a client such as Claude Code)
    inspection-camera --http [--host 0.0.0.0] [--port 8000] [--tls-cert C --tls-key K]
                                      # over the network, at http(s)://<host>:<port>/mcp

Environment:
    CAMERA       "fake" (default) or the path of a V4L2 camera, such as
                 /dev/v4l/by-id/usb-046d_0825_<serial>-video-index0
    SAMPLES_DIR  photos the fake camera serves (default: samples/)
    DATA_DIR     where photos (captures/) and logs (logs/) are kept (default: this repo)
    API_KEY      with --http: the secret key every client must send, at least 32 characters
    OAUTH_ISSUER with --http, instead of API_KEY: the login server (OAuth authorization
                 server) whose tokens are accepted, e.g. http://localhost:8080/realms/inspection
    SERVER_URL   with OAUTH_ISSUER: this server's address as clients use it, e.g.
                 http://localhost:8000/mcp; tokens must be issued for it
"""

import argparse
import asyncio
import hmac
import io
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal
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

from inspection_camera.camera import CameraError, FakeCamera, RealCamera

REPO = Path(__file__).resolve().parent.parent

MAX_PHOTO = (1280, 720)   # longest photo the AI is sent, in pixels
ZOOM_SIZE = 1024          # longer side of an enlarged crop, in pixels
MIN_ZOOM = 0.1            # smallest crop, as a fraction of the photo's width or height
MAX_FINDINGS = 500        # characters
MIN_KEY_LENGTH = 32       # characters of API_KEY

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
    record: bool = Field(description="Record this part as FAILED?")


class InspectionRecord(BaseModel):
    time: str
    image_id: str
    part_id: str
    verdict: Literal["pass", "fail", "unsure"]
    findings: str
    confirmed_by_human: bool = Field(description="True when a human confirmed a fail")
    recorded_by: str = Field(description="Who recorded it: a login's user name, "
                                         "'api-key' or 'local'")
    note: str = ""


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

    def confirm_fail(image_id: str, part_id: str, verdict: str, findings: str):
        # Runs before the tool body. Only a fail asks the human, and only for a valid record.
        if verdict != "fail":
            return None
        require(INSPECTOR, "record_inspection")
        check_record(image_id)
        return Elicit(f"Record part {part_id} as FAILED (it will be scrapped)? "
                      f"Photo {image_id}. Findings: {findings}", Confirmation)

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

        Verdict pass, fail or unsure. A fail means the part is scrapped, so a human
        must confirm it first.
        """
        require(INSPECTOR, "record_inspection")
        check_record(image_id)
        confirmed = False
        if verdict == "fail":
            confirmed = isinstance(answer, AcceptedElicitation) and answer.data.record
            if not confirmed:
                how = "said no" if isinstance(answer, AcceptedElicitation) else answer.action
                audit(f"fail not confirmed ({how}) {part_id} {image_id}")
                raise ToolError("The human did not confirm the fail. Nothing was recorded.")
        record = InspectionRecord(
            time=datetime.now().isoformat(timespec="seconds"), image_id=image_id,
            part_id=part_id, verdict=verdict, findings=findings, confirmed_by_human=confirmed,
            recorded_by=caller()[0],
        )
        with open(inspection_log, "a", encoding="utf-8") as f:
            f.write(record.model_dump_json(exclude={"note"}) + "\n")
        audit(f"record_inspection {part_id} {verdict} {image_id}"
              + (" (confirmed by human)" if confirmed else ""))
        if verdict == "unsure":
            record.note = f"Recorded as unsure: a person should look at part {part_id}."
        return record

    return mcp


def key_auth(key: str) -> dict:
    """Settings for create_server: every request must carry the secret key."""
    # The SDK's token check needs an issuer URL; with a fixed key nobody issues tokens,
    # and without resource_server_url the URL is never published.
    return {"auth": AuthSettings(issuer_url="http://localhost", resource_server_url=None),
            "token_verifier": ApiKeyVerifier(key)}


def oauth_auth(issuer: str, server_url: str, signing_key=None) -> dict:
    """Settings for create_server: every request must carry a token from the login server.

    signing_key(token) returns the public key to check a token with; by default the
    login server's published keys are used.
    """
    issuer = issuer.rstrip("/")
    if signing_key is None:
        # The login server publishes where its public keys are (OpenID Connect discovery).
        with urlopen(f"{issuer}/.well-known/openid-configuration", timeout=10) as response:
            signing_key = jwt.PyJWKClient(json.load(response)["jwks_uri"]).get_signing_key_from_jwt
    # resource_server_url publishes, for clients such as Claude Code, which login server
    # to use. The verifier checks that a token was issued for this server (its audience).
    return {"auth": AuthSettings(issuer_url=issuer, resource_server_url=server_url,
                                 validate_token_resource=False),
            "token_verifier": JwtVerifier(issuer, server_url, signing_key)}


def main() -> None:
    parser = argparse.ArgumentParser(description="The inspection station as an MCP server.")
    parser.add_argument("--http", action="store_true",
                        help="serve over the network instead of stdio; "
                             "needs API_KEY or OAUTH_ISSUER and SERVER_URL")
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
    data_dir = os.environ.get("DATA_DIR", REPO)

    if not args.http:
        create_server(camera, data_dir).run()
        return
    key, issuer = os.environ.get("API_KEY", ""), os.environ.get("OAUTH_ISSUER", "")
    if issuer and not key:
        server_url = os.environ.get("SERVER_URL") or sys.exit(
            "Set SERVER_URL to this server's address as clients use it, "
            f"e.g. http://localhost:{args.port}/mcp")
        auth = oauth_auth(issuer, server_url)
    elif len(key) >= MIN_KEY_LENGTH and not issuer:
        auth = key_auth(key)
    else:
        sys.exit(f"Set either API_KEY, to a secret of at least {MIN_KEY_LENGTH} characters, e.g.\n"
                 '    export API_KEY="$(python -c "import secrets; print(secrets.token_urlsafe(32))")"\n'
                 "or OAUTH_ISSUER and SERVER_URL, for logins.")
    app = create_server(camera, data_dir, **auth).streamable_http_app(host=args.host)
    uvicorn.run(app, host=args.host, port=args.port,
                ssl_certfile=args.tls_cert, ssl_keyfile=args.tls_key)


if __name__ == "__main__":
    main()
