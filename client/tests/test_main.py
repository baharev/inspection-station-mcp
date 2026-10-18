"""The app's start: which key or login, address and certificates its parts are given.

main() runs as it is, with the window, Qt and the key files replaced: nothing opens, no
key is read, and the camera server is never reached.
"""

import inspect
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QSize

from inspection_client import app
from inspection_client.station import (CAMERA_KEY_FILE, CLAUDE_KEY_FILE, KeyAuth, camera_client,
                                        live_view)

KEYS = {"API_KEY": "camera key", "ANTHROPIC_API_KEY": "Claude key"}


def called_with(function):
    """Stands in for function: returns the arguments it was given, defaults filled in."""
    def record(*args, **kwargs):
        bound = inspect.signature(function).bind(*args, **kwargs)
        bound.apply_defaults()
        return SimpleNamespace(**bound.arguments)
    return record


def start(monkeypatch, *arguments):
    """Runs main() with these command-line arguments. Returns what the station's
    connection to the camera server and the live view were given, and the keys read."""
    keys_read = []

    def read_key(variable, path):
        keys_read.append((variable, path))
        return KEYS[variable]

    window = MagicMock(**{"width.return_value": 1400, "height.return_value": 820,
                          "screen.return_value.availableSize.return_value": QSize(1920, 1080)})
    Window, Worker = MagicMock(return_value=window), MagicMock()
    for name, stand_in in {"QApplication": MagicMock(), "Window": Window, "Worker": Worker,
                           "read_key": read_key, "camera_client": called_with(camera_client),
                           "live_view": called_with(live_view)}.items():
        monkeypatch.setattr(app, name, stand_in)
    monkeypatch.setattr(sys, "argv", ["inspection-client", *arguments])
    with pytest.raises(SystemExit):
        app.main()

    station = Worker.call_args.args[0]
    live = Window.call_args.args[2]
    return SimpleNamespace(station=station.connect(None), claude=station.claude,
                           live=live(print, print), keys_read=keys_read)


def test_without_a_login_the_station_and_the_live_view_send_the_key(monkeypatch):
    started = start(monkeypatch)
    for part in started.station, started.live:
        assert isinstance(part.auth, KeyAuth) and part.auth.header == "Bearer camera key"
    assert started.live.ready(), "Without a login, the live view waits for one anyway."


def test_with_a_login_the_station_and_the_live_view_use_it(monkeypatch):
    started = start(monkeypatch, "--login", "--server", "http://station:8000/mcp")
    assert not isinstance(started.station.auth, KeyAuth), "With --login, the station sends the key."
    assert started.live.auth is started.station.auth, "The live view does not send the login."
    login = started.station.auth.context.storage
    assert login.auth.context.server_url == "http://station:8000/mcp"
    assert not started.live.ready(), "The live view asks for frames before the login."
    login.tokens = "a token"   # the person has logged in
    assert started.live.ready()


@pytest.mark.parametrize("arguments, keys", [
    ([], [("API_KEY", CAMERA_KEY_FILE), ("ANTHROPIC_API_KEY", CLAUDE_KEY_FILE)]),
    (["--login"], [("ANTHROPIC_API_KEY", CLAUDE_KEY_FILE)]),
], ids=["with the key", "with a login"])
def test_each_key_needed_is_read_from_its_own_file(monkeypatch, arguments, keys):
    started = start(monkeypatch, *arguments)
    assert started.keys_read == keys, f"Read: {started.keys_read}"
    assert started.claude.api_key == "Claude key"


@pytest.mark.parametrize("arguments, station, live", [
    ([], "http://localhost:8000/mcp", "http://localhost:8000/live/frame.jpg"),
    (["--server", "https://station:8443/mcp"],
     "https://station:8443/mcp", "https://station:8443/live/frame.jpg"),
], ids=["default", "--server"])
def test_the_station_and_the_live_view_go_to_the_same_server(monkeypatch, arguments, station,
                                                             live):
    started = start(monkeypatch, *arguments)
    assert (started.station.url, started.live.url) == (station, live)


def test_trust_gives_the_station_and_the_live_view_the_certificate_authority(monkeypatch):
    context = MagicMock()
    monkeypatch.setattr(app.ssl, "create_default_context", lambda: context)
    started = start(monkeypatch, "--trust", "certs/ca.pem")
    context.load_verify_locations.assert_called_once_with("certs/ca.pem")
    assert started.station.verify is context, "The station does not trust the --trust file."
    assert started.live.verify is context, "The live view does not trust the --trust file."

    started = start(monkeypatch)
    assert (started.station.verify, started.live.verify) == (True, True)
