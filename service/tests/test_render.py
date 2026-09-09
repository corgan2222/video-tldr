import json

import pytest

from corganshelper_service import llm
from corganshelper_service.config import Settings
from corganshelper_service.render import by_section, render, render_markdown

FETCHED = {
    "id": "Zvc5QkrWgAU",
    "title": "Docker vs Podman",
    "channel": "Kanal",
    "upload_date": "20260901",
    "duration": 300,
    "thumbnail": "Zvc5QkrWgAU.jpg",
}
ANALYSIS = {
    "language": "de",
    "kind": "explainer",
    "summary": "Zwei Werkzeuge, ein Ziel.",
    "sections": [
        {"title": "Einführung", "start": 0, "end": 60, "summary": "Worum es geht."},
        {"title": "Rootless", "start": 125, "end": 200, "summary": "Ohne Daemon."},
    ],
    "key_points": [{"time": 12, "text": "Beide bauen Container."}],
    "frame_candidates": [],
    "links": [{"url": "https://github.com/a/b", "role": "repository"}],
}


def test_the_note_opens_with_the_thumbnail_and_links_every_timestamp():
    note = render_markdown(
        FETCHED,
        ANALYSIS,
        images=[{"file": "Zvc5QkrWgAU-1.png", "time": 130, "caption": "Ein Bild"}],
        repositories=[
            {
                "repo": "a/b",
                "url": "https://github.com/a/b",
                "what": "Ein Werkzeug.",
                "install": ["`pip install b`", "Run it."],
            }
        ],
    )
    lines = note.splitlines()

    assert lines[0] == "![Docker vs Podman](Zvc5QkrWgAU.jpg)"
    assert "# Docker vs Podman" in lines
    assert (
        "Kanal · 2026-09-01 · 5:00 · [Video](https://youtu.be/Zvc5QkrWgAU) · Art: Erklärvideo"
        in lines
    )
    assert "## Kurzfassung" in lines
    assert "### [2:05](https://youtu.be/Zvc5QkrWgAU?t=125) Rootless" in lines
    assert "- [0:12](https://youtu.be/Zvc5QkrWgAU?t=12) Beide bauen Container." in lines
    # The picture sits under the section it falls into, with its caption.
    rootless = lines.index("### [2:05](https://youtu.be/Zvc5QkrWgAU?t=125) Rootless")
    assert lines[rootless + 4] == "![Ein Bild](Zvc5QkrWgAU-1.png)"
    assert (
        lines[rootless + 6] == "*[2:10](https://youtu.be/Zvc5QkrWgAU?t=130) Ein Bild*"
    )
    assert "## Installation" in lines
    assert "### [a/b](https://github.com/a/b)" in lines
    assert "1. `pip install b`" in lines and "1. Run it." in lines
    assert "- <https://github.com/a/b> (repository)" in lines


def test_english_labels_follow_the_language():
    note = render_markdown(FETCHED, {**ANALYSIS, "language": "en"})
    assert "## Summary" in note and "Kind: explainer" in note


def test_a_picture_before_the_first_section_goes_on_top():
    late = [{**s, "start": s["start"] + 10} for s in ANALYSIS["sections"]]
    early = {"file": "a.png", "time": 5, "caption": "c"}
    inside = {"file": "b.png", "time": 12, "caption": "c"}
    placed = by_section(late, [early, inside])
    assert placed[-1] == [early] and placed[0] == [inside]


def test_render_places_what_frames_and_enrich_wrote(tmp_path, monkeypatch):
    settings = Settings(home=tmp_path)
    folder = settings.work_dir / "Zvc5QkrWgAU"
    folder.mkdir(parents=True)
    (folder / "fetch.json").write_text(json.dumps(FETCHED), encoding="utf-8")
    (folder / "analysis.json").write_text(json.dumps(ANALYSIS), encoding="utf-8")
    kept = {"file": "Zvc5QkrWgAU-1.png", "time": 130, "caption": "Bild", "chosen": True}
    gone = {"file": "Zvc5QkrWgAU-2.png", "time": 140, "caption": "weg", "chosen": False}
    (folder / "frames.json").write_text(
        json.dumps({"frames": [kept, gone]}), encoding="utf-8"
    )
    repo = {
        "repo": "a/b",
        "url": "https://github.com/a/b",
        "what": "w",
        "install": ["`x`"],
    }
    (folder / "enrich.json").write_text(
        json.dumps({"repositories": [repo]}), encoding="utf-8"
    )
    monkeypatch.setattr(llm, "complete", lambda *a, **k: pytest.fail("no request"))

    target = render("https://youtu.be/Zvc5QkrWgAU", settings, force=True)

    note = target.read_text(encoding="utf-8")
    assert target == folder / "summary.md"
    assert "![Bild](Zvc5QkrWgAU-1.png)" in note and "weg" not in note
    assert "### [a/b](https://github.com/a/b)" in note and "1. `x`" in note
