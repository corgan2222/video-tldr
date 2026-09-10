import json
from types import SimpleNamespace
from typing import ClassVar

import pytest

from video_tldr_service import llm
from video_tldr_service.config import Settings
from video_tldr_service.llm import LlmError, parse_result


def settings_for(tmp_path, **config):
    settings = Settings(home=tmp_path)
    settings.config.update(config)
    return settings


UNKNOWN = {"vision": None, "context": None, "detail": "no answer"}

# What LM Studio answered on this machine on 2026-09-10, shortened to two
# entries: the field names are the measured ones, and `capabilities` holds
# `tool_use` even for the model that reads pictures.
LMSTUDIO_LISTING = {
    "object": "list",
    "data": [
        {
            "id": "prism-ml/bonsai-27b",
            "object": "model",
            "type": "vlm",
            "publisher": "prism-ml",
            "arch": "qwen35",
            "compatibility_type": "gguf",
            "quantization": "Q1_0",
            "state": "loaded",
            "max_context_length": 262144,
            "loaded_context_length": 32768,
            "capabilities": ["tool_use"],
        },
        {
            "id": "gemma-4-12b-coder",
            "object": "model",
            "type": "llm",
            "state": "not-loaded",
            "max_context_length": 262144,
            "capabilities": ["tool_use"],
        },
    ],
}

# ollama's `/api/show`, as its API document describes it: no ollama server
# ran on this machine on 2026-09-10 to answer for itself.
OLLAMA_SHOW = {
    "capabilities": ["completion", "vision", "tools"],
    "model_info": {"qwen3.context_length": 4096, "qwen3.embedding_length": 2048},
}


def answering(body):
    """A stand-in for `fetch_json` that answers every call with `body` and
    keeps what it was asked."""
    asked = []

    def fetch(url, payload=None):
        asked.append((url, payload))
        return body

    return fetch, asked


def openai_that_raises(error):
    """An openai client whose every request fails, counting the attempts."""
    tries = []

    class Client:
        def __init__(self, **kwargs):
            class Completions:
                def create(self, **request):
                    tries.append(request)
                    raise error

            self.chat = SimpleNamespace(completions=Completions())

    return Client, tries


def test_the_structured_answer_is_taken_from_the_envelope():
    out = json.dumps(
        {"type": "result", "is_error": False, "structured_output": {"kind": "a"}}
    )
    assert parse_result(out) == {"kind": "a"}


def test_a_json_string_in_result_is_accepted_as_well():
    out = json.dumps({"type": "result", "result": json.dumps({"kind": "b"})})
    assert parse_result(out) == {"kind": "b"}


def test_an_expired_login_names_the_way_out():
    out = json.dumps(
        {"is_error": True, "result": "Failed to authenticate: OAuth session expired"}
    )
    with pytest.raises(LlmError) as caught:
        parse_result(out)
    assert "claude login" in str(caught.value)


def test_no_json_at_all_is_an_error_with_stderr_in_it():
    with pytest.raises(LlmError) as caught:
        parse_result("", "boom")
    assert "boom" in str(caught.value)


def test_an_error_without_a_reason_still_names_the_subtype():
    out = json.dumps({"is_error": True, "result": "", "subtype": "error_max_turns"})
    with pytest.raises(LlmError) as caught:
        parse_result(out)
    assert "error_max_turns" in str(caught.value)


def test_a_failed_request_is_tried_once_more(monkeypatch, tmp_path):
    answers = [
        SimpleNamespace(stdout="not json", stderr="boom"),
        SimpleNamespace(
            stdout=json.dumps({"is_error": False, "structured_output": {"kind": "a"}}),
            stderr="",
        ),
    ]
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return answers[len(calls) - 1]

    monkeypatch.setattr(llm.subprocess, "run", fake_run)
    monkeypatch.setattr(llm, "claude_binary", lambda: "claude")
    assert llm.complete("i", "d", {}, settings_for(tmp_path)) == {"kind": "a"}
    assert len(calls) == 2
    assert calls[0][calls[0].index("--model") + 1] == "sonnet"


