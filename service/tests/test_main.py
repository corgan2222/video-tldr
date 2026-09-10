import io
import json
import sys

import pytest

from video_tldr_service import __main__ as cli


def test_a_caption_outside_the_console_codepage_is_printed_anyway(
    tmp_path, monkeypatch
):
    heart = "cloud❤berry"
    monkeypatch.setattr(
        cli, "frames", lambda url, settings, force=False, language=None: {"c": heart}
    )
    narrow = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", narrow)

    assert (
        cli.main(["--home", str(tmp_path), "frames", "https://youtu.be/x_x_x_x_x_x"])
        == 0
    )

    narrow.flush()
    assert json.loads(narrow.buffer.getvalue().decode("utf-8")) == {"c": heart}


def test_bench_takes_a_comma_list_of_models_and_prints_a_table(
    tmp_path, monkeypatch, capsys
):
    seen = []

    def fake_bench(url, settings, models, repeat, progress=None):
        seen.append((url, models, repeat))
        if progress:
            progress("bench qwen 1", "12.0s, 40 tokens")
        return [
            {
                "model": "qwen",
                "run": 1,
                "seconds": 12.0,
                "input": 100,
                "output": 40,
                "tokens_per_second": 3.3,
                "sections": 2,
                "key_points": 1,
                "links": 3,
            }
        ]

    monkeypatch.setattr(cli, "bench", fake_bench)
    url = "https://youtu.be/x_x_x_x_x_x"

    code = cli.main(
        [
            "--home",
            str(tmp_path),
            "bench",
            url,
            "--models",
            "qwen, gemma",
            "--repeat",
            "3",
        ]
    )

    assert code == 0
    assert seen == [(url, ["qwen", "gemma"], 3)]
    printed = capsys.readouterr()
    assert "| model | run | seconds |" in printed.out
    assert "| qwen | 1 | 12.0 |" in printed.out
    assert "bench qwen 1 12.0s, 40 tokens" in printed.err
    # Without --models there is nothing to compare.
    with pytest.raises(SystemExit):
        cli.main(["--home", str(tmp_path), "bench", url])


def test_render_passes_the_format_flags_through_and_none_without_them(
    tmp_path, monkeypatch, capsys
):
    calls = []

    def fake_render(url, settings, force=False, language=None, formats=None):
        calls.append(formats)
        return {"summary": tmp_path / "summary.md"}

    monkeypatch.setattr(cli, "render", fake_render)
    url = "https://youtu.be/x_x_x_x_x_x"
    assert cli.main(["--home", str(tmp_path), "render", url]) == 0
    assert (
        cli.main(
            [
                "--home",
                str(tmp_path),
                "render",
                "--format",
                "pdf",
                "--format",
                "docx",
                url,
            ]
        )
        == 0
    )
    assert calls == [None, ["pdf", "docx"]]
    assert "summary" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        cli.main(["--home", str(tmp_path), "render", "--format", "xls", url])


def test_a_port_windows_reserved_says_how_to_find_out(tmp_path, monkeypatch, capsys):
    """WinError 10013 reads like a permission problem, and the ranges move
    on every reboot: 8765 was free on 2026-09-09 and reserved a day later.
    The message has to name the command that shows the ranges."""
    blocked = OSError("access denied")
    blocked.winerror = cli.WSAEACCES

    def refuse(*args, **kwargs):
        raise blocked

    monkeypatch.setattr(cli, "serve", refuse)
    assert cli.main(["--home", str(tmp_path), "serve"]) == 1
    complaint = capsys.readouterr().err
    assert "excludedportrange" in complaint
    assert "--port" in complaint
