import json
from types import SimpleNamespace

import pytest

from corganshelper_service.config import Settings
from corganshelper_service.fetch import FetchError
from corganshelper_service.transcribe import segments_from_json3, transcribe

# Three caption lines as YouTube writes them, with the scrolling line breaks
# between them and durations that overlap the following line.
JSON3 = {
    "events": [
        {"tStartMs": 0, "dDurationMs": 905320, "id": 1},
        {
            "tStartMs": 80,
            "dDurationMs": 4800,
            "segs": [{"utf8": "Welcome"}, {"utf8": " back", "tOffsetMs": 320}],
        },
        {"tStartMs": 2070, "dDurationMs": 2810, "aAppend": 1, "segs": [{"utf8": "\n"}]},
        {
            "tStartMs": 2080,
            "dDurationMs": 5199,
            "segs": [{"utf8": "GitHub"}, {"utf8": " trending", "tOffsetMs": 400}],
        },
        {"tStartMs": 4870, "dDurationMs": 2409, "aAppend": 1, "segs": [{"utf8": "\n"}]},
        {"tStartMs": 4880, "dDurationMs": 6320, "segs": [{"utf8": "number 47."}]},
    ]
}


def test_caption_lines_become_segments_that_end_where_the_next_begins():
    segments = segments_from_json3(JSON3)
    assert [s["text"] for s in segments] == [
        "Welcome back",
        "GitHub trending",
        "number 47.",
    ]
    assert segments[0] == {"start": 0.08, "end": 2.08, "text": "Welcome back"}
    assert segments[1]["end"] == 4.88
    assert segments[2]["end"] == pytest.approx(4.88 + 6.32)


def test_the_youtube_track_is_used_when_it_was_fetched(tmp_path):
    settings = Settings(home=tmp_path)
    folder = settings.work_dir / "BT4ywlPr6Pk"
    folder.mkdir(parents=True)
    (folder / "BT4ywlPr6Pk.en-orig.json3").write_text(
        json.dumps(JSON3), encoding="utf-8"
    )
    (folder / "fetch.json").write_text(
        json.dumps({"id": "BT4ywlPr6Pk", "subtitles": ["BT4ywlPr6Pk.en-orig.json3"]}),
        encoding="utf-8",
    )

    result = transcribe("https://youtu.be/BT4ywlPr6Pk", settings)

    assert result["source"] == "youtube"
    assert result["language"] == "en"
    assert result["text"] == "Welcome back GitHub trending number 47."
    assert (folder / "transcript.json").exists()


def test_asking_for_subtitles_without_a_track_is_an_error(tmp_path):
    settings = Settings(home=tmp_path)
    folder = settings.work_dir / "BT4ywlPr6Pk"
    folder.mkdir(parents=True)
    (folder / "fetch.json").write_text(
        json.dumps({"id": "BT4ywlPr6Pk", "subtitles": []}), encoding="utf-8"
    )

    with pytest.raises(FetchError):
        transcribe("https://youtu.be/BT4ywlPr6Pk", settings, engine="subtitles")


