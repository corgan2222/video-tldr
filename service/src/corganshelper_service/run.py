"""Every step in a row: `corganshelper run URL` is what the service runs
for a job, `run --batch urls.txt` what measures the pipeline over many.

Each step skips itself when its result exists, so a second run of the
same video costs seconds; `force` redoes every step. The note is
rendered once right after analyze, before the expensive steps, so a
video that fails in frames still has a readable summary. What a run
took and cost goes to `work/<id>/run.json`; `stats()` reads those back
for the popup's time estimate and the options page's model table.
"""

from __future__ import annotations

import json
import statistics
import time
from collections.abc import Callable
from pathlib import Path

from . import llm
from .analyze import analyze
from .config import Settings
from .enrich import enrich
from .fetch import FetchError, fetch, video_id, work_folder
from .frames import frames
from .llm import LlmError
from .render import render
from .transcribe import transcribe

# In the order they run. `note` is render with no format but summary.md.
STEPS = ["fetch", "transcribe", "analyze", "note", "enrich", "frames", "render"]
RESULT_NAME = "run.json"
# A step under this took its result from the cache and says nothing
# about how long the step takes.
CACHED_SECONDS = 0.05
# Called with (step) when a step starts and (step, detail) when it ends;
# the detail names what the step did in one line.
Progress = Callable[..., None]


