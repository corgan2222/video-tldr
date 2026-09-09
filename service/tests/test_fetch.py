import json

import pytest

from corganshelper_service.config import Settings
from corganshelper_service.fetch import (
    JFIF,
    FetchError,
    ensure_jfif,
    fetch,
    subtitle_languages,
    summarise,
    video_id,
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
    folder = settings.work_dir / "BT4ywlPr6Pk"
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


def test_settings_default_to_the_data_drive(monkeypatch):
    monkeypatch.delenv("CORGANSHELPER_HOME", raising=False)
    monkeypatch.delenv("CORGANSHELPER_COOKIES", raising=False)
    settings = Settings.load()
    assert settings.work_dir.as_posix() == "D:/corganshelper/work"
    assert settings.cookies_file is None
