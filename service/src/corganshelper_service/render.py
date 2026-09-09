"""Step 4 and 7: Markdown, the format every other output is made from,
and the outputs made from it.

`work/<id>/summary.md` is always written. `formats` in config.json, or
`--format` on the command line, adds a copy under `out/`, a note in the
Obsidian vault, a PDF and a Word file. The Markdown is rendered once per
target because each one embeds a picture differently: by file name next
to the note, as a wikilink into the vault, as a file URL for the browser.
"""

from __future__ import annotations

import json
import re
import shutil
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path

from .analyze import analyze, stamp
from .config import Settings, split_formats
from .documents import docx as write_docx
from .documents import html as to_html
from .documents import pdf as write_pdf
from .enrich import installations
from .fetch import FetchError, convert_thumbnail, fetch, work_folder
from .frames import chosen_images, diagram_of

RESULT_NAME = "summary.md"
PICTURES_FOLDER = "_bilder"
# What Windows refuses in a file name, plus control characters.
FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
TITLE_LENGTH = 80

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

# How a picture file is written into the Markdown: (file name, alt text).
Embed = Callable[[str, str], str]


def plain(name: str, alt: str) -> str:
    return f"![{alt}]({name})"


def at(vid: str, seconds: float) -> str:
    return f"https://youtu.be/{vid}?t={int(seconds)}"


def note_name(fetched: dict, today: date) -> str:
    """`YYYY_MM_DD_Title`: the day of processing, then the title without
    what Windows refuses, cut to TITLE_LENGTH."""
    title = FORBIDDEN.sub("", fetched.get("title") or "").strip(" .")
    title = title[:TITLE_LENGTH].rstrip(" .") or fetched["id"]
    return f"{today:%Y_%m_%d}_{title}"


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


def picture(vid: str, image: dict, embed: Embed) -> list[str]:
    caption = image.get("caption", "")
    return [
        "",
        embed(image["file"], caption),
        "",
        f"*[{stamp(image['time'])}]({at(vid, image['time'])}) {caption}*",
    ]


def render_markdown(
    fetched: dict,
    analysis: dict,
    images: list[dict] | None = None,
    repositories: list[dict] | None = None,
    embed: Embed = plain,
    diagram: dict | None = None,
    with_source: bool = True,
) -> str:
    """The note. `images` are the chosen frames (file, time, caption),
    `repositories` what enrich read out of the READMEs, `embed` writes a
    picture file into the text, `diagram` the drawn one after the summary,
    its Mermaid source below it when `with_source` (the printed formats
    show the picture only)."""
    vid = fetched["id"]
    labels = LABELS.get(analysis.get("language", "de"), LABELS["en"])
    date = fetched.get("upload_date") or ""
    date = f"{date[:4]}-{date[4:6]}-{date[6:]}" if len(date) == 8 else date
    lines = []
    if fetched.get("thumbnail"):
        lines.append(embed(fetched["thumbnail"], fetched.get("title") or vid))
        lines.append("")
    lines.append(f"# {fetched.get('title')}")
    lines.append("")
    lines.append(
        f"{fetched.get('channel')} · {date} · {stamp(fetched.get('duration') or 0)} · "
        f"[{labels['video']}](https://youtu.be/{vid}) · "
        f"{labels['kind']}: {labels['kinds'].get(analysis.get('kind'), analysis.get('kind'))}"
    )
    lines += ["", f"## {labels['summary']}", "", analysis.get("summary", "").strip()]
    if diagram:
        caption = diagram.get("caption", "")
        lines += ["", embed(diagram["file"], caption), "", f"*{caption}*"]
        if with_source:
            lines += ["", "```mermaid", diagram["mermaid"].strip(), "```"]
    lines += ["", f"## {labels['sections']}"]
    sections = analysis.get("sections", [])
    placed = by_section(sections, images or [])
    for image in placed[-1]:
        lines += picture(vid, image, embed)
    for section, pictures in zip(sections, placed):
        lines += [
            "",
            f"### [{stamp(section['start'])}]({at(vid, section['start'])}) {section['title']}",
            "",
            section["summary"].strip(),
        ]
        for image in pictures:
            lines += picture(vid, image, embed)
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


