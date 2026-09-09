from corganshelper_service.render import render_markdown

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
    note = render_markdown(FETCHED, ANALYSIS, images=["Zvc5QkrWgAU-1.png"])
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
    assert "![](Zvc5QkrWgAU-1.png)" in lines
    assert "- <https://github.com/a/b> (repository)" in lines


def test_english_labels_follow_the_language():
    note = render_markdown(FETCHED, {**ANALYSIS, "language": "en"})
    assert "## Summary" in note and "Kind: explainer" in note
