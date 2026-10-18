"""Try the server's tools without an AI: this script plays the AI's part with fixed calls,
and you play the person's part, in the terminal.

    python scripts/try_tools.py

No server to start and no key: the server runs inside this script, with the fake camera
and a sample photo of a tool tray with its hammer missing. The script takes a photo,
zooms in on the empty slot and proposes a fail, which the server asks you to confirm.
Photos and logs go to a new temporary folder, so the station's own logs stay untouched;
the script says where, so you can open the photo and the zoom.
"""

import asyncio
import base64
import shutil
import tempfile
from pathlib import Path

from mcp import Client
from mcp.types import ElicitResult

from inspection_server.camera import FakeCamera
from inspection_server.server import create_server

PHOTO = Path(__file__).resolve().parent.parent / "samples" / "02-tray-incomplete.jpg"


async def ask_the_person(context, params) -> ElicitResult:
    """The server's question to the person (MCP elicitation), asked here in the terminal."""
    print(f"\nThe server asks you:\n{params.message}\n")
    answer = input("Mark this part as FAILED? (y/n) ").strip().lower()
    return ElicitResult(action="accept", content={"mark_failed": answer.startswith("y")})


async def main() -> None:
    folder = Path(tempfile.mkdtemp(prefix="inspection-try-"))
    (folder / "samples").mkdir()
    shutil.copy(PHOTO, folder / "samples")
    server = create_server(FakeCamera(folder / "samples"), folder)

    async with Client(server, elicitation_callback=ask_the_person) as ai:
        print("The AI calls capture_image.")
        photo = await ai.call_tool("capture_image", {})
        print("  The server answers:", photo.content[0].text)
        image_id = photo.structured_content["image_id"]

        print("The AI calls zoom_image on the empty slot at the left of the tray.")
        zoom = await ai.call_tool("zoom_image", {
            "image_id": image_id, "left": 0.15, "top": 0.25, "width": 0.2, "height": 0.6})
        print("  The server answers:", zoom.content[0].text)
        (folder / "zoom.jpg").write_bytes(base64.b64decode(zoom.content[1].data))

        print("The AI calls record_inspection with the verdict fail.")
        record = await ai.call_tool("record_inspection", {
            "image_id": image_id, "part_id": "tray-02", "verdict": "fail",
            "findings": "The hammer is missing: its slot at the left of the tray is empty."})
        print("\nThe server recorded:")
        for field, value in record.structured_content.items():
            if value != "":
                print(f"  {field}: {value}")

    print(f"\nThe photo: {folder / 'captures' / (image_id + '.jpg')}")
    print(f"The zoom:  {folder / 'zoom.jpg'}")
    print(f"The audit log, {folder / 'logs' / 'audit.log'}:")
    print((folder / "logs" / "audit.log").read_text(encoding="utf-8"), end="")


if __name__ == "__main__":
    asyncio.run(main())
