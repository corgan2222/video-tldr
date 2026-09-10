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
    # The command goes into a block to copy from, the sentence stays prose.
    assert "```bash\npip install b\n```" in note
    assert "1. Run it." in lines
    assert "- <https://github.com/a/b> (repository)" in lines


def test_a_step_is_a_command_when_it_reads_like_one():
    note = render_markdown(
        FETCHED,
        ANALYSIS,
        repositories=[
            {
                "repo": "a/b",
                "url": "https://github.com/a/b",
                "install": [
                    "`git clone https://github.com/a/b`",
                    "cd b",
                    "Open the file. Then edit it.",
                    "$ docker compose up",
                ],
            }
        ],
    )

    # Two neighbouring commands share one block; the sentence splits them.
    assert "```bash\ngit clone https://github.com/a/b\ncd b\n```" in note
    assert "1. Open the file. Then edit it." in note
    assert "```bash\n$ docker compose up\n```" in note


def test_the_commands_read_off_a_picture_follow_its_caption():
    note = render_markdown(
        FETCHED,
        ANALYSIS,
        images=[
            {
                "file": "a.png",
                "time": 130,
                "caption": "Ein Bild",
                "commands": ["uv sync", "uv run x"],
            },
            {"file": "b.png", "time": 140, "caption": "Ohne"},
        ],
    )

    assert (
        "*[2:10](https://youtu.be/Zvc5QkrWgAU?t=130) Ein Bild*\n\n"
        "```bash\nuv sync\nuv run x\n```" in note
    )
    # A frame without the key, as every frames.json written before it had.
    assert note.count("```bash") == 1


def test_the_obsidian_note_ends_with_the_player_and_the_others_do_not():
    with_player = render_markdown(FETCHED, ANALYSIS, player=True)
    without = render_markdown(FETCHED, ANALYSIS)

    assert with_player.rstrip().endswith(
        "## Video\n\n"
        '<iframe width="560" height="315" '
        'src="https://www.youtube.com/embed/Zvc5QkrWgAU" '
        'title="YouTube video player" frameborder="0" allowfullscreen></iframe>'
    )
    assert "<iframe" not in without
    # The link in the head is what every format carries.
    assert "[Video](https://youtu.be/Zvc5QkrWgAU)" in without
    assert "## Video" in render_markdown(
        FETCHED, {**ANALYSIS, "language": "en"}, player=True
    )


def test_without_timestamps_the_note_carries_the_text_alone():
    note = render_markdown(
        FETCHED,
        ANALYSIS,
        images=[{"file": "a.png", "time": 130, "caption": "Ein Bild"}],
        timestamps=False,
    )

    assert "### Rootless" in note.splitlines()
    assert "- Beide bauen Container." in note.splitlines()
    assert "*Ein Bild*" in note.splitlines()
    assert "?t=" not in note
    # The video itself keeps its link, it is no timestamp.
    assert "[Video](https://youtu.be/Zvc5QkrWgAU)" in note


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
    # Without this the outputs land in the machine's own Downloads folder,
    # which is where a run of these tests would leave its litter.
    settings.config["download_dir"] = str(tmp_path / "out")
    folder = settings.work_dir / "Zvc5QkrWgAU"
    folder.mkdir(parents=True)
    (folder / "fetch.json").write_text(json.dumps(FETCHED), encoding="utf-8")
    (folder / "analysis.json").write_text(json.dumps(ANALYSIS), encoding="utf-8")
    kept = {"file": "Zvc5QkrWgAU-1.png", "time": 130, "caption": "Bild", "chosen": True}
    gone = {"file": "Zvc5QkrWgAU-2.png", "time": 140, "caption": "weg", "chosen": False}
    diagram = {
        "file": "Zvc5QkrWgAU-diagram.png",
        "mermaid": 'flowchart LR\n  A["a"] --> B["b"]',
        "caption": "Gezeichnet",
    }
    (folder / "frames.json").write_text(
        json.dumps({"frames": [kept, gone], "diagram": diagram}), encoding="utf-8"
    )
    for name in (
        "Zvc5QkrWgAU-1.png",
        "Zvc5QkrWgAU-2.png",
        "Zvc5QkrWgAU-diagram.png",
        "Zvc5QkrWgAU.jpg",
    ):
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
    assert "### [a/b](https://github.com/a/b)" in note and "```bash\nx\n```" in note
    # The drawn diagram follows the summary, its source below it.
    summary_at = note.index("## Kurzfassung")
    diagram_at = note.index("![Gezeichnet](Zvc5QkrWgAU-diagram.png)\n\n*Gezeichnet*")
    assert summary_at < diagram_at < note.index("## Abschnitte")
    assert '```mermaid\nflowchart LR\n  A["a"] --> B["b"]\n```' in note

    # A diagram Mermaid could not draw stays out of the note.
    stored = json.loads((folder / "frames.json").read_text(encoding="utf-8"))
    stored["diagram"]["file"] = None
    (folder / "frames.json").write_text(json.dumps(stored), encoding="utf-8")
    written = render("https://youtu.be/Zvc5QkrWgAU", settings, formats=[])
    assert "Gezeichnet" not in written["summary"].read_text(encoding="utf-8")


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
    text = copy.read_text(encoding="utf-8")
    assert "![Bild](2026_09_10_Zvc5QkrWgAU-1.png)" in text
    assert "![Gezeichnet](2026_09_10_Zvc5QkrWgAU-diagram.png)" in text
    assert (settings.out_dir / "2026_09_10_Zvc5QkrWgAU-diagram.png").exists()
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


