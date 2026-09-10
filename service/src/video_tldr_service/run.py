"""Every step in a row: `video-tldr run URL` is what the service runs
for a job, `run --batch urls.txt` what measures the pipeline over many.

Each step skips itself when its result exists, so a second run of the
same video costs seconds; `force` redoes every step. The note is
rendered once right after analyze, before the expensive steps, so a
video that fails in frames still has a readable summary. What a run
took and cost goes to the video's `tmp/run.json`; `stats()` reads those back
for the popup's time estimate and the options page's model table.

`bench()` is the other way in: the same analyze step over several models,
so the owner can see what a model costs before choosing it.
"""

from __future__ import annotations

import json
import shutil
import statistics
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from . import llm
from .analyze import analyze
from .config import WORK, Settings
from .enrich import enrich
from .fetch import FetchError, fetch, video_id, work_folder
from .frames import frames
from .llm import LlmError
from .render import render
from .transcribe import transcribe

# In the order they run. `note` is render with no format but summary.md.
STEPS = ["fetch", "transcribe", "analyze", "note", "enrich", "frames", "render"]
RESULT_NAME = "run.json"
# What only the language model can write. A folder that holds all three
# answers every step from the cache, so such a run needs no model and no
# reachable server.
MODEL_RESULTS = ("analysis.json", "enrich.json", "frames.json")
# A step under this took its result from the cache and says nothing
# about how long the step takes.
CACHED_SECONDS = 0.05
# Called with (step) when a step starts and (step, detail) when it ends;
# the detail names what the step did in one line.
Progress = Callable[..., None]


class Cancelled(Exception):
    """`should_stop` said so between two steps."""


def needs_model(settings: Settings, vid: str, force: bool = False) -> bool:
    """Whether a run of this video would ask the language model at all.
    The caller checks the backend before queueing a job, and a video whose
    steps are all cached must not be turned away for a server it never
    talks to."""
    if force:
        return True
    folder = work_folder(settings, vid)
    return any(not (folder / name).exists() for name in MODEL_RESULTS)


