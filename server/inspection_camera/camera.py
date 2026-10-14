"""The cameras: the real USB webcam, and a fake one that serves stored photos.

Both have one method, take(), which returns a Pillow image. The server does not
care which one it talks to.
"""

from itertools import cycle
from pathlib import Path

from PIL import Image


class CameraError(Exception):
    """The camera could not deliver a photo; the message says why."""


class RealCamera:
    """A V4L2 webcam (Linux), opened by its stable /dev/v4l/by-id/ path."""

    def __init__(self, device: str, width: int = 1280, height: int = 720):
        self.device, self.width, self.height = device, width, height

    def take(self) -> Image.Image:
        import cv2  # only needed with real hardware

        camera = cv2.VideoCapture(self.device, cv2.CAP_V4L2)
        if not camera.isOpened():
            raise CameraError(f"The camera {self.device} does not open. Is it plugged in?")
        try:
            # MJPG gives garbled frames on the Logitech C270; the uncompressed format is clean.
            camera.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"YUYV"))
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
