"""Tests for the window that starts the server. The ones that open a window are skipped
on a computer without a screen or without Tkinter.

    pytest -q
"""

import subprocess
import sys
from pathlib import Path

import pytest

from inspection_server import choice, window

C270 = ("/dev/v4l/by-id/usb-046d_0825_1-video-index0", "Logitech Webcam C270 (plugged in)")


def test_start_runs_the_server_over_http_for_this_computer_or_for_others_too():
    assert window.server_command(False)[-4:] == ["inspection_server.server", "--http",
                                                  "--port", "8000"]
    assert window.server_command(True)[-2:] == ["--host", "0.0.0.0"]


def test_a_camera_set_in_a_terminal_does_not_override_the_one_chosen_in_the_window(monkeypatch):
    monkeypatch.setenv("CAMERA", "fake")
    monkeypatch.setenv("CAMERA_SIZE", "640x480")
    assert "CAMERA" not in window.server_environment()
    assert "CAMERA_SIZE" not in window.server_environment()


def test_the_window_and_the_terminal_keep_each_others_settings():
    choice.write_settings({window.OTHER_COMPUTERS: True})
    choice.save(choice.Choice(*C270, "", (1280, 720)))
    choice.write_settings({window.OTHER_COMPUTERS: False})
    assert choice.read_settings() == {window.OTHER_COMPUTERS: False, "camera": C270[0],
                                      "camera_name": C270[1], "size": "1280x720"}


def test_the_key_copied_is_the_one_the_server_takes(tmp_path, monkeypatch):
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.setattr(window, "KEY_FILE", tmp_path / "api-key")
    assert window.secret_key() is None   # not made yet: the server makes it
    (tmp_path / "api-key").write_text("k" * 43 + "\r\n")
    assert window.secret_key() == "k" * 43
    monkeypatch.setenv("API_KEY", "a" * 40)
    assert window.secret_key() == "a" * 40


def test_without_tkinter_the_window_says_how_to_get_it():
    # Some Linux distributions ship Tkinter separately. The window's module still loads
    # without it, so the tests above run there too.
    started = subprocess.run(
        [sys.executable, "-c", "import sys; sys.modules['tkinter'] = None; "
         "from inspection_server import window; print('loaded'); window.main()"],
        capture_output=True, text=True, cwd=Path(__file__).resolve().parent.parent)
    assert (started.stdout, started.returncode, started.stderr.strip()) == ("loaded\n", 1, (
        "This Python has no Tkinter, which the window needs. On Ubuntu and Debian: "
        f"sudo apt install python{sys.version_info.major}.{sys.version_info.minor}-tk"))


def test_the_linux_launcher_quotes_paths_with_spaces():
    entry = window.desktop_entry(["/home/a b/env/bin/python", "-m", "inspection_server.window"])
    assert 'Exec="/home/a b/env/bin/python" -m inspection_server.window\n' in entry
    assert "Exec=/opt/env/bin/inspection-server-window\n" in window.desktop_entry(
        ["/opt/env/bin/inspection-server-window"])


@pytest.fixture
def screen(monkeypatch):
    """A window on this computer's screen, with the cameras the test sets."""
    tk = pytest.importorskip("tkinter")
    try:
        root = tk.Tk()
    except tk.TclError as err:
        pytest.skip(f"no screen ({err})")
    found = [C270]
    monkeypatch.setattr("inspection_server.choice.list_cameras", lambda: found)
    monkeypatch.setattr("inspection_server.window.camera_sizes",
                        lambda device: [(1280, 960), (1280, 720), (640, 480)])
    monkeypatch.setattr("inspection_server.choice.sys.platform", "linux")
    yield root, found
    root.destroy()


def test_start_waits_until_a_camera_is_chosen_and_the_choice_is_saved(screen):
    root, _ = screen
    w = window.Window(root)
    assert w.camera["values"] == (C270[1], choice.SAMPLE_PHOTOS)
    assert str(w.start["state"]) == "disabled"
    w.camera.current(0)
    w.camera_chosen()
    assert str(w.start["state"]) == "normal"
    assert (choice.saved().device, choice.saved().name) == C270


def test_a_camera_comes_with_its_suggested_size_which_the_list_can_change(screen):
    root, _ = screen
    w = window.Window(root)
    w.camera.current(0)
    w.camera_chosen()
    assert w.size.get() == "1280x960 (suggested)" and "suggested" in w.note["text"]
    assert w.size["values"] == ("1280x960 (suggested)", "1280x720", "640x480")
    assert choice.saved().size == (1280, 960)
    w.size.current(1)
    w.size_chosen()
    assert choice.saved().size == (1280, 720)
    w.camera.current(1)   # the sample photos: no size
    w.camera_chosen()
    assert w.size.get() == "" and str(w.size["state"]) == "disabled"
    assert str(w.start["state"]) == "normal"


def test_a_camera_chosen_before_sizes_existed_waits_for_a_size(screen):
    root, _ = screen
    choice.write_settings({"camera": C270[0], "camera_name": C270[1]})
    w = window.Window(root)
    assert w.camera.current() == 0 and w.size.get() == ""
    assert str(w.start["state"]) == "disabled" and "photo size" in w.note["text"]
    assert w.list_sizes() and w.size["values"][0] == "1280x960 (suggested)"


def test_the_saved_size_is_shown(screen):
    root, _ = screen
    choice.save(choice.Choice(*C270, "", (1280, 720)))
    w = window.Window(root)
    assert w.size.get() == "1280x720" and str(w.start["state"]) == "normal"


def test_a_missing_camera_is_never_replaced_by_another(screen):
    root, found = screen
    choice.save(choice.Choice(*C270, ""))
    found.clear()   # unplugged
    w = window.Window(root)
    assert w.camera.current() == -1
    assert str(w.start["state"]) == "disabled"
    assert "cannot be found" in w.note["text"]
    assert choice.saved().device == C270[0]


def test_the_checkbox_is_remembered(screen):
    root, _ = screen
    choice.write_settings({window.OTHER_COMPUTERS: True})
    assert window.Window(root).others.get() is True
