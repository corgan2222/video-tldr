"""Step 3: what the video is about, in a shape the renderer can use.

One request per video; a transcript longer than the model comfortably reads
in one go is cut at chapter borders, each part summarised on its own and a
final request stitches the parts together.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import llm
from .config import Settings
from .fetch import URL_IN_TEXT, FetchError, fetch, work_folder
from .transcribe import RESULT_NAME as TRANSCRIPT_NAME
from .transcribe import transcribe

RESULT_NAME = "analysis.json"
# Roughly 15k tokens of transcript; above this the request is split.
PART_LIMIT = 60_000

KINDS = ["software-tutorial", "explainer", "review", "news", "other"]
FRAME_KINDS = ["code", "diagram", "ui", "table", "other"]
LINK_ROLES = ["repository", "docs", "sponsor", "other"]

LANGUAGES = {"de": "German", "en": "English"}


def _obj(properties: dict, required: list[str] | None = None) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": required or list(properties),
        "additionalProperties": False,
    }


# A moment travels as the stamp the transcript already carries. Asked for
# seconds, the model converts, and on 2026-09-09 that put key points at 7:10
# of a 5:00 video; `seconds()` does the arithmetic instead.
STAMP = {"type": "string"}

SECTION = _obj(
    {
        "title": {"type": "string"},
        "start": STAMP,
        "end": STAMP,
        "summary": {"type": "string"},
    }
)
KEY_POINT = _obj({"time": STAMP, "text": {"type": "string"}})
FRAME = _obj(
    {
        "time": STAMP,
        "kind": {"type": "string", "enum": FRAME_KINDS},
        "why": {"type": "string"},
    }
)
LINK = _obj({"url": {"type": "string"}, "role": {"type": "string", "enum": LINK_ROLES}})

PART_SCHEMA = _obj(
    {
        "sections": {"type": "array", "items": SECTION},
        "key_points": {"type": "array", "items": KEY_POINT},
        "frame_candidates": {"type": "array", "items": FRAME},
    }
)
ANALYSIS_SCHEMA = _obj(
    {
        "kind": {"type": "string", "enum": KINDS},
        "summary": {"type": "string"},
        "sections": {"type": "array", "items": SECTION},
        "key_points": {"type": "array", "items": KEY_POINT},
        "frame_candidates": {"type": "array", "items": FRAME},
        "links": {"type": "array", "items": LINK},
    }
)
STITCH_SCHEMA = _obj(
    {
        "kind": {"type": "string", "enum": KINDS},
        "summary": {"type": "string"},
        "links": {"type": "array", "items": LINK},
    }
)


def stamp(seconds: float) -> str:
    seconds = int(seconds)
    if seconds >= 3600:
        return f"{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"
    return f"{seconds // 60}:{seconds % 60:02d}"


def seconds(value: object) -> float:
    """A `[m:ss]` or `[h:mm:ss]` stamp as seconds; a number stays itself."""
    if isinstance(value, (int, float)):
        return float(value)
    total = 0.0
    try:
        for part in str(value).strip().strip("[]").split(":"):
            total = total * 60 + float(part)
    except ValueError:
        return 0.0
    return total


def normalize(result: dict, duration: float) -> dict:
    """Every moment as seconds inside the video, in the order it is said."""
    limit = float(duration) if duration else float("inf")

    def at(value: object) -> float:
        return max(0.0, min(seconds(value), limit))

    sections = result.get("sections") or []
    key_points = result.get("key_points") or []
    for section in sections:
        section["start"] = at(section.get("start"))
        section["end"] = at(section.get("end"))
    for moment in key_points + (result.get("frame_candidates") or []):
        moment["time"] = at(moment.get("time"))
    sections.sort(key=lambda s: s["start"])
    key_points.sort(key=lambda k: k["time"])
    return result


def transcript_lines(segments: list[dict]) -> list[str]:
    return [f"[{stamp(s['start'])}] {s['text']}" for s in segments]


def header(fetched: dict, info: dict) -> str:
    chapters = info.get("chapters") or []
    lines = [
        f"Title: {fetched.get('title')}",
        f"Channel: {fetched.get('channel')}",
        f"Uploaded: {fetched.get('upload_date')}",
        f"Duration: {stamp(fetched.get('duration') or 0)}",
        "",
        "Description:",
        (info.get("description") or "").strip(),
    ]
    if chapters:
        lines += ["", "Chapters:"]
        lines += [
            f"[{stamp(c.get('start_time', 0))}] {c.get('title')}" for c in chapters
        ]
    return "\n".join(lines)


def instruction(language: str, part: bool = False) -> str:
    name = LANGUAGES.get(language, language)
    common = (
        f"You summarise a YouTube video for a personal knowledge base. Write "
        f"every text field in {name}; keep product names and technical terms "
        "in English and quote wording verbatim where the wording matters. "
        "Timestamps in the transcript are [m:ss] or [h:mm:ss]; every start, "
        "end and time field is such a stamp, copied from the line it belongs "
        "to. Copy the digits, never convert them and never estimate a moment "
        "that no line carries. "
        "sections: the video's own structure, 4 to 12 entries, each with a "
        "two- to four-sentence summary. key_points: the claims, numbers and "
        "recommendations worth remembering, each at the second it is said. "
        "frame_candidates: up to 12 moments, spread over the video, where the "
        "screen most likely shows code, a diagram, a user interface or a "
        "table that a reader would want to see; say why."
    )
    if part:
        return common + " This is one part of a longer video; cover only this part."
    return common + (
        " kind: software-tutorial when the video installs or operates software "
        "step by step, explainer when it explains concepts, review for tests, "
        "benchmarks and comparisons, news for announcements, else other. "
        "summary: five to eight sentences on what the video says and for whom. "
        "links: every URL in the description, with its role."
    )


def split_parts(segments: list[dict], chapters: list[dict]) -> list[list[dict]]:
    """Segments in parts of roughly PART_LIMIT characters. A chapter start
    is the preferred cut and is taken once a part is half full; without one
    the cut falls wherever twice the limit is reached, so that a chapter
    longer than the limit still ends in one piece."""
    borders = sorted({float(c.get("start_time", 0)) for c in chapters if c})
    parts: list[list[dict]] = [[]]
    size = 0
    for segment in segments:
        at_border = any(abs(segment["start"] - b) < 0.5 for b in borders)
        cut = (at_border and size > PART_LIMIT / 2) or size > 2 * PART_LIMIT
        if parts[-1] and cut:
            parts.append([])
            size = 0
        parts[-1].append(segment)
        size += len(segment["text"]) + 12
    return [p for p in parts if p]


def links_from(info: dict) -> list[dict]:
    return [
        {"url": u, "role": "other"}
        for u in URL_IN_TEXT.findall(info.get("description") or "")
    ]


def analyze(
    url: str, settings: Settings, force: bool = False, language: str | None = None
) -> dict:
    language = language or settings.config["language"]
    fetched = fetch(url, settings)
    vid = fetched["id"]
    folder = work_folder(settings, vid)
    result_path = folder / RESULT_NAME
    if result_path.exists() and not force:
        return json.loads(result_path.read_text(encoding="utf-8"))
    transcript = transcribe(url, settings)
    if not (folder / TRANSCRIPT_NAME).exists():
        raise FetchError("transcribe first")
    info = json.loads((folder / fetched["info"]).read_text(encoding="utf-8"))
    head = header(fetched, info)

    segments = transcript["segments"]
    spend: list[dict] = []
    duration = fetched.get("duration") or (segments[-1]["end"] if segments else 0)
    text_size = sum(len(s["text"]) for s in segments)
    if text_size <= PART_LIMIT:
        data = head + "\n\nTranscript:\n" + "\n".join(transcript_lines(segments))
        result = normalize(
            llm.complete(instruction(language), data, ANALYSIS_SCHEMA, settings),
            duration,
        )
        spend.append(dict(llm.last_cost))
    else:
        parts = split_parts(segments, info.get("chapters") or [])
        partial = []
        for index, part in enumerate(parts, 1):
            data = (
                f"{head}\n\nTranscript, part {index} of {len(parts)}, "
                f"{stamp(part[0]['start'])} to {stamp(part[-1]['end'])}:\n"
                + "\n".join(transcript_lines(part))
            )
            partial.append(
                normalize(
                    llm.complete(
                        instruction(language, part=True), data, PART_SCHEMA, settings
                    ),
                    duration,
                )
            )
            spend.append(dict(llm.last_cost))
        stitched = llm.complete(
            instruction(language),
            head
            + "\n\nSummaries of the parts:\n"
            + json.dumps(partial, ensure_ascii=False),
            STITCH_SCHEMA,
            settings,
        )
        spend.append(dict(llm.last_cost))
        result = {
            **stitched,
            "sections": [s for p in partial for s in p["sections"]],
            "key_points": [k for p in partial for k in p["key_points"]],
            "frame_candidates": [f for p in partial for f in p["frame_candidates"]],
        }
    result = {
        "id": vid,
        "language": language,
        "model": llm.describe(settings),
        "parts": 1 if text_size <= PART_LIMIT else len(parts),
        "cost": llm.totals(spend),
        **result,
    }
    if not result.get("links"):
        result["links"] = links_from(info)
    result_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return result


def analysis_path(settings: Settings, vid: str) -> Path:
    return work_folder(settings, vid) / RESULT_NAME