def run(
    url: str,
    settings: Settings,
    force: bool = False,
    language: str | None = None,
    formats: list[str] | None = None,
    progress: Progress | None = None,
) -> dict:
    """Run every step for one video and return what happened: the seconds
    per step, the pictures kept, the tokens spent, the files written. A
    step that fails ends the run with `error` naming it; what the steps
    before it wrote stays in `written`. `progress` hears each step start
    and end."""
    result: dict = {
        "id": None,
        "url": url,
        "title": None,
        "model": llm.describe(settings),
        "stt": settings.config["stt"],
        "step": None,
        "steps": {},
        "seconds": 0.0,
        "images": 0,
        "input": 0,
        "output": 0,
        "usd": 0.0,
        "written": {},
        "error": None,
    }
    started = time.monotonic()

    def tell(*event: str) -> None:
        if progress:
            progress(*event)

    def step(name: str, call: Callable[[], dict], describe=None) -> dict:
        result["step"] = name
        tell(name)
        began = time.monotonic()
        value = call()
        seconds = round(time.monotonic() - began, 1)
        result["steps"][name] = seconds
        detail = f"{seconds}s"
        if seconds < CACHED_SECONDS:
            detail += ", from the cache"
        elif describe:
            detail += describe(value)
        tell(name, detail)
        return value

    def spent(cost: dict) -> None:
        result["input"] += cost.get("input", 0)
        result["output"] += cost.get("output", 0)
        result["usd"] = round(result["usd"] + cost.get("usd", 0.0), 4)

    def cost_line(cost: dict) -> str:
        return (
            f", {result['model']}, {cost.get('input', 0)}+{cost.get('output', 0)} "
            f"tokens, {cost.get('usd', 0.0):.3f} USD"
        )

    try:
        result["id"] = video_id(url)
        fetched = step(
            "fetch",
            lambda: fetch(url, settings, force=force),
            lambda f: (
                f", {f.get('title')}, {len(f.get('subtitles') or [])} caption tracks"
            ),
        )
        result["title"] = fetched.get("title")
        step(
            "transcribe",
            lambda: transcribe(url, settings, force=force),
            lambda t: (
                f", {t.get('source')} {t.get('model') or ''}".rstrip()
                + f", {len(t.get('segments') or [])} segments"
            ),
        )
        analysis = step(
            "analyze",
            lambda: analyze(url, settings, force=force, language=language),
            lambda a: (
                cost_line(a.get("cost") or {})
                + f", {len(a.get('sections') or [])} sections"
            ),
        )
        spent(analysis.get("cost") or {})
        result["written"] = paths(
            step("note", lambda: render(url, settings, language=language, formats=[]))
        )
        enriched = step(
            "enrich",
            lambda: enrich(url, settings, force=force, language=language),
            lambda e: (
                cost_line(e.get("cost") or {})
                + f", {len(e.get('repositories') or [])} repositories"
            ),
        )
        spent(enriched.get("cost") or {})
        framed = step(
            "frames",
            lambda: frames(url, settings, force=force, language=language),
            lambda f: (
                cost_line(f.get("cost") or {})
                + f", {sum(1 for x in f.get('frames') or [] if x.get('chosen'))} pictures"
            ),
        )
        spent(framed.get("cost") or {})
        result["images"] = sum(1 for f in framed.get("frames") or [] if f.get("chosen"))
        result["written"] = paths(
            step(
                "render",
                lambda: render(url, settings, language=language, formats=formats),
                lambda w: ", " + ", ".join(w),
            )
        )
    except (FetchError, LlmError) as error:
        result["error"] = {"step": result["step"] or "fetch", "message": str(error)}
        tell(result["error"]["step"], f"failed: {error}")
    result["seconds"] = round(time.monotonic() - started, 1)
    if result["id"]:
        folder = work_folder(settings, result["id"])
        folder.mkdir(parents=True, exist_ok=True)
        (folder / RESULT_NAME).write_text(
            json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    return result


def paths(written: dict[str, Path]) -> dict[str, str]:
    """What render returned, as strings a job can carry as JSON."""
    return {kind: str(path) for kind, path in written.items()}


def stats(settings: Settings) -> dict:
    """What earlier runs on this machine took: the median seconds per
    step (cached steps left out), and per language model and transcriber
    the runs, seconds and tokens they cost. Empty until a run happened."""
    runs = []
    for path in sorted(settings.work_dir.glob(f"*/{RESULT_NAME}")):
        try:
            runs.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    by_step: dict[str, list[float]] = {name: [] for name in STEPS}
    for done in runs:
        for name, seconds in done.get("steps", {}).items():
            if name in by_step and seconds >= CACHED_SECONDS:
                by_step[name].append(seconds)

    def summary(group: str, step: str) -> dict:
        table: dict[str, dict] = {}
        for done in runs:
            name = done.get(group)
            seconds = done.get("steps", {}).get(step, 0.0)
            if not name or seconds < CACHED_SECONDS:
                continue
            entry = table.setdefault(
                name, {"runs": 0, "seconds": [], "input": 0, "output": 0, "usd": 0.0}
            )
            entry["runs"] += 1
            entry["seconds"].append(seconds)
            entry["input"] += done.get("input", 0)
            entry["output"] += done.get("output", 0)
            entry["usd"] += done.get("usd", 0.0)
        return {
            name: {
                "runs": e["runs"],
                "seconds": round(statistics.median(e["seconds"]), 1),
                "input": round(e["input"] / e["runs"]),
                "output": round(e["output"] / e["runs"]),
                "usd": round(e["usd"] / e["runs"], 3),
            }
            for name, e in table.items()
        }

    return {
        "runs": len(runs),
        "steps": {
            name: round(statistics.median(values), 1)
            for name, values in by_step.items()
            if values
        },
        "models": summary("model", "analyze"),
        "stt": summary("stt", "transcribe"),
    }


def urls_in(path: Path) -> list[str]:
    """One URL per line; blank lines and `#` comments are skipped."""
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()]
    return [line for line in lines if line and not line.startswith("#")]


COLUMNS = ["id", "status", "s", *STEPS, "images", "input", "output", "usd"]


def header() -> str:
    """The head of the Markdown table `run --batch` prints, one row per
    video below it; the measurements file takes it as it is."""
    return "| " + " | ".join(COLUMNS) + " |\n|" + "---|" * len(COLUMNS)


def row(result: dict) -> str:
    error = result["error"]
    cells = [
        result["id"] or "?",
        f"error in {error['step']}" if error else "ok",
        f"{result['seconds']:.0f}",
        *(f"{result['steps'][s]:.1f}" if s in result["steps"] else "" for s in STEPS),
        str(result["images"]),
        str(result["input"]),
        str(result["output"]),
        f"{result['usd']:.3f}",
    ]
    return "| " + " | ".join(cells) + " |"
