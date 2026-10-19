"""Tests for the cameras, without hardware: the real camera's device is replaced by a
stand-in that delivers numbered frames, so a test can tell which frame it got.

    pytest -q
"""

import threading
import time
from types import SimpleNamespace

import cv2
import numpy as np
import pytest
from PIL import Image

from inspection_server import camera as cameras
from inspection_server.camera import (
    CameraError,
    FakeCamera,
    RealCamera,
    camera_sizes,
    parse_size,
    suggested_size,
)
from inspection_server.server import main


class StandIn:
    """Replaces OpenCV's VideoCapture: frame n is a small picture with every pixel n."""

    def __init__(self, opens=True, period=0.02, frames=None, size=(64, 48), sizes=()):
        self.opens, self.period, self.frames, self.size = opens, period, frames, size
        self.sizes = sizes   # what it offers, for set(): the nearest one is taken
        self.n = 0
        self.released = False
        self.asked = [0, 0]

    def isOpened(self):
        return self.opens

    def set(self, setting, value):
        self.asked[setting == cv2.CAP_PROP_FRAME_HEIGHT] = value
        if setting == cv2.CAP_PROP_FRAME_HEIGHT and self.sizes:
            self.size = min(self.sizes, key=lambda s: abs(s[0] - self.asked[0])
                            + abs(s[1] - self.asked[1]))
        return True

    def get(self, setting):
        return self.size[setting == cv2.CAP_PROP_FRAME_HEIGHT]

    def read(self):
        time.sleep(self.period)
        if self.frames is not None and self.n >= self.frames:   # unplugged
            return False, None
        self.n += 1
        return True, np.full((self.size[1], self.size[0], 3), self.n, np.uint8)

    def release(self):
        self.released = True


def stand_in_camera(monkeypatch, idle=0.5, **stand_in):
    """A real camera whose device is a stand-in; also the list of devices it opened."""
    opened = []

    def open_device(self):
        opened.append(StandIn(**stand_in))
        return opened[-1]

    monkeypatch.setattr(RealCamera, "_open", open_device)
    camera = RealCamera("stand-in", (64, 48), idle=idle)
    camera.WARM_UP = 5
    return camera, opened


def number(photo: Image.Image) -> int:
    return photo.getpixel((0, 0))[0]


def test_a_photo_waits_for_the_exposure_to_settle_the_live_view_does_not(monkeypatch):
    camera, _ = stand_in_camera(monkeypatch)
    assert number(camera.view()) < camera.WARM_UP
    assert number(camera.take()) >= camera.WARM_UP


def test_a_photo_is_a_frame_that_arrived_after_the_call(monkeypatch):
    camera, _ = stand_in_camera(monkeypatch, period=0.05)
    first = number(camera.take())
    assert number(camera.take()) > first   # not the frame that was already there


def test_photos_and_live_view_share_one_open_camera(monkeypatch):
    camera, opened = stand_in_camera(monkeypatch)
    for _ in range(3):
        camera.view()
        camera.take()
    assert len(opened) == 1 and not opened[0].released


def test_the_camera_is_released_when_unused_and_opened_again(monkeypatch):
    camera, opened = stand_in_camera(monkeypatch)
    camera.take()
    deadline = time.monotonic() + 3
    while not opened[0].released and time.monotonic() < deadline:
        time.sleep(0.02)
    assert opened[0].released
    camera.take()
    assert len(opened) == 2


def test_a_camera_that_does_not_open_is_tried_again_on_the_next_call(monkeypatch):
    camera, opened = stand_in_camera(monkeypatch, opens=False)
    for _ in range(2):
        with pytest.raises(CameraError, match="does not open"):
            camera.take()
    assert len(opened) == 2


def test_a_camera_that_stops_sending_gives_a_readable_error(monkeypatch):
    camera, opened = stand_in_camera(monkeypatch, frames=2)
    with pytest.raises(CameraError, match="returned no picture"):
        camera.take()
    assert opened[0].released


def test_a_camera_failure_reaches_the_caller_waiting_even_if_another_comes_in(monkeypatch):
    camera = RealCamera("stand-in", (64, 48), idle=0.5)
    camera.WARM_UP, camera.TIMEOUT = 5, 0.3
    newcomer = threading.Thread(target=lambda: camera.view())   # the live view, say

    class Failing(StandIn):
        def release(self):   # the reader has noted the error and not yet finished
            newcomer.start()
            newcomer.join()
            super().release()

    devices = iter([Failing(frames=2), StandIn(period=1)])   # opened again: slow
    monkeypatch.setattr(RealCamera, "_open", lambda self: next(devices))
    with pytest.raises(CameraError, match="returned no picture"):   # not "sent no picture"
        camera.take()


def test_a_slow_camera_is_waited_for_as_long_as_frames_keep_coming(monkeypatch):
    camera, _ = stand_in_camera(monkeypatch, period=0.2)
    camera.TIMEOUT = 0.6   # less than the five frames of warm-up take
    assert number(camera.take()) >= camera.WARM_UP


