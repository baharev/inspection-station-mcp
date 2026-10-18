"""Tests for choosing the camera and its photo size (menus, the choice saved) and the
start-up instructions.

    pytest -q
"""

import json

import pytest

from inspection_server import choice
from inspection_server.server import main, next_steps

C270 = ("/dev/v4l/by-id/usb-046d_0825_1-video-index0", "Logitech Webcam C270 (plugged in)")
BUILT_IN = ("/dev/v4l/by-id/usb-Chicony_Integrated_Camera-video-index0",
            "Chicony Integrated Camera (built in)")


SIZES = [(1920, 1080), (1280, 720), (640, 480)]


def answers(*typed):
    """Stands in for the keyboard: the lines typed, one per question."""
    lines = iter(typed)
    return lambda prompt: next(lines)


def nobody(prompt):
    raise AssertionError("asked, but nobody should have been asked")


@pytest.fixture
def cameras(monkeypatch):
    """The cameras the menu finds, settable by the test; Linux unless the test says otherwise."""
    found = [C270, BUILT_IN]
    monkeypatch.setattr("inspection_server.choice.list_cameras", lambda: found)
    monkeypatch.setattr("inspection_server.choice.camera_sizes", lambda device: SIZES)
    monkeypatch.setattr("inspection_server.choice.sys.platform", "linux")
    return found


def test_a_number_chooses_the_camera_and_its_path_is_saved_not_the_number(cameras, tmp_path):
    shown = []
    picked = choice.for_start(False, True, read=answers("", "4", "two", "2", "2"),
                              say=shown.append)
    assert (picked.device, picked.name, picked.size) == (*BUILT_IN, (1280, 720))
    assert shown[1:4] == [f"  1  {C270[1]}", f"  2  {BUILT_IN[1]}", f"  3  {choice.SAMPLE_PHOTOS}"]
    assert shown.count("Please type a number from 1 to 3.") == 3
    saved = json.loads((tmp_path / "settings.json").read_text())
    assert saved == {"camera": BUILT_IN[0], "camera_name": BUILT_IN[1], "size": "1280x720"}

    again = choice.for_start(False, True, read=nobody)   # the next start does not ask
    assert (again.device, again.name, again.size) == (*BUILT_IN, (1280, 720))
    assert again.describe().startswith(f"Camera: {BUILT_IN[1]}, photos of 1280x720 pixels, "
                                       "chosen earlier")


def test_the_size_menu_suggests_one_that_enter_takes(cameras):
    shown = []
    picked = choice.for_start(False, True, read=answers("1", "9", ""), say=shown.append)
    assert picked.size == (1920, 1080)
    assert any(line.startswith("Asking the camera which photo sizes") for line in shown)
    assert "  1  1920x1080  (suggested)" in shown and "  2  1280x720" in shown
    assert "Please type a number from 1 to 3, or just press Enter." in shown


def test_the_sample_photos_need_no_size(cameras, tmp_path):
    picked = choice.for_start(False, True, read=answers("3"), say=lambda text: None)
    assert picked.device == choice.FAKE and picked.size is None
    assert choice.for_start(False, False, read=nobody).device == choice.FAKE


def test_a_camera_chosen_before_sizes_existed_is_asked_only_its_size(cameras):
    choice.write_settings({"camera": C270[0], "camera_name": C270[1]})
    with pytest.raises(SystemExit, match="No photo size chosen yet"):
        choice.for_start(False, False, read=nobody)
    picked = choice.for_start(False, True, read=answers("2"), say=lambda text: None)
    assert (picked.device, picked.size) == (C270[0], (1280, 720))
    assert choice.saved().size == (1280, 720)


def test_a_single_camera_is_still_chosen_by_a_person(cameras):
    cameras[:] = [C270]
    shown = []
    picked = choice.for_start(False, True, read=answers("1", ""), say=shown.append)
    assert shown[0] == "Which camera should the server use?"   # asked, even with one camera
    assert f"  2  {choice.SAMPLE_PHOTOS}" in shown
    assert picked.device == C270[0]


def test_without_a_person_to_ask_the_server_stops_instead_of_guessing(cameras):
    cameras[:] = [C270]
    with pytest.raises(SystemExit, match="No camera chosen yet"):
        choice.for_start(False, False, read=nobody)


def test_ctrl_c_in_the_menu_starts_nothing(cameras, tmp_path):
    def ctrl_c(prompt):
        raise KeyboardInterrupt
    with pytest.raises(SystemExit, match="No camera chosen"):
        choice.for_start(False, True, read=ctrl_c, say=lambda text: None)
    assert not (tmp_path / "settings.json").exists()


def test_choose_camera_asks_again_and_replaces_the_saved_choice(cameras):
    choice.for_start(False, True, read=answers("1", ""), say=lambda text: None)
    picked = choice.for_start(True, True, read=answers("3"), say=lambda text: None)
    assert picked.device == choice.FAKE
    assert choice.saved().device == choice.FAKE


