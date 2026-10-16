"""Tests for choosing the camera (a menu, the choice saved) and the start-up instructions.

    pytest -q
"""

import json

import pytest

from inspection_camera import choice
from inspection_camera.server import main, next_steps

C270 = ("/dev/v4l/by-id/usb-046d_0825_1-video-index0", "Logitech Webcam C270 (plugged in)")
BUILT_IN = ("/dev/v4l/by-id/usb-Chicony_Integrated_Camera-video-index0",
            "Chicony Integrated Camera (built in)")


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
    monkeypatch.setattr("inspection_camera.choice.list_cameras", lambda: found)
    monkeypatch.setattr("inspection_camera.choice.sys.platform", "linux")
    return found


def test_a_number_chooses_the_camera_and_its_path_is_saved_not_the_number(cameras, tmp_path):
    shown = []
    picked = choice.for_start(False, True, read=answers("", "4", "two", "2"), say=shown.append)
    assert (picked.device, picked.name) == BUILT_IN
    assert shown[1:4] == [f"  1  {C270[1]}", f"  2  {BUILT_IN[1]}", f"  3  {choice.SAMPLE_PHOTOS}"]
    assert shown.count("Please type a number from 1 to 3.") == 3
    saved = json.loads((tmp_path / "settings.json").read_text())
    assert saved == {"camera": BUILT_IN[0], "camera_name": BUILT_IN[1]}

    again = choice.for_start(False, True, read=nobody)   # the next start does not ask
    assert (again.device, again.name) == BUILT_IN
    assert "chosen earlier" in again.describe()


def test_a_single_camera_is_still_chosen_by_a_person(cameras):
    cameras[:] = [C270]
    shown = []
    picked = choice.for_start(False, True, read=answers("1"), say=shown.append)
    assert picked.device == C270[0]
    assert f"  2  {choice.SAMPLE_PHOTOS}" in shown


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
    choice.for_start(False, True, read=answers("1"), say=lambda text: None)
    picked = choice.for_start(True, True, read=answers("3"), say=lambda text: None)
    assert picked.device == choice.FAKE
    assert choice.saved().device == choice.FAKE


def test_the_setting_camera_comes_before_the_saved_choice(cameras, monkeypatch):
    choice.for_start(False, True, read=answers("1"), say=lambda text: None)
    monkeypatch.setenv("CAMERA", "fake")
    picked = choice.for_start(False, False, read=nobody)
    assert (picked.device, picked.source) == ("fake", choice.FROM_CAMERA)
    with pytest.raises(SystemExit, match="Remove it first"):
        choice.for_start(True, True, read=nobody)


def test_on_windows_a_camera_is_saved_by_name_unless_two_share_it(cameras, monkeypatch):
    monkeypatch.setattr("inspection_camera.choice.sys.platform", "win32")
    cameras[:] = [("usb#1", "USB Camera"), ("usb#2", "USB Camera"), ("obs", "OBS Virtual Camera")]
    assert choice.menu_entries() == [("usb#1", "USB Camera"), ("usb#2", "USB Camera"),
                                     ("OBS Virtual Camera", "OBS Virtual Camera"),
                                     (choice.FAKE, choice.SAMPLE_PHOTOS)]


def test_claude_code_starting_the_server_with_no_camera_chosen_gets_the_reason(monkeypatch):
    monkeypatch.setattr("sys.argv", ["inspection-camera"])
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    with pytest.raises(SystemExit) as stop:
        main()
    assert "inspection-camera --choose-camera" in str(stop.value.code)


def test_a_chosen_camera_that_is_unplugged_stops_the_server_with_what_to_do(tmp_path, monkeypatch):
    choice.save(choice.Choice(str(tmp_path / "unplugged"), "Old Webcam (plugged in)", ""))
    monkeypatch.setattr("sys.argv", ["inspection-camera", "--http"])
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
    assert lines[4] == ("  Linux, macOS: claude mcp add -s local --transport http inspection-camera "
                        "http://192.168.0.20:8000/mcp --header \"Authorization: Bearer "
                        "$(cat ~/.config/inspection-camera/api-key)\"")
    assert lines[5].startswith("  PowerShell:   claude mcp add")
    assert lines[5].endswith("$(Get-Content $HOME\\.config\\inspection-camera\\api-key)\"")


def test_the_start_says_when_only_this_computer_can_connect():
    lines = next_steps("127.0.0.1", 8000, "https", key_file=True)
    assert lines[0].startswith("Only this computer can connect")
    assert "https://localhost:8000/mcp" in lines[-1]
    assert "copy the key file" not in "\n".join(lines)


def test_with_logins_the_start_shows_the_server_url_and_no_key_command():
    lines = next_steps("0.0.0.0", 8000, "https", key_file=False, address="192.168.0.20",
                       mcp_url="https://station.example:8000/mcp")
    assert lines[-1] == "MCP address: https://station.example:8000/mcp"
