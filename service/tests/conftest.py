"""What every test needs before it starts.

A video's folder now lives under the user's download folder, and a test
that wrote there would leave files in the owner's Downloads. So the
download folder is the test's own `tmp_path` for the length of a test,
and `library(settings)` points into it.
"""

import pytest

from video_tldr_service import config


@pytest.fixture(autouse=True)
def downloads_in_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "default_download_dir", lambda: tmp_path / "Downloads")
    return tmp_path / "Downloads"
