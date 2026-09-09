import io
import json
import sys

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
