"""Step 6: the pictures worth keeping.

`analyze` names the moments where the screen probably shows code, a diagram,
a user interface or a table. For each one, yt-dlp fetches a short clip
around it (the slide someone talks about is regularly a few seconds off the
sentence), ffmpeg keeps the sharpest second, and the model labels the
pictures. A speaker's face never makes it into the note, and at most LIMIT
pictures do.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import llm
from .analyze import FRAME_KINDS, LANGUAGES, _obj, analyze, stamp
from .config import Settings
from .documents import mermaid_png
from .fetch import FetchError, fetch, ffmpeg, work_folder

RESULT_NAME = "frames.json"
LIMIT = 8
# Seconds of clip before and after the moment.
MARGIN = 8
CANDIDATES = 12
LABELS = [*FRAME_KINDS, "speaker"]

LABEL_SCHEMA = _obj(
    {"label": {"type": "string", "enum": LABELS}, "caption": {"type": "string"}}
)
DIAGRAM_SCHEMA = _obj({"mermaid": {"type": "string"}, "caption": {"type": "string"}})


def moments(analysis: dict) -> list[dict]:
    """The candidates in time order, at least MARGIN seconds apart (closer
    ones share a clip and yield the same picture twice), at most
    CANDIDATES of them, sampled evenly over the list: a long video arrives
    with the candidates of every part, and a prefix would show its
    opening only."""
    spaced: list[dict] = []
    for candidate in sorted(
        analysis.get("frame_candidates") or [], key=lambda c: c["time"]
    ):
        if not spaced or candidate["time"] - spaced[-1]["time"] >= MARGIN:
            spaced.append(candidate)
    if len(spaced) <= CANDIDATES:
        return spaced
    step = len(spaced) / CANDIDATES
    return [spaced[int(i * step)] for i in range(CANDIDATES)]


def clip_path(folder: Path, vid: str, start: float) -> Path:
    """The clip yt-dlp wrote for that start, whatever container it chose;
    the mp4 name when none is there, and the caller checks."""
    return next(
        folder.glob(f"{vid}-clip-{int(start)}.*"),
        folder / f"{vid}-clip-{int(start)}.mp4",
    )


def download_clips(
    url: str, folder: Path, vid: str, times: list[float], settings: Settings
) -> dict[float, Path]:
    """One yt-dlp run, one ffmpeg cut per moment, video only, 1080p at most.
    Measured 2026-09-09: two 16-second clips in 27 s, no PO token asked."""
    import yt_dlp
    from yt_dlp.utils import download_range_func

    ranges = [(max(0.0, t - MARGIN), t + MARGIN) for t in times]
    options = {
        # Direct downloads only: a section cut from YouTube's HLS "Premium"
        # stream (itag 616) came back as an empty 257-byte container for
        # every moment of a 32-minute video on 2026-09-10.
        "format": (
            "bestvideo[height<=1080][ext=mp4][protocol=https]"
            "/bestvideo[height<=1080][protocol=https]"
            "/best[height<=1080][protocol=https]"
        ),
        "download_ranges": download_range_func(None, ranges),
        "outtmpl": str(folder / "%(id)s-clip-%(section_start)d.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
    }
    if settings.cookies_file:
        options["cookiefile"] = str(settings.cookies_file)
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            ydl.download([url])
    except yt_dlp.utils.DownloadError as error:
        raise FetchError(f"clip download failed: {error}") from error
    return {t: clip_path(folder, vid, start) for t, (start, _) in zip(times, ranges)}


# The frames are compared at this size: enough for the variance, quick to
# read. The height is fixed too, so the byte count says how many there are.
PROBE_WIDTH, PROBE_HEIGHT = 480, 270


def sharpest_second(raw: bytes) -> int:
    """Index of the frame with the highest Laplacian variance among the
    grey PROBE-sized frames in `raw`: many sharp edges. A slide that has
    been built up beats the blank it starts as; ffmpeg's `blurdetect`
    measures edge width instead and took the blank four times out of four
    on 2026-09-10."""
    import numpy as np

    size = PROBE_WIDTH * PROBE_HEIGHT
    count = len(raw) // size
    if count == 0:
        return 0
    frames = np.frombuffer(raw[: count * size], dtype=np.uint8)
    frames = frames.reshape(count, PROBE_HEIGHT, PROBE_WIDTH).astype(np.float32)
    laplace = (
        frames[:, :-2, 1:-1]
        + frames[:, 2:, 1:-1]
        + frames[:, 1:-1, :-2]
        + frames[:, 1:-1, 2:]
        - 4 * frames[:, 1:-1, 1:-1]
    )
    return int(laplace.reshape(count, -1).var(axis=1).argmax())


def sharpest(clip: Path) -> int:
    """Seconds into the clip of its sharpest frame, one frame per second."""
    return sharpest_second(
        ffmpeg(
            *("-i", str(clip)),
            *("-vf", f"fps=1,scale={PROBE_WIDTH}:{PROBE_HEIGHT},format=gray"),
            *("-f", "rawvideo", "-"),
        )
    )


def extract(clip: Path, at: float, target: Path) -> Path:
    ffmpeg("-y", "-ss", str(at), "-i", str(clip), "-frames:v", "1", str(target))
    return target


def instruction(language: str, image: Path) -> str:
    return (
        f"You label one screenshot from a YouTube video for a note: "
        f"{image.name}. When the picture is not attached, read {image} with "
        "the Read tool. label: code when it shows source code or a terminal, "
        "diagram for a chart, graph or architecture drawing, ui for an "
        "application or website on screen, table for a table of numbers or "
        "features, speaker when a person fills the picture and nothing else "
        f"matters, else other. caption: one sentence in "
        f"{LANGUAGES.get(language, language)} on what the picture shows, with "
        "the names and numbers that are visible."
    )


def label(
    images: list[Path],
    candidates: list[dict],
    settings: Settings,
    language: str,
    spend: list[dict],
) -> list[dict]:
    """One request per picture; each one's cost goes onto `spend`. Ten
    pictures in one request had the model swap two captions on
    2026-09-09; with one picture per request there is nothing to
    confuse."""
    labeled: list[dict] = []
    for image, candidate in zip(images, candidates):
        data = (
            f"{image.name}: at {stamp(candidate['time'])}, analyze expected "
            f"{candidate['kind']}: {candidate['why']}"
        )
        answer = llm.complete(
            instruction(language, image),
            data,
            LABEL_SCHEMA,
            settings,
            images=[image],
            # With `claude` the Read is one turn, the answer another.
            max_turns=4,
        )
        spend.append(dict(llm.last_cost))
        labeled.append(
            {
                "file": image.name,
                "label": answer.get("label", "other"),
                "caption": answer.get("caption", ""),
            }
        )
    return labeled


def diagram_instruction(language: str) -> str:
    name = LANGUAGES.get(language, language)
    return (
        "You decide whether a note on a YouTube video needs a diagram the "
        "video did not show: an architecture, a flow, how components relate. "
        "Below are the summary and the sections. If one diagram would help "
        "the reader, write it as Mermaid: flowchart LR or TD, or "
        "sequenceDiagram; at most twelve nodes. In a flowchart every node "
        'has a letter id and a quoted label, like A["Docker CLI"] --> '
        'B["dockerd"]; a bare "label" --> "label" is not Mermaid. Labels in '
        f"{name} except product names; no styling, no comments, no markdown "
        "fence. Else leave mermaid empty. caption: one sentence in "
        f"{name} on what the diagram shows."
    )


def draw_diagram(
    analysis: dict,
    folder: Path,
    vid: str,
    settings: Settings,
    language: str,
    spend: list[dict],
    warnings: list[str],
) -> dict | None:
    """When no chosen picture shows a diagram, the model may draw one; it
    is rendered here so that a source Mermaid cannot read is dropped with
    a warning now, not when the note is written. The source stays in the
    result either way, so a dropped one can be read."""
    sections = "\n".join(
        f"- [{stamp(s['start'])}] {s['title']}: {s['summary']}"
        for s in analysis.get("sections") or []
    )
    data = f"Summary:\n{analysis.get('summary', '')}\n\nSections:\n{sections}"
    answer = llm.complete(diagram_instruction(language), data, DIAGRAM_SCHEMA, settings)
    spend.append(dict(llm.last_cost))
    source = str(answer.get("mermaid") or "").strip()
    if not source:
        return None
    target = folder / f"{vid}-diagram.png"
    drawn = {
        "file": target.name,
        "mermaid": source,
        "caption": answer.get("caption", ""),
    }
    try:
        mermaid_png(source, target, settings.config["browser"])
    except FetchError as error:
        warnings.append(f"diagram dropped: {error}")
        drawn["file"] = None
    return drawn


def choose(labeled: list[dict], kind: str | None, limit: int = LIMIT) -> list[dict]:
    """Which pictures stay: no speaker, `other` last, diagrams first in an
    explainer, at most `limit`, returned in time order."""

    def rank(frame: dict) -> tuple:
        return (
            frame["label"] == "other",
            kind == "explainer" and frame["label"] != "diagram",
            frame["time"],
        )

    kept = [f for f in labeled if f["label"] != "speaker"]
    return sorted(sorted(kept, key=rank)[:limit], key=lambda f: f["time"])


def frames(
    url: str, settings: Settings, force: bool = False, language: str | None = None
) -> dict:
    """Write work/<id>/frames.json and the chosen `<id>-N.png` next to it."""
    fetched = fetch(url, settings)
    vid = fetched["id"]
    folder = work_folder(settings, vid)
    result_path = folder / RESULT_NAME
    if result_path.exists() and not force:
        return json.loads(result_path.read_text(encoding="utf-8"))
    analysis = analyze(url, settings, language=language)
    language = language or analysis.get("language") or settings.config["language"]
    candidates = moments(analysis)
    result: dict = {
        "id": vid,
        "model": llm.describe(settings),
        "cost": {},
        "warnings": [],
        "frames": [],
        "diagram": None,
    }
    if not candidates:
        result["warnings"].append("analyze named no frame candidates")
        result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result

    clips = download_clips(url, folder, vid, [c["time"] for c in candidates], settings)
    # A run with --force must not leave last time's pictures next to the new.
    for old in folder.glob(f"{vid}-*.png"):
        old.unlink()
    images: list[Path] = []
    taken: list[dict] = []
    try:
        for candidate in candidates:
            clip = clips[candidate["time"]]
            if not clip.exists():
                result["warnings"].append(f"no clip at {stamp(candidate['time'])}")
                continue
            target = folder / f"{vid}-{len(images) + 1}.png"
            try:
                images.append(extract(clip, sharpest(clip), target))
            except FetchError as error:
                # One clip ffmpeg cannot read must not cost the others
                # (2026-09-10, a 32-minute video); the size says why.
                result["warnings"].append(
                    f"no picture at {stamp(candidate['time'])}, clip of "
                    f"{clip.stat().st_size} bytes: {error}"
                )
                continue
            taken.append(candidate)
    finally:
        for clip in set(clips.values()):
            clip.unlink(missing_ok=True)
    if not images:
        result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result

    spend: list[dict] = []
    labeled = label(images, taken, settings, language, spend)
    for entry, candidate in zip(labeled, taken):
        entry.update(time=candidate["time"], expected=candidate["kind"])
    chosen = {f["file"] for f in choose(labeled, analysis.get("kind"))}
    for entry in labeled:
        entry["chosen"] = entry["file"] in chosen
        if not entry["chosen"]:
            (folder / entry["file"]).unlink(missing_ok=True)
    result["frames"] = labeled
    if not any(f["label"] == "diagram" and f["chosen"] for f in labeled):
        result["diagram"] = draw_diagram(
            analysis, folder, vid, settings, language, spend, result["warnings"]
        )
    result["cost"] = llm.totals(spend)
    result_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return result


def stored_result(settings: Settings, vid: str) -> dict:
    path = work_folder(settings, vid) / RESULT_NAME
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def chosen_images(settings: Settings, vid: str) -> list[dict]:
    """The pictures the renderer places: file, time and caption of each
    chosen frame; empty when `frames` has not run."""
    return [
        f for f in stored_result(settings, vid).get("frames", []) if f.get("chosen")
    ]


def diagram_of(settings: Settings, vid: str) -> dict | None:
    """The drawn diagram (file, mermaid, caption); None when there is
    none, or when Mermaid could not draw the source."""
    diagram = stored_result(settings, vid).get("diagram")
    return diagram if diagram and diagram.get("file") else None
