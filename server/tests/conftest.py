import pytest


@pytest.fixture(autouse=True)
def no_saved_camera(tmp_path, monkeypatch):
    """Keeps the tests away from this computer's saved camera choice and its CAMERA."""
    monkeypatch.setattr("inspection_server.choice.SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.delenv("CAMERA", raising=False)


@pytest.fixture
def server_must_not_start(monkeypatch):
    """For tests of main() that expect it to stop: a server that starts anyway fails the
    test at once, instead of serving for real and never returning."""
    def start(camera, *args, **kwargs):
        where = getattr(camera, "device", None) or getattr(camera, "folder", "")
        pytest.fail(f"The server started anyway, with {type(camera).__name__} {where}")
    monkeypatch.setattr("inspection_server.server.create_server", start)
    monkeypatch.setenv("API_KEY", "k" * 32)   # never the key file in the home folder
