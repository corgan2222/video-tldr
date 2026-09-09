"""Step 4: Markdown, the format every other output is made from."""

from __future__ import annotations

import json
from pathlib import Path

from .analyze import RESULT_NAME as ANALYSIS_NAME
from .analyze import analyze, stamp
from .config import Settings
from .fetch import FetchError, fetch, work_folder

RESULT_NAME = "summary.md"

LABELS = {
    "de": {
        "summary": "Kurzfassung",
        "sections": "Abschnitte",
        "key_points": "Kernaussagen",
        "links": "Links",
        "video": "Video",
        "kind": "Art",
        "kinds": {
            "software-tutorial": "Software-Tutorial",
            "explainer": "Erklärvideo",
            "review": "Test",
            "news": "Nachrichten",
            "other": "Sonstiges",
        },
    },
    "en": {
        "summary": "Summary",
        "sections": "Sections",
        "key_points": "Key points",
        "links": "Links",
        "video": "Video",
        "kind": "Kind",
        "kinds": {
            "software-tutorial": "software tutorial",
            "explainer": "explainer",
            "review": "review",
            "news": "news",
            "other": "other",
        },
    },
}


def at(vid: str, seconds: float) -> str:
    return f"https://youtu.be/{vid}?t={int(seconds)}"


def render_markdown(
    fetched: dict, analysis: dict, images: list[str] | None = None
) -> str:
    """The note. `images` are file names next to it, already chosen."""
    vid = fetched["id"]
    labels = LABELS.get(analysis.get("language", "de"), LABELS["en"])
    date = fetched.get("upload_date") or ""
    date = f"{date[:4]}-{date[4:6]}-{date[6:]}" if len(date) == 8 else date
    lines = []
    if fetched.get("thumbnail"):
        lines.append(f"![{fetched.get('title')}]({fetched['thumbnail']})")
        lines.append("")
    lines.append(f"# {fetched.get('title')}")
    lines.append("")
    lines.append(
        f"{fetched.get('channel')} · {date} · {stamp(fetched.get('duration') or 0)} · "
        f"[{labels['video']}](https://youtu.be/{vid}) · "
        f"{labels['kind']}: {labels['kinds'].get(analysis.get('kind'), analysis.get('kind'))}"
    )
    lines += ["", f"## {labels['summary']}", "", analysis.get("summary", "").strip()]
    lines += ["", f"## {labels['sections']}"]
    for section in analysis.get("sections", []):
        lines += [
            "",
            f"### [{stamp(section['start'])}]({at(vid, section['start'])}) {section['title']}",
            "",
            section["summary"].strip(),
        ]
    if analysis.get("key_points"):
        lines += ["", f"## {labels['key_points']}", ""]
        lines += [
            f"- [{stamp(k['time'])}]({at(vid, k['time'])}) {k['text']}"
            for k in analysis["key_points"]
        ]
    if images:
        lines += [""]
        lines += [f"![]({name})" for name in images]
    if analysis.get("links"):
        lines += ["", f"## {labels['links']}", ""]
        lines += [f"- <{link['url']}> ({link['role']})" for link in analysis["links"]]
    return "\n".join(lines).rstrip() + "\n"


def render(
    url: str, settings: Settings, force: bool = False, language: str = "de"
) -> Path:
    fetched = fetch(url, settings)
    folder = work_folder(settings, fetched["id"])
    if not (folder / ANALYSIS_NAME).exists() and not force:
        analyze(url, settings, language=language)
    analysis = json.loads((folder / ANALYSIS_NAME).read_text(encoding="utf-8"))
    if not analysis:
        raise FetchError("analyze first")
    target = folder / RESULT_NAME
    target.write_text(render_markdown(fetched, analysis), encoding="utf-8")
    return target
