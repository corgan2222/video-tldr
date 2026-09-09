"""Step 7, the documents: the HTML a browser prints to PDF, and the Word
file python-docx builds from the same data as the Markdown.

No pandoc on purpose: it is not installed, and the note's data is a dict
the renderers read directly, so nothing has to parse Markdown back.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from html import escape
from pathlib import Path

from .analyze import stamp
from .fetch import FetchError

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


def pdf(page: str, target: Path, configured_browser: str = "") -> Path:
    """Print `page` to `target`; the HTML stays next to it. Without the
    time budget Chrome prints before scripts ran, without the header flag
    every page carries the date and the file path."""
    source = target.with_suffix(".html")
    source.write_text(page, encoding="utf-8")
    command = [
        browser(configured_browser),
        "--headless",
        "--disable-gpu",
        "--no-pdf-header-footer",
        "--virtual-time-budget=10000",
        f"--print-to-pdf={target}",
        source.as_uri(),
    ]
    try:
        run = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=PRINT_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise FetchError(
            f"the browser printed no PDF within {PRINT_TIMEOUT_SECONDS}s"
        ) from error
    if run.returncode != 0 or not target.exists():
        raise FetchError(f"the browser printed no PDF: {run.stderr.strip()[:300]}")
    return target


def docx(
    fetched: dict,
    analysis: dict,
    placed: list[list[dict]],
    repositories: list[dict],
    labels: dict,
    folder: Path,
    target: Path,
) -> Path:
    """The Word file. `placed` holds the pictures per section, the extra
    list at the end the ones before the first section, as `by_section`
    in render.py hands them over; the files lie in `folder`."""
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
