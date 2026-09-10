"""Step 3: what the video is about, in a shape the renderer can use.

One request per video; a transcript longer than the model comfortably reads
in one go is cut at chapter borders, each part summarised on its own and a
final request stitches the parts together.
"""

from __future__ import annotations

import json

from . import llm
from .config import LANGUAGES, Settings
from .fetch import URL_IN_TEXT, FetchError, fetch, work_folder
from .transcribe import RESULT_NAME as TRANSCRIPT_NAME
from .transcribe import transcribe

RESULT_NAME = "analysis.json"
# Roughly 15k tokens of transcript; above this the request is split.
PART_LIMIT = 60_000

KINDS = ["software-tutorial", "explainer", "review", "news", "other"]
FRAME_KINDS = ["code", "diagram", "ui", "table", "other"]
LINK_ROLES = ["repository", "docs", "sponsor", "other"]


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


# What a wording changes: the voice that leads the prompt, and the shape
# of the two long fields. A voice tacked on at the end lost against "a
# two- to four-sentence summary" in the middle of the text, and the five
# wordings of one video read alike (owner, 2026-09-10). So the voice goes
# first and writes the lengths itself. `normal` sets none, and the keys
# in this order are what `style=all` walks; `all` is no wording itself.
STYLE_INSTRUCTIONS = {
    "normal": {
        "voice": "",
        "section": "a two- to four-sentence summary",
        "summary": "five to eight sentences",
        "points": "one sentence each",
    },
    "caveman": {
        "voice": (
            "Voice, and it outranks every length below: caveman speech. "
            "Fragments, never full sentences. No articles, no pronouns, no "
            'auxiliary verbs, no hedging. Like this: "Old way: copy files by '
            'hand. Restart server. Hope nothing break." Keep every technical '
            "term, product name, command and number exactly as the video says "
            "it. Titles too."
        ),
        "section": "two to four fragments, never a full sentence",
        "summary": "six to ten fragments, never a full sentence",
        "points": "one fragment each, under eight words",
    },
    "noslop": {
        "voice": (
            "Voice: plain and concrete, the way a good manual reads. No "
            'marketing words, no "delve", "seamless", "robust", '
            '"landscape", "powerful", "leverage". No opener that '
            "announces what follows and no closing sentence that repeats it. "
            "Name the thing, say what happens, stop. Do not borrow an English "
            "verb where the target language has its own."
        ),
        "section": "two to four plain sentences, no opener, no summary line",
        "summary": "five to eight plain sentences",
        "points": "one plain sentence each",
    },
    "engineer": {
        "voice": (
            "Voice: an engineer writing for engineers. Lead with the command, "
            "the flag, the file, the version, the number. Quote a command "
            "verbatim in backticks instead of describing it. Skip the "
            "motivation and the analogies; keep what someone would type or "
            "check."
        ),
        "section": (
            "two to four dense sentences that name the commands, files and "
            "numbers shown"
        ),
        "summary": "five to eight dense sentences, numbers included",
        "points": "one line each, the command or the number first",
    },
    "human": {
        "voice": (
            "Voice: a colleague explaining it over coffee. Address the reader "
            "directly, use contractions and short everyday words, allow an "
            "aside where it helps. Warm, never chatty, and never at the cost "
            "of a fact: every term, number and name stays exact."
        ),
        "section": "two to four sentences that speak to the reader",
        "summary": "five to eight sentences that speak to the reader",
        "points": "one spoken sentence each",
    },
}
CONDENSED_INSTRUCTION = (
    "The note is a two-minute read: three to five sections, at most five "
    "key points, the summary under 120 words, the whole note under 300 "
    "words. Keep the frame candidates as they are."
)
# The "five" of that instruction, for the split video where the code has to
# hold the count itself.
CONDENSED_LIMIT = 5


def instruction(
    language: str,
    part: bool = False,
    style: str = "normal",
    condensed: bool = False,
) -> str:
    spec = STYLE_INSTRUCTIONS.get(style) or STYLE_INSTRUCTIONS["normal"]
    name = LANGUAGES.get(language, language)
    voice = f"{spec['voice']} " if spec["voice"] else ""
    common = (
        f"{voice}You summarise a YouTube video for a personal knowledge base. "
        f"Write every text field in {name}; keep product names and technical "
        "terms in English and quote wording verbatim where the wording "
        "matters. "
        "Timestamps in the transcript are [m:ss] or [h:mm:ss]; every start, "
        "end and time field is such a stamp, copied from the line it belongs "
        "to. Copy the digits, never convert them and never estimate a moment "
        "that no line carries. "
        f"sections: the video's own structure, 4 to 12 entries, each with "
        f"{spec['section']}. key_points: the claims, numbers and "
        f"recommendations worth remembering, {spec['points']}, each at the "
        "second it is said. "
        "frame_candidates: up to 12 moments, spread over the video, where the "
        "screen most likely shows code, a diagram, a user interface or a "
        "table that a reader would want to see; say why."
    )
    if part:
        common += " This is one part of a longer video; cover only this part."
    else:
        common += (
            " kind: software-tutorial when the video installs or operates "
            "software step by step, explainer when it explains concepts, "
            "review for tests, benchmarks and comparisons, news for "
            "announcements, else other. summary: "
            f"{spec['summary']} on what the video says and for whom. links: "
            "every URL in the description, with its role."
        )
    tail = [CONDENSED_INSTRUCTION] if condensed else []
    if spec["voice"]:
        # Said twice on purpose: a model weighs the start and the end of a
        # prompt over its middle, and the middle is where the fields live.
        tail.append(f"Keep the voice through every field. {spec['voice']}")
    return " ".join([common, *tail])


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