def run(
    url: str,
    settings: Settings,
    force: bool = False,
    language: str | None = None,
    formats: list[str] | None = None,
    progress: Progress | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> dict:
    """Run every step for one video and return what happened: the seconds
    per step, the pictures kept, the tokens spent, the files written. A
    step that fails ends the run with `error` naming it; what the steps
    before it wrote stays in `written`. `progress` hears each step start
    and end. `should_stop` is asked before each step and ends the run with
    `cancelled`; a step that has begun is never interrupted, because
    killing yt-dlp or ffmpeg halfway leaves a broken file behind."""
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
        # The first failure, and every one of them: a step that only adds
        # to the note lets the run go on, so there can be more than one.
        "error": None,
        "errors": [],
    }
    started = time.monotonic()

    def tell(*event: str) -> None:
        if progress:
            progress(*event)

    def step(name: str, call: Callable[[], dict], describe=None) -> dict:
        result["step"] = name
        if should_stop and should_stop():
            raise Cancelled("cancelled")
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

    def failed(name: str, error: Exception) -> None:
        """Every failure lands in `errors`; `error` keeps the first one,
        which is what the badge and the older readers show."""
        entry = {"step": name, "message": str(error)}
        result["errors"].append(entry)
        result["error"] = result["error"] or entry
        tell(name, f"failed: {error}")

    def optional(name: str, call: Callable[[], dict], describe=None) -> dict:
        """A step whose failure costs its own part of the note and not the
        rest of the run: the outputs are still rendered from what the
        steps before it produced."""
        try:
            return step(name, call, describe)
        except (FetchError, LlmError) as error:
            failed(name, error)
            return {}

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
        # The two steps that add to the note rather than make it: one of
        # them failing costs its own part, not the video (asked for on
        # 2026-09-10, after a blind model ended a run at the pictures).
        enriched = optional(
            "enrich",
            lambda: enrich(url, settings, force=force, language=language),
            lambda e: (
                cost_line(e.get("cost") or {})
                + f", {len(e.get('repositories') or [])} repositories"
            ),
        )
        spent(enriched.get("cost") or {})
        framed = optional(
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
    except (FetchError, LlmError, Cancelled) as error:
        failed(result["step"] or "fetch", error)
    result["seconds"] = round(time.monotonic() - started, 1)
    if result["id"]:
        folder = work_folder(settings, result["id"])
        folder.mkdir(parents=True, exist_ok=True)
        (folder / RESULT_NAME).write_text(
            json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        # Cleaned only after a run that wrote every output: a failed step
        # is worth resuming, and that needs the files it left behind.
        if not result["errors"] and settings.config.get("cleanup") == "on":
            tell("cleanup", cleanup(folder))
    return result


def cleanup(folder: Path) -> str:
    """Empty `work/<id>/` but for run.json, which `stats` reads back. Only
    after a run that wrote its outputs: what goes here is the transcript
    and the video clips, and a failed run is worth resuming."""
    removed = 0
    for path in folder.iterdir():
        if path.name == RESULT_NAME:
            continue
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        else:
            path.unlink()
        removed += 1
    return f"{removed} removed from {folder}, run.json kept"


def paths(written: dict[str, Path]) -> dict[str, str]:
    """What render returned, as strings a job can carry as JSON."""
    return {kind: str(path) for kind, path in written.items()}


def stats(settings: Settings) -> dict:
    """What earlier runs on this machine took: the median seconds per
    step (cached steps left out), and per language model and transcriber
    the runs, seconds and tokens they cost. Empty until a run happened."""
    runs = []
    for path in sorted(settings.library.glob(f"*/{WORK}/{RESULT_NAME}")):
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


# The bench table, column heading to row key.
BENCH_NAME = "bench.json"
BENCH_COLUMNS = {
    "model": "model",
    "run": "run",
    "seconds": "seconds",
    "input": "input",
    "output": "output",
    "tokens/s": "tokens_per_second",
    "sections": "sections",
    "key points": "key_points",
    "links": "links",
}


def bench(
    url: str,
    settings: Settings,
    models: list[str],
    repeat: int = 1,
    progress: Progress | None = None,
) -> list[dict]:
    """What each model makes of one video: analyze again per name, `repeat`
    times, one row per run. Only analyze, because that is the step the
    model decides; the rows also land in `<home>/bench.json`, so a later
    bench compares against this one."""
    rows: list[dict] = []
    for name in models:
        for number in range(1, repeat + 1):
            # The backend stays what it is; only the model name changes.
            chosen = replace(settings, config={**settings.config, "model": name})
            step = f"bench {name} {number}"
            if progress:
                progress(step)
            began = time.monotonic()
            result = analyze(url, chosen, force=True)
            seconds = round(time.monotonic() - began, 1)
            cost = result.get("cost") or {}
            output = cost.get("output", 0)
            rows.append(
                {
                    "model": name,
                    "run": number,
                    "seconds": seconds,
                    "input": cost.get("input", 0),
                    "output": output,
                    # The backend counts this itself where it can; the
                    # division is the fallback and counts the wait too.
                    "tokens_per_second": round(
                        llm.last_cost.get("tokens_per_second")
                        or (output / seconds if seconds else 0.0),
                        1,
                    ),
                    "sections": len(result.get("sections") or []),
                    "key_points": len(result.get("key_points") or []),
                    "links": len(result.get("links") or []),
                }
            )
            if progress:
                progress(step, f"{seconds}s, {output} tokens")
    store_bench(settings, rows)
    return rows


def bench_path(settings: Settings) -> Path:
    return settings.home / BENCH_NAME


def read_bench(settings: Settings) -> list[dict]:
    """Every row an earlier bench wrote; empty until one ran."""
    try:
        stored = json.loads(bench_path(settings).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return stored if isinstance(stored, list) else []


def store_bench(settings: Settings, rows: list[dict]) -> Path:
    """Append the rows; a bench is worth comparing against the last one."""
    path = bench_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(read_bench(settings) + rows, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def bench_table(rows: list[dict]) -> str:
    """The rows as Markdown, heading included."""
    lines = [
        "| " + " | ".join(BENCH_COLUMNS) + " |",
        "|" + "---|" * len(BENCH_COLUMNS),
    ]
    for entry in rows:
        cells = [str(entry.get(key, "")) for key in BENCH_COLUMNS.values()]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


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
