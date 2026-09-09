import json

import pytest

from corganshelper_service.__main__ import main
from corganshelper_service.config import ConfigError, Settings, parse_assignments


def clean_env(monkeypatch):
    for variable in (
        "CORGANSHELPER_LLM",
        "CORGANSHELPER_MODEL",
        "CORGANSHELPER_STT",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
    ):
        monkeypatch.delenv(variable, raising=False)


def test_without_a_file_the_subscription_cli_is_the_default(tmp_path, monkeypatch):
    clean_env(monkeypatch)
    settings = Settings.load(home=tmp_path)
    assert settings.config["llm"] == "claude"
    assert settings.config["stt"] == "auto"
    assert settings.config["lmstudio_url"].startswith("http://localhost:1234")


def test_the_file_is_read_and_a_variable_and_a_flag_override_it(tmp_path, monkeypatch):
    clean_env(monkeypatch)
    (tmp_path / "config.json").write_text(
        json.dumps({"llm": "ollama", "model": "qwen3", "openai_api_key": "file"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENAI_API_KEY", "env")

    settings = Settings.load(home=tmp_path, overrides={"llm": "lmstudio"})

    assert settings.config["llm"] == "lmstudio"
    assert settings.config["model"] == "qwen3"
    assert settings.config["openai_api_key"] == "env"


def test_an_unknown_key_or_backend_is_named(tmp_path, monkeypatch):
    clean_env(monkeypatch)
    (tmp_path / "config.json").write_text('{"llm": "bard"}', encoding="utf-8")
    with pytest.raises(ConfigError) as caught:
        Settings.load(home=tmp_path)
    assert "llm must be one of" in str(caught.value)
    with pytest.raises(ConfigError) as caught:
        parse_assignments(["modle=x"])
    assert "unknown setting modle" in str(caught.value)


def test_config_set_writes_the_file_and_the_key_is_never_printed(
    tmp_path, monkeypatch, capsys
):
    clean_env(monkeypatch)
    # A key from the environment must not be copied into the file.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-secret")
    home = str(tmp_path)

    assert (
        main(
            [
                "--home",
                home,
                "config",
                "--set",
                "llm=openai",
                "--set",
                "openai_api_key=sk-fake",
            ]
        )
        == 0
    )

    stored = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert stored["llm"] == "openai" and stored["openai_api_key"] == "sk-fake"
    assert stored["anthropic_api_key"] == ""
    shown = json.loads(capsys.readouterr().out)
    assert shown["llm"] == "openai" and "sk-fake" not in json.dumps(shown)
    assert "env-secret" not in json.dumps(shown)

    assert main(["--home", home, "config", "--set", "stt=loud"]) == 1
    assert "stt must be one of" in capsys.readouterr().err


def test_models_stt_lists_speed_error_rate_and_languages(tmp_path, monkeypatch, capsys):
    clean_env(monkeypatch)
    assert main(["--home", str(tmp_path), "models", "stt"]) == 0
    out = capsys.readouterr().out
    assert out.splitlines()[0].startswith("auto")
    assert "canary" in out and "slow" in out and "%" in out
    assert "parakeet" in out and "fast" in out
    assert main(["--home", str(tmp_path), "--stt", "canary", "config"]) == 0
    assert '"stt": "canary"' in capsys.readouterr().out