def checked_links(result: dict, info: dict) -> list[dict]:
    """The description's own URLs, each with the role the model gave it.
    A URL the answer adds has no line in the description to come from, so
    it goes (2026-09-10): the description is ours, the answer is not, and
    enrich turns a link with role `repository` into a README request."""
    roles = {
        str(link.get("url")): link.get("role")
        for link in result.get("links") or []
        if link.get("role") in LINK_ROLES
    }
    return [
        {"url": link["url"], "role": roles.get(link["url"]) or "other"}
        for link in links_from(info)
    ]


def thin(items: list, limit: int) -> list:
    """At most `limit` entries, evenly spread, in their own order. Slicing
    would cut the end of a long video off instead."""
    if len(items) <= limit:
        return items
    step = len(items) / limit
    return [items[int(i * step)] for i in range(limit)]


def one_analysis(
    head: str,
    segments: list[dict],
    info: dict,
    duration: float,
    language: str,
    style: str,
    condensed: bool,
    settings: Settings,
    spend: list[dict],
) -> tuple[dict, int]:
    """One analysis in one wording, and how many parts it took. Every
    request's cost lands on `spend`."""
    whole = instruction(language, style=style, condensed=condensed)
    if sum(len(s["text"]) for s in segments) <= PART_LIMIT:
        data = head + "\n\nTranscript:\n" + "\n".join(transcript_lines(segments))
        result = normalize(
            llm.complete(whole, data, ANALYSIS_SCHEMA, settings), duration
        )
        spend.append(dict(llm.last_cost))
        return result, 1

    piece = instruction(language, part=True, style=style, condensed=condensed)
    parts = split_parts(segments, info.get("chapters") or [])
    partial = []
    for index, part in enumerate(parts, 1):
        data = (
            f"{head}\n\nTranscript, part {index} of {len(parts)}, "
            f"{stamp(part[0]['start'])} to {stamp(part[-1]['end'])}:\n"
            + "\n".join(transcript_lines(part))
        )
        partial.append(
            normalize(llm.complete(piece, data, PART_SCHEMA, settings), duration)
        )
        spend.append(dict(llm.last_cost))
    stitched = llm.complete(
        whole,
        head
        + "\n\nSummaries of the parts:\n"
        + json.dumps(partial, ensure_ascii=False),
        STITCH_SCHEMA,
        settings,
    )
    spend.append(dict(llm.last_cost))
    sections = [s for p in partial for s in p["sections"]]
    key_points = [k for p in partial for k in p["key_points"]]
    if condensed:
        # Every part read the condensed limits on its own, so joining them
        # gave parts times five sections (2026-09-10). The frame candidates
        # stay whole, the instruction asks for that on purpose.
        sections = thin(sections, CONDENSED_LIMIT)
        key_points = thin(key_points, CONDENSED_LIMIT)
    return {
        **stitched,
        "sections": sections,
        "key_points": key_points,
        "frame_candidates": [f for p in partial for f in p["frame_candidates"]],
    }, len(parts)


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
    duration = fetched.get("duration") or (segments[-1]["end"] if segments else 0)
    condensed = settings.config.get("condensed") == "on"
    wanted = settings.config.get("style") or "normal"
    styles = list(STYLE_INSTRUCTIONS) if wanted == "all" else [wanted]

    spend: list[dict] = []
    written = []
    for style in styles:
        result, parts = one_analysis(
            head, segments, info, duration, language, style, condensed, settings, spend
        )
        written.append(
            {
                "id": vid,
                "language": language,
                "style": style,
                "condensed": condensed,
                "model": llm.describe(settings),
                "parts": parts,
                # One video, one bill: with `style=all` the five wordings
                # are one job, so each file carries the whole run's cost.
                "cost": {},
                **result,
            }
        )
    for style, result in zip(styles, written):
        result["cost"] = llm.totals(spend)
        result["links"] = checked_links(result, info)
        # The first wording keeps analysis.json, the name every other step
        # reads; the rest of a `style=all` run sit next to it.
        path = result_path if style == styles[0] else folder / f"analysis-{style}.json"
        path.write_text(
            json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    return written[0]
