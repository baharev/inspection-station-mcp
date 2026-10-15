"""The cameras: the real USB webcam, and a fake one that serves stored photos.

Both have one method, take(), which returns a Pillow image. The server does not
care which one it talks to.
"""

import re
import sys
from itertools import cycle
from pathlib import Path

from PIL import Image


class CameraError(Exception):
    """The camera could not deliver a photo; the message says why."""


def _enumerate():
    """Windows and macOS: the cameras with their names, through cv2-enumerate-cameras."""
    if sys.platform not in ("win32", "darwin"):
        raise CameraError("Real cameras work on Linux, Windows and macOS only; use CAMERA=fake here.")
    import cv2
    from cv2_enumerate_cameras import enumerate_cameras
    return enumerate_cameras(cv2.CAP_MSMF if sys.platform == "win32" else cv2.CAP_AVFOUNDATION)


def list_cameras() -> list[tuple[str, str]]:
    """The cameras found, as (device, name). The device is what CAMERA is set to."""
    if sys.platform != "linux":
        return [(c.path, c.name) for c in _enumerate()]
    return [(str(path), _linux_name(path))
            for path in sorted(Path("/dev/v4l/by-id").glob("*-video-index0"))]


def _linux_name(path: Path) -> str:
    """Maker and model as udev knows them, and whether the camera is built in."""
    import subprocess

    out = subprocess.run(["udevadm", "info", "--query=property", f"--name={path.resolve()}"],
                         capture_output=True, text=True).stdout
    props = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)

    def text(key):  # the database name (lsusb's list), else the device's own, \x-escaped
        if value := props.get(f"{key}_FROM_DATABASE"):
            return value
        raw = props.get(f"{key}_ENC", "").encode()
        return re.sub(rb"\\x([0-9a-f]{2})", lambda m: bytes([int(m[1], 16)]), raw).decode(
            "utf-8", "replace").strip()

    removable = Path(f"/sys/class/video4linux/{path.resolve().name}/device/../removable")
    where = {"fixed": "built in", "removable": "plugged in"}.get(
        removable.read_text().strip() if removable.exists() else "", "built in or plugged in: unknown")
    return f"{text('ID_VENDOR')} {text('ID_MODEL')} ({where})".strip()


class RealCamera:
    """A webcam, always chosen by name, never by a number (numbers change when devices
    are plugged in). Linux: a V4L2 camera by its stable /dev/v4l/by-id/ path. Windows and
    macOS (not tested yet): by its name or device path (macOS: its unique ID), as
    list_cameras() shows them."""

    def __init__(self, device: str, width: int = 1280, height: int = 720):
        self.device, self.width, self.height = device, width, height

    def _open(self):
        import cv2  # only needed with real hardware

        if sys.platform == "linux":
            camera = cv2.VideoCapture(self.device, cv2.CAP_V4L2)
            # MJPG gives garbled frames on the Logitech C270; the uncompressed format is clean.
            camera.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"YUYV"))
            return camera
        found = [c for c in _enumerate() if self.device in (c.name, c.path)]
        if len(found) != 1:
            raise CameraError(f"{len(found)} cameras match {self.device!r}; set CAMERA to exactly "
                              "one, as scripts/check_camera.py lists them.")
        return cv2.VideoCapture(found[0].index, found[0].backend)

    def take(self) -> Image.Image:
        import cv2

        camera = self._open()
        if not camera.isOpened():
            raise CameraError(f"The camera {self.device} does not open. Is it plugged in?")
        try:
            camera.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            camera.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            for _ in range(20):  # let the auto-exposure settle
                ok, frame = camera.read()
        finally:
            camera.release()
        if not ok:
            raise CameraError(f"The camera {self.device} opened but returned no picture.")
        return Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))


class FakeCamera:
    """Serves the JPEG photos in a folder, one per call, in name order, then from the start."""

    def __init__(self, folder: str | Path):
        self.folder = Path(folder)
        self._photos = None

    def take(self) -> Image.Image:
        if self._photos is None:
            files = sorted(self.folder.glob("*.jpg"))
            if not files:
                raise CameraError(f"The fake camera has no photos: no .jpg files in {self.folder}")
            self._photos = cycle(files)
        with Image.open(next(self._photos)) as photo:
            return photo.convert("RGB")
