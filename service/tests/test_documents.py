import struct
import zipfile
import zlib
from types import SimpleNamespace

import pytest

from corganshelper_service import documents
from corganshelper_service.documents import browser, docx, html, pdf
from corganshelper_service.fetch import FetchError
from corganshelper_service.render import LABELS, by_section


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
        return SimpleNamespace(returncode=0, stderr="")

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
        return SimpleNamespace(returncode=1, stderr="boom")

    monkeypatch.setattr(documents.subprocess, "run", failing_run)
    with pytest.raises(FetchError) as caught:
        pdf("<html>x</html>", tmp_path / "other.pdf", str(chrome))
    assert "boom" in str(caught.value)

    # Exit 0 without a file is a failure too, and so is running out of time.
    def silent_run(command, **kwargs):
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(documents.subprocess, "run", silent_run)
    with pytest.raises(FetchError):
        pdf("<html>x</html>", tmp_path / "other.pdf", str(chrome))

    def slow_run(command, **kwargs):
        raise documents.subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(documents.subprocess, "run", slow_run)
    with pytest.raises(FetchError) as caught:
        pdf("<html>x</html>", tmp_path / "other.pdf", str(chrome))
    assert "within" in str(caught.value)


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
