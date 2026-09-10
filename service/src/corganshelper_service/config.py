"""Where the service keeps its data, and the knobs it reads.

The knobs live in `<home>/config.json`, written by `corganshelper config`
and later by the extension's options page. An environment variable
overrides the file, a command line flag overrides both. API keys stay in
that file or in the environment; the file lives next to the data, outside
the repository.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_HOME = "D:/corganshelper"
CONFIG_NAME = "config.json"

LLM_BACKENDS = ["claude", "anthropic", "openai", "lmstudio", "ollama"]

# What `stt` may name besides `auto` and `subtitles`, and how each one runs.
# The owner asked on 2026-09-09 for a choice between fast and accurate, so
# every entry carries its speed class and its word error rate: Open ASR
# Leaderboard, English, mean WER, lower is better, as quoted by Northflank
# on 2026-01-07 and read again on 2026-09-09. The language counts come from
# the model cards. OpenAI's whisper-1 is not on the leaderboard.
STT_MODELS = {
    "whisper": {
        "engine": "whisper",
        "model": "large-v3-turbo",
        "speed": "fast",
        "wer": "7.75 %",
        "languages": "99 languages",
    },
    "whisper-large": {
        "engine": "whisper",
        "model": "large-v3",
        "speed": "slow",
        "wer": "7.4 %",
        "languages": "99 languages",
    },
    "parakeet": {
        "engine": "onnx",
        "model": "nemo-parakeet-tdt-0.6b-v3",
        "speed": "fast",
        "wer": "6.32 %",
        "languages": "25 European languages",
    },
    "canary": {
        "engine": "onnx",
        "model": "nemo-canary-1b-v2",
        "speed": "slow",
        "wer": "7.15 %",
        "languages": "25 European languages",
    },
    "openai": {
        "engine": "openai",
        "model": "whisper-1",
        "speed": "cloud",
        "wer": "",
        "languages": "99 languages, needs a key",
    },
}
STT_DEFAULT = "whisper"
STT_ENGINES = ["auto", "subtitles", *STT_MODELS]

# What `render` can write besides work/<id>/summary.md. `formats` in
# config.json is a comma list of these; the options page will edit it.
FORMATS = ["md", "obsidian", "pdf", "docx"]

# The languages the note can be written in; the prompts name them in full.
LANGUAGES = {"de": "German", "en": "English"}

# Every key config.json may carry, with the environment variable that
# overrides it. The vendor variables are the ones their SDKs read anyway.
KEYS = {
    "llm": "CORGANSHELPER_LLM",
    "model": "CORGANSHELPER_MODEL",
    "stt": "CORGANSHELPER_STT",
    "language": "CORGANSHELPER_LANGUAGE",
    "openai_api_key": "OPENAI_API_KEY",
    "openai_base_url": "OPENAI_BASE_URL",
    "anthropic_api_key": "ANTHROPIC_API_KEY",
    "lmstudio_url": "LMSTUDIO_URL",
    "ollama_url": "OLLAMA_URL",
    "formats": "CORGANSHELPER_FORMATS",
    "obsidian_vault": "CORGANSHELPER_OBSIDIAN_VAULT",
    "obsidian_folder": "CORGANSHELPER_OBSIDIAN_FOLDER",
    "browser": "CORGANSHELPER_BROWSER",
    "token": "CORGANSHELPER_TOKEN",
    # Asked for on 2026-09-10: where the outputs go, a look for the PDF,
    # and four switches the popup offers per run (they travel as
    # `options` of a job, the stored value is the default).
    "download_dir": "CORGANSHELPER_DOWNLOAD_DIR",
    "pdf_template": "CORGANSHELPER_PDF_TEMPLATE",
    "cleanup": "CORGANSHELPER_CLEANUP",
    "timestamps": "CORGANSHELPER_TIMESTAMPS",
    "condensed": "CORGANSHELPER_CONDENSED",
    "style": "CORGANSHELPER_STYLE",
}

# How the note is worded. `normal` is the plain prompt; the others add a
# style instruction to analyze, and `all` writes one note per style.
STYLES = ["normal", "caveman", "noslop", "engineer", "human", "all"]
EXTRA_STYLES = [s for s in STYLES if s not in ("normal", "all")]
SWITCH = ["on", "off"]
DEFAULTS = {
    "llm": "claude",
    "model": "",
    "stt": "auto",
    "language": "de",
    "openai_api_key": "",
    "openai_base_url": "",
    "anthropic_api_key": "",
    "lmstudio_url": "http://localhost:1234/v1",
    "ollama_url": "http://localhost:11434/v1",
    "formats": "md",
    # The vault the Obsidian note goes to; empty means that format fails
    # with a hint. The folder inside it holds the notes, `_bilder` below
    # it the pictures.
    "obsidian_vault": "",
    "obsidian_folder": "Videos",
    # Chrome or Edge for the PDF; empty means the usual places are searched.
    "browser": "",
    # What the extension sends with every request; optional, see serve.
    "token": "",
    # Empty means the user's Downloads folder (default_download_dir).
    "download_dir": "",
    # An HTML file with a `{{content}}` placeholder, or a CSS file; empty
    # means the built-in look of the PDF.
    "pdf_template": "",
    # Delete work/<id>/ once the outputs are written.
    "cleanup": "off",
    # Timestamp links into the video in the note.
    "timestamps": "on",
    # Boil the video down to its core message, a two-minute read.
    "condensed": "off",
    "style": "normal",
}
SECRETS = ("openai_api_key", "anthropic_api_key", "token")
MASK = "*" * 8
CHOICES = {
    "llm": LLM_BACKENDS,
    "stt": STT_ENGINES,
    "language": list(LANGUAGES),
    "cleanup": SWITCH,
    "timestamps": SWITCH,
    "condensed": SWITCH,
    "style": STYLES,
}


def default_download_dir() -> Path:
    """The user's Downloads folder, where a browser puts what it fetches;
    the data directory's `out/` when there is none."""
    downloads = Path.home() / "Downloads"
    return downloads if downloads.is_dir() else resolve_home(None) / "out"


