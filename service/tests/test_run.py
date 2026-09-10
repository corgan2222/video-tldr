import json
from pathlib import Path

import pytest

from corganshelper_service import run as module
from corganshelper_service.config import Settings
from corganshelper_service.fetch import FetchError
from corganshelper_service.run import STEPS, header, row, run, stats, urls_in

URL = "https://youtu.be/x_x_x_x_x_x"


@pytest.fixture
def steps(monkeypatch, tmp_path):
    """Every step replaced by a recorder; each returns what run reads."""
    calls: list[tuple] = []

    def record(name, value):
        def fake(url, settings, force=False, language=None, formats=None):
            calls.append((name, force, language, formats))
            if isinstance(value, Exception):
                raise value
            return value

        return fake

    monkeypatch.setattr(
        module, "fetch", record("fetch", {"title": "A video", "subtitles": ["a"]})
    )
    monkeypatch.setattr(
        module,
        "transcribe",
        record("transcribe", {"source": "youtube", "segments": []}),
    )
    monkeypatch.setattr(
        module,
        "analyze",
        record("analyze", {"cost": {"input": 100, "output": 10, "usd": 0.1}}),
    )
    monkeypatch.setattr(
        module, "enrich", record("enrich", {"cost": {"input": 50, "output": 5}})
    )
    monkeypatch.setattr(
        module,
        "frames",
        record(
            "frames",
            {
                "cost": {"input": 200, "output": 20, "usd": 0.2},
                "frames": [{"chosen": True}, {"chosen": False}, {"chosen": True}],
            },
        ),
    )
    monkeypatch.setattr(
        module,
        "render",
        record("render", {"summary": tmp_path / "summary.md", "pdf": tmp_path / "a"}),
    )
    return calls


def test_run_walks_every_step_in_order_and_adds_up_the_costs(steps, tmp_path):
    result = run(URL, Settings(home=tmp_path), formats=["pdf"], language="en")

    assert [c[0] for c in steps] == [
        "fetch",
        "transcribe",
        "analyze",
        "render",
        "enrich",
        "frames",
        "render",
    ]
    assert list(result["steps"]) == STEPS
    assert result["error"] is None
    assert result["id"] == "x_x_x_x_x_x"
    assert result["title"] == "A video"
    assert result["model"] == "claude:sonnet"
    assert result["stt"] == "auto"
    assert result["images"] == 2
    assert (result["input"], result["output"], result["usd"]) == (350, 35, 0.3)
    assert result["written"]["pdf"] == str(tmp_path / "a")
    assert result["step"] == "render"
    stored = json.loads((tmp_path / "work/x_x_x_x_x_x/run.json").read_text("utf-8"))
    assert stored == result


def test_progress_hears_each_step_start_and_what_it_did(steps, tmp_path):
    heard = []
    run(URL, Settings(home=tmp_path), progress=lambda *event: heard.append(event))

    assert heard[0] == ("fetch",)
    assert [e[0] for e in heard[::2]] == STEPS
    # A step that took no time came from the cache and says so, nothing more.
    assert all("from the cache" in e[1] for e in heard[1::2])


def test_the_note_is_rendered_without_formats_and_the_end_with_the_wanted(
    steps, tmp_path
):
    run(URL, Settings(home=tmp_path), formats=["pdf"], force=True)

    renders = [c for c in steps if c[0] == "render"]
    assert [c[3] for c in renders] == [[], ["pdf"]]
    # force reaches the steps that cache; render always rewrites anyway.
    assert all(c[1] for c in steps if c[0] in ("fetch", "analyze", "frames"))


def test_a_failing_step_ends_the_run_and_names_itself(steps, monkeypatch, tmp_path):
    def broken(url, settings, force=False, language=None):
        raise FetchError("ffmpeg failed")

    monkeypatch.setattr(module, "frames", broken)
    heard = []

    result = run(URL, Settings(home=tmp_path), progress=lambda *e: heard.append(e))

    assert result["error"] == {"step": "frames", "message": "ffmpeg failed"}
    assert list(result["steps"]) == ["fetch", "transcribe", "analyze", "note", "enrich"]
    # The note from before the failure is still there to open.
    assert "summary" in result["written"]
    assert "error in frames" in row(result)
    assert heard[-1] == ("frames", "failed: ffmpeg failed")


def test_a_url_that_is_no_video_fails_before_the_first_step(steps, tmp_path):
    result = run("https://example.org/", Settings(home=tmp_path))

    assert result["id"] is None
    assert result["error"]["step"] == "fetch"
    assert steps == []
    assert row(result).startswith("| ? | error in fetch |")
    assert not list(tmp_path.glob("work/*/run.json"))


def test_the_table_has_one_cell_per_column(steps, tmp_path):
    result = run(URL, Settings(home=tmp_path))

    head = header().splitlines()
    assert head[0].count("|") == head[1].count("|") == row(result).count("|")


def test_stats_take_the_median_over_runs_and_skip_cached_steps(tmp_path):
    settings = Settings(home=tmp_path)
    runs = {
        "a": {
            "model": "claude:sonnet",
            "stt": "auto",
            "input": 100,
            "output": 10,
            "usd": 0.1,
            "steps": {"fetch": 9.0, "analyze": 70.0, "transcribe": 0.0},
        },
        "b": {
            "model": "claude:sonnet",
            "stt": "whisper",
            "input": 300,
            "output": 30,
            "usd": 0.3,
            "steps": {"fetch": 11.0, "analyze": 80.0, "transcribe": 17.0},
        },
        "c": {
            "model": "lmstudio:qwen",
            "stt": "auto",
            "input": 7000,
            "output": 8000,
            "usd": 0.0,
            "steps": {"fetch": 0.0, "analyze": 88.0, "transcribe": 0.0},
        },
    }
    for vid, done in runs.items():
        folder = tmp_path / "work" / vid
        folder.mkdir(parents=True)
        (folder / "run.json").write_text(json.dumps(done), "utf-8")
    (tmp_path / "work" / "broken").mkdir()
    (tmp_path / "work" / "broken" / "run.json").write_text("{", "utf-8")

    result = stats(settings)

    assert result["runs"] == 3
    assert result["steps"] == {"fetch": 10.0, "transcribe": 17.0, "analyze": 80.0}
    assert result["models"]["claude:sonnet"] == {
        "runs": 2,
        "seconds": 75.0,
        "input": 200,
        "output": 20,
        "usd": 0.2,
    }
    assert result["models"]["lmstudio:qwen"]["runs"] == 1
    # Only the run that transcribed says something about the transcriber.
    assert list(result["stt"]) == ["whisper"]
    assert result["stt"]["whisper"]["seconds"] == 17.0
    assert stats(Settings(home=tmp_path / "empty")) == {
        "runs": 0,
        "steps": {},
        "models": {},
        "stt": {},
    }


def test_urls_in_skips_blank_lines_and_comments(tmp_path):
    listing = tmp_path / "urls.txt"
    listing.write_text(
        "# the test videos\n\nhttps://a\n  https://b  \n  # indented note\n", "utf-8"
    )

    assert urls_in(Path(listing)) == ["https://a", "https://b"]
