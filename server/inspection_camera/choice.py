"""Which camera the server uses: always chosen by a person, never guessed.

A person chooses it once in a menu (a number to type), and the choice is saved, so later
starts use it without asking. The setting CAMERA, if set, comes first. What is saved is
the camera's name or path, never its number in the menu: numbers change when devices are
plugged in. Where nobody can answer the menu (Claude Code starting the server, or a
server started without a terminal), the server stops with the reason instead of guessing.
"""

import json
import os
import sys
from pathlib import Path

from inspection_camera.camera import CameraError, list_cameras

SETTINGS_FILE = Path.home() / ".config" / "inspection-camera" / "settings.json"
FAKE = "fake"
SAMPLE_PHOTOS = "Sample photos, no camera (the fake camera)"
CHOOSE = "inspection-camera --choose-camera"
FROM_CAMERA = "set by CAMERA"


class Choice:
    """A camera to start with: its setting (what CAMERA would be) and what to call it."""

    def __init__(self, device: str, name: str, source: str):
        self.device, self.name, self.source = device, name, source

    def describe(self) -> str:
        return f"Camera: {self.name}, {self.source}"


def read_settings(path: Path | None = None) -> dict:
    """Everything in the settings file; empty if there is none or it cannot be read."""
    try:
        settings = json.loads((path or SETTINGS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return settings if isinstance(settings, dict) else {}


def write_settings(values: dict, path: Path | None = None) -> None:
    """Sets these values in the settings file and keeps the others (the window's, say)."""
    path = path or SETTINGS_FILE
    settings = read_settings(path) | values
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")


def saved(path: Path | None = None) -> Choice | None:
    """The camera chosen earlier, if any."""
    settings = read_settings(path)
    try:
        return Choice(settings["camera"], settings["camera_name"],
                      f"chosen earlier; to choose another: {CHOOSE}")
    except KeyError:
        return None


def save(choice: Choice, path: Path | None = None) -> None:
    write_settings({"camera": choice.device, "camera_name": choice.name}, path)


def menu_entries() -> list[tuple[str, str]]:
    """What the menu offers, as (setting, name): the cameras found, then the sample photos.

    On Windows and macOS the setting is the camera's name, which stays the same in any
    USB port; for two cameras of the same model, it is the device path instead.
    """
    try:
        found = list_cameras()
    except CameraError:   # an operating system without real cameras here
        found = []
    names = [name for _, name in found]
    entries = [(device if sys.platform == "linux" or names.count(name) > 1 else name, name)
               for device, name in found]
    return entries + [(FAKE, SAMPLE_PHOTOS)]


def ask(entries: list[tuple[str, str]], read=input, say=print) -> tuple[str, str]:
    """Shows the menu and returns the entry whose number the person types."""
    say("Which camera should the server use?")
    for n, (_, name) in enumerate(entries, 1):
        say(f"  {n}  {name}")
    if len(entries) == 1:
        say("(No camera found. Is it plugged in? Then press Ctrl+C and start again.)")
    while True:
        try:
            answer = read(f"Type its number (1 to {len(entries)}) and press Enter: ").strip()
        except (EOFError, KeyboardInterrupt):
            sys.exit("\nNo camera chosen; the server did not start.")
        if answer.isdigit() and 1 <= int(answer) <= len(entries):
            return entries[int(answer) - 1]
        say(f"Please type a number from 1 to {len(entries)}.")


def for_start(choose: bool, can_ask: bool, path: Path | None = None,
              read=input, say=print) -> Choice:
    """The camera to start with: CAMERA if set, else the saved choice, else the menu.

    choose: show the menu even if a camera was chosen earlier (--choose-camera).
    can_ask: someone can answer the menu in a terminal.
    """
    if setting := os.environ.get("CAMERA", "").strip():
        if choose:
            sys.exit("The setting CAMERA is set in this terminal, and it comes before any "
                     "choice made in the menu. Remove it first (Linux and macOS: "
                     "unset CAMERA; PowerShell: Remove-Item Env:CAMERA), then start again.")
        name = SAMPLE_PHOTOS if setting == FAKE else setting
        return Choice(setting, name, FROM_CAMERA)
    if not choose and (choice := saved(path)):
        return choice
    if not can_ask:
        sys.exit(f"No camera chosen yet. Choose one once, in a terminal: {CHOOSE} "
                 "(or set CAMERA; CAMERA=fake serves the sample photos).")
    device, name = ask(menu_entries(), read, say)
    choice = Choice(device, name, f"chosen now; to choose another: {CHOOSE}")
    path = path or SETTINGS_FILE
    save(choice, path)
    say(f"Saved in {path}: from now on the server starts with this choice without asking.")
    return choice