def test_the_cli_gets_no_tools_without_pictures_and_only_read_with_them(
    monkeypatch, tmp_path
):
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(
            stdout=json.dumps({"structured_output": {"kind": "a"}}), stderr=""
        )

    monkeypatch.setattr(llm.subprocess, "run", fake_run)
    monkeypatch.setattr(llm, "claude_binary", lambda: "claude")
    picture = tmp_path / "x.png"
    picture.write_bytes(b"png")

    llm.complete("i", "d", {}, settings_for(tmp_path))
    llm.complete("i", "d", {}, settings_for(tmp_path), images=[picture])

    assert calls[0][calls[0].index("--tools") + 1] == ""
    assert calls[0][calls[0].index("--max-turns") + 1] == "1"
    assert calls[1][calls[1].index("--tools") + 1] == "Read"
    assert calls[1][calls[1].index("--allowedTools") + 1] == "Read"
    assert int(calls[1][calls[1].index("--max-turns") + 1]) >= 4
    assert calls[1][calls[1].index("--add-dir") + 1] == str(tmp_path)


def test_what_a_run_cost_is_read_from_the_envelope_and_added_up():
    from video_tldr_service.llm import last_cost, totals

    parse_result(
        json.dumps(
            {
                "is_error": False,
                "structured_output": {"kind": "a"},
                "usage": {
                    "input_tokens": 2,
                    "cache_creation_input_tokens": 10,
                    "cache_read_input_tokens": 5,
                    "output_tokens": 7,
                },
                "total_cost_usd": 0.25,
            }
        ),
        "",
        3.5,
    )
    assert last_cost == {
        "input": 17,
        "output": 7,
        "usd": 0.25,
        "seconds": 3.5,
        "tokens_per_second": 2.0,
    }
    assert totals([dict(last_cost), dict(last_cost)]) == {
        "requests": 2,
        "input": 34,
        "output": 14,
        "usd": 0.5,
    }


def test_a_request_nobody_timed_reports_no_speed_instead_of_dividing_by_zero():
    parse_result(json.dumps({"structured_output": {"kind": "a"}, "usage": {}}))
    assert llm.last_cost["seconds"] == 0.0
    assert llm.last_cost["tokens_per_second"] == 0


def test_a_request_carries_the_seconds_it_took_and_its_speed(
    monkeypatch, tmp_path, fake_openai
):
    clock = iter([100.0, 102.0])
    monkeypatch.setattr(llm.time, "monotonic", lambda: next(clock))
    llm.complete("i", "d", {}, settings_for(tmp_path, llm="lmstudio", model="q"))
    # Three output tokens in two seconds.
    assert llm.last_cost["seconds"] == 2.0
    assert llm.last_cost["tokens_per_second"] == 1.5


class FakeOpenAI:
    """Enough of the openai client for one chat request and a model list."""

    made: ClassVar[list] = []

    def __init__(self, api_key=None, base_url=None, timeout=None):
        self.api_key, self.base_url = api_key, base_url
        FakeOpenAI.made.append(self)
        self.requests: list[dict] = []
        self.answer = json.dumps({"kind": "news"})
        outer = self

        class Completions:
            def create(self, **request):
                outer.requests.append(request)
                message = SimpleNamespace(content=outer.answer, refusal=None)
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=message, finish_reason="stop")],
                    usage=SimpleNamespace(prompt_tokens=11, completion_tokens=3),
                )

        self.chat = SimpleNamespace(completions=Completions())
        # What LM Studio lists on this machine: two chat models, a Whisper
        # and an embedding model. Only the first two can answer a prompt.
        self.models = SimpleNamespace(
            list=lambda: [
                SimpleNamespace(id="qwen3-8b"),
                SimpleNamespace(id="whisper-large-v3-turbo"),
                SimpleNamespace(id="gemma"),
                SimpleNamespace(id="text-embedding-nomic-embed-text-v1.5"),
            ]
        )


@pytest.fixture
def fake_openai(monkeypatch):
    import openai

    FakeOpenAI.made = []
    monkeypatch.setattr(openai, "OpenAI", FakeOpenAI)
    return FakeOpenAI


def test_a_local_server_gets_the_schema_as_strict_response_format(
    tmp_path, fake_openai
):
    settings = settings_for(tmp_path, llm="lmstudio", model="qwen3-8b")
    schema = {"type": "object", "properties": {"kind": {"type": "string"}}}

    result = llm.complete("do it", "the data", schema, settings)

    client = fake_openai.made[0]
    assert result == {"kind": "news"}
    assert client.base_url == "http://localhost:1234/v1"
    request = client.requests[0]
    assert request["model"] == "qwen3-8b"
    assert request["messages"][0] == {"role": "system", "content": "do it"}
    assert request["messages"][1]["content"][-1]["text"] == "the data"
    assert request["response_format"]["json_schema"]["schema"] is schema
    assert request["response_format"]["json_schema"]["strict"] is True
    assert llm.last_cost["input"] == 11
    assert llm.last_cost["output"] == 3
    assert llm.last_cost["usd"] == 0.0
    assert llm.describe(settings) == "lmstudio:qwen3-8b"


