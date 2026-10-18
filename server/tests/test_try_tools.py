"""Tests for scripts/try_tools.py, the way to try the tools without an AI.

    pytest -q
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "try_tools.py"


@pytest.mark.parametrize("typed, confirmation, verdict", [("y", "yes", "fail"),
                                                         ("n", "no", "unsure")])
def test_the_script_asks_the_person_and_shows_the_record_and_the_log(tmp_path, typed,
                                                                     confirmation, verdict):
    run = subprocess.run([sys.executable, str(SCRIPT)], input=typed + "\n", text=True,
                         capture_output=True, timeout=60,
                         env=dict(os.environ, TMPDIR=str(tmp_path)))   # its new folder: here
    assert run.returncode == 0, run.stderr
    assert "Mark this part as FAILED? (y/n)" in run.stdout
    assert f"  fail_confirmation: {confirmation}\n  verdict: {verdict}\n" in run.stdout
    folder = next(tmp_path.glob("inspection-try-*"))   # not the station's own logs
    assert (folder / "zoom.jpg").exists() and len(list((folder / "captures").glob("*.jpg"))) == 1
    assert run.stdout.endswith(f"(AI: fail, fail confirmation: {confirmation})\n")
