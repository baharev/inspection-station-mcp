"""Take one test photo with a real camera and save it to captures/, without MCP.

    python scripts/check_camera.py <camera> [<size>]

<camera> is what CAMERA is set to: on Linux the camera's /dev/v4l/by-id/ path, on
Windows and macOS its name or device path; <size> is what CAMERA_SIZE is set to, like
1920x1080 (without it, the size the server's menu suggests). Without an argument it
lists the cameras found, with their names (on Linux also whether each is built in or
plugged in) and the photo sizes each offers. The photo is real: look at it before
sharing it anywhere (captures/ is git-ignored).

A running server holds its camera while it is used and for a minute after; meanwhile
this script cannot open it. To see the camera while the server runs, use the server's
live view (/live) instead.
"""

import sys
from datetime import datetime
from pathlib import Path

from inspection_server.camera import (CameraError, RealCamera, camera_sizes, list_cameras,
                                      parse_size, size_text, suggested_size)


def sizes(device: str) -> str:
    try:
        offered = camera_sizes(device)
    except CameraError as err:
        return str(err)
    suggested = suggested_size(offered) if offered else None
    return ", ".join(size_text(s) + (" (suggested)" if s == suggested else "") for s in offered)


if len(sys.argv) not in (2, 3):
    try:
        found = list_cameras()
    except CameraError as err:
        sys.exit(str(err))
    print("Usage: python scripts/check_camera.py <camera> [<size>]")
    print("Cameras found (name, then what to pass, then the photo sizes):" if found
          else "No camera found.")
    for device, name in found:
        print(f"    {name}\n        {device}\n        {sizes(device)}")
    sys.exit(1)

device = sys.argv[1]
if len(sys.argv) == 3:
    size = parse_size(sys.argv[2]) or sys.exit(
        f"Write the size like 1920x1080, not {sys.argv[2]!r}.")
else:
    try:
        size = suggested_size(camera_sizes(device))
    except (CameraError, ValueError) as err:
        sys.exit(str(err) or "The camera offers no photo size of at least 640 pixels across.")
try:
    photo = RealCamera(device, size).take()
except CameraError as err:
    sys.exit(str(err))

out = Path(__file__).resolve().parent.parent / "captures"
out.mkdir(exist_ok=True)
path = out / f"check-{datetime.now():%Y%m%d-%H%M%S}.jpg"
photo.save(path, quality=95)
print(f"{photo.width}x{photo.height} -> {path}")
