"""Take one test photo with a real camera and save it to captures/, without MCP.

    python scripts/check_camera.py <camera>

<camera> is what CAMERA is set to: on Linux the camera's /dev/v4l/by-id/ path, on
Windows and macOS its name or device path. Without an argument it lists the cameras
found, with their names (on Linux also whether each is built in or plugged in). The
photo is real: look at it before sharing it anywhere (captures/ is git-ignored).

A running server holds its camera while it is used and for a minute after; meanwhile
this script cannot open it. To see the camera while the server runs, use the server's
live view (/live) instead.
"""

import sys
from datetime import datetime
from pathlib import Path

from inspection_camera.camera import CameraError, RealCamera, list_cameras

if len(sys.argv) != 2:
    try:
        found = list_cameras()
    except CameraError as err:
        sys.exit(str(err))
    print("Usage: python scripts/check_camera.py <camera>")
    print("Cameras found (name, then what to pass):" if found else "No camera found.")
    for device, name in found:
        print(f"    {name}\n        {device}")
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
