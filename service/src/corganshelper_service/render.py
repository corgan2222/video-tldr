"""Step 4: Markdown, the format every other output is made from."""

from __future__ import annotations

from pathlib import Path

from .analyze import analyze, stamp
from .config import Settings
from .enrich import installations
from .fetch import fetch, work_folder
from .frames import chosen_images

RESULT_NAME = "summary.md"

LABELS = {
    "de": {
        "summary": "Kurzfassung",
        "sections": "Abschnitte",
        "key_points": "Kernaussagen",
        "links": "Links",
        "install": "Installation",
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
        "install": "Installation",
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


def by_section(sections: list[dict], images: list[dict]) -> list[list[dict]]:
    """Each picture under the last section that starts before it; the
    extra list at the end holds what falls before the first section."""
    placed: list[list[dict]] = [[] for _ in range(len(sections) + 1)]
    for image in images:
        index = max(
            (i for i, s in enumerate(sections) if s["start"] <= image["time"]),
            default=len(sections),
        )
        placed[index].append(image)
    return placed


def picture(vid: str, image: dict) -> list[str]:
    return [
        "",
        f"![{image.get('caption', '')}]({image['file']})",
        "",
        f"*[{stamp(image['time'])}]({at(vid, image['time'])}) {image.get('caption', '')}*",
    ]


def render_markdown(
    fetched: dict,
    analysis: dict,
    images: list[dict] | None = None,
    repositories: list[dict] | None = None,
) -> str:
    """The note. `images` are the chosen frames (file, time, caption), the
    files next to it; `repositories` what enrich read out of the READMEs."""
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
    sections = analysis.get("sections", [])
    placed = by_section(sections, images or [])
    for image in placed[-1]:
        lines += picture(vid, image)
    for section, pictures in zip(sections, placed):
        lines += [
            "",
            f"### [{stamp(section['start'])}]({at(vid, section['start'])}) {section['title']}",
            "",
            section["summary"].strip(),
        ]
        for image in pictures:
            lines += picture(vid, image)
    if analysis.get("key_points"):
        lines += ["", f"## {labels['key_points']}", ""]
        lines += [
            f"- [{stamp(k['time'])}]({at(vid, k['time'])}) {k['text']}"
            for k in analysis["key_points"]
        ]
    for repository in repositories or []:
        if repository is repositories[0]:
            lines += ["", f"## {labels['install']}"]
        lines += ["", f"### [{repository['repo']}]({repository['url']})", ""]
        if repository.get("what"):
            lines += [repository["what"].strip(), ""]
        lines += [f"1. {step}" for step in repository.get("install") or []]
    if analysis.get("links"):
        lines += ["", f"## {labels['links']}", ""]
        lines += [f"- <{link['url']}> ({link['role']})" for link in analysis["links"]]
    return "\n".join(lines).rstrip() + "\n"


def render(
    url: str, settings: Settings, force: bool = False, language: str | None = None
) -> Path:
    fetched = fetch(url, settings)
    folder = work_folder(settings, fetched["id"])
    # analyze skips itself when its result exists, like every step before
    # this one; `force` rewrites the note, which happens anyway.
    analysis = analyze(url, settings, language=language)
    target = folder / RESULT_NAME
    note = render_markdown(
        fetched,
        analysis,
        images=chosen_images(settings, fetched["id"]),
        repositories=installations(settings, fetched["id"]),
    )
    target.write_text(note, encoding="utf-8")
    return target
