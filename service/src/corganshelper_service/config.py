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
STT_ENGINES = ["auto", "subtitles", "whisper", "parakeet", "openai"]

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
}
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
}
SECRETS = ("openai_api_key", "anthropic_api_key")
CHOICES = {"llm": LLM_BACKENDS, "stt": STT_ENGINES}


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
        return self.home / "out"

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
        return {
            k: ("*" * 8 if k in SECRETS and v else v) for k, v in self.config.items()
        }


def resolve_home(home: Path | None) -> Path:
    return Path(home or os.environ.get("CORGANSHELPER_HOME", DEFAULT_HOME))


def store(home: Path | None, values: dict) -> Path:
    """Write `values` into config.json and keep the rest of the file. The
    environment is read here on purpose not at all: a key that lives in a
    variable stays there instead of being copied into the file."""
    path = resolve_home(home) / CONFIG_NAME
    config = {**DEFAULTS, **read_config(path), **validate(values)}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({k: config[k] for k in KEYS}, indent=2) + "\n", encoding="utf-8"
    )
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
    for key, allowed in CHOICES.items():
        if key in values and values[key] not in allowed:
            raise ConfigError(f"{key} must be one of {', '.join(allowed)}")
    return values


def parse_assignments(pairs: list[str]) -> dict:
    """`key=value` arguments of `corganshelper config --set`."""
    values = {}
    for pair in pairs:
        key, separator, value = pair.partition("=")
        if not separator:
            raise ConfigError(f"expected key=value, got {pair!r}")
        values[key.strip()] = value.strip()
    return validate(values)
