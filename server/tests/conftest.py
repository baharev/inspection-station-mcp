import pytest


@pytest.fixture(autouse=True)
def no_saved_camera(tmp_path, monkeypatch):
    """Keeps the tests away from this computer's saved camera choice and its CAMERA."""
    monkeypatch.setattr("inspection_camera.choice.SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.delenv("CAMERA", raising=False)
