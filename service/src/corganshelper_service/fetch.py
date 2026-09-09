"""Step 1: metadata, thumbnail and subtitles of a YouTube video.

No video and no audio here on purpose: frames come from short sections
fetched later, and audio only when there are no subtitles to read.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .config import Settings

VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
URL_IN_TEXT = re.compile(r"https?://[^\s)>\]]+")
RESULT_NAME = "fetch.json"


class FetchError(Exception):
    """Something a retry will not fix without a change: bad URL, sign-in check."""


def video_id(url: str) -> str:
    """The eleven-character id of a YouTube watch, share, shorts or embed URL."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().removeprefix("www.").removeprefix("m.")
    candidate = None
    if host == "youtu.be":
        candidate = parsed.path.strip("/").split("/")[0]
    elif host in ("youtube.com", "music.youtube.com"):
        if parsed.path == "/watch":
            candidate = parse_qs(parsed.query).get("v", [None])[0]
        else:
            parts = parsed.path.strip("/").split("/")
            if len(parts) >= 2 and parts[0] in ("shorts", "embed", "live", "v"):
                candidate = parts[1]
    if not candidate or not VIDEO_ID.match(candidate):
        raise FetchError(f"not a YouTube video URL: {url}")
    return candidate


def work_folder(settings: Settings, vid: str) -> Path:
    return settings.work_dir / vid


def _ydl_options(folder: Path, settings: Settings) -> dict:
    options = {
        "skip_download": True,
        "writeinfojson": True,
        "writethumbnail": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        # Filled in per video by `subtitle_languages`: every extra language
        # costs a request YouTube renders on demand, the third of them
        # answered 429 on 2026-09-09, and `.*-orig` matched 21 dubbed tracks.
        "subtitleslangs": [],
        "subtitlesformat": "json3",
        "sleep_interval_subtitles": 2,
        "retries": 3,
        "retry_sleep_functions": {"http": lambda attempt: 5 * attempt},
        "outtmpl": str(folder / "%(id)s.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
    }
    if settings.cookies_file:
        options["cookiefile"] = str(settings.cookies_file)
    return options


def subtitle_languages(info: dict) -> list[str]:
    """The track YouTube transcribed from the original audio, plus a manual
    track in that language when the uploader provided one.

    `language` names the audio; the auto captions of that audio are called
    `<lang>-orig`. Dubbed audio tracks bring their own `<xx>-orig`, which is
    why the list is built from the language and not from a wildcard.
    """
    language = (info.get("language") or "").split("-")[0]
    automatic = info.get("automatic_captions") or {}
    if not language:
        original = sorted(key for key in automatic if key.endswith("-orig"))
        language = original[0].removesuffix("-orig") if original else "en"
    wanted = [f"{language}-orig"]
    # A plain `en` in the automatic captions is rendered on request and
    # answered 429 on 2026-09-09; only an uploader's own track is worth it.
    if language in (info.get("subtitles") or {}):
        wanted.append(language)
    return wanted


class _Log:
    """Collects what yt-dlp reports while `ignoreerrors` keeps it running."""

    def __init__(self) -> None:
        self.errors: list[str] = []

    def debug(self, message: str) -> None:
        pass

    def info(self, message: str) -> None:
        pass

    def warning(self, message: str) -> None:
        pass

    def error(self, message: str) -> None:
        self.errors.append(message)


def convert_thumbnail(folder: Path, vid: str) -> Path | None:
    """YouTube serves webp; python-docx cannot embed that, so jpg it is.

    yt-dlp's own converter is a post-processor that never runs when the
    video download is skipped, hence ffmpeg by hand.
    """
    target = folder / f"{vid}.jpg"
    if target.exists():
        return target
    source = next(
        (p for p in folder.glob(f"{vid}.*") if p.suffix in (".webp", ".png")), None
    )
    if source is None:
        return None
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(source), str(target)],
        check=True,
    )
    source.unlink()
    return target


def summarise(info: dict, folder: Path, vid: str, url: str) -> dict:
    subtitles = sorted(p.name for p in folder.glob(f"{vid}.*.json3"))
    thumbnail = folder / f"{vid}.jpg"
    description = info.get("description") or ""
    return {
        "id": vid,
        "url": url,
        "title": info.get("title"),
        "channel": info.get("channel") or info.get("uploader"),
        "upload_date": info.get("upload_date"),
        "duration": info.get("duration"),
        "chapters": len(info.get("chapters") or []),
        "description_links": len(URL_IN_TEXT.findall(description)),
        "info": f"{vid}.info.json",
        "thumbnail": thumbnail.name if thumbnail.exists() else None,
        "subtitles": subtitles,
    }


def fetch(url: str, settings: Settings, force: bool = False) -> dict:
    """Fill work/<id>/ and return the summary; a second call returns the
    stored summary unless `force` is set."""
    vid = video_id(url)
    folder = work_folder(settings, vid)
    result_path = folder / RESULT_NAME
    if result_path.exists() and not force:
        return json.loads(result_path.read_text(encoding="utf-8"))

    import yt_dlp  # slow import, kept out of the module load

    folder.mkdir(parents=True, exist_ok=True)
    options = _ydl_options(folder, settings)
    try:
        # Pass one only reads which language the audio is in; a sign-in
        # check surfaces here as an error.
        with yt_dlp.YoutubeDL({**options, "writesubtitles": False}) as probe:
            info = probe.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as error:
        message = str(error)
        if "Sign in to confirm" in message or "not a bot" in message:
            raise FetchError(
                "YouTube asks for a sign-in (bot check). Set CORGANSHELPER_COOKIES "
                "to a cookies file exported the way the yt-dlp wiki describes, "
                "or try again later."
            ) from error
        raise FetchError(message) from error

    # Pass two writes info.json, the thumbnail and that language's captions.
    # A caption that fails (429 is YouTube's answer to too many requests)
    # must not cost the rest: the log keeps the message, transcribe falls
    # back to whisper when no track arrived.
    log = _Log()
    options["subtitleslangs"] = subtitle_languages(info)
    options["ignoreerrors"] = True
    options["logger"] = log
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=True) or info

    convert_thumbnail(folder, vid)
    result = summarise(info, folder, vid, url)
    result["warnings"] = log.errors
    result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result
