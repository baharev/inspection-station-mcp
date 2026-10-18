"""A stand-in for the inspection server in the tests: the same three tools, seen from outside.

The app depends only on what any inspection server offers over MCP: the tool names and
arguments, a photo's ID in the field image_id (and, for Claude, in the text "Photo <ID>
..."), a refusal as a tool error, a question with the one yes-or-no field mark_failed
before a fail is recorded, and the record's fields part_id, verdict, fail_confirmation
and note. So the tests need neither the real server (repository inspection-mcp-server)
nor a camera. What the stand-in got is kept in `answers`.
"""

import io
from typing import Annotated, Literal

from mcp.server import MCPServer
from mcp.server.elicitation import AcceptedElicitation, ElicitationResult
from mcp.server.mcpserver import Context, Elicit, Image, Resolve
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, TextContent
from PIL import Image as PILImage
from pydantic import BaseModel, Field

MIN_ZOOM = 0.1   # smallest crop, as a fraction of the photo, as in the real server
SIZE = (64, 48)
CANNOT_ASK = "cannot ask"


class Confirmation(BaseModel):
    mark_failed: bool = Field(False, title="Mark this part as FAILED")


class PhotoInfo(BaseModel):
    image_id: str
    width: int
    height: int


class ZoomInfo(PhotoInfo):   # the photo the zoom was cut from
    box: tuple[int, int, int, int]
    scale: float


class Record(BaseModel):
    image_id: str
    part_id: str
    ai_verdict: str
    fail_confirmation: str
    verdict: str
    note: str = ""


def photo(shade: int = 200) -> bytes:
    buffer = io.BytesIO()
    PILImage.new("RGB", SIZE, (shade, shade, shade)).save(buffer, "JPEG")
    return buffer.getvalue()


def picture_result(text: str, picture: bytes, info: PhotoInfo) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=text),
                 Image(data=picture, format="jpeg").to_image_content()],
        structured_content=info.model_dump(mode="json"))


def stand_in_server():
    """The stand-in server, and the list of what the person answered (as the server saw it)."""
    answers = []
    mcp = MCPServer("stand-in", instructions="Take photos with capture_image, look closer "
                                             "with zoom_image, record with record_inspection.")
    taken = 0

    @mcp.tool()
    async def capture_image() -> Annotated[CallToolResult, PhotoInfo]:
        """Take a photo."""
        nonlocal taken
        taken += 1
        image_id = f"p{taken}"
        return picture_result(f"Photo {image_id} (64x48 pixels)",
                              photo(250 - 30 * taken),   # each photo a shade of its own
                              PhotoInfo(image_id=image_id, width=SIZE[0], height=SIZE[1]))

    @mcp.tool()
    async def zoom_image(image_id: str, left: float, top: float, width: float,
                         height: float) -> Annotated[CallToolResult, ZoomInfo]:
        """Look closer at part of a photo."""
        if width < MIN_ZOOM or height < MIN_ZOOM:
            raise ToolError("The rectangle is too small.")
        if left + width > 1 or top + height > 1:
            raise ToolError("The rectangle reaches outside the photo.")
        box = (round(left * SIZE[0]), round(top * SIZE[1]), round((left + width) * SIZE[0]),
               round((top + height) * SIZE[1]))
        return picture_result(f"Photo {image_id}, enlarged", photo(),
                              ZoomInfo(image_id=image_id, width=SIZE[0], height=SIZE[1], box=box,
                                       scale=1.0))

    def confirm_fail(image_id: str, part_id: str, verdict: str, findings: str, ctx: Context):
        if verdict == "fail":
            capabilities = ctx.client_capabilities
            if capabilities is None or capabilities.elicitation is None:
                return CANNOT_ASK
            return Elicit(f"Part {part_id}: {findings} Mark it FAILED?", Confirmation)

    @mcp.tool()
    async def record_inspection(
        image_id: str, part_id: str, verdict: Literal["pass", "fail", "unsure"], findings: str,
        answer: Annotated[ElicitationResult[Confirmation], Resolve(confirm_fail)],
    ) -> Record:
        """Record the result of an inspection."""
        confirmation, recorded, note = "not asked", verdict, ""
        if verdict == "fail":
            if not isinstance(answer, AcceptedElicitation):
                got = answer.action
                confirmation = "declined" if got == "decline" else "no answer"
            elif answer.data == CANNOT_ASK:
                got = confirmation = CANNOT_ASK
            else:
                got = answer.data.mark_failed
                confirmation = "yes" if got else "no"
            answers.append(got)
            if confirmation != "yes":
                recorded = "unsure"
                note = (f"The fail was not confirmed (answer: {confirmation}), so part "
                        f"{part_id} was recorded as unsure.")
        return Record(image_id=image_id, part_id=part_id, ai_verdict=verdict,
                      fail_confirmation=confirmation, verdict=recorded, note=note)

    return mcp, answers
