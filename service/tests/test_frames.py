import json
import struct
import zlib
from pathlib import Path

import pytest

from corganshelper_service import frames as frames_module
from corganshelper_service import llm
from corganshelper_service.config import Settings
from corganshelper_service.frames import (
    LABEL_SCHEMA,
    LIMIT,
    NO_VISION,
    PROBE_HEIGHT,
    PROBE_WIDTH,
    SEND_WIDTH,
    choose,
    frames,
    moments,
    png_width,
    sharpest_second,
    shrink,
)

VID = "jFHu6wx_TMQ"
PNG_SIGNATURE = bytes.fromhex("89504e470d0a1a0a")


def png(width: int, height: int = 2) -> bytes:
    """A real grey PNG of that size: signature, IHDR, IDAT, IEND."""

    def chunk(kind: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body))
            + kind
            + body
            + struct.pack(">I", zlib.crc32(kind + body))
        )

    rows = b"".join(bytes([0]) + bytes([128]) * width for _ in range(height))
    return (
        PNG_SIGNATURE
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


def prepare(tmp_path, candidates, kind="review"):
    settings = Settings(home=tmp_path)
    folder = settings.work_dir / VID
    folder.mkdir(parents=True)
    (folder / "fetch.json").write_text(
        json.dumps({"id": VID, "title": "t", "duration": 828}), encoding="utf-8"
    )
    (folder / "analysis.json").write_text(
        json.dumps(
            {
                "id": VID,
                "language": "de",
                "kind": kind,
                "sections": [],
                "key_points": [],
                "frame_candidates": candidates,
                "links": [],
            }
        ),
        encoding="utf-8",
    )
    return settings, folder


def test_the_frame_with_the_most_edges_wins():
    import numpy as np

    blank = np.full((PROBE_HEIGHT, PROBE_WIDTH), 128, dtype=np.uint8)
    checker = (np.indices((PROBE_HEIGHT, PROBE_WIDTH)).sum(axis=0) % 2 * 255).astype(
        np.uint8
    )
    assert sharpest_second(np.concatenate([blank, checker, blank]).tobytes()) == 1
    assert sharpest_second(b"") == 0


def test_candidates_keep_their_distance_and_sample_the_whole_video():
    close = [
        {"time": t, "kind": "ui", "why": "w"} for t in (7.0, 3.0, 20.0, 21.0, 30.0)
    ]
    # 3 and 7 would share the clip that starts at 0, 20 and 21 nearly so.
    assert [c["time"] for c in moments({"frame_candidates": close})] == [
        3.0,
        20.0,
        30.0,
    ]

    # Three parts of twelve, as analyze concatenates them for a long video.
    many = [{"time": float(t), "kind": "ui", "why": "w"} for t in range(0, 3600, 100)]
    picked = moments({"frame_candidates": many})
    assert len(picked) == frames_module.CANDIDATES
    assert picked[0]["time"] == 0.0 and picked[-1]["time"] >= 3000.0


def test_no_speaker_at_most_eight_and_diagrams_first_in_an_explainer():
    labeled = [
        {"file": f"{VID}-{i}.png", "time": i * 60, "label": "ui"} for i in range(1, 11)
    ]
    labeled[1]["label"] = "speaker"
    labeled[8]["label"] = "diagram"
    labeled[9]["label"] = "other"

    kept = choose(labeled, "review")
    assert len(kept) == LIMIT
    assert all(f["label"] != "speaker" for f in kept)
    assert [f["time"] for f in kept] == sorted(f["time"] for f in kept)
    # `other` goes last: the tenth picture is dropped before the ninth.
    assert labeled[9] not in kept and labeled[8] in kept

    kept = choose(labeled, "explainer", limit=2)
    assert labeled[8] in kept and len(kept) == 2


def test_frames_end_to_end_keeps_the_chosen_pictures_only(tmp_path, monkeypatch):
    candidates = [
        {"time": 20.0 * i, "kind": "ui", "why": f"w{i}"} for i in range(1, 11)
    ]
    settings, folder = prepare(tmp_path, candidates)
    # Left by an earlier run; a picture of that number is not made this time.
    (folder / f"{VID}-11.png").write_bytes(b"old")
    requests = []

    def fake_download(url, folder, vid, times, settings):
        clips = {}
        for t in times:
            clip = frames_module.clip_path(folder, vid, max(0.0, t - 8))
            clip.write_bytes(b"clip")
            clips[t] = clip
        return clips

    def fake_ffmpeg(*args):
        if args[0] == "-y":
            tmp_path.joinpath(args[-1]).write_bytes(b"png")
            return b""
        return bytes(PROBE_WIDTH * PROBE_HEIGHT)

    def fake_complete(instruction, data, schema, settings, images=None, max_turns=1):
        requests.append((instruction, data, schema, images, max_turns))
        index = int(images[0].stem.rsplit("-", 1)[1])
        label = {1: "speaker", 4: "speaker", 3: "diagram"}.get(index, "code")
        llm.last_cost.update(input=100, output=10, usd=0.01)
        return {
            "label": label,
            "caption": f"c{index - 1}",
            "commands": ["docker ps"] if index == 2 else [],
        }

    monkeypatch.setattr(frames_module, "download_clips", fake_download)
    monkeypatch.setattr(frames_module, "ffmpeg", fake_ffmpeg)
    monkeypatch.setattr(llm, "complete", fake_complete)

    result = frames(f"https://youtu.be/{VID}", settings)

    # One request per picture: the file in the prompt is the one attached.
    assert len(requests) == 10
    instruction, data, schema, images, max_turns = requests[0]
    assert schema is LABEL_SCHEMA
    assert images == [folder / f"{VID}-1.png"] and max_turns >= 2
    assert "at 0:20, analyze expected ui: w1" in data
    assert f"{VID}-1.png" in instruction
    assert result["cost"] == {"requests": 10, "input": 1000, "output": 100, "usd": 0.1}

    chosen = [f for f in result["frames"] if f["chosen"]]
    assert len(chosen) == LIMIT
    assert all(f["label"] != "speaker" for f in chosen)
    assert chosen[0]["caption"] == "c1" and chosen[0]["time"] == 40.0
    # The commands on screen travel with the picture that shows them.
    assert chosen[0]["commands"] == ["docker ps"] and chosen[1]["commands"] == []
    assert sorted(p.name for p in folder.glob("*.png")) == sorted(
        f["file"] for f in chosen
    )
    assert not list(folder.glob("*-clip-*"))
    assert json.loads((folder / "frames.json").read_text(encoding="utf-8")) == result
    assert frames_module.chosen_images(settings, VID) == chosen
    # A chosen diagram picture: no drawn one, and no request for it.
    assert result["diagram"] is None and frames_module.diagram_of(settings, VID) is None


def test_without_a_diagram_picture_the_model_may_draw_one(tmp_path, monkeypatch):
    settings, folder = prepare(tmp_path, [{"time": 40.0, "kind": "code", "why": "w"}])
    source = 'flowchart LR\n  A["Docker CLI"] --> B["dockerd"]'
    drawn = []

    def fake_download(url, folder, vid, times, settings):
        clip = frames_module.clip_path(folder, vid, 32.0)
        clip.write_bytes(b"clip")
        return {40.0: clip}

    def fake_ffmpeg(*args):
        if args[0] == "-y":
            tmp_path.joinpath(args[-1]).write_bytes(b"png")
            return b""
        return bytes(PROBE_WIDTH * PROBE_HEIGHT)

    def fake_complete(instruction, data, schema, settings, images=None, max_turns=1):
        llm.last_cost.update(input=100, output=10, usd=0.01)
        if schema is frames_module.DIAGRAM_SCHEMA:
            assert "Summary:" in data and images is None
            return {"mermaid": source, "caption": "Zwei Wege"}
        return {"label": "code", "caption": "c"}

    def fake_mermaid_png(mermaid, target, configured_browser=""):
        drawn.append((mermaid, configured_browser))
        target.write_bytes(b"diagram")
        return target

    monkeypatch.setattr(frames_module, "download_clips", fake_download)
    monkeypatch.setattr(frames_module, "ffmpeg", fake_ffmpeg)
    monkeypatch.setattr(frames_module, "mermaid_png", fake_mermaid_png)
    monkeypatch.setattr(llm, "complete", fake_complete)

    result = frames(f"https://youtu.be/{VID}", settings)

    assert drawn == [(source, "")]
    assert result["diagram"] == {
        "file": f"{VID}-diagram.png",
        "mermaid": source,
        "caption": "Zwei Wege",
    }
    assert result["cost"]["requests"] == 2
    assert frames_module.diagram_of(settings, VID) == result["diagram"]
    assert (folder / f"{VID}-diagram.png").exists()

    # A source Mermaid cannot read is dropped now, with a warning.
    def broken_png(mermaid, target, configured_browser=""):
        raise frames_module.FetchError("diagram: Mermaid could not read the source")

    monkeypatch.setattr(frames_module, "mermaid_png", broken_png)
    result = frames(f"https://youtu.be/{VID}", settings, force=True)
    # The source stays readable in the result, the note gets no picture.
    assert result["diagram"] == {
        "file": None,
        "mermaid": source,
        "caption": "Zwei Wege",
    }
    assert result["warnings"] == [
        "diagram dropped: diagram: Mermaid could not read the source"
    ]
    assert not (folder / f"{VID}-diagram.png").exists()
    assert frames_module.diagram_of(settings, VID) is None


def test_clips_are_cut_from_direct_https_formats_only(tmp_path, monkeypatch):
    import yt_dlp

    seen = {}

    class Recording:
        def __init__(self, options):
            seen.update(options)

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def download(self, urls):
            seen["urls"] = urls

    monkeypatch.setattr(yt_dlp, "YoutubeDL", Recording)
    clips = frames_module.download_clips(
        "https://youtu.be/x", tmp_path, "x", [3.0, 40.0], Settings(home=tmp_path)
    )
    assert seen["urls"] == ["https://youtu.be/x"]
    assert seen["format"].count("[protocol=https]") == 3
    assert "%(section_start)d" in seen["outtmpl"]
    assert [c.name for c in clips.values()] == ["x-clip-0.mp4", "x-clip-32.mp4"]


def test_a_clip_ffmpeg_cannot_read_is_skipped_with_a_warning(tmp_path, monkeypatch):
    settings, folder = prepare(tmp_path, [{"time": 40.0, "kind": "ui", "why": "w"}])

    def fake_download(url, folder, vid, times, settings):
        clip = folder / f"{vid}-clip-32.webm"
        clip.write_bytes(b"")
        return {40.0: frames_module.clip_path(folder, vid, 32.0)}

    def broken_ffmpeg(*args):
        raise frames_module.FetchError("ffmpeg failed: does not contain any stream")

    monkeypatch.setattr(frames_module, "download_clips", fake_download)
    monkeypatch.setattr(frames_module, "ffmpeg", broken_ffmpeg)
    monkeypatch.setattr(llm, "complete", lambda *a, **k: pytest.fail("no request"))
    result = frames(f"https://youtu.be/{VID}", settings)
    assert result["frames"] == []
    assert result["warnings"] == [
        "no picture at 0:40, clip of 0 bytes: ffmpeg failed: does not contain any stream"
    ]
    assert not list(folder.glob("*-clip-*"))


def test_the_label_schema_asks_for_the_commands_on_screen():
    assert LABEL_SCHEMA["properties"]["commands"] == {
        "type": "array",
        "items": {"type": "string"},
    }
    assert "commands" in LABEL_SCHEMA["required"]
    assert LABEL_SCHEMA["additionalProperties"] is False
    assert "commands:" in frames_module.instruction("de", Path(f"{VID}-1.png"))


def test_a_picture_wider_than_the_send_width_travels_as_a_jpeg(tmp_path, monkeypatch):
    wide = tmp_path / f"{VID}-1.png"
    wide.write_bytes(png(1920))
    small = tmp_path / f"{VID}-2.png"
    small.write_bytes(png(640))
    converted = []

    def fake_ffmpeg(*args):
        converted.append(args)
        Path(args[-1]).write_bytes(b"jpeg")
        return b""

    monkeypatch.setattr(frames_module, "ffmpeg", fake_ffmpeg)
    assert png_width(wide) == 1920 and png_width(small) == 640
    # A file ffmpeg wrote as something else is sent as it is.
    other = tmp_path / f"{VID}-3.png"
    other.write_bytes(b"not a picture at all, but on disk")
    assert png_width(other) == 0 and shrink(other) == other

    # A picture that is no wider goes as it is, without a conversion.
    assert shrink(small) == small and converted == []
    sent = shrink(wide)
    assert sent == tmp_path / f"{VID}-1.jpg" and sent.exists()
    assert f"scale={SEND_WIDTH}:-2" in converted[0]

    requests = []

    def fake_complete(instruction, data, schema, settings, images=None, max_turns=1):
        requests.append((instruction, images))
        assert images[0].exists()
        return {"label": "code", "caption": "c", "commands": []}

    monkeypatch.setattr(llm, "complete", fake_complete)
    labeled = frames_module.label(
        [wide],
        [{"time": 5.0, "kind": "code", "why": "w"}],
        Settings(home=tmp_path),
        "de",
        [],
    )
    # The model reads the JPEG, the result names the PNG the outputs keep.
    assert requests[0][1] == [tmp_path / f"{VID}-1.jpg"]
    assert f"{VID}-1.jpg" in requests[0][0]
    assert labeled[0]["file"] == f"{VID}-1.png" and wide.exists()
    assert not (tmp_path / f"{VID}-1.jpg").exists()


def test_a_model_without_eyes_keeps_the_pictures_unlabelled(tmp_path, monkeypatch):
    candidates = [
        {"time": 20.0 * i, "kind": "ui", "why": f"w{i}"} for i in range(1, 11)
    ]
    settings, folder = prepare(tmp_path, candidates)

    def fake_download(url, folder, vid, times, settings):
        clips = {}
        for t in times:
            clip = frames_module.clip_path(folder, vid, max(0.0, t - 8))
            clip.write_bytes(b"clip")
            clips[t] = clip
        return clips

    def fake_ffmpeg(*args):
        if args[0] == "-y":
            tmp_path.joinpath(args[-1]).write_bytes(b"png")
            return b""
        return bytes(PROBE_WIDTH * PROBE_HEIGHT)

    def blind(instruction, data, schema, settings, images=None, max_turns=1):
        raise llm.NoVisionError("this model takes no images")

    monkeypatch.setattr(frames_module, "download_clips", fake_download)
    monkeypatch.setattr(frames_module, "ffmpeg", fake_ffmpeg)
    monkeypatch.setattr(llm, "complete", blind)

    result = frames(f"https://youtu.be/{VID}", settings)

    # The run goes through, and the warning says what the note is missing.
    assert result["warnings"] == [NO_VISION]
    chosen = [f for f in result["frames"] if f["chosen"]]
    assert len(chosen) == LIMIT
    assert [f["time"] for f in chosen] == [20.0 * i for i in range(1, LIMIT + 1)]
    assert all(f["label"] == "unknown" for f in chosen)
    # An empty caption, because render places it as text next to the picture.
    assert all(f["caption"] == "" and f["commands"] == [] for f in chosen)
    assert result["diagram"] is None
    assert sorted(p.name for p in folder.glob("*.png")) == sorted(
        f["file"] for f in chosen
    )


def test_a_failed_clip_download_is_tried_once_more(tmp_path, monkeypatch):
    import yt_dlp

    tries = []
    slept = []

    class Flaky:
        def __init__(self, options):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def download(self, urls):
            tries.append(urls)
            if len(tries) == 1:
                raise yt_dlp.utils.DownloadError("ffmpeg exited with code 3436169992")

    monkeypatch.setattr(yt_dlp, "YoutubeDL", Flaky)
    monkeypatch.setattr(frames_module.time, "sleep", slept.append)
    clips = frames_module.download_clips(
        "https://youtu.be/x", tmp_path, "x", [40.0], Settings(home=tmp_path)
    )
    assert len(tries) == 2 and slept == [frames_module.RETRY_PAUSE]
    assert [c.name for c in clips.values()] == ["x-clip-32.mp4"]

    # Twice failed is failed, with the message the step always carried.
    class Broken(Flaky):
        def download(self, urls):
            tries.append(urls)
            raise yt_dlp.utils.DownloadError("no video formats found")

    monkeypatch.setattr(yt_dlp, "YoutubeDL", Broken)
    with pytest.raises(frames_module.FetchError, match="clip download failed"):
        frames_module.download_clips(
            "https://youtu.be/x", tmp_path, "x", [40.0], Settings(home=tmp_path)
        )
    assert len(tries) == 4


def test_without_candidates_nothing_is_fetched(tmp_path, monkeypatch):
    settings, folder = prepare(tmp_path, [])
    monkeypatch.setattr(
        frames_module, "download_clips", lambda *a: pytest.fail("fetched")
    )
    result = frames(f"https://youtu.be/{VID}", settings)
    assert result["frames"] == [] and result["warnings"]
    assert (folder / "frames.json").exists()