def test_a_code_fence_around_the_answer_is_tolerated(tmp_path, fake_openai):
    settings = settings_for(tmp_path, llm="ollama", model="gemma")
    llm.complete("i", "d", {}, settings)
    fake_openai.made[0].answer = '```json\n{"kind": "review"}\n```'
    # The client is built per request; the next one answers with the fence.
    original = fake_openai.__init__

    def fenced(self, **kwargs):
        original(self, **kwargs)
        self.answer = '```json\n{"kind": "review"}\n```'

    fake_openai.__init__ = fenced
    try:
        assert llm.complete("i", "d", {}, settings) == {"kind": "review"}
    finally:
        fake_openai.__init__ = original


def test_an_empty_answer_points_at_the_context_window(tmp_path, fake_openai):
    original = fake_openai.__init__

    def silent(self, **kwargs):
        original(self, **kwargs)
        self.answer = ""

    fake_openai.__init__ = silent
    try:
        with pytest.raises(LlmError) as caught:
            llm.complete(
                "i", "d", {}, settings_for(tmp_path, llm="lmstudio", model="q")
            )
    finally:
        fake_openai.__init__ = original
    assert "empty answer" in str(caught.value)
    assert "11 prompt tokens" in str(caught.value)
    assert "32768" in str(caught.value)


def test_openai_without_a_key_and_a_local_server_without_a_model_are_named(
    tmp_path, fake_openai, monkeypatch
):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(LlmError) as caught:
        llm.complete("i", "d", {}, settings_for(tmp_path, llm="openai"))
    assert "openai_api_key" in str(caught.value)

    with pytest.raises(LlmError) as caught:
        llm.complete("i", "d", {}, settings_for(tmp_path, llm="ollama"))
    assert "video-tldr models" in str(caught.value)

    assert llm.models(settings_for(tmp_path, llm="lmstudio")) == ["qwen3-8b", "gemma"]
    assert llm.models(settings_for(tmp_path)) == ["sonnet", "opus", "haiku"]


def test_a_refused_key_names_the_setting_and_is_not_asked_twice(tmp_path, monkeypatch):
    """What the owner met on 2026-09-10: `Unauthorized`, asked twice over,
    with nothing in it about where the key is kept."""
    import openai

    tries = []

    def unauthorised():
        raise openai.OpenAIError(
            "Error code: 401 - {'code': 'unauthorized', 'message': 'Unauthorized'}"
        )

    class Refusing:
        """A server that turns down the key, on the chat as on the list of
        models: the second is what the check before a job asks."""

        def __init__(self, api_key=None, base_url=None, timeout=None):
            class Completions:
                def create(self, **request):
                    tries.append(request)
                    unauthorised()

            self.chat = SimpleNamespace(completions=Completions())
            self.models = SimpleNamespace(list=unauthorised)

    monkeypatch.setattr(openai, "OpenAI", Refusing)
    settings = settings_for(
        tmp_path, llm="openai", openai_api_key="sk-wrong", model="gpt-5-mini"
    )

    with pytest.raises(LlmError) as caught:
        llm.complete("i", "d", {}, settings)

    said = str(caught.value)
    assert "did not accept the key" in said
    assert "openai_api_key" in said
    assert "after" not in said  # a wrong key stays wrong; no second try
    assert len(tries) == 1
    # The same words reach the check the options page runs before a job.
    assert "did not accept the key" in (llm.check(settings) or "")


