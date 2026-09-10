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
    FORMATS,
    LLM_BACKENDS,
    STT_DEFAULT,
    STT_ENGINES,
    STT_MODELS,
    ConfigError,
    Settings,
    parse_assignments,
    store,
)
from .enrich import enrich
from .fetch import FetchError, fetch
from .frames import frames
from .llm import LlmError
from .render import render
from .run import bench, bench_table, header, row, run, urls_in
from .serve import PORT, serve
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
    models_cmd = commands.add_parser(
        "models", help="list the models the llm backend offers, or the stt ones"
    )
    models_cmd.add_argument("kind", nargs="?", choices=["llm", "stt"], default="llm")
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
        ("enrich", "read the installation steps out of the linked repositories"),
        ("frames", "fetch, pick and label the pictures worth keeping"),
        ("render", "write summary.md from the analysis, pictures and steps"),
    ):
        cmd = commands.add_parser(name, help=help_text)
        cmd.add_argument("url")
        cmd.add_argument("--language", help="language of the note; default from config")
        cmd.add_argument(
            "--force", action="store_true", help="redo although a result exists"
        )
        if name == "render":
            cmd.add_argument(
                "--format",
                action="append",
                choices=FORMATS,
                help="an output besides summary.md; repeatable; default from config",
            )
    run_cmd = commands.add_parser(
        "run", help="every step in a row, for one URL or for --batch FILE"
    )
    run_cmd.add_argument("url", nargs="?")
    run_cmd.add_argument(
        "--batch",
        type=Path,
        metavar="FILE",
        help="one URL per line; prints a Markdown table, one row per video",
    )
    run_cmd.add_argument("--language", help="language of the note; default from config")
    run_cmd.add_argument(
        "--force", action="store_true", help="redo every step although results exist"
    )
    run_cmd.add_argument(
        "--format",
        action="append",
        choices=FORMATS,
        help="an output besides summary.md; repeatable; default from config",
    )
    bench_cmd = commands.add_parser(
        "bench", help="analyze one video with several models and compare them"
    )
    bench_cmd.add_argument("url")
    bench_cmd.add_argument(
        "--models", required=True, metavar="A,B,C", help="model names, comma separated"
    )
    bench_cmd.add_argument(
        "--repeat", type=int, default=1, help="runs per model; default 1"
    )
    serve_cmd = commands.add_parser(
        "serve", help="listen on 127.0.0.1 for the extension until Ctrl+C"
    )
    serve_cmd.add_argument("--port", type=int, default=PORT, help=f"default {PORT}")
    return parser


def main(argv: list[str] | None = None) -> int:
    # A caption with a heart character crashed the print of frames.json on
    # a cp1252 pipe (2026-09-10). The output is UTF-8, and a console that
    # cannot show a character shows a question mark instead of a traceback.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "run" and not (args.url or args.batch):
        parser.error("run needs a URL or --batch FILE")
    overrides = {"llm": args.llm, "model": args.model, "stt": args.stt}
    try:
        if args.command == "config" and args.set:
            # Written first, then loaded like any other run reads it.
            store(args.home, parse_assignments(args.set))
        settings = Settings.load(home=args.home, overrides=overrides)
    except ConfigError as error:
        print(f"config error: {error}", file=sys.stderr)
        return 1

    if args.command == "serve":
        try:
            return serve(args.home, overrides, args.port)
        except OSError as error:
            print(f"serve failed: {error}", file=sys.stderr)
            return 1

    if args.command == "run":
        urls = urls_in(args.batch) if args.batch else [args.url]
        if args.batch:
            print(header(), flush=True)
        failed = 0
        for url in urls:
            result = run(
                url,
                settings,
                force=args.force,
                language=args.language,
                formats=args.format,
                progress=lambda step, detail="", url=url: print(
                    f"  {url} {step} {detail}".rstrip(), file=sys.stderr
                ),
            )
            if result["error"]:
                failed += 1
                print(
                    f"{url}: {result['error']['step']} failed: "
                    f"{result['error']['message']}",
                    file=sys.stderr,
                )
            if args.batch:
                print(row(result), flush=True)
            else:
                print(json.dumps(result, indent=2, ensure_ascii=False))
        return 1 if failed else 0

    if args.command == "bench":
        names = [name.strip() for name in args.models.split(",") if name.strip()]
        if not names:
            parser.error("bench needs --models with at least one name")
        try:
            rows = bench(
                args.url,
                settings,
                names,
                args.repeat,
                progress=lambda step, detail="": print(
                    f"  {step} {detail}".rstrip(), file=sys.stderr
                ),
            )
        except (FetchError, LlmError) as error:
            print(f"bench failed: {error}", file=sys.stderr)
            return 1
        print(bench_table(rows))
        return 0

    if args.command == "probe":
        problems = probe(settings)
        for problem in problems:
            print(problem, file=sys.stderr)
        print("probe failed" if problems else f"probe ok, home {settings.home}")
        return 1 if problems else 0

    if args.command == "config":
        print(json.dumps(settings.shown(), indent=2))
        return 0

    if args.command == "models" and args.kind == "stt":
        print(f"{'auto':14} caption track when there is one, else {STT_DEFAULT}")
        print(f"{'subtitles':14} caption track only")
        print(f"{'':14} {'speed':6} {'WER':7} {'languages':26} engine:model")
        for name, spec in STT_MODELS.items():
            print(
                f"{name:14} {spec['speed']:6} {spec['wer'] or '-':7} "
                f"{spec['languages']:26} {spec['engine']}:{spec['model']}"
            )
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

    steps = {"analyze": analyze, "enrich": enrich, "frames": frames}
    if args.command in steps:
        try:
            result = steps[args.command](
                args.url, settings, force=args.force, language=args.language
            )
        except (FetchError, LlmError) as error:
            print(f"{args.command} failed: {error}", file=sys.stderr)
            return 1
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    if args.command == "render":
        try:
            written = render(
                args.url,
                settings,
                force=args.force,
                language=args.language,
                formats=args.format,
            )
        except (FetchError, LlmError) as error:
            print(f"render failed: {error}", file=sys.stderr)
            return 1
        for kind, path in written.items():
            print(f"{kind:9} {path}")
        return 0

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
