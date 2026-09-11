import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from video_tldr_service import fetch as module
from video_tldr_service.config import Settings
from video_tldr_service.fetch import (
    FFMPEG_TIMEOUT_SECONDS,
    JFIF,
    FetchError,
    clean_title,
    convert_thumbnail,
    ensure_jfif,
    fetch,
    subtitle_languages,
    summarise,
    video_id,
    work_folder,
)


def test_only_the_original_audio_track_is_asked_for():
    info = {
        "language": "en",
        "automatic_captions": {"ar-orig": [], "en-orig": [], "de-DE-orig": []},
    }
    assert subtitle_languages(info) == ["en-orig"]


def test_an_uploader_track_in_that_language_is_taken_as_well():
    info = {"language": "en", "subtitles": {"en": []}, "automatic_captions": {}}
    assert subtitle_languages(info) == ["en-orig", "en"]


def test_without_a_language_the_first_original_track_decides():
    info = {"automatic_captions": {"pt-BR-orig": [], "de-orig": []}}
    assert subtitle_languages(info) == ["de-orig"]


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=BT4ywlPr6Pk",
        "https://youtube.com/watch?v=BT4ywlPr6Pk&t=42",
        "https://m.youtube.com/watch?v=BT4ywlPr6Pk",
        "https://youtu.be/BT4ywlPr6Pk",
        "https://youtu.be/BT4ywlPr6Pk?si=abc",
        "https://www.youtube.com/shorts/BT4ywlPr6Pk",
        "https://www.youtube.com/embed/BT4ywlPr6Pk",
    ],
)
def test_every_youtube_url_shape_yields_the_same_id(url):
    assert video_id(url) == "BT4ywlPr6Pk"


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/yt-dlp/yt-dlp",
        "https://www.youtube.com/",
        "https://www.youtube.com/watch?v=short",
        "not a url",
    ],
)
def test_anything_that_is_not_a_youtube_video_is_refused(url):
    with pytest.raises(FetchError):
        video_id(url)


def test_a_stored_result_is_returned_without_touching_the_network(tmp_path):
    settings = Settings(home=tmp_path)
    folder = work_folder(settings, "BT4ywlPr6Pk")
    folder.mkdir(parents=True)
    stored = {"id": "BT4ywlPr6Pk", "title": "stored"}
    (folder / "fetch.json").write_text(json.dumps(stored), encoding="utf-8")

    assert fetch("https://youtu.be/BT4ywlPr6Pk", settings) == stored


def test_the_summary_counts_links_chapters_and_lists_subtitle_files(tmp_path):
    folder = tmp_path / "BT4ywlPr6Pk"
    folder.mkdir()
    (folder / "BT4ywlPr6Pk.en.json3").write_text("{}", encoding="utf-8")
    (folder / "BT4ywlPr6Pk.jpg").write_bytes(b"jpg")
    info = {
        "title": "t",
        "channel": "c",
        "duration": 905,
        "chapters": [{}, {}],
        "description": "see https://github.com/a/b and https://example.org/x.",
    }

    summary = summarise(info, folder, "BT4ywlPr6Pk", "https://youtu.be/BT4ywlPr6Pk")

    assert summary["chapters"] == 2
    assert summary["description_links"] == 2
    assert summary["subtitles"] == ["BT4ywlPr6Pk.en.json3"]
    assert summary["thumbnail"] == "BT4ywlPr6Pk.jpg"


def test_a_jpeg_without_a_jfif_segment_gets_one_and_one_with_it_stays(tmp_path):
    # As ffmpeg writes it: the start marker, then a quantisation table.
    raw = tmp_path / "raw.jpg"
    raw.write_bytes(bytes.fromhex("ffd8ffdb0043") + b"tables" + bytes.fromhex("ffd9"))
    fixed = ensure_jfif(raw).read_bytes()
    assert fixed[:2] == bytes.fromhex("ffd8") and fixed[2:20] == JFIF
    assert fixed[6:10] == b"JFIF" and fixed.endswith(b"tables" + bytes.fromhex("ffd9"))
    assert ensure_jfif(raw).read_bytes() == fixed
    exif = tmp_path / "exif.jpg"
    exif.write_bytes(
        bytes.fromhex("ffd8ffe10010") + b"Exif" + bytes.fromhex("0000ffd9")
    )
    assert ensure_jfif(exif).read_bytes()[6:10] == b"Exif"


@pytest.mark.parametrize(
    "title", ["CON", "nul", "COM1", "lpt9.txt", "AUX.part.one", "PRN "]
)
def test_a_title_that_is_a_windows_device_name_falls_back_to_the_id(title):
    """Windows keeps CON, NUL, COM1 and their kin whatever the extension,
    and the date prefix both callers add is their property, not this
    function's."""
    assert clean_title(title, "BT4ywlPr6Pk") == "BT4ywlPr6Pk"


def test_a_title_that_only_begins_like_a_device_name_is_kept():
    assert clean_title("CONcert", "BT4ywlPr6Pk") == "CONcert"


def test_the_thumbnail_conversion_goes_through_the_helper_with_a_time_limit(
    tmp_path, monkeypatch
):
    """A hanging ffmpeg would hold up every following job, and a failing
    one has to name its complaint instead of a CalledProcessError."""
    calls = []
    (tmp_path / "BT4ywlPr6Pk.webp").write_bytes(b"webp")

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        (tmp_path / "BT4ywlPr6Pk.jpg").write_bytes(bytes.fromhex("ffd8ffd9"))
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    assert convert_thumbnail(tmp_path, "BT4ywlPr6Pk").name == "BT4ywlPr6Pk.jpg"

    command, kwargs = calls[0]
    assert command[:2] == ["ffmpeg", "-hide_banner"]
    assert kwargs["timeout"] == FFMPEG_TIMEOUT_SECONDS
    assert command.count("-loglevel") == 1


def test_settings_default_to_the_place_windows_keeps_machine_data(
    tmp_path, monkeypatch
):
    """Not APPDATA: that roams, and ten gigabytes of speech models would
    follow the user to every machine they sign in to.

    The directory comes from tmp_path rather than a written-out
    `C:/Users/...`: on the Linux runner that string is a relative path,
    and the assertion compared the checkout directory with it."""
    monkeypatch.delenv("VIDEO_TLDR_HOME", raising=False)
    monkeypatch.delenv("VIDEO_TLDR_COOKIES", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    settings = Settings.load()
    assert settings.work_dir == tmp_path / "video-tldr" / "work"
    assert settings.cookies_file is None


def test_settings_fall_back_to_a_dot_folder_without_localappdata(monkeypatch):
    """The CI runs on Linux, where that variable does not exist."""
    monkeypatch.delenv("VIDEO_TLDR_HOME", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    assert Settings.load().work_dir == Path.home() / ".video-tldr" / "work"
