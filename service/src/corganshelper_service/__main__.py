"""Command line entry point: the same code paths the HTTP service will serve."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from . import __version__, llm
from .analyze import analyze
from .config import (
    LLM_BACKENDS,
    STT_ENGINES,
    ConfigError,
    Settings,
    parse_assignments,
    store,
)
from .fetch import FetchError, fetch
from .llm import LlmError
from .render import render
from .transcribe import transcribe

PROG = "corganshelper"


def probe(settings: Settings) -> list[str]:
    """What keeps the pipeline from running; empty when nothing does."""
    problems: list[str] = []
    try:
        import yt_dlp  # noqa: F401
    except ImportError:
        problems.append("yt-dlp is not installed")
    if shutil.which("ffmpeg") is None:
        problems.append("ffmpeg is not on the PATH")
    try:
        settings.work_dir.mkdir(parents=True, exist_ok=True)
        marker = settings.work_dir / ".probe"
        marker.write_text("ok", encoding="utf-8")
        marker.unlink()
    except OSError as error:
        problems.append(f"{settings.work_dir} is not writable: {error}")
    trouble = llm.check(settings)
    if trouble:
        problems.append(f"llm {llm.backend(settings)}: {trouble}")
    return problems


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=PROG)
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.add_argument(
        "--home",
        type=Path,
        help="data directory; default CORGANSHELPER_HOME or D:/corganshelper",
    )
    parser.add_argument(
        "--llm", choices=LLM_BACKENDS, help="language model backend for this run"
    )
    parser.add_argument("--model", help="model name at that backend")
    parser.add_argument(
        "--stt", choices=STT_ENGINES, help="speech-to-text engine for this run"
    )
    commands = parser.add_subparsers(dest="command")
    commands.add_parser(
        "probe", help="check the tools, the data directory and the backend"
    )
    config_cmd = commands.add_parser(
        "config", help="show the settings, or change them with --set"
    )
    config_cmd.add_argument(
        "--set",
        metavar="KEY=VALUE",
        action="append",
        default=[],
        help="write a setting to config.json; repeatable",
    )
    commands.add_parser("models", help="list the models the llm backend offers")
    fetch_cmd = commands.add_parser(
        "fetch", help="store metadata, thumbnail and subtitles of a video"
    )
    fetch_cmd.add_argument("url")
    fetch_cmd.add_argument(
        "--force", action="store_true", help="fetch again although a result exists"
    )
    transcribe_cmd = commands.add_parser(
        "transcribe", help="turn the caption track, or whisper, into segments"
    )
    transcribe_cmd.add_argument("url")
    transcribe_cmd.add_argument(
        "--engine",
        choices=STT_ENGINES,
        help="auto takes the caption track when there is one; default from config",
    )
    transcribe_cmd.add_argument(
        "--force", action="store_true", help="transcribe again although a result exists"
    )
    for name, help_text in (
        ("analyze", "ask the model what the video is about, as JSON"),
        ("render", "write summary.md from the analysis"),
    ):
        cmd = commands.add_parser(name, help=help_text)
        cmd.add_argument("url")
        cmd.add_argument("--language", help="language of the note; default from config")
        cmd.add_argument(
            "--force", action="store_true", help="redo although a result exists"
        )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "config" and args.set:
            # Written first, then loaded like any other run reads it.
            store(args.home, parse_assignments(args.set))
        settings = Settings.load(
            home=args.home,
            overrides={"llm": args.llm, "model": args.model, "stt": args.stt},
        )
    except ConfigError as error:
        print(f"config error: {error}", file=sys.stderr)
        return 1

    if args.command == "probe":
        problems = probe(settings)
        for problem in problems:
            print(problem, file=sys.stderr)
        print("probe failed" if problems else f"probe ok, home {settings.home}")
        return 1 if problems else 0

    if args.command == "config":
        print(json.dumps(settings.shown(), indent=2))
        return 0

    if args.command == "models":
        try:
            names = llm.models(settings)
        except LlmError as error:
            print(f"models failed: {error}", file=sys.stderr)
            return 1
        print("\n".join(names))
        return 0

    if args.command == "fetch":
        try:
            result = fetch(args.url, settings, force=args.force)
        except FetchError as error:
            print(f"fetch failed: {error}", file=sys.stderr)
            return 1
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "transcribe":
        try:
            result = transcribe(
                args.url, settings, force=args.force, engine=args.engine
            )
        except FetchError as error:
            print(f"transcribe failed: {error}", file=sys.stderr)
            return 1
        shown = {**result, "segments": f"{len(result['segments'])} segments"}
        shown["text"] = result["text"][:200] + "…"
        print(json.dumps(shown, indent=2, ensure_ascii=False))
        return 0

    if args.command == "analyze":
        try:
            result = analyze(
                args.url, settings, force=args.force, language=args.language
            )
        except (FetchError, LlmError) as error:
            print(f"analyze failed: {error}", file=sys.stderr)
            return 1
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    if args.command == "render":
        try:
            target = render(
                args.url, settings, force=args.force, language=args.language
            )
        except (FetchError, LlmError) as error:
            print(f"render failed: {error}", file=sys.stderr)
            return 1
        print(target)
        return 0

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
