"""Take one test photo with a real camera and save it to captures/, without MCP.

    python scripts/check_camera.py /dev/v4l/by-id/<your camera>-video-index0

Without an argument it lists the cameras found. The photo is real: look at it before
sharing it anywhere (captures/ is git-ignored).
"""

import sys
from datetime import datetime
from pathlib import Path

from inspection_camera.camera import CameraError, RealCamera

if len(sys.argv) != 2:
    found = sorted(Path("/dev/v4l/by-id").glob("*-video-index0"))
    print("Usage: python scripts/check_camera.py <camera path>")
    print("Cameras found:" if found else "No camera found in /dev/v4l/by-id/.")
    for path in found:
        print(f"    {path}")
    sys.exit(1)

try:
    photo = RealCamera(sys.argv[1]).take()
except CameraError as err:
    sys.exit(str(err))

out = Path(__file__).resolve().parent.parent / "captures"
out.mkdir(exist_ok=True)
path = out / f"check-{datetime.now():%Y%m%d-%H%M%S}.jpg"
photo.save(path, quality=95)
print(f"{photo.width}x{photo.height} -> {path}")