def test_the_setting_camera_comes_before_the_saved_choice(cameras, monkeypatch):
    choice.for_start(False, True, read=answers("1", ""), say=lambda text: None)
    monkeypatch.setenv("CAMERA", "fake")
    picked = choice.for_start(False, False, read=nobody)
    assert (picked.device, picked.source) == ("fake", choice.FROM_CAMERA)
    with pytest.raises(SystemExit, match="Remove it first"):
        choice.for_start(True, True, read=nobody)


def test_a_real_camera_in_camera_needs_its_size_in_camera_size(cameras, monkeypatch):
    monkeypatch.setenv("CAMERA", C270[0])
    with pytest.raises(SystemExit, match="set CAMERA_SIZE too.*1920x1080, 1280x720, 640x480"):
        choice.for_start(False, True, read=nobody)
    monkeypatch.setenv("CAMERA_SIZE", "1280x720")
    picked = choice.for_start(False, False, read=nobody)
    assert (picked.device, picked.size, picked.source) == (C270[0], (1280, 720), choice.FROM_CAMERA)
    monkeypatch.setenv("CAMERA_SIZE", "large")
    with pytest.raises(SystemExit, match="like 1920x1080"):
        choice.for_start(False, False, read=nobody)


def test_the_setting_camera_size_comes_before_the_saved_size(cameras, monkeypatch):
    choice.for_start(False, True, read=answers("1", ""), say=lambda text: None)
    monkeypatch.setenv("CAMERA_SIZE", "640x480")
    assert choice.for_start(False, False, read=nobody).size == (640, 480)
    assert choice.saved().size == (1920, 1080)   # the saved choice is kept
    with pytest.raises(SystemExit, match="Remove-Item Env:CAMERA_SIZE"):
        choice.for_start(True, True, read=nobody)


def test_on_windows_a_camera_is_saved_by_name_unless_two_share_it(cameras, monkeypatch):
    monkeypatch.setattr("inspection_server.choice.sys.platform", "win32")
    cameras[:] = [("usb#1", "USB Camera"), ("usb#2", "USB Camera"), ("obs", "OBS Virtual Camera")]
    assert choice.menu_entries() == [("usb#1", "USB Camera"), ("usb#2", "USB Camera"),
                                     ("OBS Virtual Camera", "OBS Virtual Camera"),
                                     (choice.FAKE, choice.SAMPLE_PHOTOS)]


@pytest.mark.usefixtures("server_must_not_start")
def test_claude_code_starting_the_server_with_no_camera_chosen_gets_the_reason(monkeypatch):
    monkeypatch.setattr("sys.argv", ["inspection-server"])
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    with pytest.raises(SystemExit) as stop:
        main()
    assert "inspection-server --choose-camera" in str(stop.value.code)


@pytest.mark.usefixtures("server_must_not_start")
def test_a_chosen_camera_that_is_unplugged_stops_the_server_with_what_to_do(tmp_path, monkeypatch):
    choice.save(choice.Choice(str(tmp_path / "unplugged"), "Old Webcam (plugged in)", "",
                              (640, 480)))
    monkeypatch.setattr("sys.argv", ["inspection-server", "--http"])
    with pytest.raises(SystemExit) as stop:
        main()
    assert "The camera chosen earlier, Old Webcam (plugged in), cannot be found" in str(stop.value.code)
    assert "--choose-camera" in str(stop.value.code)


def test_the_start_shows_the_addresses_and_the_claude_code_command():
    lines = next_steps("0.0.0.0", 8000, "http", key_file=True, address="192.168.0.20")
    assert lines[:3] == [
        "Live view: http://localhost:8000/live",
        "           http://192.168.0.20:8000/live from other computers, "
        "with the secret key or a login",
        "MCP address: http://192.168.0.20:8000/mcp"]
    assert "copy the key file there first" in lines[3]
    assert lines[4] == ("  Linux, macOS: claude mcp add -s local --transport http inspection-server "
                        "http://192.168.0.20:8000/mcp --header \"Authorization: Bearer "
                        "$(cat ~/.config/inspection-server/api-key)\"")
    assert lines[5].startswith("  PowerShell:   claude mcp add")
    assert lines[5].endswith("$(Get-Content $HOME\\.config\\inspection-server\\api-key)\"")
    assert lines[6].startswith("Warning: other computers connect over plain HTTP")


def test_the_start_says_when_only_this_computer_can_connect():
    lines = next_steps("127.0.0.1", 8000, "https", key_file=True)
    assert lines[0].startswith("Only this computer can connect")
    assert "https://localhost:8000/mcp" in lines[-1]
    assert "copy the key file" not in "\n".join(lines)
    assert "Warning" not in "\n".join(lines + next_steps("127.0.0.1", 8000, "http", key_file=True))


def test_with_logins_the_start_shows_the_server_url_and_no_key_command():
    lines = next_steps("0.0.0.0", 8000, "https", key_file=False, address="192.168.0.20",
                       mcp_url="https://station.example:8000/mcp")
    assert lines[-1] == "MCP address: https://station.example:8000/mcp"   # HTTPS: no warning