def test_every_style_analyze_left_behind_becomes_its_own_note(tmp_path, monkeypatch):
    monkeypatch.setattr(llm, "complete", lambda *a, **k: pytest.fail("no request"))
    settings, folder = prepare(tmp_path)
    vault = tmp_path / "vault"
    vault.mkdir()
    settings.config.update(obsidian_vault=str(vault), obsidian_folder="Videos")
    (folder / "analysis-caveman.json").write_text(
        json.dumps({**ANALYSIS, "summary": "Zwei Ding, ein Ziel."}), encoding="utf-8"
    )
    today = date(2026, 9, 10)

    written = render(
        "https://youtu.be/Zvc5QkrWgAU",
        settings,
        formats=["md", "obsidian"],
        today=today,
    )

    assert written["md:caveman"] == (
        settings.out_dir / "2026_09_10_Docker vs Podman - caveman.md"
    )
    assert "Zwei Ding, ein Ziel." in written["md:caveman"].read_text(encoding="utf-8")
    assert written["obsidian:caveman"] == (
        vault / "Videos" / "2026_09_10_Docker vs Podman - caveman.md"
    )
    assert "Zwei Werkzeuge, ein Ziel." in written["md"].read_text(encoding="utf-8")
    # Only the styles whose analysis is there.
    assert not [key for key in written if key.endswith(":noslop")]
    # The player belongs to Obsidian, which renders the iframe.
    assert "<iframe" in written["obsidian"].read_text(encoding="utf-8")
    assert "<iframe" in written["obsidian:caveman"].read_text(encoding="utf-8")
    assert "<iframe" not in written["md"].read_text(encoding="utf-8")


def test_a_download_folder_that_is_not_there_yet_is_created(tmp_path, monkeypatch):
    monkeypatch.setattr(llm, "complete", lambda *a, **k: pytest.fail("no request"))
    settings, _ = prepare(tmp_path)
    settings.config["download_dir"] = str(tmp_path / "neu" / "unten")
    assert not settings.out_dir.exists()

    written = render("https://youtu.be/Zvc5QkrWgAU", settings, formats=["md"])

    assert settings.out_dir.is_dir() and written["md"].exists()


def test_timestamps_off_reaches_the_written_note(tmp_path, monkeypatch):
    monkeypatch.setattr(llm, "complete", lambda *a, **k: pytest.fail("no request"))
    settings, _ = prepare(tmp_path)
    settings.config["timestamps"] = "off"

    written = render("https://youtu.be/Zvc5QkrWgAU", settings, formats=["md"])

    assert "?t=" not in written["md"].read_text(encoding="utf-8")
    assert "?t=" not in written["summary"].read_text(encoding="utf-8")


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
        render_module, "write_docx", lambda *args: calls.append(args) or args[6]
    )

    written = render("https://youtu.be/Zvc5QkrWgAU", settings, formats=["docx"])

    assert written["docx"] == settings.out_dir / f"{written['docx'].name}"
    assert (folder / "Zvc5QkrWgAU.jpg").read_bytes()[6:10] == b"JFIF"
    (
        _fetched,
        _analysis,
        placed,
        repositories,
        labels,
        source,
        target,
        diagram,
        timestamps,
    ) = calls[0]
    assert source == folder and target.suffix == ".docx"
    assert [i["file"] for i in placed[1]] == ["Zvc5QkrWgAU-1.png"]
    assert repositories[0]["repo"] == "a/b" and labels["summary"] == "Kurzfassung"
    assert diagram["file"] == "Zvc5QkrWgAU-diagram.png"
    assert timestamps is True

    settings.config["timestamps"] = "off"
    render("https://youtu.be/Zvc5QkrWgAU", settings, formats=["docx"])
    assert calls[1][-1] is False
