"""Tests for the cameras, without hardware: the real camera's device is replaced by a
stand-in that delivers numbered frames, so a test can tell which frame it got.

    pytest -q
"""

import time
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from inspection_camera.camera import CameraError, FakeCamera, RealCamera
from inspection_camera.server import main


class StandIn:
    """Replaces OpenCV's VideoCapture: frame n is a small picture with every pixel n."""

    def __init__(self, opens=True, period=0.02, frames=None):
        self.opens, self.period, self.frames = opens, period, frames
        self.n = 0
        self.released = False

    def isOpened(self):
        return self.opens

    def set(self, setting, value):
        return True

    def read(self):
        time.sleep(self.period)
        if self.frames is not None and self.n >= self.frames:   # unplugged
            return False, None
        self.n += 1
        return True, np.full((48, 64, 3), self.n, np.uint8)

    def release(self):
        self.released = True


def stand_in_camera(monkeypatch, idle=0.5, **stand_in):
    """A real camera whose device is a stand-in; also the list of devices it opened."""
    opened = []

    def open_device(self):
        opened.append(StandIn(**stand_in))
        return opened[-1]

    monkeypatch.setattr(RealCamera, "_open", open_device)
    camera = RealCamera("stand-in", idle=idle)
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
    camera, opened = stand_in_camera(monkeypatch, idle=0.1)
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


def test_a_camera_that_is_not_there_is_refused_without_opening_it(monkeypatch, tmp_path):
    monkeypatch.setattr(RealCamera, "_open", lambda self: pytest.fail("the camera was opened"))
    monkeypatch.setattr("inspection_camera.camera.sys.platform", "linux")
    (tmp_path / "camera").touch()
    RealCamera(str(tmp_path / "camera")).check()
    with pytest.raises(CameraError, match="No camera at"):
        RealCamera(str(tmp_path / "unplugged")).check()


def test_on_windows_and_macos_the_setting_must_match_exactly_one_camera(monkeypatch):
    listed = [SimpleNamespace(name="USB Camera", path="usb#1"),
              SimpleNamespace(name="USB Camera", path="usb#2"),
              SimpleNamespace(name="OBS Virtual Camera", path="obs")]
    monkeypatch.setattr("inspection_camera.camera._enumerate", lambda: listed)
    monkeypatch.setattr("inspection_camera.camera.sys.platform", "win32")
    RealCamera("usb#2").check()
    for device, count in (("USB Camera", 2), ("Webcam", 0)):
        with pytest.raises(CameraError, match=f"{count} cameras match"):
            RealCamera(device).check()


def test_the_server_does_not_start_without_its_camera(monkeypatch):
    monkeypatch.setenv("CAMERA", "no-such-camera")
    monkeypatch.setattr("sys.argv", ["inspection-camera"])
    with pytest.raises(SystemExit) as stop:
        main()
    assert "no-such-camera" in str(stop.value.code)


def test_the_fake_camera_sees_the_photo_it_serves_next(tmp_path):
    Image.new("RGB", (640, 480)).save(tmp_path / "a.jpg")
    Image.new("RGB", (320, 240)).save(tmp_path / "b.jpg")
    camera = FakeCamera(tmp_path)
    assert camera.view().size == camera.view().size == (640, 480)
    assert camera.take().size == (640, 480)
    assert camera.view().size == camera.take().size == (320, 240)
    assert camera.view().size == (640, 480)   # then from the start
