"""Step 2: a transcript with timestamps.

YouTube's own caption track is the default; it exists for every test video
and costs nothing. faster-whisper is the fallback when no track arrived, or
the way out when the captions mangle the terms that matter (`--engine
whisper`). The result has the same shape either way.
"""

from __future__ import annotations

import json
import os
import subprocess
from itertools import pairwise
from pathlib import Path

from .config import Settings
from .fetch import RESULT_NAME as FETCH_RESULT
from .fetch import FetchError, fetch, work_folder

RESULT_NAME = "transcript.json"
WHISPER_MODEL = "large-v3-turbo"
# NVIDIA's Parakeet TDT 0.6B v3 (25 European languages) as ONNX, through
# onnx-asr. Hears 20 to 30 seconds at a time; the Silero VAD cuts the
# audio into speech segments first, and those become the transcript lines.
PARAKEET_MODEL = "nemo-parakeet-tdt-0.6b-v3"


class Segment(dict):
    """{start, end, text}, seconds as floats."""


def segments_from_json3(data: dict) -> list[dict]:
    """YouTube writes one event per caption line; `aAppend` events only carry
    the line break that scrolls the previous line up. A line's own duration
    overlaps the next line on screen, so the next line's start ends it."""
    lines = []
    for event in data.get("events", []):
        if event.get("aAppend") or "segs" not in event:
            continue
        text = "".join(seg.get("utf8", "") for seg in event["segs"]).strip()
        if not text:
            continue
        start = event["tStartMs"] / 1000
        lines.append([start, start + event.get("dDurationMs", 0) / 1000, text])
    for current, following in pairwise(lines):
        current[1] = min(current[1], following[0])
    return [{"start": s, "end": e, "text": t} for s, e, t in lines]


def audio_path(folder: Path, vid: str) -> Path:
    return folder / f"{vid}.m4a"


def download_audio(url: str, folder: Path, settings: Settings) -> Path:
    """Audio only, once, for whisper. Deleted again by the cleanup step."""
    target = audio_path(folder, video_id_of(folder))
    if target.exists():
        return target
    import yt_dlp

    options = {
        "format": "bestaudio[ext=m4a]/bestaudio/best",
        "outtmpl": str(folder / "%(id)s.%(ext)s"),
        "postprocessors": [
            {"key": "FFmpegExtractAudio", "preferredcodec": "m4a"},
        ],
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
        raise FetchError(f"audio download failed: {error}") from error
    if not target.exists():
        raise FetchError(f"audio download left no {target.name}")
    return target


def video_id_of(folder: Path) -> str:
    return folder.name


def whisper_device() -> tuple[str, int, str]:
    """(device, index, compute_type) from CORGANSHELPER_WHISPER, default the
    first CUDA device in float16. `cpu` means int8 on the CPU. Parakeet
    reads the same variable, so one setting moves both local models."""
    spec = os.environ.get("CORGANSHELPER_WHISPER", "cuda:0")
    if spec == "cpu":
        return "cpu", 0, "int8"
    device, _, index = spec.partition(":")
    return device, int(index or 0), "float16"


def add_nvidia_dll_dirs() -> list[Path]:
    """Windows finds cuBLAS and cuDNN only on the DLL search path. The pip
    wheels (`nvidia-cublas-cu12`, `nvidia-cudnn-cu12`, the `gpu` extra) put
    them under site-packages/nvidia/*/bin, so those go on the path here
    before ctranslate2 loads. A no-op elsewhere."""
    if os.name != "nt" or not hasattr(os, "add_dll_directory"):
        return []
    import sysconfig

    added = []
    root = Path(sysconfig.get_paths()["purelib"]) / "nvidia"
    for binary_dir in sorted(root.glob("*/bin")):
        os.add_dll_directory(str(binary_dir))
        added.append(binary_dir)
    # ctranslate2 loads cuBLAS by name at first use through the plain search
    # order, which ignores add_dll_directory; PATH is what it reads.
    if added:
        os.environ["PATH"] = os.pathsep.join(
            [str(p) for p in added] + [os.environ.get("PATH", "")]
        )
    return added


def whisper_transcribe(audio: Path, models_dir: Path) -> tuple[str, list[dict]]:
    add_nvidia_dll_dirs()
    from faster_whisper import WhisperModel

    device, index, compute = whisper_device()
    # The model (1.6 GB) lives next to the data, not in the user's cache;
    # first use downloads it from Hugging Face.
    models_dir.mkdir(parents=True, exist_ok=True)
    model = WhisperModel(
        WHISPER_MODEL,
        device=device,
        device_index=index,
        compute_type=compute,
        download_root=str(models_dir),
    )
    # Without the previous window as prompt the model cannot fall into a
    # loop of its own words: on 2026-09-09 one run of the 5-minute test
    # video carried 210 repeated six-word runs, and the run without the
    # prompt none, in half the time.
    segments, info = model.transcribe(
        str(audio), beam_size=5, vad_filter=True, condition_on_previous_text=False
    )
    result = [
        {"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()}
        for s in segments
    ]
    return info.language, result


def to_wav16k(audio: Path) -> Path:
    """Mono 16 kHz WAV, the one format every ONNX speech model reads."""
    target = audio.with_suffix(".16k.wav")
    if not target.exists():
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(audio)]
            + ["-ac", "1", "-ar", "16000", str(target)],
            check=True,
        )
    return target


