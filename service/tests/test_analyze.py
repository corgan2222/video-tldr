import copy
import json

from corganshelper_service import analyze as analyze_module
from corganshelper_service import llm
from corganshelper_service.analyze import (
    ANALYSIS_SCHEMA,
    PART_LIMIT,
    STYLE_INSTRUCTIONS,
    analyze,
    header,
    split_parts,
    stamp,
    transcript_lines,
)
from corganshelper_service.config import Settings
from corganshelper_service.fetch import work_folder

FAKE_ANALYSIS = {
    "kind": "explainer",
    "summary": "Docker und Podman im Vergleich.",
    "sections": [
        {"title": "Einführung", "start": 0, "end": 60, "summary": "Worum es geht."}
    ],
    "key_points": [{"time": 12, "text": "Beide bauen Container."}],
    "frame_candidates": [{"time": 45, "kind": "diagram", "why": "Architekturbild"}],
    "links": [{"url": "https://github.com/a/b", "role": "repository"}],
}


def prepare(tmp_path, text_size=100):
    settings = Settings(home=tmp_path)
    folder = work_folder(settings, "Zvc5QkrWgAU")
    folder.mkdir(parents=True)
    (folder / "fetch.json").write_text(
        json.dumps(
            {
                "id": "Zvc5QkrWgAU",
                "title": "Docker vs Podman",
                "channel": "c",
                "upload_date": "20260901",
                "duration": 300,
                "info": "Zvc5QkrWgAU.info.json",
                "subtitles": [],
            }
        ),
        encoding="utf-8",
    )
    (folder / "Zvc5QkrWgAU.info.json").write_text(
        json.dumps(
            {
                "description": "see https://github.com/a/b",
                "chapters": [
                    {"start_time": 0, "title": "Intro"},
                    {"start_time": 150, "title": "Deep dive"},
                ],
            }
        ),
        encoding="utf-8",
    )
    segments = [
        {"start": i * 10, "end": i * 10 + 10, "text": "x" * text_size}
        for i in range(30)
    ]
    (folder / "transcript.json").write_text(
        json.dumps(
            {
                "id": "Zvc5QkrWgAU",
                "source": "youtube",
                "language": "en",
                "segments": segments,
                "text": "",
            }
        ),
        encoding="utf-8",
    )
    return settings, folder


def test_timestamps_read_like_youtube():
    assert stamp(65) == "1:05"
    assert stamp(3725) == "1:02:05"


def test_the_prompt_carries_header_chapters_and_stamped_lines():
    head = header(
        {"title": "T", "channel": "C", "upload_date": "20260901", "duration": 65},
        {"description": "d", "chapters": [{"start_time": 30, "title": "Two"}]},
    )
    assert "Title: T" in head and "[0:30] Two" in head
    assert transcript_lines([{"start": 61, "end": 62, "text": "hi"}]) == ["[1:01] hi"]


def test_one_request_when_the_transcript_is_short(tmp_path, monkeypatch):
    settings, folder = prepare(tmp_path)
    calls = []

    def fake(instruction, data, schema, settings, images=None, max_turns=1):
        calls.append((instruction, data, schema))
        return dict(FAKE_ANALYSIS)

    monkeypatch.setattr(llm, "complete", fake)
    result = analyze("https://youtu.be/Zvc5QkrWgAU", settings)

    assert len(calls) == 1
    assert calls[0][2] is ANALYSIS_SCHEMA
    assert "[0:00] Intro" in calls[0][1] and "[2:30] Deep dive" in calls[0][1]
    assert result["kind"] == "explainer" and result["parts"] == 1
    assert (
        json.loads((folder / "analysis.json").read_text(encoding="utf-8"))["id"]
        == "Zvc5QkrWgAU"
    )


