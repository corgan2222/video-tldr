import json
from datetime import date

import pytest

from corganshelper_service import llm
from corganshelper_service import render as render_module
from corganshelper_service.config import Settings
from corganshelper_service.fetch import FetchError
from corganshelper_service.render import (
    by_section,
    frontmatter,
    note_name,
    render,
    render_markdown,
)

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


def test_the_file_name_carries_the_day_and_nothing_windows_refuses():
    fetched = {"id": "v", "title": ' Docker: "vs" Podman/2026? | a*b. '}
    assert (
        note_name(fetched, date(2026, 9, 10)) == "2026_09_10_Docker vs Podman2026  ab"
    )
    assert note_name({"id": "v", "title": "?"}, date(2026, 9, 10)) == "2026_09_10_v"
    assert len(note_name({"id": "v", "title": "x" * 200}, date(2026, 9, 10))) == 91


def prepare(tmp_path):
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
    for name in ("Zvc5QkrWgAU-1.png", "Zvc5QkrWgAU-2.png", "Zvc5QkrWgAU.jpg"):
        (folder / name).write_bytes(b"picture")
    repo = {
        "repo": "a/b",
        "url": "https://github.com/a/b",
        "what": "w",
        "install": ["`x`"],
    }
    (folder / "enrich.json").write_text(
        json.dumps({"repositories": [repo]}), encoding="utf-8"
    )
    return settings, folder


def test_render_places_what_frames_and_enrich_wrote(tmp_path, monkeypatch):
    settings, folder = prepare(tmp_path)
    monkeypatch.setattr(llm, "complete", lambda *a, **k: pytest.fail("no request"))

    written = render("https://youtu.be/Zvc5QkrWgAU", settings, force=True, formats=[])

    assert list(written) == ["summary"]
    note = written["summary"].read_text(encoding="utf-8")
    assert written["summary"] == folder / "summary.md"
    assert "![Bild](Zvc5QkrWgAU-1.png)" in note and "weg" not in note
    assert "### [a/b](https://github.com/a/b)" in note and "1. `x`" in note


def test_a_channel_with_quotes_or_backslashes_stays_valid_yaml():
    head = frontmatter(
        {"id": "v", "channel": 'Tech\\Talk "TV"', "upload_date": "20260901"},
        {"kind": "news"},
    )
    assert 'kanal: "Tech\\\\Talk \\"TV\\""\n' in head
    assert head.endswith("tags: [video, news]\n---\n\n")


def test_the_copy_under_out_and_the_obsidian_note_carry_their_own_pictures(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(llm, "complete", lambda *a, **k: pytest.fail("no request"))
    settings, _ = prepare(tmp_path)
    vault = tmp_path / "vault"
    vault.mkdir()
    settings.config.update(obsidian_vault=str(vault), obsidian_folder="Videos\\Neu")
    today = date(2026, 9, 10)

    written = render(
        "https://youtu.be/Zvc5QkrWgAU",
        settings,
        formats=["md", "obsidian"],
        today=today,
    )

    copy = written["md"]
    assert copy == settings.out_dir / "2026_09_10_Docker vs Podman.md"
    assert "![Bild](2026_09_10_Zvc5QkrWgAU-1.png)" in copy.read_text(encoding="utf-8")
    assert (
        settings.out_dir / "2026_09_10_Zvc5QkrWgAU-1.png"
    ).read_bytes() == b"picture"
    assert (settings.out_dir / "2026_09_10_Zvc5QkrWgAU.jpg").exists()
    assert not (settings.out_dir / "2026_09_10_Zvc5QkrWgAU-2.png").exists()

    note = written["obsidian"]
    assert note == vault / "Videos" / "Neu" / "2026_09_10_Docker vs Podman.md"
    text = note.read_text(encoding="utf-8")
    assert text.startswith("---\nurl: https://youtu.be/Zvc5QkrWgAU\n")
    assert 'kanal: "Kanal"\ndatum: 2026-09-01\nart: explainer\n' in text
    assert (
        "tags: [video, explainer]\n---\n\n![[Videos/Neu/_bilder/2026_09_10_Zvc5QkrWgAU.jpg]]"
        in text
    )
    assert "![[Videos/Neu/_bilder/2026_09_10_Zvc5QkrWgAU-1.png]]" in text
    assert (
        vault / "Videos" / "Neu" / "_bilder" / "2026_09_10_Zvc5QkrWgAU-1.png"
    ).exists()

    # The vault root as the folder: no leading slash in the wikilinks.
    settings.config["obsidian_folder"] = "/"
    written = render(
        "https://youtu.be/Zvc5QkrWgAU", settings, formats=["obsidian"], today=today
    )
    assert written["obsidian"].parent == vault
    assert "![[_bilder/2026_09_10_Zvc5QkrWgAU-1.png]]" in written["obsidian"].read_text(
        encoding="utf-8"
    )


def test_obsidian_without_a_vault_or_with_a_mistyped_one_names_it(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(llm, "complete", lambda *a, **k: pytest.fail("no request"))
    settings, _ = prepare(tmp_path)
    with pytest.raises(FetchError) as caught:
        render("https://youtu.be/Zvc5QkrWgAU", settings, formats=["obsidian"])
    assert "obsidian_vault" in str(caught.value)

    settings.config["obsidian_vault"] = str(tmp_path / "typo")
    with pytest.raises(FetchError) as caught:
        render("https://youtu.be/Zvc5QkrWgAU", settings, formats=["obsidian"])
    assert "not a folder" in str(caught.value)
    assert not (tmp_path / "typo").exists()


def test_the_word_file_gets_a_thumbnail_python_docx_accepts(tmp_path, monkeypatch):
    monkeypatch.setattr(llm, "complete", lambda *a, **k: pytest.fail("no request"))
    settings, folder = prepare(tmp_path)
    # As ffmpeg wrote it before the fix, and as every older work folder has it.
    (folder / "Zvc5QkrWgAU.jpg").write_bytes(bytes.fromhex("ffd8fffe0010") + b"Lavc")
    calls = []
    monkeypatch.setattr(
        render_module, "write_docx", lambda *args: calls.append(args) or args[-1]
    )

    written = render("https://youtu.be/Zvc5QkrWgAU", settings, formats=["docx"])

    assert written["docx"] == settings.out_dir / f"{written['docx'].name}"
    assert (folder / "Zvc5QkrWgAU.jpg").read_bytes()[6:10] == b"JFIF"
    _fetched, _analysis, placed, repositories, labels, source, target = calls[0]
    assert source == folder and target.suffix == ".docx"
    assert [i["file"] for i in placed[1]] == ["Zvc5QkrWgAU-1.png"]
    assert repositories[0]["repo"] == "a/b" and labels["summary"] == "Kurzfassung"
