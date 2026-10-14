"""An inspection station behind MCP: the AI takes photos, looks closer, records results.

The rules live here, not in the prompt: photo size is capped, every input is checked,
a "fail" (the part gets scrapped) needs a human's yes, and everything is audit-logged.

    inspection-camera        # stdio MCP server (started by a client such as Claude Code)

Environment:
    CAMERA       "fake" (default) or the path of a V4L2 camera, such as
                 /dev/v4l/by-id/usb-046d_0825_<serial>-video-index0
    SAMPLES_DIR  photos the fake camera serves (default: samples/)
    DATA_DIR     where photos (captures/) and logs (logs/) are kept (default: this repo)
"""

import asyncio
import io
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal

from mcp.server import MCPServer
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
    note: str = ""


def create_server(camera, data_dir: str | Path = REPO) -> MCPServer:
    captures = Path(data_dir) / "captures"
    logs = Path(data_dir) / "logs"
    captures.mkdir(parents=True, exist_ok=True)
    logs.mkdir(parents=True, exist_ok=True)
    inspection_log = logs / "inspections.jsonl"

    # Never print() in a stdio server: stdout carries the protocol. Logs go to files.
    def audit(text: str) -> None:
        with open(logs / "audit.log", "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat(timespec='seconds')} {text}\n")

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
    )

    @mcp.tool(annotations=ToolAnnotations(destructive_hint=False))
    async def capture_image() -> list:
        """Take a photo of the inspection station. Returns the photo and its ID."""
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
        )
        with open(inspection_log, "a", encoding="utf-8") as f:
            f.write(record.model_dump_json(exclude={"note"}) + "\n")
        audit(f"record_inspection {part_id} {verdict} {image_id}"
              + (" (confirmed by human)" if confirmed else ""))
        if verdict == "unsure":
            record.note = f"Recorded as unsure: a person should look at part {part_id}."
        return record

    return mcp


def main() -> None:
    device = os.environ.get("CAMERA", "fake")
    if device == "fake":
        camera = FakeCamera(os.environ.get("SAMPLES_DIR", REPO / "samples"))
    else:
        camera = RealCamera(device)
    create_server(camera, os.environ.get("DATA_DIR", REPO)).run()


if __name__ == "__main__":
    main()
