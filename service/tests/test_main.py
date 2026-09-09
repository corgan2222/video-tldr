import io
import json
import sys

import pytest

from corganshelper_service import __main__ as cli


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
