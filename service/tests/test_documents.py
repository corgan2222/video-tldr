import struct
import zipfile
import zlib
from types import SimpleNamespace

import pytest

from video_tldr_service import documents
from video_tldr_service.documents import (
    browser,
    command_runs,
    content_box,
    docx,
    html,
    is_command,
    mermaid_page,
    mermaid_png,
    pdf,
)
from video_tldr_service.fetch import FetchError
from video_tldr_service.render import LABELS, by_section


def png(shade: int) -> bytes:
    """A 2x2 grey PNG. python-docx reads the header to size the picture
    and stores identical bytes once, so every test picture gets its own
    shade."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(kind + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)

    rows = b"".join(b"\x00" + bytes([shade]) * 2 for _ in range(2))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 0, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


def test_the_page_carries_the_title_and_the_pictures_as_file_urls():
    page = html("A <b> title", "# Head\n\n![alt](file:///D:/x/a.png)\n\n- one\n")
    assert "<title>A &lt;b&gt; title</title>" in page
    assert '<img alt="alt" src="file:///D:/x/a.png"' in page
    assert "<h1>Head</h1>" in page and "<li>one</li>" in page


# The title, the channel and the description come from whoever uploaded
# the video, and the model's answer is built from those. Chrome renders
# this page from a file:// URL to print the PDF, and it stays on disk, so
# a script tag in a title would run on the reader's machine.
def test_html_in_the_note_is_shown_not_run():
    page = html("t", "# <script>alert(1)</script>\n\nand <iframe src=x></iframe>\n")
    assert "<script>alert(1)</script>" not in page
    assert "<iframe" not in page
    assert "&lt;script&gt;" in page


def test_an_event_attribute_stays_text():
    page = html("t", '<img src=x onerror="alert(1)">\n')
    # The whole tag is escaped, so no img element exists to fire the
    # handler; what is left reads as the text it was.
    assert "<img" not in page
    assert "&lt;img src=x onerror=" in page


def test_markdown_that_should_work_still_does():
    page = html("t", "| a | b |\n|---|---|\n| 1 | 2 |\n\n**bold** [l](https://e.com)\n")
    assert "<table>" in page and "<td>1</td>" in page
    assert "<strong>bold</strong>" in page
    assert '<a href="https://e.com">l</a>' in page


def test_a_command_block_becomes_a_pre_the_style_sets_apart():
    page = html("t", "```bash\npip install b\n```\n")
    assert "<pre><code" in page and "pip install b" in page
    assert "pre {" in documents.STYLE and "monospace" in documents.STYLE


def test_a_template_replaces_the_page_and_a_stylesheet_follows_the_style(tmp_path):
    template = tmp_path / "page.html"
    template.write_text(
        "<html><head><title>{{title}}</title></head><body>{{content}}</body></html>",
        encoding="utf-8",
    )
    page = html("A <b> title", "# Head\n", str(template))
    assert page.startswith("<html><head><title>A &lt;b&gt; title</title>")
    assert "<h1>Head</h1>" in page and "Segoe UI" not in page

    sheet = tmp_path / "look.css"
    sheet.write_text("body { color: red; }\n", encoding="utf-8")
    page = html("t", "# Head\n", str(sheet))
    assert "<h1>Head</h1>" in page
    # The built-in look first, the file after it, so its rules win.
    assert page.index("Segoe UI") < page.index("color: red")

    with pytest.raises(FetchError) as caught:
        html("t", "# Head\n", str(tmp_path / "typo.css"))
    assert "typo.css" in str(caught.value)


def test_a_step_is_a_command_only_when_no_sentence_is_in_it():
    assert is_command("`pip install b`") and is_command("$ docker compose up")
    assert is_command("cd b") and is_command("> npm ci")
    assert not is_command("Run it.") and not is_command("")
    assert not is_command("pip install b. Then start it.")
    # Neighbours of the same kind share a run, and the order holds.
    assert command_runs(["`a`", "Do this. Then that.", "`b`"]) == [
        (True, ["a"]),
        (False, ["Do this. Then that."]),
        (True, ["b"]),
    ]


def test_the_configured_browser_wins_and_none_at_all_is_named(tmp_path, monkeypatch):
    installed = tmp_path / "chrome.exe"
    installed.write_bytes(b"exe")
    assert browser(str(installed)) == str(installed)
    with pytest.raises(FetchError) as caught:
        browser(str(tmp_path / "typo.exe"))
    assert "does not exist" in str(caught.value) and "browser=" in str(caught.value)

    monkeypatch.setattr(documents.shutil, "which", lambda name: None)
    monkeypatch.setattr(documents, "BROWSERS", ["~/nowhere/chrome.exe", str(installed)])
    assert browser() == str(installed)
    monkeypatch.setattr(documents, "BROWSERS", [])
    with pytest.raises(FetchError) as caught:
        browser()
    assert "browser=" in str(caught.value)


def test_printing_writes_the_html_and_calls_the_browser_with_the_flags(
    tmp_path, monkeypatch
):
    commands = []

    def fake_run(command, **kwargs):
        commands.append(command)
        tmp_path.joinpath("note.pdf").write_bytes(b"%PDF-1.7")
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr(documents.subprocess, "run", fake_run)
    chrome = tmp_path / "chrome.exe"
    chrome.write_bytes(b"exe")
    target = pdf("<html>x</html>", tmp_path / "note.pdf", str(chrome))

    assert target.exists() and (tmp_path / "note.html").read_text() == "<html>x</html>"
    command = commands[0]
    assert command[0] == str(chrome)
    assert "--headless" in command and "--no-pdf-header-footer" in command
    assert "--virtual-time-budget=10000" in command
    assert f"--print-to-pdf={target}" in command
    assert command[-1] == (tmp_path / "note.html").as_uri()

    def failing_run(command, **kwargs):
        return SimpleNamespace(returncode=1, stderr="boom", stdout="")

    monkeypatch.setattr(documents.subprocess, "run", failing_run)
    with pytest.raises(FetchError) as caught:
        pdf("<html>x</html>", tmp_path / "other.pdf", str(chrome))
    assert "boom" in str(caught.value)

    # Exit 0 without a file is a failure too, and so is running out of time.
    def silent_run(command, **kwargs):
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr(documents.subprocess, "run", silent_run)
    with pytest.raises(FetchError):
        pdf("<html>x</html>", tmp_path / "other.pdf", str(chrome))

    def slow_run(command, **kwargs):
        raise documents.subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(documents.subprocess, "run", slow_run)
    with pytest.raises(FetchError) as caught:
        pdf("<html>x</html>", tmp_path / "other.pdf", str(chrome))
    assert "within" in str(caught.value)


def test_the_diagram_page_ships_its_own_script_and_escapes_the_source():
    page = mermaid_page('flowchart LR\n  A["a"] --> B["<b>"]')
    assert documents.MERMAID_JS.exists() and documents.MERMAID_JS.as_uri() in page
    assert "A[&quot;a&quot;] --&gt; B[&quot;&lt;b&gt;&quot;]" in page
    assert "startOnLoad: true" in page


def test_the_content_box_hugs_the_drawing():
    width, height = 100, 50
    frame = bytearray(b"\xff" * width * height)
    for y in range(10, 20):
        for x in range(30, 40):
            frame[y * width + x] = 0
    assert content_box(bytes(frame), width, height, margin=4) == (26, 6, 18, 18)
    assert content_box(b"\xff" * width * height, width, height) == (0, 0, 100, 50)


def test_the_diagram_is_checked_in_the_dom_and_cut_from_a_screenshot(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(documents, "DIAGRAM_WINDOW", (50, 25))
    calls = []

    def fake_chromium(arguments, page, configured_browser="", task=""):
        calls.append(arguments)
        assert page.exists() and page.suffix == ".html"
        if "--dump-dom" in arguments:
            return '<html><svg viewBox="0 0 10 10"></svg></html>'
        shot = next(a for a in arguments if a.startswith("--screenshot=")).split("=")[1]
        tmp_path.joinpath(shot).write_bytes(b"shot")
        return ""

    def fake_ffmpeg(*args):
        if "rawvideo" in args:
            frame = bytearray(b"\xff" * 100 * 50)
            frame[20 * 100 + 40] = 0
            return bytes(frame)
        tmp_path.joinpath(args[-1]).write_bytes(b"png")
        return b""

    monkeypatch.setattr(documents, "chromium", fake_chromium)
    monkeypatch.setattr(documents, "ffmpeg", fake_ffmpeg)
    target = mermaid_png("flowchart LR", tmp_path / "v-diagram.png", "C:/c.exe")

    assert target.read_bytes() == b"png"
    assert calls[0] == ["--dump-dom"]
    assert "--force-device-scale-factor=2" in calls[1]
    assert "--window-size=50,25" in calls[1]
    assert not list(tmp_path.glob("*.html")) and not list(tmp_path.glob("*-shot.png"))

    def error_dom(arguments, page, configured_browser="", task=""):
        return '<svg aria-roledescription="error"></svg>'

    monkeypatch.setattr(documents, "chromium", error_dom)
    with pytest.raises(FetchError) as caught:
        mermaid_png("flowchart LR\n  A[", tmp_path / "bad-diagram.png", "C:/c.exe")
    assert "could not read" in str(caught.value)
    assert not list(tmp_path.glob("bad-*"))


def test_the_word_file_carries_every_chosen_picture_and_the_steps(tmp_path):
    folder = tmp_path / "work"
    folder.mkdir()
    for shade, name in enumerate(("v-1.png", "v-2.png", "v.png")):
        (folder / name).write_bytes(png(shade * 100))
    fetched = {
        "id": "v",
        "title": "Docker vs Podman",
        "channel": "Kanal",
        "upload_date": "20260901",
        "duration": 300,
        "thumbnail": "v.png",
    }
    analysis = {
        "language": "de",
        "kind": "explainer",
        "summary": "Zwei Werkzeuge.",
        "sections": [
            {"title": "Intro", "start": 0, "end": 60, "summary": "Worum es geht."},
            {"title": "Rootless", "start": 125, "end": 200, "summary": "Ohne Daemon."},
        ],
        "key_points": [{"time": 12, "text": "Beide bauen Container."}],
        "links": [{"url": "https://github.com/a/b", "role": "repository"}],
    }
    images = [
        {"file": "v-1.png", "time": 130, "caption": "Eins"},
        {"file": "v-2.png", "time": 140, "caption": "Zwei"},
        {"file": "missing.png", "time": 150, "caption": "Fehlt"},
    ]
    repositories = [
        {
            "repo": "a/b",
            "url": "https://github.com/a/b",
            "what": "w",
            "install": ["`x`"],
        }
    ]

    target = docx(
        fetched,
        analysis,
        by_section(analysis["sections"], images),
        repositories,
        LABELS["de"],
        folder,
        tmp_path / "out" / "note.docx",
    )

    with zipfile.ZipFile(target) as archive:
        media = [n for n in archive.namelist() if n.startswith("word/media/")]
        document = archive.read("word/document.xml").decode("utf-8")
    # Thumbnail and the two pictures that exist; the missing one is skipped.
    assert len(media) == 3
    assert "Docker vs Podman" in document and "Installation" in document
    assert "[2:10] Eins" in document and "Fehlt" not in document
    assert ">x<" in document and "`" not in document


def test_the_word_file_shades_every_command_and_drops_the_stamps(tmp_path):
    folder = tmp_path / "work"
    folder.mkdir()
    (folder / "v-1.png").write_bytes(png(40))
    fetched = {
        "id": "v",
        "title": "Docker vs Podman",
        "channel": "Kanal",
        "upload_date": "20260901",
        "duration": 300,
    }
    analysis = {
        "language": "de",
        "kind": "explainer",
        "summary": "Zwei Werkzeuge.",
        "sections": [{"title": "Intro", "start": 0, "end": 60, "summary": "Worum."}],
        "key_points": [{"time": 12, "text": "Beide bauen Container."}],
    }
    images = [
        {"file": "v-1.png", "time": 30, "caption": "Eins", "commands": ["uv sync"]}
    ]
    repositories = [
        {
            "repo": "a/b",
            "url": "https://github.com/a/b",
            "install": ["`pip install b`", "Read the docs. Then start it."],
        }
    ]

    target = docx(
        fetched,
        analysis,
        by_section(analysis["sections"], images),
        repositories,
        LABELS["de"],
        folder,
        tmp_path / "out" / "note.docx",
        None,
        False,
    )

    with zipfile.ZipFile(target) as archive:
        document = archive.read("word/document.xml").decode("utf-8")
    assert 'w:fill="F2F2F2"' in document and "Consolas" in document
    assert ">uv sync<" in document and ">pip install b<" in document
    # A step that reads like a sentence stays a numbered paragraph.
    assert ">Read the docs. Then start it.<" in document
    # Without the timestamps the heading, the point and the caption are bare.
    assert "[0:30]" not in document and "[0:12]" not in document
    assert ">Eins<" in document and ">Intro<" in document
