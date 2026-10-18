"""The cameras: the real USB webcam, and a fake one that serves stored photos.

Both have two methods that return a Pillow image: take(), a photo, and view(), what the
camera sees now, for the live view. The server does not care which camera it talks to.
"""

import re
import sys
import threading
import time
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
    # Windows: DirectShow. The OpenCV wheels for Windows (4.14, 5.0) leave out Media
    # Foundation: cameras are listed through it, but OpenCV cannot open them with it.
    return enumerate_cameras(cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_AVFOUNDATION)


def list_cameras() -> list[tuple[str, str]]:
    """The cameras found, as (device, name). The device is what CAMERA is set to."""
    if sys.platform != "linux":
        return [(c.path, c.name) for c in _enumerate()]
    return [(str(path), _linux_name(path))
            for path in sorted(Path("/dev/v4l/by-id").glob("*-video-index0"))]


# Sizes tried on Windows and macOS, whose camera lists give no sizes: the camera answers
# each with the nearest size it has. Linux asks the camera for its own list instead.
COMMON_SIZES = [(640, 480), (800, 600), (1024, 768), (1280, 720), (1280, 960), (1280, 1024),
                (1600, 900), (1600, 1200), (1920, 1080), (2048, 1536), (2304, 1536),
                (2560, 1440), (2592, 1944), (3264, 2448), (3840, 2160)]
MIN_WIDTH = 640           # smaller photos show too little for an inspection
SUGGESTED = (1920, 1080)  # the suggested size: this, else the largest that fits inside it


def parse_size(text: str) -> tuple[int, int] | None:
    """'1920x1080' as (1920, 1080); None if it is not written like that."""
    if match := re.fullmatch(r"\s*(\d+)\s*[xX×]\s*(\d+)\s*", text or ""):
        return int(match[1]), int(match[2])
    return None


def size_text(size: tuple[int, int]) -> str:
    return f"{size[0]}x{size[1]}"


def camera_sizes(device: str) -> list[tuple[int, int]]:
    """The photo sizes the camera offers, largest first, from MIN_WIDTH pixels across."""
    sizes = _linux_sizes(device) if sys.platform == "linux" else _probed_sizes(device)
    return sorted({s for s in sizes if s[0] >= MIN_WIDTH}, key=lambda s: (s[0] * s[1], s[0]),
                  reverse=True)


def suggested_size(sizes: list[tuple[int, int]]) -> tuple[int, int]:
    """SUGGESTED if offered, else the largest size that fits inside it, else the smallest.

    Never simply the largest: cameras offer sizes their sensor does not have, enlarged
    from a smaller picture (the Logitech C922's 2304x1536 shows less than its 1920x1080).
    """
    fitting = [s for s in sizes if s[0] <= SUGGESTED[0] and s[1] <= SUGGESTED[1]]
    return max(fitting, key=lambda s: s[0] * s[1]) if fitting else min(
        sizes, key=lambda s: s[0] * s[1])


def _linux_sizes(device: str) -> list[tuple[int, int]]:
    """The camera's own list of sizes in the format the server reads (YUYV), through V4L2.

    Works while another program reads the camera too.
    """
    import fcntl
    import struct

    yuyv = int.from_bytes(b"YUYV", "little")
    enum_framesizes = (3 << 30) | (44 << 16) | (ord("V") << 8) | 74   # VIDIOC_ENUM_FRAMESIZES
    sizes = []
    try:
        with open(device, "rb", buffering=0) as camera:
            for index in range(200):
                answer = bytearray(struct.pack("<3I", index, yuyv, 0) + bytes(32))
                try:
                    fcntl.ioctl(camera, enum_framesizes, answer)
                except OSError:   # the end of the list
                    break
                kind, *numbers = struct.unpack_from("<3I6I", answer)[2:]
                if kind == 1:   # a fixed size
                    sizes.append((numbers[0], numbers[1]))
                    continue
                # Any size within limits (rare in webcams): the common ones that fit.
                low_w, high_w, _, low_h, high_h, _ = numbers
                sizes += [(w, h) for w, h in COMMON_SIZES + [(high_w, high_h)]
                          if low_w <= w <= high_w and low_h <= h <= high_h]
                break
    except OSError as err:
        raise CameraError(f"Cannot read which sizes the camera {device} offers: {err}") from None
    return sizes