def test_the_openai_engine_uploads_shrunk_audio_and_keeps_the_segments(
    tmp_path, monkeypatch
):
    import openai

    from corganshelper_service import transcribe as module

    settings = Settings(home=tmp_path)
    settings.config.update(stt="openai", openai_api_key="sk-fake")
    folder = settings.work_dir / "BT4ywlPr6Pk"
    folder.mkdir(parents=True)
    (folder / "fetch.json").write_text(
        json.dumps({"id": "BT4ywlPr6Pk", "subtitles": []}), encoding="utf-8"
    )
    audio = folder / "BT4ywlPr6Pk.m4a"
    audio.write_bytes(b"m4a")
    uploads = []

    class FakeOpenAI:
        def __init__(self, api_key=None, base_url=None, timeout=None):
            outer = self

            class Transcriptions:
                def create(self, file, **request):
                    uploads.append((file.name, request))
                    return SimpleNamespace(
                        language="english",
                        segments=[
                            SimpleNamespace(start=0.0, end=2.5, text=" Hello "),
                            SimpleNamespace(start=2.5, end=4.0, text=" there."),
                        ],
                    )

            outer.audio = SimpleNamespace(transcriptions=Transcriptions())

    monkeypatch.setattr(openai, "OpenAI", FakeOpenAI)
    monkeypatch.setattr(module, "download_audio", lambda url, folder, settings: audio)
    monkeypatch.setattr(
        module, "shrink_for_upload", lambda path: path.with_suffix(".upload.mp3")
    )
    audio.with_suffix(".upload.mp3").write_bytes(b"mp3")

    result = transcribe("https://youtu.be/BT4ywlPr6Pk", settings)

    assert result["source"] == "openai" and result["language"] == "english"
    assert result["text"] == "Hello there."
    assert result["segments"][1] == {"start": 2.5, "end": 4.0, "text": "there."}
    assert uploads[0][0].endswith("BT4ywlPr6Pk.upload.mp3")
    assert uploads[0][1]["response_format"] == "verbose_json"
    assert uploads[0][1]["timestamp_granularities"] == ["segment"]


def test_the_parakeet_engine_turns_vad_segments_into_lines(tmp_path, monkeypatch):
    import sys
    import types

    from corganshelper_service import transcribe as module

    settings = Settings(home=tmp_path)
    folder = settings.work_dir / "BT4ywlPr6Pk"
    folder.mkdir(parents=True)
    (folder / "fetch.json").write_text(
        json.dumps({"id": "BT4ywlPr6Pk", "subtitles": ["BT4ywlPr6Pk.de-orig.json3"]}),
        encoding="utf-8",
    )
    audio = folder / "BT4ywlPr6Pk.m4a"
    audio.write_bytes(b"m4a")
    loaded = {}

    class Recognizer:
        def with_vad(self, vad, **options):
            loaded["vad"] = vad
            return self

        def recognize(self, path):
            loaded["path"] = path
            yield SimpleNamespace(start=0.0, end=2.5, text=" Hallo ")
            yield SimpleNamespace(start=2.5, end=3.0, text="   ")
            yield SimpleNamespace(start=3.0, end=4.0, text="Welt.")

    fake = types.SimpleNamespace(
        load_model=lambda name, path, providers: (
            loaded.update(model=name, models=path, providers=providers) or Recognizer()
        ),
        load_vad=lambda name, providers: name,
    )
    monkeypatch.setitem(sys.modules, "onnx_asr", fake)
    monkeypatch.setattr(module, "download_audio", lambda url, folder, settings: audio)
    monkeypatch.setattr(module, "to_wav16k", lambda path: path.with_suffix(".16k.wav"))
    monkeypatch.setenv("CORGANSHELPER_WHISPER", "cuda:1")

    result = transcribe("https://youtu.be/BT4ywlPr6Pk", settings, engine="parakeet")

    assert result["source"] == "parakeet" and result["language"] == "de"
    assert result["segments"] == [
        {"start": 0.0, "end": 2.5, "text": "Hallo"},
        {"start": 3.0, "end": 4.0, "text": "Welt."},
    ]
    assert loaded["model"] == "nemo-parakeet-tdt-0.6b-v3"
    assert loaded["models"] == tmp_path / "models" / "nemo-parakeet-tdt-0.6b-v3"
    assert loaded["providers"][0] == ("CUDAExecutionProvider", {"device_id": 1})
    assert loaded["vad"] == "silero"
    assert loaded["path"].endswith("BT4ywlPr6Pk.16k.wav")


