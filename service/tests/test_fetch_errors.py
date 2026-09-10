import subprocess

import pytest
import yt_dlp

from video_tldr_service import fetch as module
from video_tldr_service.config import Settings
from video_tldr_service.fetch import FetchError, convert_thumbnail, fetch, work_folder


class Refusing:
    """Stands in for yt_dlp.YoutubeDL and answers with YouTube's bot check."""

    def __init__(self, options):
        self.options = options

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def extract_info(self, url, download):
        raise yt_dlp.utils.DownloadError(
            "ERROR: [youtube] x: Sign in to confirm you’re not a bot."
        )


def test_the_bot_check_becomes_a_message_that_names_the_way_out(tmp_path, monkeypatch):
    monkeypatch.setattr(yt_dlp, "YoutubeDL", Refusing)
    settings = Settings(home=tmp_path)

    with pytest.raises(FetchError) as caught:
        fetch("https://youtu.be/BT4ywlPr6Pk", settings)

    assert "VIDEO_TLDR_COOKIES" in str(caught.value)
    assert not (work_folder(settings, "BT4ywlPr6Pk") / "fetch.json").exists()


def test_an_ffmpeg_that_never_answers_becomes_an_error_naming_the_seconds(
    tmp_path, monkeypatch
):
    """One thread works the jobs, so an ffmpeg without an end stops every
    later job too."""

    def slow_run(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(module.subprocess, "run", slow_run)
    (tmp_path / "BT4ywlPr6Pk.webp").write_bytes(b"webp")

    with pytest.raises(FetchError) as caught:
        convert_thumbnail(tmp_path, "BT4ywlPr6Pk")

    assert f"within {module.FFMPEG_TIMEOUT_SECONDS}s" in str(caught.value)


def test_a_failing_thumbnail_conversion_carries_what_ffmpeg_complained(
    tmp_path, monkeypatch
):
    def failing_run(command, **kwargs):
        raise subprocess.CalledProcessError(1, command, b"", b"webp decoder missing")

    monkeypatch.setattr(module.subprocess, "run", failing_run)
    (tmp_path / "BT4ywlPr6Pk.webp").write_bytes(b"webp")

    with pytest.raises(FetchError) as caught:
        convert_thumbnail(tmp_path, "BT4ywlPr6Pk")

    assert "webp decoder missing" in str(caught.value)
