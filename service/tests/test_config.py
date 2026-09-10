import json

import pytest

from video_tldr_service.__main__ import main
from video_tldr_service.config import ConfigError, Settings, parse_assignments


def clean_env(monkeypatch):
    for variable in (
        "VIDEO_TLDR_LLM",
        "VIDEO_TLDR_MODEL",
        "VIDEO_TLDR_STT",
        "VIDEO_TLDR_FORMATS",
        "VIDEO_TLDR_OBSIDIAN_VAULT",
        "VIDEO_TLDR_OBSIDIAN_FOLDER",
        "VIDEO_TLDR_BROWSER",
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


def test_formats_are_a_comma_list_of_known_names(tmp_path, monkeypatch, capsys):
    from video_tldr_service.config import split_formats

    clean_env(monkeypatch)
    home = str(tmp_path)
    assert main(["--home", home, "config", "--set", "formats=md, pdf"]) == 0
    stored = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert split_formats(stored["formats"]) == ["md", "pdf"]
    assert stored["obsidian_folder"] == "Videos"

    assert main(["--home", home, "config", "--set", "formats=md,xls"]) == 1
    assert "formats must name only" in capsys.readouterr().err
    assert split_formats(" md ,,pdf, ") == ["md", "pdf"]


def test_models_stt_lists_speed_error_rate_and_languages(tmp_path, monkeypatch, capsys):
    clean_env(monkeypatch)
    assert main(["--home", str(tmp_path), "models", "stt"]) == 0
    out = capsys.readouterr().out
    assert out.splitlines()[0].startswith("auto")
    assert "canary" in out and "slow" in out and "%" in out
    assert "parakeet" in out and "fast" in out
    assert main(["--home", str(tmp_path), "--stt", "canary", "config"]) == 0
    assert '"stt": "canary"' in capsys.readouterr().out


def test_language_is_a_choice_and_the_file_is_replaced_not_truncated(
    tmp_path, monkeypatch, capsys
):
    clean_env(monkeypatch)
    home = str(tmp_path)
    assert main(["--home", home, "config", "--set", "language=fr"]) == 1
    assert "language must be one of de, en" in capsys.readouterr().err

    assert main(["--home", home, "config", "--set", "language=en"]) == 0
    # Written beside and renamed over, so a reader never sees a half file.
    assert [p.name for p in tmp_path.iterdir()] == ["config.json"]


def test_outputs_go_to_downloads_unless_a_folder_is_set(tmp_path, monkeypatch):
    from pathlib import Path

    from video_tldr_service.config import default_download_dir

    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    settings = Settings(home=tmp_path / "data")
    assert settings.out_dir == default_download_dir()
    (tmp_path / "Downloads").mkdir()
    assert settings.out_dir == tmp_path / "Downloads"

    settings.config["download_dir"] = str(tmp_path / "elsewhere")
    assert settings.out_dir == Path(tmp_path / "elsewhere")


def test_the_run_switches_are_on_or_off_and_style_is_a_choice(
    tmp_path, monkeypatch, capsys
):
    clean_env(monkeypatch)
    home = str(tmp_path)
    assert main(["--home", home, "config", "--set", "timestamps=off"]) == 0
    assert main(["--home", home, "config", "--set", "style=caveman"]) == 0
    assert main(["--home", home, "config", "--set", "condensed=maybe"]) == 1
    assert "condensed must be one of on, off" in capsys.readouterr().err
    assert main(["--home", home, "config", "--set", "style=shakespeare"]) == 1
    assert "style must be one of normal, caveman" in capsys.readouterr().err
    stored = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert (stored["timestamps"], stored["style"]) == ("off", "caveman")


def test_profiles_change_the_transcriber_and_the_model_on_top_of_the_file():
    from video_tldr_service.config import DEFAULTS, ConfigError, profile_overrides

    assert profile_overrides("fast", DEFAULTS) == {"stt": "auto", "model": ""}
    assert profile_overrides("thorough", DEFAULTS) == {
        "stt": "whisper-large",
        "model": "opus",
    }
    # A backend with no known strongest model keeps the one in the file.
    assert profile_overrides("thorough", {**DEFAULTS, "llm": "lmstudio"})["model"] == ""
    with pytest.raises(ConfigError):
        profile_overrides("quick", DEFAULTS)


def test_a_broken_file_is_named_without_its_path(tmp_path, monkeypatch):
    """The text of a ConfigError travels to the extension as the answer of
    a request, so it names config.json, not where the machine keeps it."""
    clean_env(monkeypatch)
    (tmp_path / "config.json").write_text("{not json", encoding="utf-8")

    with pytest.raises(ConfigError) as caught:
        Settings.load(home=tmp_path)

    assert "config.json is not valid JSON" in str(caught.value)
    assert str(tmp_path) not in str(caught.value)

    (tmp_path / "config.json").write_text("[]", encoding="utf-8")
    with pytest.raises(ConfigError) as caught:
        Settings.load(home=tmp_path)
    assert "config.json must hold one JSON object" in str(caught.value)
    assert str(tmp_path) not in str(caught.value)


def test_config_json_is_written_for_its_owner_alone(tmp_path, monkeypatch):
    """The API keys and the token stand in this file. The mode is set on
    the staging file, so the name never exists with a wider one."""
    import os

    from video_tldr_service.config import store

    asked: list[tuple[str, int]] = []
    real = os.chmod
    monkeypatch.setattr(os, "chmod", lambda path, mode: asked.append((str(path), mode)))

    store(tmp_path, {"llm": "ollama"})

    assert [mode for _, mode in asked] == [0o600]
    assert asked[0][0].startswith(str(tmp_path / "config.json"))
    assert asked[0][0] != str(tmp_path / "config.json")  # the staging file

    # Windows knows the bit only as the read-only flag, and a filesystem
    # may refuse it outright; neither may cost the owner a setting.
    def refuse(path, mode):
        raise PermissionError("no modes here")

    monkeypatch.setattr(os, "chmod", refuse)
    store(tmp_path, {"llm": "claude"})
    assert json.loads((tmp_path / "config.json").read_text())["llm"] == "claude"

    monkeypatch.setattr(os, "chmod", real)
    if os.name != "nt":
        store(tmp_path, {"llm": "claude"})
        assert (tmp_path / "config.json").stat().st_mode & 0o777 == 0o600


def test_a_request_sets_the_switches_and_nothing_that_reaches_the_machine():
    """A request says how to summarise. Which program runs, where the
    outputs land and where the API key travels are the machine owner's,
    through `video-tldr config --set`."""
    from video_tldr_service.config import KEYS, OVER_HTTP, over_http

    assert over_http({"style": "caveman", "stt": "whisper"}) == {
        "style": "caveman",
        "stt": "whisper",
    }
    # A subfolder name inside the vault starts no program and writes
    # nothing outside it, so it travels like the other fields of the
    # options page.
    assert over_http({"obsidian_folder": "Clips"}) == {"obsidian_folder": "Clips"}
    barred = set(KEYS) - OVER_HTTP
    assert barred == {
        "browser",
        "download_dir",
        "pdf_template",
        "obsidian_vault",
        "openai_base_url",
        "lmstudio_url",
        "ollama_url",
        "openai_api_key",
        "anthropic_api_key",
        "token",
    }
    for key in sorted(barred):
        with pytest.raises(ConfigError) as caught:
            over_http({key: "anything"})
        assert f"{key} may not be set over HTTP" in str(caught.value)
        assert "video-tldr config --set" in str(caught.value)
        # A job passes no token, and no token on the machine lifts its bar,
        # so its answer offers only the way through the command line.
        assert "or a token" not in str(caught.value)
    # The command line writes every one of them.
    assert parse_assignments(["browser=C:/x/chrome.exe"])["browser"]


def test_a_token_lets_a_request_set_what_the_command_line_sets():
    """`PUT /config` passes the service's token. A caller that got past the
    Authorization check owns the machine as much as the command line does,
    so the options page keeps saving every field it shows. Without a token
    the answer names both ways in: the command line, or a token."""
    from video_tldr_service.config import over_http

    assert over_http({"browser": "C:/x/chrome.exe"}, token="secret") == {
        "browser": "C:/x/chrome.exe"
    }
    # A token does not make a wrong value right.
    with pytest.raises(ConfigError):
        over_http({"stt": "loud"}, token="secret")

    with pytest.raises(ConfigError) as caught:
        over_http({"browser": "C:/x/chrome.exe"}, token="")
    assert "video-tldr config --set browser=" in str(caught.value)
    assert "or a token set there and sent with the request" in str(caught.value)


def test_the_obsidian_subfolder_stays_inside_the_vault():
    """`render` hangs this value onto the vault, and a request may set it
    without a token. A `..` part would write the note outside the vault and
    a drive letter would win over the vault altogether, so the check sits
    where every way in passes: the file, a variable, `config --set` and
    PUT /config.

    It normalises the way `render` does, `strip("/")` included. A leading
    slash is therefore a name, not an absolute path: `\\Videos`, which is
    what a Windows user types, reached `render` as `Videos` all along.
    Refusing it locked the service out of its own config file, because
    `Settings.load` validates what it read and `config --set` could not
    repair it either (2026-09-10)."""
    from video_tldr_service.config import over_http, validate

    assert validate({"obsidian_folder": "Clips/2026"}) == {
        "obsidian_folder": "Clips/2026"
    }
    for harmless in ("Videos", "/Videos", r"\Videos", "Clips/2026"):
        assert validate({"obsidian_folder": harmless}) == {
            "obsidian_folder": harmless
        }, harmless
    for bad in (
        "../Desktop",
        "Clips/../../Desktop",
        r"..\Desktop",
        "/../Desktop",
        "C:/Windows/Temp",
        r"C:\Windows\Temp",
    ):
        with pytest.raises(ConfigError) as caught:
            validate({"obsidian_folder": bad})
        assert "subfolder inside the vault" in str(caught.value), bad
    # Both entrances take the same check, the one without a token included.
    with pytest.raises(ConfigError):
        over_http({"obsidian_folder": "../Desktop"})
    with pytest.raises(ConfigError):
        over_http({"obsidian_folder": r"C:\Windows\Temp"}, token="secret")
    with pytest.raises(ConfigError):
        parse_assignments(["obsidian_folder=../Desktop"])


def test_two_saves_at_once_keep_both_values(tmp_path):
    """The options page saves every field on its own, and the service
    answers each request in its own thread. Without a lock around read
    and write, the slower one wrote back the file it had read before the
    faster one changed it, and the owner lost a setting on 2026-09-10."""
    import threading

    from video_tldr_service.config import store

    store(tmp_path, {"llm": "claude"})
    ready = threading.Barrier(4)
    values = [
        {"llm": "lmstudio"},
        {"model": "qwen3-8b"},
        {"language": "de"},
    ]

    failures: list[str] = []

    def save(one: dict) -> None:
        ready.wait(timeout=5)
        for _ in range(20):
            try:
                store(tmp_path, one)
            except OSError as error:  # two renames over one target
                failures.append(str(error))

    threads = [threading.Thread(target=save, args=(v,)) for v in values]
    for thread in threads:
        thread.start()
    ready.wait(timeout=5)
    for thread in threads:
        thread.join(timeout=10)

    # Without the lock this counted dozens of "the process cannot access
    # the file", the 500 the options page showed.
    assert failures == []
    stored = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert stored["llm"] == "lmstudio"
    assert stored["model"] == "qwen3-8b"
    assert stored["language"] == "de"
    # Nothing left behind: the staging file is renamed, never kept.
    assert not list(tmp_path.glob("*.tmp"))


def test_a_save_that_cannot_replace_the_file_leaves_no_staging_file(
    tmp_path, monkeypatch
):
    """A replace that fails, the target held open or the disk full, used to
    leave config.json.<pid>.tmp behind, with the keys in it."""
    from video_tldr_service import config as module

    def refuse(source, target):
        raise OSError("the target is held open")

    monkeypatch.setattr(module.os, "replace", refuse)

    with pytest.raises(OSError):
        module.store(tmp_path, {"llm": "ollama"})

    assert list(tmp_path.iterdir()) == []
