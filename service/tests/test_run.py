import json
from pathlib import Path

import pytest

from corganshelper_service import run as module
from corganshelper_service.config import DEFAULTS, Settings
from corganshelper_service.fetch import FetchError, work_folder
from corganshelper_service.run import (
    STEPS,
    bench,
    bench_table,
    header,
    read_bench,
    row,
    run,
    stats,
    urls_in,
)

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
    stored = json.loads(
        (work_folder(Settings(home=tmp_path), "x_x_x_x_x_x") / "run.json").read_text(
            "utf-8"
        )
    )
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


def test_a_failing_picture_step_costs_the_pictures_and_not_the_run(
    steps, monkeypatch, tmp_path
):
    """Asked for on 2026-09-10: a step that only adds to the note lets the
    rest run, and the outputs are written from what there is."""

    def broken(url, settings, force=False, language=None):
        raise FetchError("ffmpeg failed")

    monkeypatch.setattr(module, "frames", broken)
    heard = []

    result = run(URL, Settings(home=tmp_path), progress=lambda *e: heard.append(e))

    assert result["error"] == {"step": "frames", "message": "ffmpeg failed"}
    assert result["errors"] == [result["error"]]
    assert list(result["steps"]) == [
        "fetch",
        "transcribe",
        "analyze",
        "note",
        "enrich",
        "render",
    ]
    assert result["images"] == 0
    # Every output is there, the pictures are what is missing.
    assert result["written"]["pdf"] == str(tmp_path / "a")
    assert "error in frames" in row(result)
    assert ("frames", "failed: ffmpeg failed") in heard


def test_a_failing_spine_step_ends_the_run(steps, monkeypatch, tmp_path):
    # Without an analysis there is nothing to render; that one does end it.
    def broken(url, settings, force=False, language=None):
        raise FetchError("the model said no")

    monkeypatch.setattr(module, "analyze", broken)

    result = run(URL, Settings(home=tmp_path))

    assert result["error"] == {"step": "analyze", "message": "the model said no"}
    assert list(result["steps"]) == ["fetch", "transcribe"]
    assert result["written"] == {}


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


def test_a_cancel_between_two_steps_ends_the_run_and_names_the_next_one(
    steps, tmp_path
):
    # The flag goes up while transcribe runs; analyze is the step that
    # never starts.
    result = run(URL, Settings(home=tmp_path), should_stop=lambda: len(steps) >= 2)

    assert result["error"] == {"step": "analyze", "message": "cancelled"}
    assert [c[0] for c in steps] == ["fetch", "transcribe"]
    assert list(result["steps"]) == ["fetch", "transcribe"]


def test_cleanup_empties_the_work_folder_but_for_run_json(steps, tmp_path):
    folder = work_folder(Settings(home=tmp_path), "x_x_x_x_x_x")
    (folder / "clips").mkdir(parents=True)
    (folder / "clips" / "a.mp4").write_text("clip", "utf-8")
    (folder / "transcript.json").write_text("{}", "utf-8")
    heard = []

    result = run(
        URL,
        Settings(home=tmp_path, config={**DEFAULTS, "cleanup": "on"}),
        progress=lambda *event: heard.append(event),
    )

    assert result["error"] is None
    assert [path.name for path in folder.iterdir()] == ["run.json"]
    assert heard[-1][0] == "cleanup"
    assert "run.json kept" in heard[-1][1]


def test_cleanup_leaves_a_failed_run_alone_to_resume(steps, monkeypatch, tmp_path):
    def broken(url, settings, force=False, language=None):
        raise FetchError("ffmpeg failed")

    monkeypatch.setattr(module, "frames", broken)
    folder = work_folder(Settings(home=tmp_path), "x_x_x_x_x_x")
    folder.mkdir(parents=True)
    (folder / "transcript.json").write_text("{}", "utf-8")

    run(URL, Settings(home=tmp_path, config={**DEFAULTS, "cleanup": "on"}))

    assert (folder / "transcript.json").exists()


def test_bench_runs_analyze_per_model_and_writes_a_row_each(monkeypatch, tmp_path):
    seen = []

    def fake_analyze(url, settings, force=False, language=None):
        seen.append((settings.config["model"], settings.config["llm"], force))
        return {
            "cost": {"input": 100, "output": 40},
            "sections": [{}, {}],
            "key_points": [{}],
            "links": [{}, {}, {}],
        }

    monkeypatch.setattr(module, "analyze", fake_analyze)
    module.llm.last_cost.clear()
    settings = Settings(home=tmp_path)

    rows = bench(URL, settings, ["qwen", "gemma"], repeat=2)

    # Every model, every repeat, and the backend untouched.
    assert seen == [("qwen", "claude", True)] * 2 + [("gemma", "claude", True)] * 2
    assert [(r["model"], r["run"]) for r in rows] == [
        ("qwen", 1),
        ("qwen", 2),
        ("gemma", 1),
        ("gemma", 2),
    ]
    assert rows[0]["input"] == 100
    assert rows[0]["output"] == 40
    assert (rows[0]["sections"], rows[0]["key_points"], rows[0]["links"]) == (2, 1, 3)
    # No count from the backend: the tokens divided by the seconds.
    assert rows[0]["tokens_per_second"] >= 0
    assert read_bench(settings) == rows

    # A second bench is appended, not written over.
    bench(URL, settings, ["qwen"], repeat=1)
    assert len(read_bench(settings)) == 5


def test_bench_takes_the_speed_the_backend_counted(monkeypatch, tmp_path):
    monkeypatch.setattr(
        module,
        "analyze",
        lambda url, settings, force=False, language=None: {
            "cost": {"input": 10, "output": 20}
        },
    )
    module.llm.last_cost.clear()
    module.llm.last_cost.update(tokens_per_second=42.5)

    rows = bench(URL, Settings(home=tmp_path), ["qwen"])
    module.llm.last_cost.clear()

    assert rows[0]["tokens_per_second"] == 42.5


def test_the_bench_table_has_one_cell_per_column():
    rows = bench_table(
        [
            {
                "model": "qwen",
                "run": 1,
                "seconds": 12.0,
                "input": 100,
                "output": 40,
                "tokens_per_second": 3.3,
                "sections": 2,
                "key_points": 1,
                "links": 3,
            }
        ]
    ).splitlines()

    assert "tokens/s" in rows[0] and "key points" in rows[0]
    assert rows[0].count("|") == rows[1].count("|") == rows[2].count("|")
    assert "| qwen | 1 | 12.0 | 100 | 40 | 3.3 | 2 | 1 | 3 |" == rows[2]


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
        folder = work_folder(Settings(home=tmp_path), vid)
        folder.mkdir(parents=True)
        (folder / "run.json").write_text(json.dumps(done), "utf-8")
    broken = work_folder(Settings(home=tmp_path), "brokenvideo")
    broken.mkdir(parents=True)
    (broken / "run.json").write_text("{", "utf-8")

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
    # A library nobody has filled yet answers with nothing, not an error.
    empty = Settings(
        home=tmp_path, config={**DEFAULTS, "download_dir": str(tmp_path / "empty")}
    )
    assert stats(empty) == {"runs": 0, "steps": {}, "models": {}, "stt": {}}


def test_urls_in_skips_blank_lines_and_comments(tmp_path):
    listing = tmp_path / "urls.txt"
    listing.write_text(
        "# the test videos\n\nhttps://a\n  https://b  \n  # indented note\n", "utf-8"
    )

    assert urls_in(Path(listing)) == ["https://a", "https://b"]
