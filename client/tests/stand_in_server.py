"""A stand-in for the camera server in the tests: the same three tools, seen from outside.

The app depends only on what any camera server offers over MCP: the tool names and
arguments, a photo's ID in the text "Photo <ID> ...", a refusal as a tool error, and a
yes-or-no question before a fail is recorded. So the tests need neither the real server
(repository inspection-mcp-server) nor a camera. What the stand-in got is kept in `answers`.
"""

import io
from typing import Annotated, Literal

from mcp.server import MCPServer
from mcp.server.elicitation import AcceptedElicitation, ElicitationResult
from mcp.server.mcpserver import Elicit, Image, Resolve
from mcp.server.mcpserver.exceptions import ToolError
from PIL import Image as PILImage
from pydantic import BaseModel


class Confirmation(BaseModel):
    record: bool


def photo(shade: int = 200) -> bytes:
    buffer = io.BytesIO()
    PILImage.new("RGB", (64, 48), (shade, shade, shade)).save(buffer, "JPEG")
    return buffer.getvalue()


def stand_in_server():
    """The stand-in server, and the list of what the person answered (as the server saw it)."""
    answers = []
    mcp = MCPServer("stand-in", instructions="Take photos with capture_image, look closer "
                                             "with zoom_image, record with record_inspection.")
    taken = 0

    @mcp.tool()
    async def capture_image() -> list:
        """Take a photo."""
        nonlocal taken
        taken += 1
        return [f"Photo p{taken} (64x48 pixels)",   # each photo a shade of its own
                Image(data=photo(250 - 30 * taken), format="jpeg")]

    @mcp.tool()
    async def zoom_image(image_id: str, left: float, top: float, width: float,
                         height: float) -> list:
        """Look closer at part of a photo."""
        if width < 0.05 or height < 0.05:
            raise ToolError("The rectangle is too small.")
        return [f"Photo {image_id}, enlarged", Image(data=photo(), format="jpeg")]

    def confirm_fail(image_id: str, part_id: str, verdict: str, findings: str):
        if verdict == "fail":
            return Elicit(f"Part {part_id}: {findings} Mark it FAILED?", Confirmation)

    @mcp.tool()
    async def record_inspection(
        image_id: str, part_id: str, verdict: Literal["pass", "fail", "unsure"], findings: str,
        answer: Annotated[ElicitationResult[Confirmation], Resolve(confirm_fail)],
    ) -> str:
        """Record the result of an inspection."""
        if verdict == "fail":
            answers.append(answer.data.record if isinstance(answer, AcceptedElicitation)
                           else answer.action)
        return f"Recorded part {part_id}."

    return mcp, answers
