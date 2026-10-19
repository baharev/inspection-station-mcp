"""Which camera the server uses, and the size of its photos: chosen by a person, never guessed.

A person chooses them once in two menus (a number to type: the camera, then the size from
those it offers, with a suggestion that Enter takes), and the choice is saved, so later
starts use it without asking. The settings CAMERA and CAMERA_SIZE, if set, come first.
What is saved is the camera's name or path, never its number in the menu: numbers change
when devices are plugged in. Where nobody can answer the menu (Claude Code starting the
server, or a server started without a terminal), the server stops with the reason
instead of guessing.
"""

import json
import os
import sys
from pathlib import Path

from inspection_server.camera import (
    CameraError,
    camera_sizes,
    list_cameras,
    parse_size,
    size_text,
    suggested_size,
)

SETTINGS_FILE = Path.home() / ".config" / "inspection-server" / "settings.json"
FAKE = "fake"
SAMPLE_PHOTOS = "Sample photos, no camera (the fake camera)"
CHOOSE = "inspection-server --choose-camera"
FROM_CAMERA = "set by CAMERA"


class Choice:
    """A camera to start with: its setting (what CAMERA would be), what to call it, and
    the size of its photos (None for the sample photos, which have their own)."""

    def __init__(self, device: str, name: str, source: str,
                 size: tuple[int, int] | None = None):
        self.device, self.name, self.source, self.size = device, name, source, size

    def describe(self) -> str:
        size = f", photos of {size_text(self.size)} pixels" if self.size else ""
        return f"Camera: {self.name}{size}, {self.source}"


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
                      f"chosen earlier; to choose another: {CHOOSE}",
                      parse_size(settings.get("size") or ""))
    except KeyError:
        return None


def save(choice: Choice, path: Path | None = None) -> None:
    write_settings({"camera": choice.device, "camera_name": choice.name,
                    "size": size_text(choice.size) if choice.size else None}, path)


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


def sizes_of(device: str) -> list[tuple[int, int]]:
    """The sizes the camera offers; stops the start if it cannot tell or offers none."""
    try:
        return camera_sizes(device)
    except CameraError as err:
        sys.exit(str(err))


def ask_size(sizes: list[tuple[int, int]], read=input, say=print) -> tuple[int, int]:
    """Shows the sizes and returns the one whose number the person types (Enter: the
    suggested one)."""
    suggested = suggested_size(sizes)
    say("Which photo size? Larger photos show more detail when the AI zooms in; the live "
        "view then shows fewer pictures a second.")
    for n, size in enumerate(sizes, 1):
        say(f"  {n:>{len(str(len(sizes)))}}  {size_text(size)}"
            + ("  (suggested)" if size == suggested else ""))
    while True:
        try:
            answer = read(f"Type its number (1 to {len(sizes)}), or press Enter for "
                          f"{size_text(suggested)}: ").strip()
        except (EOFError, KeyboardInterrupt):
            sys.exit("\nNo photo size chosen; the server did not start.")
        if not answer:
            return suggested
        if answer.isdigit() and 1 <= int(answer) <= len(sizes):
            return sizes[int(answer) - 1]
        say(f"Please type a number from 1 to {len(sizes)}, or just press Enter.")


def for_start(choose: bool, can_ask: bool, path: Path | None = None,
              read=input, say=print) -> Choice:
    """The camera to start with: CAMERA if set, else the saved choice, else the menu; and
    the size of its photos: CAMERA_SIZE if set, else the saved one, else the size menu.

    choose: show the menus even if a camera was chosen earlier (--choose-camera).
    can_ask: someone can answer the menus in a terminal.
    """
    size = size_setting()
    if choose:
        settings_unset()
    if device := os.environ.get("CAMERA", "").strip():
        return from_setting(device, size)
    path = path or SETTINGS_FILE
    earlier = None if choose else saved(path)
    if earlier and (earlier.device == FAKE or earlier.size or size):   # nothing to ask
        earlier.size = None if earlier.device == FAKE else size or earlier.size
        return earlier
    return from_menus(earlier, size, can_ask, path, read, say)


def size_setting() -> tuple[int, int] | None:
    """The photo size in CAMERA_SIZE, if set; stops the start if it cannot be read."""
    setting = os.environ.get("CAMERA_SIZE", "").strip()
    size = parse_size(setting)
    if setting and not size:
        sys.exit(f"CAMERA_SIZE is {setting!r}; write it as width x height in pixels, "
                 "like 1920x1080.")
    return size


def settings_unset() -> None:
    """Stops the start if CAMERA or CAMERA_SIZE is set: either would win over the menus."""
    for setting in ("CAMERA", "CAMERA_SIZE"):
        if os.environ.get(setting, "").strip():
            sys.exit(f"The setting {setting} is set in this terminal, and it comes before "
                     "any choice made in the menu. Remove it first (Linux and macOS: "
                     f"unset {setting}; PowerShell: Remove-Item Env:{setting}), then start "
                     "again.")


def from_setting(device: str, size: tuple[int, int] | None) -> Choice:
    """The camera in CAMERA; a real one needs its photo size in CAMERA_SIZE too."""
    if device == FAKE:
        return Choice(device, SAMPLE_PHOTOS, FROM_CAMERA)
    if not size:
        sizes = ", ".join(size_text(s) for s in sizes_of(device))
        sys.exit(f"CAMERA is set, so set CAMERA_SIZE too: the size of the photos, one of "
                 f"those this camera offers: {sizes}.")
    return Choice(device, device, FROM_CAMERA, size)


def from_menus(earlier: Choice | None, size: tuple[int, int] | None, can_ask: bool,
               path: Path, read, say) -> Choice:
    """Asks the camera and its photo size, and saves them; for a camera chosen before
    photo sizes could be chosen (earlier), asks only the size. CAMERA_SIZE, if set,
    stands in for the size menu."""
    if not can_ask and earlier:
        sys.exit(f"No photo size chosen yet. Choose it once, in a terminal: {CHOOSE} "
                 "(or set CAMERA_SIZE, like 1920x1080).")
    if not can_ask:
        sys.exit(f"No camera chosen yet. Choose one once, in a terminal: {CHOOSE} "
                 "(or set CAMERA; CAMERA=fake serves the sample photos).")
    if earlier:
        choice = earlier
        say(f"Camera: {choice.name}, chosen earlier.")
    else:
        device, name = ask(menu_entries(), read, say)
        choice = Choice(device, name, f"chosen now; to choose another: {CHOOSE}")
    if choice.device != FAKE and not size:
        say("Asking the camera which photo sizes it offers; this can take a few seconds.")
        choice.size = ask_size(sizes_of(choice.device), read, say)
    save(choice, path)   # CAMERA_SIZE is not saved: like CAMERA, it counts while it is set
    if choice.size or choice.device == FAKE:
        say(f"Saved in {path}: from now on the server starts with this choice without asking.")
    else:
        say(f"Saved in {path}, without a photo size: CAMERA_SIZE gives it while it is set.")
        choice.size = size
    return choice