# The two buttons in the extension's popup. `fast` keeps every cached
# result, takes YouTube's captions and the backend's default model.
# `thorough` redoes every step, transcribes with the large Whisper even
# when captions exist, and asks the strongest model where the backend
# has a known one.
PROFILES = {
    "fast": {"stt": "auto", "model": ""},
    "thorough": {"stt": "whisper-large", "model": ""},
}
THOROUGH_MODELS = {"claude": "opus", "anthropic": "claude-opus-5"}


def profile_overrides(name: str, config: dict) -> dict:
    """What a profile changes on top of the stored settings; an empty
    value changes nothing."""
    if name not in PROFILES:
        raise ConfigError(f"profile must be one of {', '.join(PROFILES)}")
    overrides = dict(PROFILES[name])
    if name == "thorough":
        overrides["model"] = THOROUGH_MODELS.get(config["llm"], "")
    return overrides


class ConfigError(Exception):
    """config.json or a flag carries something the service cannot use."""


@dataclass(frozen=True)
class Settings:
    home: Path
    # yt-dlp only reads this when YouTube demands a sign-in; the wiki warns
    # that an account used this way can be locked, so it stays opt-in.
    cookies_file: Path | None = None
    config: dict = field(default_factory=lambda: dict(DEFAULTS))

    @property
    def work_dir(self) -> Path:
        return self.home / "work"

    @property
    def out_dir(self) -> Path:
        """Where the rendered outputs go: `download_dir`, else Downloads."""
        chosen = self.config.get("download_dir")
        return Path(chosen).expanduser() if chosen else default_download_dir()

    @property
    def config_path(self) -> Path:
        return self.home / CONFIG_NAME

    @classmethod
    def load(cls, home: Path | None = None, overrides: dict | None = None) -> Settings:
        """File, then environment, then `overrides` (the command line)."""
        base = resolve_home(home)
        cookies = os.environ.get("CORGANSHELPER_COOKIES")
        config = dict(DEFAULTS)
        config.update(read_config(base / CONFIG_NAME))
        for key, variable in KEYS.items():
            if os.environ.get(variable):
                config[key] = os.environ[variable]
        config.update(validate({k: v for k, v in (overrides or {}).items() if v}))
        validate(config)
        return cls(
            home=base,
            cookies_file=Path(cookies) if cookies else None,
            config=config,
        )

    def shown(self) -> dict:
        """The knobs for printing: a key is masked, never printed."""
        return {k: (MASK if k in SECRETS and v else v) for k, v in self.config.items()}


def resolve_home(home: Path | None) -> Path:
    # Absolute: the PDF step turns paths below it into file URLs.
    return Path(home or os.environ.get("CORGANSHELPER_HOME", DEFAULT_HOME)).resolve()


def store(home: Path | None, values: dict) -> Path:
    """Write `values` into config.json and keep the rest of the file. The
    environment is read here on purpose not at all: a key that lives in a
    variable stays there instead of being copied into the file."""
    path = resolve_home(home) / CONFIG_NAME
    config = {**DEFAULTS, **read_config(path), **validate(values)}
    path.parent.mkdir(parents=True, exist_ok=True)
    # Written beside and renamed over: the service's worker thread reads
    # this file while the options page writes it, and a truncated file
    # in between would fail that job with "not valid JSON".
    staging = path.with_suffix(".json.tmp")
    staging.write_text(
        json.dumps({k: config[k] for k in KEYS}, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(staging, path)
    return path


def read_config(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ConfigError(f"{path} is not valid JSON: {error}") from error
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must hold one JSON object")
    return validate({k: v for k, v in data.items() if v not in (None, "")})


def validate(values: dict) -> dict:
    """The same values back, or a ConfigError naming the wrong one."""
    unknown = sorted(set(values) - set(KEYS))
    if unknown:
        raise ConfigError(
            f"unknown setting {', '.join(unknown)}; known: {', '.join(KEYS)}"
        )
    # PUT /config takes JSON, and a number where a path belongs would be
    # stored and then break the next render.
    odd = sorted(k for k, v in values.items() if not isinstance(v, str))
    if odd:
        raise ConfigError(f"every setting is a string, not {', '.join(odd)}")
    for key, allowed in CHOICES.items():
        if key in values and values[key] not in allowed:
            raise ConfigError(f"{key} must be one of {', '.join(allowed)}")
    if "formats" in values:
        unknown = [f for f in split_formats(values["formats"]) if f not in FORMATS]
        if unknown:
            raise ConfigError(
                f"formats must name only {', '.join(FORMATS)}, not {', '.join(unknown)}"
            )
    return values


def split_formats(text: str) -> list[str]:
    """`md, pdf` as a list, empty entries dropped."""
    return [f.strip() for f in str(text).split(",") if f.strip()]


def parse_assignments(pairs: list[str]) -> dict:
    """`key=value` arguments of `corganshelper config --set`."""
    values = {}
    for pair in pairs:
        key, separator, value = pair.partition("=")
        if not separator:
            raise ConfigError(f"expected key=value, got {pair!r}")
        values[key.strip()] = value.strip()
    return validate(values)
