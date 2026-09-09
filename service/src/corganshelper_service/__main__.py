"""Command line entry point: the same code paths the HTTP service will serve."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from . import __version__
from .config import Settings
from .fetch import FetchError, fetch

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
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog=PROG)
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.add_argument(
        "--home",
        type=Path,
        help="data directory; default CORGANSHELPER_HOME or D:/corganshelper",
    )
    commands = parser.add_subparsers(dest="command")
    commands.add_parser(
        "probe", help="check the tools and the data directory, change nothing"
    )
    fetch_cmd = commands.add_parser(
        "fetch", help="store metadata, thumbnail and subtitles of a video"
    )
    fetch_cmd.add_argument("url")
    fetch_cmd.add_argument(
        "--force", action="store_true", help="fetch again although a result exists"
    )
    args = parser.parse_args(argv)
    settings = Settings.load(home=args.home)

    if args.command == "probe":
        problems = probe(settings)
        for problem in problems:
            print(problem, file=sys.stderr)
        print("probe failed" if problems else f"probe ok, home {settings.home}")
        return 1 if problems else 0

    if args.command == "fetch":
        try:
            result = fetch(args.url, settings, force=args.force)
        except FetchError as error:
            print(f"fetch failed: {error}", file=sys.stderr)
            return 1
        print(json.dumps(result, indent=2))
        return 0

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