def test_status_is_one_line_for_the_popup(tmp_path, fake_openai, monkeypatch):
    monkeypatch.setattr(llm, "claude_binary", lambda: "C:/bin/claude.exe")
    monkeypatch.setattr(llm, "capabilities", lambda settings: UNKNOWN)
    llm.last_cost.clear()
    assert llm.status(settings_for(tmp_path)) == {
        "ok": True,
        "detail": "claude CLI at C:/bin/claude.exe, model sonnet",
    }

    state = llm.status(settings_for(tmp_path, llm="lmstudio", model="qwen3-8b"))
    assert state["ok"] is True
    assert state["detail"] == "lmstudio at http://localhost:1234/v1, model qwen3-8b"

    state = llm.status(settings_for(tmp_path, llm="lmstudio"))
    assert state["ok"] is False
    assert "no model set" in state["detail"]

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert llm.status(settings_for(tmp_path, llm="openai"))["ok"] is False
    state = llm.status(settings_for(tmp_path, llm="openai", openai_api_key="k"))
    assert state == {"ok": True, "detail": "openai API, key set, model gpt-5-mini"}


def test_the_anthropic_api_gets_the_schema_as_output_config(tmp_path, monkeypatch):
    import anthropic

    requests = []

    class FakeAnthropic:
        def __init__(self, api_key=None, timeout=None):
            self.api_key = api_key
            outer = self

            class Messages:
                def create(self, **request):
                    requests.append((outer.api_key, request))
                    return SimpleNamespace(
                        content=[
                            SimpleNamespace(type="text", text='{"kind": "explainer"}')
                        ],
                        usage=SimpleNamespace(
                            input_tokens=5,
                            output_tokens=2,
                            cache_creation_input_tokens=1,
                            cache_read_input_tokens=None,
                        ),
                    )

            self.messages = Messages()

    monkeypatch.setattr(anthropic, "Anthropic", FakeAnthropic)
    settings = settings_for(tmp_path, llm="anthropic", anthropic_api_key="sk-fake")
    schema = {"type": "object"}

    assert llm.complete("do it", "data", schema, settings) == {"kind": "explainer"}

    key, request = requests[0]
    assert key == "sk-fake"
    assert request["model"] == "claude-sonnet-5"
    assert request["system"] == "do it"
    assert request["output_config"]["format"] == {
        "type": "json_schema",
        "schema": schema,
    }
    assert llm.last_cost["input"] == 6
    assert llm.last_cost["output"] == 2
    assert llm.last_cost["usd"] == 0.0

    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    with pytest.raises(LlmError) as caught:
        llm.complete("i", "d", {}, settings_for(tmp_path, llm="anthropic"))
    assert "anthropic_api_key" in str(caught.value)


def test_lm_studio_is_asked_which_model_is_loaded_and_how_big_its_context_is(
    tmp_path, monkeypatch
):
    fetch, asked = answering(LMSTUDIO_LISTING)
    monkeypatch.setattr(llm, "fetch_json", fetch)

    seeing = llm.capabilities(
        settings_for(tmp_path, llm="lmstudio", model="prism-ml/bonsai-27b")
    )
    assert asked == [("http://localhost:1234/api/v0/models", None)]
    assert seeing["vision"] is True
    assert seeing["context"] == 32768
    assert seeing["detail"] == "prism-ml/bonsai-27b: vision, context 32768 tokens"

    # A model that is not loaded has no loaded length; its maximum is what
    # the server knows about it.
    reading = llm.capabilities(
        settings_for(tmp_path, llm="lmstudio", model="gemma-4-12b-coder")
    )
    assert reading["vision"] is False
    assert reading["context"] == 262144

    # Without a model name the loaded one answers for the server.
    assert llm.capabilities(settings_for(tmp_path, llm="lmstudio"))["context"] == 32768

    missing = llm.capabilities(settings_for(tmp_path, llm="lmstudio", model="nope"))
    assert missing["vision"] is None
    assert missing["context"] is None
    assert "no model called nope" in missing["detail"]


def test_ollama_is_asked_by_name_and_answers_vision_and_context(tmp_path, monkeypatch):
    fetch, asked = answering(OLLAMA_SHOW)
    monkeypatch.setattr(llm, "fetch_json", fetch)

    able = llm.capabilities(settings_for(tmp_path, llm="ollama", model="qwen3"))

    assert asked == [("http://localhost:11434/api/show", {"model": "qwen3"})]
    assert able["vision"] is True
    assert able["context"] == 4096


def test_a_server_that_does_not_answer_leaves_the_capabilities_unknown(
    tmp_path, monkeypatch
):
    def refused(url, payload=None):
        raise OSError("connection refused")

    monkeypatch.setattr(llm, "fetch_json", refused)
    able = llm.capabilities(settings_for(tmp_path, llm="lmstudio", model="q"))
    assert able["vision"] is None
    assert able["context"] is None
    assert "lms server start" in able["detail"]


