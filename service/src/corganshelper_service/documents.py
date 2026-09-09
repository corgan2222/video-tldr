"""Step 7, the documents: the HTML a browser prints to PDF, the Word file
python-docx builds from the same data as the Markdown, and the PNG the
browser draws from a Mermaid diagram.

No pandoc on purpose: it is not installed, and the note's data is a dict
the renderers read directly, so nothing has to parse Markdown back. The
Mermaid script ships in `assets/` next to this file; nothing is fetched.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from html import escape
from pathlib import Path

from .analyze import stamp
from .fetch import FetchError, ffmpeg

MERMAID_JS = Path(__file__).parent / "assets" / "mermaid.min.js"
# The diagram is drawn in a window this large at twice the pixel density
# and cut to its content plus this margin, in pixels of the result.
DIAGRAM_WINDOW = (1400, 1000)
DIAGRAM_MARGIN = 24

# Where Chrome and Edge install on Windows; `browser` in config.json
# overrides the search.
BROWSERS = [
    "C:/Program Files/Google/Chrome/Application/chrome.exe",
    "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
    "~/AppData/Local/Google/Chrome/Application/chrome.exe",
    "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
    "C:/Program Files/Microsoft/Edge/Application/msedge.exe",
]
PRINT_TIMEOUT_SECONDS = 120

STYLE = """
body { font-family: Segoe UI, Helvetica, Arial, sans-serif; max-width: 52em;
       margin: 2em auto; line-height: 1.45; color: #222; }
img { max-width: 100%; height: auto; page-break-inside: avoid; }
h2 { page-break-after: avoid; }
code { font-family: Consolas, monospace; font-size: 0.95em; }
"""


def html(title: str, markdown_text: str) -> str:
    """A complete page from the note's Markdown."""
    import markdown

    body = markdown.markdown(markdown_text, extensions=["tables", "fenced_code"])
    return (
        "<!doctype html>\n<html>\n<head>\n<meta charset='utf-8'>\n"
        f"<title>{escape(title)}</title>\n<style>{STYLE}</style>\n</head>\n"
        f"<body>\n{body}\n</body>\n</html>\n"
    )


BROWSER_HINT = "`corganshelper config --set browser=<path to chrome.exe>`"


def browser(configured: str = "") -> str:
    """The Chrome or Edge to print with: the configured one, else the
    first on the PATH or in the usual places."""
    if configured:
        if Path(configured).exists() or shutil.which(configured):
            return configured
        raise FetchError(f"browser {configured} does not exist; {BROWSER_HINT}")
    for name in ("chrome", "google-chrome", "chromium", "msedge"):
        found = shutil.which(name)
        if found:
            return found
    for candidate in BROWSERS:
        path = Path(os.path.expanduser(candidate))
        if path.exists():
            return str(path)
    raise FetchError(f"no Chrome or Edge found for the PDF; {BROWSER_HINT}")


def chromium(
    arguments: list[str], page: Path, configured_browser: str = "", task: str = ""
) -> str:
    """Run the browser headless on `page` with `arguments`; its stdout.
    Without the time budget Chrome acts before scripts ran."""
    command = [
        browser(configured_browser),
        "--headless",
        "--disable-gpu",
        "--virtual-time-budget=10000",
        *arguments,
        page.as_uri(),
    ]
    try:
        run = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=PRINT_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise FetchError(
            f"{task}: no answer within {PRINT_TIMEOUT_SECONDS}s"
        ) from error
    if run.returncode != 0:
        raise FetchError(f"{task}: the browser failed: {run.stderr.strip()[:300]}")
    return run.stdout


def pdf(page: str, target: Path, configured_browser: str = "") -> Path:
    """Print `page` to `target`; the HTML stays next to it. Without the
    header flag every page carries the date and the file path."""
    source = target.with_suffix(".html")
    source.write_text(page, encoding="utf-8")
    chromium(
        ["--no-pdf-header-footer", f"--print-to-pdf={target}"],
        source,
        configured_browser,
        "pdf",
    )
    if not target.exists():
        raise FetchError("pdf: the browser printed no file")
    return target


def mermaid_page(source: str) -> str:
    """A page that draws one Mermaid diagram with the shipped script."""
    return (
        "<!doctype html>\n<html>\n<head>\n<meta charset='utf-8'>\n"
        f"<script src='{MERMAID_JS.as_uri()}'></script>\n"
        "<style>body { margin: 0; background: white; }"
        " .mermaid { display: inline-block; padding: 8px; }</style>\n</head>\n"
        f"<body>\n<pre class='mermaid'>{escape(source)}</pre>\n"
        "<script>mermaid.initialize({startOnLoad: true, theme: 'neutral'});"
        "</script>\n</body>\n</html>\n"
    )


def content_box(
    raw: bytes, width: int, height: int, margin: int = DIAGRAM_MARGIN
) -> tuple[int, int, int, int]:
    """(x, y, w, h) around what is not white in a grey frame, plus the
    margin; the whole frame when nothing is drawn."""
    import numpy as np

    pixels = np.frombuffer(raw[: width * height], dtype=np.uint8)
    pixels = pixels.reshape(height, width)
    rows = np.flatnonzero((pixels < 250).any(axis=1))
    cols = np.flatnonzero((pixels < 250).any(axis=0))
    if not len(rows):
        return (0, 0, width, height)
    x0, y0 = max(0, cols[0] - margin), max(0, rows[0] - margin)
    x1, y1 = min(width, cols[-1] + 1 + margin), min(height, rows[-1] + 1 + margin)
    return (int(x0), int(y0), int(x1 - x0), int(y1 - y0))


def mermaid_png(source: str, target: Path, configured_browser: str = "") -> Path:
    """Draw the diagram to `target`. The DOM says whether Mermaid could
    read the source; a screenshot of a large window is then cut to the
    drawing, because the browser's own window sizing left white space
    around the SVG on 2026-09-10."""
    page = target.with_suffix(".html")
    page.write_text(mermaid_page(source), encoding="utf-8")
    try:
        dom = chromium(["--dump-dom"], page, configured_browser, "diagram")
        if 'aria-roledescription="error"' in dom or "<svg" not in dom:
            raise FetchError("diagram: Mermaid could not read the source")
        width, height = DIAGRAM_WINDOW
        shot = target.with_name(f"{target.stem}-shot.png")
        chromium(
            [
                "--force-device-scale-factor=2",
                f"--window-size={width},{height}",
                f"--screenshot={shot}",
            ],
            page,
            configured_browser,
            "diagram",
        )
        if not shot.exists():
            raise FetchError("diagram: the browser wrote no screenshot")
        try:
            raw = ffmpeg("-i", str(shot), "-vf", "format=gray", "-f", "rawvideo", "-")
            x, y, w, h = content_box(raw, 2 * width, 2 * height)
            ffmpeg("-y", "-i", str(shot), "-vf", f"crop={w}:{h}:{x}:{y}", str(target))
        finally:
            shot.unlink(missing_ok=True)
    finally:
        page.unlink(missing_ok=True)
    return target


def docx(
    fetched: dict,
    analysis: dict,
    placed: list[list[dict]],
    repositories: list[dict],
    labels: dict,
    folder: Path,
    target: Path,
    diagram: dict | None = None,
) -> Path:
    """The Word file. `placed` holds the pictures per section, the extra
    list at the end the ones before the first section, as `by_section`
    in render.py hands them over; the files lie in `folder`. `diagram`
    is the drawn one, placed after the summary."""
    from docx import Document
    from docx.shared import Inches

    vid = fetched["id"]
    doc = Document()
    doc.add_heading(fetched.get("title") or vid, 0)
    date = fetched.get("upload_date") or ""
    date = f"{date[:4]}-{date[4:6]}-{date[6:]}" if len(date) == 8 else date
    kind = labels["kinds"].get(analysis.get("kind"), analysis.get("kind"))
    doc.add_paragraph(
        f"{fetched.get('channel')} · {date} · {stamp(fetched.get('duration') or 0)}"
        f" · https://youtu.be/{vid} · {labels['kind']}: {kind}"
    )

    def picture(image: dict, caption: str = "") -> None:
        path = folder / image["file"]
        if not path.exists():
            return
        doc.add_picture(str(path), width=Inches(6))
        if caption:
            doc.add_paragraph().add_run(caption).italic = True

    if fetched.get("thumbnail"):
        picture({"file": fetched["thumbnail"]})
    doc.add_heading(labels["summary"], 1)
    doc.add_paragraph((analysis.get("summary") or "").strip())
    if diagram:
        picture(diagram, diagram.get("caption", ""))
    doc.add_heading(labels["sections"], 1)
    sections = analysis.get("sections") or []
    for image in placed[-1]:
        picture(image, f"[{stamp(image['time'])}] {image.get('caption', '')}")
    for section, pictures in zip(sections, placed):
        doc.add_heading(f"[{stamp(section['start'])}] {section['title']}", 2)
        doc.add_paragraph(section["summary"].strip())
        for image in pictures:
            picture(image, f"[{stamp(image['time'])}] {image.get('caption', '')}")
    if analysis.get("key_points"):
        doc.add_heading(labels["key_points"], 1)
        for point in analysis["key_points"]:
            doc.add_paragraph(
                f"[{stamp(point['time'])}] {point['text']}", style="List Bullet"
            )
    if repositories:
        doc.add_heading(labels["install"], 1)
        for repository in repositories:
            doc.add_heading(f"{repository['repo']} ({repository['url']})", 2)
            if repository.get("what"):
                doc.add_paragraph(repository["what"].strip())
            for step in repository.get("install") or []:
                doc.add_paragraph(step.replace("`", ""), style="List Number")
    if analysis.get("links"):
        doc.add_heading(labels["links"], 1)
        for link in analysis["links"]:
            doc.add_paragraph(f"{link['url']} ({link['role']})", style="List Bullet")
    target.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(target))
    return target