def test_whisper_large_is_the_accurate_whisper_and_auto_takes_the_default(
    tmp_path, monkeypatch
):
    import sys
    import types

    from corganshelper_service import transcribe as module

    settings = Settings(home=tmp_path)
    folder = settings.work_dir / "BT4ywlPr6Pk"
    folder.mkdir(parents=True)
    (folder / "fetch.json").write_text(
        json.dumps({"id": "BT4ywlPr6Pk", "subtitles": []}), encoding="utf-8"
    )
    audio = folder / "BT4ywlPr6Pk.m4a"
    audio.write_bytes(b"m4a")
    built = {}

    class FakeWhisper:
        def __init__(self, name, **options):
            built.update(model=name, **options)

        def transcribe(self, path, **options):
            built["options"] = options
            segments = iter([SimpleNamespace(start=0.0, end=1.5, text=" Hi ")])
            return segments, SimpleNamespace(language="en")

    monkeypatch.setitem(
        sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=FakeWhisper)
    )
    monkeypatch.setattr(module, "download_audio", lambda url, folder, settings: audio)
    monkeypatch.setenv("CORGANSHELPER_WHISPER", "cpu")

    result = transcribe(
        "https://youtu.be/BT4ywlPr6Pk", settings, engine="whisper-large"
    )

    assert result["source"] == "whisper-large" and result["language"] == "en"
    assert result["segments"] == [{"start": 0.0, "end": 1.5, "text": "Hi"}]
    assert built["model"] == "large-v3" and built["compute_type"] == "int8"
    assert built["options"]["condition_on_previous_text"] is False

    (folder / "transcript.json").unlink()
    assert transcribe("https://youtu.be/BT4ywlPr6Pk", settings)["source"] == "whisper"
    assert built["model"] == "large-v3-turbo"


def test_canary_is_told_the_language_and_parakeet_is_not(tmp_path, monkeypatch):
    import sys
    import types

    from corganshelper_service import transcribe as module

    calls = []

    class Recognizer:
        def with_vad(self, vad, **options):
            return self

        def recognize(self, path, **options):
            calls.append(options)
            return iter([SimpleNamespace(start=0.0, end=1.0, text="x")])

    fake = types.SimpleNamespace(
        load_model=lambda name, path, providers: Recognizer(),
        load_vad=lambda name, providers: name,
    )
    monkeypatch.setitem(sys.modules, "onnx_asr", fake)
    monkeypatch.setattr(module, "to_wav16k", lambda path: path)
    monkeypatch.setenv("CORGANSHELPER_WHISPER", "cpu")
    audio = tmp_path / "a.m4a"

    module.onnx_transcribe(audio, tmp_path, "nemo-canary-1b-v2", "de")
    module.onnx_transcribe(audio, tmp_path, "nemo-canary-1b-v2", "und")
    module.onnx_transcribe(audio, tmp_path, "nemo-parakeet-tdt-0.6b-v3", "de")

    assert calls == [{"language": "de"}, {}, {}]


def test_stt_status_says_what_would_run_and_whether_it_can(tmp_path, monkeypatch):
    from corganshelper_service import transcribe as module
    from corganshelper_service.config import Settings

    monkeypatch.setenv("CORGANSHELPER_WHISPER", "cpu")
    settings = Settings(home=tmp_path)

    state = module.stt_status(settings)
    assert state["ok"] is True
    assert state["detail"].startswith("captions first, else whisper (large-v3-turbo)")
    assert "downloads on first use" in state["detail"]
    assert "cpu" in state["detail"]

    (tmp_path / "models" / "faster-whisper-large-v3-turbo").mkdir(parents=True)
    assert "downloaded" in module.stt_status(settings)["detail"]

    settings.config["stt"] = "subtitles"
    assert module.stt_status(settings) == {
        "ok": True,
        "detail": "captions only, no model needed",
    }

    settings.config["stt"] = "openai"
    assert module.stt_status(settings)["ok"] is False
    settings.config["openai_api_key"] = "k"
    assert module.stt_status(settings) == {
        "ok": True,
        "detail": "openai whisper-1, key set",
    }

    settings.config["stt"] = "parakeet"
    state = module.stt_status(settings)
    assert state["ok"] is True
    assert state["detail"].startswith("parakeet (nemo-parakeet-tdt-0.6b-v3)")