def parakeet_transcribe(audio: Path, models_dir: Path) -> list[dict]:
    add_nvidia_dll_dirs()
    import onnx_asr

    device, index, _ = whisper_device()
    providers: list = ["CPUExecutionProvider"]
    if device == "cuda":
        providers.insert(0, ("CUDAExecutionProvider", {"device_id": index}))
    # The model (about 2.5 GB as ONNX) lives next to the data, like whisper's.
    model = onnx_asr.load_model(
        PARAKEET_MODEL, models_dir / "parakeet-v3", providers=providers
    )
    vad = onnx_asr.load_vad("silero", providers=providers)
    return [
        {"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()}
        for s in model.with_vad(vad).recognize(str(to_wav16k(audio)))
        if s.text.strip()
    ]


def track_language(tracks: list[str]) -> str:
    """`en` from `<id>.en-orig.json3`; `und` when no track says."""
    if not tracks:
        return "und"
    return Path(tracks[0]).name.split(".")[-2].removesuffix("-orig")


def shrink_for_upload(audio: Path) -> Path:
    """Mono MP3 at 48 kbit/s: a 25 MB cap sits on the transcription
    endpoint, and half an hour of m4a is past it. Whisper resamples to
    16 kHz anyway, so nothing it hears is lost."""
    target = audio.with_suffix(".upload.mp3")
    if not target.exists():
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(audio)]
            + ["-vn", "-ac", "1", "-b:a", "48k", str(target)],
            check=True,
        )
    return target


def openai_transcribe(audio: Path, settings: Settings) -> tuple[str, list[dict]]:
    """whisper-1 at OpenAI, or at any server that speaks its protocol."""
    import openai

    config = settings.config
    if not config["openai_api_key"]:
        raise FetchError(
            "no OpenAI API key; put it in config.json as openai_api_key "
            "or set OPENAI_API_KEY"
        )
    client = openai.OpenAI(
        api_key=config["openai_api_key"],
        base_url=config["openai_base_url"] or None,
        timeout=600,
    )
    try:
        with shrink_for_upload(audio).open("rb") as handle:
            result = client.audio.transcriptions.create(
                model="whisper-1",
                file=handle,
                response_format="verbose_json",
                timestamp_granularities=["segment"],
            )
    except openai.OpenAIError as error:
        raise FetchError(f"openai transcription failed: {error}") from error
    segments = [
        {"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()}
        for s in result.segments or []
    ]
    return result.language, segments


def transcribe(
    url: str, settings: Settings, force: bool = False, engine: str | None = None
) -> dict:
    """Write work/<id>/transcript.json and return it. `engine` is `auto`
    (captions when present, else local whisper), `subtitles`, `whisper`,
    `parakeet` or `openai`; default from the settings."""
    engine = engine or settings.config["stt"]
    fetched = fetch(url, settings)
    vid = fetched["id"]
    folder = work_folder(settings, vid)
    result_path = folder / RESULT_NAME
    if result_path.exists() and not force:
        return json.loads(result_path.read_text(encoding="utf-8"))
    if not (folder / FETCH_RESULT).exists():
        raise FetchError("fetch first")

    tracks = fetched.get("subtitles") or []
    if engine == "subtitles" and not tracks:
        raise FetchError("no caption track was fetched; use --engine whisper")
    if engine in ("auto", "subtitles") and tracks:
        # An uploader's own track (`en`) beats the automatic one (`en-orig`).
        track = folder / min(tracks, key=lambda name: "-orig" in name)
        data = json.loads(track.read_text(encoding="utf-8"))
        language = track.name.split(".")[-2].removesuffix("-orig")
        segments = segments_from_json3(data)
        source = "youtube"
    elif engine == "openai":
        audio = download_audio(url, folder, settings)
        language, segments = openai_transcribe(audio, settings)
        source = "openai"
    elif engine == "parakeet":
        audio = download_audio(url, folder, settings)
        # Parakeet names no language; the caption track does, when there is one.
        language = track_language(tracks)
        segments = parakeet_transcribe(audio, settings.home / "models")
        source = "parakeet"
    else:
        audio = download_audio(url, folder, settings)
        language, segments = whisper_transcribe(audio, settings.home / "models")
        source = "whisper"

    result = {
        "id": vid,
        "source": source,
        "language": language,
        "segments": segments,
        "text": " ".join(s["text"] for s in segments),
    }
    result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def run_ffprobe_duration(path: Path) -> float:
    """Seconds of media in a file, for the batch table later."""
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nw=1:nk=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(out.stdout.strip())
