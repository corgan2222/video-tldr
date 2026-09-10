"""Every step in a row: `corganshelper run URL` is what the service runs
for a job, `run --batch urls.txt` what measures the pipeline over many.

Each step skips itself when its result exists, so a second run of the
same video costs seconds; `force` redoes every step. The note is
rendered once right after analyze, before the expensive steps, so a
video that fails in frames still has a readable summary.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from .analyze import analyze
from .config import Settings
from .enrich import enrich
from .fetch import FetchError, fetch, video_id
from .frames import frames
from .llm import LlmError
from .render import render
from .transcribe import transcribe

# In the order they run. `note` is render with no format but summary.md.
STEPS = ["fetch", "transcribe", "analyze", "note", "enrich", "frames", "render"]
Progress = Callable[[str], None]


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
    before it wrote stays in `written`. `progress` hears each step's name
    as it starts."""
    result: dict = {
        "id": None,
        "url": url,
        "title": None,
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

    def step(name: str, call: Callable[[], dict]) -> dict:
        result["step"] = name
        if progress:
            progress(name)
        began = time.monotonic()
        value = call()
        result["steps"][name] = round(time.monotonic() - began, 1)
        return value

    def spent(cost: dict) -> None:
        result["input"] += cost.get("input", 0)
        result["output"] += cost.get("output", 0)
        result["usd"] = round(result["usd"] + cost.get("usd", 0.0), 4)

    try:
        result["id"] = video_id(url)
        fetched = step("fetch", lambda: fetch(url, settings, force=force))
        result["title"] = fetched.get("title")
        step("transcribe", lambda: transcribe(url, settings, force=force))
        analysis = step(
            "analyze",
            lambda: analyze(url, settings, force=force, language=language),
        )
        spent(analysis.get("cost") or {})
        result["written"] = paths(
            step("note", lambda: render(url, settings, language=language, formats=[]))
        )
        enriched = step(
            "enrich", lambda: enrich(url, settings, force=force, language=language)
        )
        spent(enriched.get("cost") or {})
        framed = step(
            "frames", lambda: frames(url, settings, force=force, language=language)
        )
        spent(framed.get("cost") or {})
        result["images"] = sum(1 for f in framed.get("frames") or [] if f.get("chosen"))
        result["written"] = paths(
            step(
                "render",
                lambda: render(url, settings, language=language, formats=formats),
            )
        )
    except (FetchError, LlmError) as error:
        result["error"] = {"step": result["step"] or "fetch", "message": str(error)}
    result["seconds"] = round(time.monotonic() - started, 1)
    return result


def paths(written: dict[str, Path]) -> dict[str, str]:
    """What render returned, as strings a job can carry as JSON."""
    return {kind: str(path) for kind, path in written.items()}


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