@pytest.mark.parametrize("size", [(32, 24), (64, 36)], ids=["smaller", "same width, less high"])
def test_a_camera_that_sends_another_size_than_chosen_is_refused(monkeypatch, size):
    camera, _ = stand_in_camera(monkeypatch, size=size)
    with pytest.raises(CameraError, match=f"sends photos of {size[0]}x{size[1]} pixels, "
                                          "not the 64x48 chosen"):
        camera.take()


def test_the_rate_of_frames_is_measured_while_the_camera_is_open(monkeypatch):
    camera, _ = stand_in_camera(monkeypatch, period=0.05)
    assert camera.rate() is None
    camera.take()
    assert 1 < camera.rate() < 25    # 20 a second at most; fewer on a slow machine


C922 = [(2304, 1536), (2304, 1296), (1920, 1080), (1600, 896), (1280, 720), (640, 480)]


def test_sizes_are_written_like_1920x1080():
    assert parse_size("1920x1080") == parse_size(" 1920 X 1080 ") == (1920, 1080)
    assert parse_size("1920") is None and parse_size("big") is None


def test_the_suggested_size_is_full_hd_or_the_largest_inside_it_never_simply_the_largest():
    assert suggested_size(C922) == (1920, 1080)
    assert suggested_size([(1280, 960), (1280, 720), (640, 480)]) == (1280, 960)   # C270
    assert suggested_size([(3840, 2160), (2560, 1440)]) == (2560, 1440)   # none fits: smallest


def test_the_sizes_are_listed_largest_first_without_the_tiny_ones(monkeypatch):
    monkeypatch.setattr("inspection_server.camera.sys.platform", "linux")
    monkeypatch.setattr(cameras, "_linux_sizes", lambda device: [(320, 240), (640, 480),
                                                                   (1920, 1080), (1280, 720)])
    assert camera_sizes("any") == [(1920, 1080), (1280, 720), (640, 480)]


def test_a_camera_with_only_tiny_sizes_is_refused_with_the_reason(monkeypatch):
    monkeypatch.setattr("inspection_server.camera.sys.platform", "linux")
    monkeypatch.setattr(cameras, "_linux_sizes", lambda device: [(320, 240)])
    with pytest.raises(CameraError, match="offers no photo size of at least 640 pixels across"):
        camera_sizes("any")


def test_on_windows_and_macos_the_sizes_are_found_by_asking_for_common_ones(monkeypatch):
    monkeypatch.setattr("inspection_server.camera.sys.platform", "win32")
    monkeypatch.setattr(RealCamera, "_open", lambda self: StandIn(sizes=C922))
    assert camera_sizes("USB Camera") == [(2304, 1536), (1920, 1080), (1600, 896),
                                          (1280, 720), (640, 480)]   # 2304x1296: not asked


def test_a_camera_that_is_not_there_is_refused_without_opening_it(monkeypatch, tmp_path):
    monkeypatch.setattr(RealCamera, "_open", lambda self: pytest.fail("the camera was opened"))
    monkeypatch.setattr("inspection_server.camera.sys.platform", "linux")
    (tmp_path / "camera").touch()
    RealCamera(str(tmp_path / "camera")).check()
    with pytest.raises(CameraError, match="No camera at"):
        RealCamera(str(tmp_path / "unplugged")).check()


def test_on_windows_and_macos_the_setting_must_match_exactly_one_camera(monkeypatch):
    listed = [SimpleNamespace(name="USB Camera", path="usb#1"),
              SimpleNamespace(name="USB Camera", path="usb#2"),
              SimpleNamespace(name="OBS Virtual Camera", path="obs")]
    monkeypatch.setattr("inspection_server.camera._enumerate", lambda: listed)
    monkeypatch.setattr("inspection_server.camera.sys.platform", "win32")
    RealCamera("usb#2").check()
    for device, count in (("USB Camera", 2), ("Webcam", 0)):
        with pytest.raises(CameraError, match=f"{count} cameras match"):
            RealCamera(device).check()


@pytest.mark.usefixtures("server_must_not_start")
def test_the_server_does_not_start_without_its_camera(monkeypatch):
    monkeypatch.setattr("inspection_server.camera.sys.platform", "linux")
    monkeypatch.setenv("CAMERA", "no-such-camera")
    monkeypatch.setenv("CAMERA_SIZE", "640x480")   # without it, the start stops sooner
    monkeypatch.setattr("sys.argv", ["inspection-server"])
    with pytest.raises(SystemExit) as stop:
        main()
    assert "No camera at no-such-camera" in str(stop.value.code)


def test_the_fake_camera_sees_the_photo_it_serves_next(tmp_path):
    Image.new("RGB", (640, 480)).save(tmp_path / "a.jpg")
    Image.new("RGB", (320, 240)).save(tmp_path / "b.jpg")
    camera = FakeCamera(tmp_path)
    assert camera.view().size == camera.view().size == (640, 480)
    assert camera.take().size == (640, 480)
    assert camera.view().size == camera.take().size == (320, 240)
    assert camera.view().size == (640, 480)   # then from the start