def _probed_sizes(device: str) -> list[tuple[int, int]]:
    """Windows and macOS: asks the camera for each common size and keeps what it gives."""
    import cv2

    camera = RealCamera(device)._open()
    try:
        if not camera.isOpened():
            raise CameraError(f"The camera {device} does not open. Is it plugged in, or is "
                              "another program using it (the server, say)?")
        sizes = set()
        for width, height in COMMON_SIZES:
            camera.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            camera.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            sizes.add((int(camera.get(cv2.CAP_PROP_FRAME_WIDTH)),
                       int(camera.get(cv2.CAP_PROP_FRAME_HEIGHT))))
    finally:
        camera.release()
    return list(sizes)


def _linux_name(path: Path) -> str:
    """Maker and model as udev knows them, and whether the camera is built in."""
    import subprocess

    def properties(*where):
        out = subprocess.run(["udevadm", "info", "--query=property", *where],
                             capture_output=True, text=True).stdout
        return dict(line.split("=", 1) for line in out.splitlines() if "=" in line)

    # Some systems keep the names from the database (lsusb's list) only on the USB device,
    # one level above the video device.
    usb_device = Path(f"/sys/class/video4linux/{path.resolve().name}/device/..").resolve()
    props = properties(f"--path={usb_device}") | properties(f"--name={path.resolve()}")

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
    macOS (macOS not tested yet): by its name or device path (macOS: its unique ID), as
    list_cameras() shows them.

    Only one program at a time can read a camera, so this object alone owns it: on first
    use a background thread opens the camera and keeps reading frames, and photos and the
    live view both take the latest one. The camera is released after `idle` seconds
    without use; the next use opens it again.
    """

    WARM_UP = 20     # frames read after opening before the first photo: the auto-exposure settles
    TIMEOUT = 15     # seconds to wait for the next frame

    def __init__(self, device: str, size: tuple[int, int] = (1280, 720), idle: float = 60):
        self.device, self.size, self.idle = device, size, idle
        self._lock = threading.Condition()
        self._reader = None     # the thread reading the camera, while it is open
        self._frame = None      # the latest frame, as OpenCV gives it (BGR)
        self._time = 0.0        # when it arrived
        self._count = 0         # frames read since the camera was opened
        self._error = ""        # why the reader stopped, if it failed
        self._last_use = 0.0
        self._rate = None       # frames a second the camera sends, once measured

    def _open(self):
        import cv2  # only needed with real hardware

        if sys.platform == "linux":
            camera = cv2.VideoCapture(self.device, cv2.CAP_V4L2)
            # MJPG gives garbled frames on the Logitech C270; the uncompressed format is clean.
            camera.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"YUYV"))
            return camera
        found = self._find()
        return cv2.VideoCapture(found.index, found.backend)

    def _find(self):
        """Windows and macOS: the one camera that CAMERA names, as listed by its system."""
        found = [c for c in _enumerate() if self.device in (c.name, c.path)]
        if len(found) != 1:
            raise CameraError(f"{len(found)} cameras match {self.device!r}; set CAMERA to exactly "
                              "one, as scripts/check_camera.py lists them.")
        return found[0]

    def check(self) -> None:
        """Refuses a camera that is not there, without opening it (the server's start)."""
        if sys.platform != "linux":
            self._find()
        elif not Path(self.device).exists():
            raise CameraError(f"No camera at {self.device}. Is it plugged in? "
                              "python scripts/check_camera.py lists the cameras.")

    def _read(self) -> None:
        """The background thread: reads frames until the camera has not been used for a while."""
        import cv2

        camera = None
        try:
            camera = self._open()
            if not camera.isOpened():
                raise CameraError(f"The camera {self.device} does not open. Is it plugged in, "
                                  "or is another program using it?")
            camera.set(cv2.CAP_PROP_FRAME_WIDTH, self.size[0])
            camera.set(cv2.CAP_PROP_FRAME_HEIGHT, self.size[1])
            times = []   # when the last frames arrived, to measure the rate
            while True:
                with self._lock:
                    if time.monotonic() - self._last_use > self.idle:
                        return
                ok, frame = camera.read()
                if not ok:
                    raise CameraError(f"The camera {self.device} returned no picture.")
                if (frame.shape[1], frame.shape[0]) != self.size:   # never another size
                    raise CameraError(
                        f"The camera {self.device} sends photos of {frame.shape[1]}x"
                        f"{frame.shape[0]} pixels, not the {size_text(self.size)} chosen. "
                        "Choose a size it offers: inspection-server --choose-camera")
                times = times[-29:] + [time.monotonic()]
                with self._lock:
                    if len(times) > 1:
                        self._rate = (len(times) - 1) / (times[-1] - times[0])
                    self._frame, self._time, self._count = frame, time.monotonic(), self._count + 1
                    self._lock.notify_all()
        except Exception as err:  # the waiting callers report it
            with self._lock:
                self._error = str(err) if isinstance(err, CameraError) else (
                    f"The camera {self.device} failed: {err}")
        finally:
            if camera is not None:
                camera.release()
            with self._lock:
                self._reader, self._frame, self._rate = None, None, None
                self._lock.notify_all()

    def _wait(self, ready) -> Image.Image:
        """The latest frame once ready(frame time, frames since opening) is true."""
        import cv2

        start = time.monotonic()
        with self._lock:
            self._error = ""
            while True:
                self._last_use = time.monotonic()
                if self._error:
                    raise CameraError(self._error)
                if self._frame is not None and ready(self._time, self._count):
                    frame = self._frame
                    break
                if self._reader is None:   # closed, or closing after a minute without use
                    self._count = 0
                    self._reader = threading.Thread(target=self._read, daemon=True)
                    self._reader.start()
                # Counted from the latest frame: a slow camera (large photos) is waited for.
                if not self._lock.wait(max(start, self._time) + self.TIMEOUT - time.monotonic()):
                    raise CameraError(f"The camera {self.device} sent no picture for "
                                      f"{self.TIMEOUT} seconds.")
        return Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))

    def take(self) -> Image.Image:
        """A photo: the first frame that arrives after this call, once the exposure has settled."""
        start = time.monotonic()
        return self._wait(lambda t, n: t > start and n >= self.WARM_UP)

    def view(self) -> Image.Image:
        """The latest frame, for the live view (also while the exposure settles)."""
        return self._wait(lambda t, n: True)

    def rate(self) -> float | None:
        """How many frames a second the camera sends, if it is open and measured."""
        with self._lock:
            return self._rate


class FakeCamera:
    """Serves the JPEG photos in a folder, one per photo taken, in name order, then from the
    start. It "sees" the photo it will serve next, as if each new part were put in front of
    it right after the previous photo."""

    def __init__(self, folder: str | Path):
        self.folder = Path(folder)
        self._photos = None
        self._next = 0
        self._lock = threading.Lock()

    def _load(self, advance: bool) -> Image.Image:
        with self._lock:
            if self._photos is None:
                self._photos = sorted(self.folder.glob("*.jpg"))
            if not self._photos:
                raise CameraError(f"The fake camera has no photos: no .jpg files in {self.folder}")
            path = self._photos[self._next]
            if advance:
                self._next = (self._next + 1) % len(self._photos)
        with Image.open(path) as photo:
            return photo.convert("RGB")

    def take(self) -> Image.Image:
        return self._load(advance=True)

    def view(self) -> Image.Image:
        return self._load(advance=False)

    def rate(self) -> None:
        return None   # stored photos: no frames a second