def frontmatter(fetched: dict, analysis: dict) -> str:
    """What Obsidian reads at the top of the note; the upload date, the
    processing date is in the file name."""
    date = fetched.get("upload_date") or ""
    date = f"{date[:4]}-{date[4:6]}-{date[6:]}" if len(date) == 8 else date
    kind = analysis.get("kind") or "other"
    # A JSON string is a YAML double-quoted scalar for every channel name,
    # backslashes included; escaping the quote alone was not (2026-09-10).
    channel = json.dumps(str(fetched.get("channel") or ""), ensure_ascii=False)
    return "\n".join(
        [
            "---",
            f"url: https://youtu.be/{fetched['id']}",
            f"kanal: {channel}",
            f"datum: {date}",
            f"art: {kind}",
            f"tags: [video, {kind}]",
            "---",
            "",
            "",
        ]
    )


def copy_pictures(source: Path, target: Path, names: list[str], prefix: str) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for name in names:
        if (source / name).exists():
            shutil.copy2(source / name, target / f"{prefix}{name}")


def render(
    url: str,
    settings: Settings,
    force: bool = False,
    language: str | None = None,
    formats: list[str] | None = None,
    today: date | None = None,
) -> dict[str, Path]:
    """Write work/<id>/summary.md and the wanted formats; the paths by
    format, `summary` always among them."""
    fetched = fetch(url, settings)
    vid = fetched["id"]
    folder = work_folder(settings, vid)
    # analyze skips itself when its result exists, like every step before
    # this one; `force` rewrites the outputs, which happens anyway.
    analysis = analyze(url, settings, language=language)
    images = chosen_images(settings, vid)
    repositories = installations(settings, vid)
    diagram = diagram_of(settings, vid)
    if diagram and not (folder / diagram["file"]).exists():
        diagram = None
    # The day on this machine's clock: the file name is for its owner.
    today = today or datetime.now(UTC).astimezone().date()
    name = note_name(fetched, today)
    prefix = f"{today:%Y_%m_%d}_"
    pictures = [fetched["thumbnail"]] if fetched.get("thumbnail") else []
    pictures += [image["file"] for image in images]
    pictures += [diagram["file"]] if diagram else []

    def note(embed: Embed = plain, with_source: bool = True) -> str:
        return render_markdown(
            fetched, analysis, images, repositories, embed, diagram, with_source
        )

    written = {"summary": folder / RESULT_NAME}
    written["summary"].write_text(note(), encoding="utf-8")
    wanted = (
        formats if formats is not None else split_formats(settings.config["formats"])
    )
    out = settings.out_dir
    if "md" in wanted:
        copy_pictures(folder, out, pictures, prefix)
        written["md"] = out / f"{name}.md"
        written["md"].write_text(
            note(lambda file, alt: plain(prefix + file, alt)), encoding="utf-8"
        )
    if "obsidian" in wanted:
        vault = Path(settings.config["obsidian_vault"] or "")
        if not settings.config["obsidian_vault"]:
            raise FetchError(
                "no obsidian_vault in config.json; "
                "`corganshelper config --set obsidian_vault=<path to the vault>`"
            )
        # A mistyped vault would be created, note and all, where Obsidian
        # never looks.
        if not vault.is_dir():
            raise FetchError(f"obsidian_vault {vault} is not a folder")
        subfolder = settings.config["obsidian_folder"].replace("\\", "/").strip("/")
        notes = vault / subfolder
        copy_pictures(folder, notes / PICTURES_FOLDER, pictures, prefix)
        wikilink_prefix = "/".join(p for p in (subfolder, PICTURES_FOLDER) if p)
        wikilink_prefix = f"{wikilink_prefix}/{prefix}"
        written["obsidian"] = notes / f"{name}.md"
        written["obsidian"].write_text(
            frontmatter(fetched, analysis)
            + note(lambda file, alt: f"![[{wikilink_prefix}{file}]]"),
            encoding="utf-8",
        )
    if "pdf" in wanted:
        out.mkdir(parents=True, exist_ok=True)
        page = to_html(
            fetched.get("title") or vid,
            note(lambda file, alt: plain((folder / file).as_uri(), alt), False),
        )
        written["pdf"] = write_pdf(
            page, out / f"{name}.pdf", settings.config["browser"]
        )
        written["html"] = written["pdf"].with_suffix(".html")
    if "docx" in wanted:
        # A thumbnail fetched before 2026-09-10 lacks the JFIF segment
        # python-docx insists on; the repair sits behind fetch's cache.
        convert_thumbnail(folder, vid)
        labels = LABELS.get(analysis.get("language", "de"), LABELS["en"])
        written["docx"] = write_docx(
            fetched,
            analysis,
            by_section(analysis.get("sections") or [], images),
            repositories,
            labels,
            folder,
            out / f"{name}.docx",
            diagram,
        )
    return written