def test_the_vendor_apis_take_pictures_and_bring_their_own_context(tmp_path):
    for name in ("claude", "anthropic", "openai"):
        able = llm.capabilities(settings_for(tmp_path, llm=name))
        assert able["vision"] is True
        assert able["context"] is None


def test_lm_studio_gets_the_switch_that_turns_the_thinking_off(tmp_path, fake_openai):
    lmstudio = settings_for(tmp_path, llm="lmstudio", model="q")
    assert llm.reasoning_hint(lmstudio) == {"reasoning_effort": "none"}
    llm.complete("i", "d", {}, lmstudio)
    assert fake_openai.made[0].requests[0]["extra_body"] == {"reasoning_effort": "none"}

    # ollama was not measured, and openai's own models are not local.
    ollama = settings_for(tmp_path, llm="ollama", model="q")
    assert llm.reasoning_hint(ollama) == {}
    llm.complete("i", "d", {}, ollama)
    assert fake_openai.made[1].requests[0]["extra_body"] is None


def test_a_model_without_eyes_is_named_as_such_and_not_asked_a_second_time(
    tmp_path, monkeypatch
):
    import openai

    refusal = openai.OpenAIError(
        "Error code: 400 - The provided messages contain images, but "
        "gemma-4-12b-coder does not support image inputs"
    )
    client, tries = openai_that_raises(refusal)
    monkeypatch.setattr(openai, "OpenAI", client)
    picture = tmp_path / "x.png"
    picture.write_bytes(b"png")

    with pytest.raises(llm.NoVisionError) as caught:
        llm.complete(
            "i",
            "d",
            {},
            settings_for(tmp_path, llm="lmstudio", model="gemma-4-12b-coder"),
            images=[picture],
        )

    assert "does not support image inputs" in str(caught.value)
    assert len(tries) == 1


def test_the_other_lmstudio_wording_for_a_blind_model_counts_too():
    # Measured 2026-09-10: the same data URL a vision model of that server
    # accepts comes back from a text model as this, which reads like a
    # broken picture and is not one.
    assert llm.no_vision(
        Exception(
            "Error code: 400 - {'error': \"'url' field must be a "
            'base64 encoded image."}'
        )
    )
    assert not llm.no_vision(Exception("Error code: 400 - Invalid url."))


def test_the_same_refusal_without_a_picture_stays_an_ordinary_error(
    tmp_path, monkeypatch
):
    import openai

    client, tries = openai_that_raises(openai.OpenAIError("does not support images"))
    monkeypatch.setattr(openai, "OpenAI", client)

    with pytest.raises(LlmError):
        llm.complete("i", "d", {}, settings_for(tmp_path, llm="lmstudio", model="m"))
    assert len(tries) == 2


def test_a_dropped_connection_is_tried_three_times_with_a_pause_between(
    tmp_path, monkeypatch
):
    import httpx
    import openai

    dropped = openai.APIConnectionError(
        message="Server disconnected without sending a response.",
        request=httpx.Request("POST", "http://localhost:1234/v1/chat/completions"),
    )
    client, tries = openai_that_raises(dropped)
    monkeypatch.setattr(openai, "OpenAI", client)
    pauses = []
    monkeypatch.setattr(llm.time, "sleep", pauses.append)

    with pytest.raises(LlmError) as caught:
        llm.complete("i", "d", {}, settings_for(tmp_path, llm="lmstudio", model="m"))

    assert len(tries) == 3
    assert pauses == [llm.RETRY_PAUSE_SECONDS] * 2
    assert "after 3 attempts" in str(caught.value)


def test_a_local_context_too_small_for_the_thinking_is_not_ok(
    tmp_path, fake_openai, monkeypatch
):
    llm.last_cost.clear()
    monkeypatch.setattr(
        llm,
        "capabilities",
        lambda settings: {"vision": True, "context": 4096, "detail": "m: vision"},
    )

    state = llm.status(settings_for(tmp_path, llm="lmstudio", model="m"))
    assert state["ok"] is False
    assert "context 4096 tokens is too small" in state["detail"]
    assert "larger context in LM Studio" in state["detail"]
    assert "32768 or more" in state["detail"]

    state = llm.status(settings_for(tmp_path, llm="ollama", model="m"))
    assert state["ok"] is False
    assert "OLLAMA_CONTEXT_LENGTH" in state["detail"]