def test_a_long_transcript_is_split_at_chapters_and_stitched(tmp_path, monkeypatch):
    settings, _ = prepare(tmp_path, text_size=PART_LIMIT // 20)
    schemas = []

    def fake(instruction, data, schema, settings, images=None, max_turns=1):
        schemas.append(schema)
        if schema is analyze_module.PART_SCHEMA:
            return {
                "sections": [{"title": "p", "start": 0, "end": 1, "summary": "s"}],
                "key_points": [],
                "frame_candidates": [],
            }
        return {"kind": "review", "summary": "sum", "links": []}

    monkeypatch.setattr(llm, "complete", fake)
    result = analyze("https://youtu.be/Zvc5QkrWgAU", settings)

    assert result["parts"] >= 2
    assert schemas[-1] is analyze_module.STITCH_SCHEMA
    assert len(result["sections"]) == result["parts"]
    # No links from the model, so the description's own are kept.
    assert result["links"] == [{"url": "https://github.com/a/b", "role": "other"}]


def test_a_style_and_condensed_reach_the_prompt_and_the_result(tmp_path, monkeypatch):
    settings, folder = prepare(tmp_path)
    settings.config["style"] = "caveman"
    settings.config["condensed"] = "on"
    prompts = []

    def fake(instruction, data, schema, settings, images=None, max_turns=1):
        prompts.append(instruction)
        return copy.deepcopy(FAKE_ANALYSIS)

    monkeypatch.setattr(llm, "complete", fake)
    result = analyze("https://youtu.be/Zvc5QkrWgAU", settings)

    # The voice leads the prompt and stands again at its end, and it
    # writes the lengths of the fields rather than trailing behind them.
    assert prompts[0].startswith(STYLE_INSTRUCTIONS["caveman"]["voice"])
    assert prompts[0].rstrip().endswith(STYLE_INSTRUCTIONS["caveman"]["voice"])
    assert STYLE_INSTRUCTIONS["caveman"]["section"] in prompts[0]
    assert "two- to four-sentence" not in prompts[0]
    assert "two-minute read" in prompts[0] and "under 120 words" in prompts[0]
    assert result["style"] == "caveman" and result["condensed"] is True
    # One wording, one file, and it keeps the name every other step reads.
    assert not list(folder.glob("analysis-*.json"))
    assert (folder / "analysis.json").exists()


def test_the_plain_wording_adds_nothing_to_the_prompt(tmp_path, monkeypatch):
    settings, _ = prepare(tmp_path)
    prompts = []

    def fake(instruction, data, schema, settings, images=None, max_turns=1):
        prompts.append(instruction)
        return copy.deepcopy(FAKE_ANALYSIS)

    monkeypatch.setattr(llm, "complete", fake)
    result = analyze("https://youtu.be/Zvc5QkrWgAU", settings)

    # No wording, so nothing leads or follows the plain instruction.
    assert prompts[0].endswith("with its role.")
    assert prompts[0].startswith("You summarise")
    assert "two- to four-sentence summary" in prompts[0]
    assert result["style"] == "normal" and result["condensed"] is False


def test_style_all_writes_one_note_per_wording_and_one_bill(tmp_path, monkeypatch):
    settings, folder = prepare(tmp_path)
    settings.config["style"] = "all"
    prompts = []

    def fake(instruction, data, schema, settings, images=None, max_turns=1):
        prompts.append(instruction)
        llm.last_cost.update(input=100, output=10, usd=0.01)
        return copy.deepcopy(FAKE_ANALYSIS)

    monkeypatch.setattr(llm, "complete", fake)
    result = analyze("https://youtu.be/Zvc5QkrWgAU", settings)

    assert len(prompts) == 5
    assert prompts[-1].startswith(STYLE_INSTRUCTIONS["human"]["voice"])
    assert sorted(p.name for p in folder.glob("analysis*.json")) == [
        "analysis-caveman.json",
        "analysis-engineer.json",
        "analysis-human.json",
        "analysis-noslop.json",
        "analysis.json",
    ]
    # The normal wording comes back, and every file carries the whole bill.
    assert result["style"] == "normal"
    assert result["cost"] == {"requests": 5, "input": 500, "output": 50, "usd": 0.05}
    other = json.loads((folder / "analysis-engineer.json").read_text(encoding="utf-8"))
    assert other["style"] == "engineer" and other["cost"] == result["cost"]


def test_parts_are_cut_only_at_chapter_starts_when_there_are_chapters():
    segments = [{"start": i, "end": i + 1, "text": "y" * 100} for i in range(1000)]
    chapters = [{"start_time": 0}, {"start_time": 700}]
    parts = split_parts(segments, chapters)
    assert len(parts) == 2
    assert parts[1][0]["start"] == 700


def test_stamps_from_the_model_become_seconds_inside_the_video():
    result = analyze_module.normalize(
        {
            "sections": [
                {"title": "b", "start": "2:05", "end": "[4:30]", "summary": "s"},
                {"title": "a", "start": "0:00", "end": "2:05", "summary": "s"},
            ],
            "key_points": [
                {"time": "7:10", "text": "past the end"},
                {"time": "0:33", "text": "first"},
            ],
            "frame_candidates": [{"time": 45, "kind": "code", "why": "w"}],
        },
        300,
    )
    assert [s["title"] for s in result["sections"]] == ["a", "b"]
    assert result["sections"][1]["start"] == 125 and result["sections"][1]["end"] == 270
    assert [k["time"] for k in result["key_points"]] == [33, 300]
    assert result["frame_candidates"][0]["time"] == 45
    assert analyze_module.seconds("1:02:05") == 3725
