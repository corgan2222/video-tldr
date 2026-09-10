import pytest
import yt_dlp

from corganshelper_service.config import Settings
from corganshelper_service.fetch import FetchError, fetch, work_folder


class Refusing:
    """Stands in for yt_dlp.YoutubeDL and answers with YouTube's bot check."""

    def __init__(self, options):
        self.options = options

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def extract_info(self, url, download):
        raise yt_dlp.utils.DownloadError(
            "ERROR: [youtube] x: Sign in to confirm you’re not a bot."
        )


def test_the_bot_check_becomes_a_message_that_names_the_way_out(tmp_path, monkeypatch):
    monkeypatch.setattr(yt_dlp, "YoutubeDL", Refusing)
    settings = Settings(home=tmp_path)

    with pytest.raises(FetchError) as caught:
        fetch("https://youtu.be/BT4ywlPr6Pk", settings)

    assert "CORGANSHELPER_COOKIES" in str(caught.value)
    assert not (work_folder(settings, "BT4ywlPr6Pk") / "fetch.json").exists()
