"""Where the service keeps its data, and the few knobs it reads."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_HOME = "D:/corganshelper"


@dataclass(frozen=True)
class Settings:
    home: Path
    # yt-dlp only reads this when YouTube demands a sign-in; the wiki warns
    # that an account used this way can be locked, so it stays opt-in.
    cookies_file: Path | None = None

    @property
    def work_dir(self) -> Path:
        return self.home / "work"

    @property
    def out_dir(self) -> Path:
        return self.home / "out"

    @classmethod
    def load(cls, home: Path | None = None) -> Settings:
        base = home or Path(os.environ.get("CORGANSHELPER_HOME", DEFAULT_HOME))
        cookies = os.environ.get("CORGANSHELPER_COOKIES")
        return cls(home=Path(base), cookies_file=Path(cookies) if cookies else None)
