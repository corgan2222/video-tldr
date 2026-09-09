import json

import pytest

from corganshelper_service.config import Settings
from corganshelper_service.fetch import FetchError
from corganshelper_service.transcribe import segments_from_json3, transcribe

# Three caption lines as YouTube writes them, with the scrolling line breaks
# between them and durations that overlap the following line.
JSON3 = {
    "events": [
        {"tStartMs": 0, "dDurationMs": 905320, "id": 1},
        {
            "tStartMs": 80,
            "dDurationMs": 4800,
            "segs": [{"utf8": "Welcome"}, {"utf8": " back", "tOffsetMs": 320}],
        },
        {"tStartMs": 2070, "dDurationMs": 2810, "aAppend": 1, "segs": [{"utf8": "\n"}]},
        {
            "tStartMs": 2080,
            "dDurationMs": 5199,
            "segs": [{"utf8": "GitHub"}, {"utf8": " trending", "tOffsetMs": 400}],
        },
        {"tStartMs": 4870, "dDurationMs": 2409, "aAppend": 1, "segs": [{"utf8": "\n"}]},
        {"tStartMs": 4880, "dDurationMs": 6320, "segs": [{"utf8": "number 47."}]},
    ]
}


def test_caption_lines_become_segments_that_end_where_the_next_begins():
    segments = segments_from_json3(JSON3)
    assert [s["text"] for s in segments] == [
        "Welcome back",
        "GitHub trending",
        "number 47.",
    ]
    assert segments[0] == {"start": 0.08, "end": 2.08, "text": "Welcome back"}
    assert segments[1]["end"] == 4.88
    assert segments[2]["end"] == pytest.approx(4.88 + 6.32)


def test_the_youtube_track_is_used_when_it_was_fetched(tmp_path):
    settings = Settings(home=tmp_path)
    folder = settings.work_dir / "BT4ywlPr6Pk"
    folder.mkdir(parents=True)
    (folder / "BT4ywlPr6Pk.en-orig.json3").write_text(
        json.dumps(JSON3), encoding="utf-8"
    )
    (folder / "fetch.json").write_text(
        json.dumps({"id": "BT4ywlPr6Pk", "subtitles": ["BT4ywlPr6Pk.en-orig.json3"]}),
        encoding="utf-8",
    )

    result = transcribe("https://youtu.be/BT4ywlPr6Pk", settings)

    assert result["source"] == "youtube"
    assert result["language"] == "en"
    assert result["text"] == "Welcome back GitHub trending number 47."
    assert (folder / "transcript.json").exists()


def test_asking_for_subtitles_without_a_track_is_an_error(tmp_path):
    settings = Settings(home=tmp_path)
    folder = settings.work_dir / "BT4ywlPr6Pk"
    folder.mkdir(parents=True)
    (folder / "fetch.json").write_text(
        json.dumps({"id": "BT4ywlPr6Pk", "subtitles": []}), encoding="utf-8"
    )

    with pytest.raises(FetchError):
        transcribe("https://youtu.be/BT4ywlPr6Pk", settings, engine="subtitles")
