from pathlib import Path

import pytest

from corganshelper_service import run as module
from corganshelper_service.config import Settings
from corganshelper_service.fetch import FetchError
from corganshelper_service.run import STEPS, header, row, run, urls_in

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

    monkeypatch.setattr(module, "fetch", record("fetch", {"title": "A video"}))
    monkeypatch.setattr(module, "transcribe", record("transcribe", {}))
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
    assert result["images"] == 2
    assert (result["input"], result["output"], result["usd"]) == (350, 35, 0.3)
    assert result["written"]["pdf"] == str(tmp_path / "a")
    assert result["step"] == "render"


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

    result = run(URL, Settings(home=tmp_path))

    assert result["error"] == {"step": "frames", "message": "ffmpeg failed"}
    assert list(result["steps"]) == ["fetch", "transcribe", "analyze", "note", "enrich"]
    # The note from before the failure is still there to open.
    assert "summary" in result["written"]
    assert "error in frames" in row(result)


def test_a_url_that_is_no_video_fails_before_the_first_step(steps, tmp_path):
    result = run("https://example.org/", Settings(home=tmp_path))

    assert result["id"] is None
    assert result["error"]["step"] == "fetch"
    assert steps == []
    assert row(result).startswith("| ? | error in fetch |")


def test_the_table_has_one_cell_per_column(steps, tmp_path):
    result = run(URL, Settings(home=tmp_path))

    head = header().splitlines()
    assert head[0].count("|") == head[1].count("|") == row(result).count("|")


def test_urls_in_skips_blank_lines_and_comments(tmp_path):
    listing = tmp_path / "urls.txt"
    listing.write_text(
        "# the test videos\n\nhttps://a\n  https://b  \n  # indented note\n", "utf-8"
    )

    assert urls_in(Path(listing)) == ["https://a", "https://b"]