def test_a_model_without_eyes_stays_ok_but_says_the_pictures_go_unlabelled(
    tmp_path, fake_openai, monkeypatch
):
    llm.last_cost.clear()
    monkeypatch.setattr(
        llm,
        "capabilities",
        lambda settings: {"vision": False, "context": 65536, "detail": "m: text only"},
    )

    state = llm.status(settings_for(tmp_path, llm="lmstudio", model="m"))
    assert state["ok"] is True
    assert "context 65536 tokens" in state["detail"]
    assert state["detail"].endswith("no image input: pictures stay unlabelled")


def test_only_an_http_address_with_a_host_reaches_a_provider():
    for good in ("http://localhost:1234/v1", "https://api.example/v1"):
        assert llm.checked_url(good) == good
    for bad in ("file:///C:/Windows", "ftp://host/v1", "http:///v1", ""):
        with pytest.raises(LlmError):
            llm.checked_url(bad)


def test_an_address_with_credentials_is_refused_without_repeating_them():
    with pytest.raises(LlmError) as caught:
        llm.checked_url("http://someone:hunter2@elsewhere.example/v1")
    said = str(caught.value)
    assert "hunter2" not in said
    assert "someone" not in said
    assert "api_key" in said


def test_a_wrong_provider_address_stops_before_the_client_is_built(
    tmp_path, fake_openai
):
    """The key travels to whatever host the address names, and the
    transcript with it, so neither the chat request nor the model list may
    get as far as building the client."""
    for config in (
        {"llm": "lmstudio", "model": "m", "lmstudio_url": "file:///etc/passwd"},
        {"llm": "ollama", "model": "m", "ollama_url": ""},
        {
            "llm": "openai",
            "model": "gpt-5-mini",
            "openai_api_key": "sk-real",
            "openai_base_url": "http://thief:hunter2@elsewhere.example/v1",
        },
    ):
        with pytest.raises(LlmError) as caught:
            llm.complete("i", "d", {}, settings_for(tmp_path, **config))
        assert "hunter2" not in str(caught.value)
        with pytest.raises(LlmError):
            llm.models(settings_for(tmp_path, **config))
    assert fake_openai.made == []


def test_the_rest_call_to_a_local_server_looks_at_the_address_as_well(tmp_path):
    """`capabilities` asks the server's own API, at a URL built from the same
    setting. No stand-in for `fetch_json` here: the point is that the request
    never leaves."""
    able = llm.capabilities(
        settings_for(
            tmp_path, llm="lmstudio", model="m", lmstudio_url="http://u:pw@host/v1"
        )
    )
    assert able["vision"] is None
    assert "pw@" not in able["detail"]
    assert "api_key" in able["detail"]


def test_an_answer_without_a_single_choice_is_an_llm_error(tmp_path, monkeypatch):
    """An IndexError here dies uncaught: run, serve and the CLI all wait for
    an LlmError."""
    import openai

    class Empty:
        def __init__(self, api_key=None, base_url=None, timeout=None):
            class Completions:
                def create(self, **request):
                    return SimpleNamespace(choices=[], usage=None)

            self.chat = SimpleNamespace(completions=Completions())

    monkeypatch.setattr(openai, "OpenAI", Empty)
    with pytest.raises(LlmError) as caught:
        llm.complete("i", "d", {}, settings_for(tmp_path, llm="lmstudio", model="m"))
    assert "without a single choice" in str(caught.value)


def test_the_missing_model_is_only_asked_about_where_it_can_be_missing(
    tmp_path, fake_openai
):
    """Only a local server serves whatever is loaded; every other backend
    falls back to DEFAULT_MODELS, so `check` has nothing to ask it."""
    for name, default in llm.DEFAULT_MODELS.items():
        assert bool(default) is (name not in llm.LOCAL)

    assert llm.check(settings_for(tmp_path, llm="openai", openai_api_key="k")) is None
    assert "no model set" in (llm.check(settings_for(tmp_path, llm="lmstudio")) or "")


def test_the_speed_of_the_last_request_travels_with_the_status(
    tmp_path, fake_openai, monkeypatch
):
    monkeypatch.setattr(llm, "capabilities", lambda settings: UNKNOWN)
    llm.last_cost.clear()
    llm.last_cost.update(tokens_per_second=12.5)

    state = llm.status(settings_for(tmp_path, llm="lmstudio", model="m"))
    assert state["detail"].endswith("12.5 tokens/s last request")
