"""One door to the language model, five backends behind it.

`claude` runs `claude -p` from the Claude Code CLI; the owner's
subscription pays for it, so there is no API key to keep. `anthropic` and
`openai` call the vendors' APIs with a key. `lmstudio` and `ollama` speak
the OpenAI protocol to a server on this machine. Every backend receives
the same instruction, data and JSON schema and returns the validated
object; `settings.config["llm"]` picks the door.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

from .config import Settings

DEFAULT_MODELS = {
    "claude": "sonnet",
    "anthropic": "claude-sonnet-5",
    "openai": "gpt-5-mini",
    # A local server serves whatever is loaded; the name has to be set.
    "lmstudio": "",
    "ollama": "",
}
# Aliases the CLI resolves itself; it has no list command.
CLAUDE_MODELS = ["sonnet", "opus", "haiku"]
MAX_OUTPUT_TOKENS = 16000
TIMEOUT_SECONDS = 600
# How long the small REST call that asks a local server what it can do may
# take. Short: `status` waits for it while the popup is open.
ASK_SECONDS = 5
ATTEMPTS = 2
CONNECTION_ATTEMPTS = 3
RETRY_PAUSE_SECONDS = 2
# A transcript plus the model's own thinking below this many tokens is what
# emptied two runs (2026-09-09, 2026-09-10).
MIN_CONTEXT = 32768
START_HINT = {
    "lmstudio": "start the server in LM Studio or run `lms server start`",
    "ollama": "run `ollama serve`",
}
CONTEXT_HINT = {
    "lmstudio": "load the model with a larger context in LM Studio",
    "ollama": "raise OLLAMA_CONTEXT_LENGTH or num_ctx",
}
LOCAL = ("lmstudio", "ollama")


# What the last answer cost. The CLI reports it per request and the
# milestone asks what a video costs, so `analyze` reads it after each
# call. ponytail: one slot, the service runs one request at a time.
last_cost: dict = {}


class NoVisionError(Exception):
    """The chosen model takes no images; raised by the backends when the
    server says so, caught by frames, which then keeps the pictures
    without labels instead of failing the run."""


class LlmError(Exception):
    """The backend did not return a usable answer; the message says why."""


def backend(settings: Settings) -> str:
    return settings.config["llm"]


def model_name(settings: Settings) -> str:
    return settings.config["model"] or DEFAULT_MODELS[backend(settings)]


def describe(settings: Settings) -> str:
    """`backend:model`, for the result file."""
    return f"{backend(settings)}:{model_name(settings)}"


def claude_binary() -> str:
    found = shutil.which("claude")
    if found is None:
        raise LlmError("the claude CLI is not on the PATH; install Claude Code first")
    return found


def endpoint(settings: Settings) -> tuple[str, str | None]:
    """(api_key, base_url) for the backends that speak the OpenAI protocol.
    A local server takes any key; the SDK insists on one."""
    config = settings.config
    if backend(settings) == "openai":
        if not config["openai_api_key"]:
            raise LlmError(
                "no OpenAI API key; put it in config.json as openai_api_key "
                "or set OPENAI_API_KEY"
            )
        return config["openai_api_key"], config["openai_base_url"] or None
    if backend(settings) == "lmstudio":
        return "lm-studio", config["lmstudio_url"]
    return "ollama", config["ollama_url"]


def check(settings: Settings) -> str | None:
    """What keeps the chosen backend from answering, or None."""
    try:
        if backend(settings) == "claude":
            claude_binary()
        else:
            models(settings)
        if not model_name(settings):
            return (
                f"no model set for {backend(settings)}; `corganshelper models` "
                "lists what it offers, `corganshelper config --set model=<name>` "
                "picks one"
            )
    except LlmError as error:
        return str(error)
    return None


def status(settings: Settings) -> dict:
    """`ok` and one line for the popup: where the model runs and which
    one answers. A local server is asked, so this takes a request."""
    trouble = check(settings)
    if trouble:
        return {"ok": False, "detail": trouble}
    name = backend(settings)
    model = model_name(settings)
    if name == "claude":
        return {"ok": True, "detail": f"claude CLI at {claude_binary()}, model {model}"}
    if name in ("anthropic", "openai"):
        return {"ok": True, "detail": f"{name} API, key set, model {model}"}
    return local_status(settings, name, model)


def local_status(settings: Settings, name: str, model: str) -> dict:
    """A local server is the one that can be set up wrong. A context too
    small for the transcript and the model's thinking emptied two runs, and
    a model without eyes failed a third after eight minutes of work."""
    detail = f"{name} at {endpoint(settings)[1]}, model {model}"
    able = capabilities(settings)
    ok = True
    context = able["context"]
    if context is not None and context < MIN_CONTEXT:
        ok = False
        detail += (
            f", context {context} tokens is too small for a transcript and "
            f"the model's thinking: {CONTEXT_HINT[name]}, {MIN_CONTEXT} or more"
        )
    elif context:
        detail += f", context {context} tokens"
    if able["vision"] is False:
        detail += ", no image input: pictures stay unlabelled"
    rate = last_cost.get("tokens_per_second")
    if rate:
        detail += f", {rate} tokens/s last request"
    return {"ok": ok, "detail": detail}


def models(settings: Settings) -> list[str]:
    """The names the chosen backend accepts as `model`."""
    name = backend(settings)
    if name == "claude":
        return list(CLAUDE_MODELS)
    try:
        if name == "anthropic":
            client = anthropic_client(settings)
        else:
            import openai

            key, url = endpoint(settings)
            client = openai.OpenAI(api_key=key, base_url=url, timeout=10)
        return [m.id for m in client.models.list() if is_chat_model(m.id)]
    except Exception as error:  # every SDK has its own error tree
        raise LlmError(reachable_message(name, error)) from error


# A local server lists everything it has loaded, and neither a Whisper nor
# an embedding model can answer a prompt. Offered anyway, one of them cost
# the owner four jobs with a 400 from LM Studio (2026-09-10).
NOT_CHAT = ("whisper", "embed")


def is_chat_model(name: str) -> bool:
    return not any(part in name.lower() for part in NOT_CHAT)


def reachable_message(name: str, error: Exception) -> str:
    text = f"{name}: {error}"
    if name in START_HINT and "onnect" in text:
        text += f"; is the server running? {START_HINT[name]}"
    return text


def fetch_json(url: str, payload: dict | None = None) -> dict:
    """One GET, or a POST when there is a payload, against a local server's
    own REST API. urllib, because the service already fetches this way and
    an HTTP client is not worth a dependency."""
    body = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=ASK_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def rest_base(url: str) -> str:
    """A local server serves its own API next to the OpenAI one, so the
    `/v1` from the configured URL comes off."""
    return (url or "").rstrip("/").removesuffix("/v1")


def capabilities(settings: Settings) -> dict:
    """What the chosen model can do: `vision`, `context` in tokens and one
    line for a human. `None` means the server did not say, and an
    unreachable server is one of those answers, not an error: the caller
    asks before the request, when nothing has failed yet."""
    name = backend(settings)
    if name not in LOCAL:
        # The vendors' current models all read pictures, and the context is
        # the model's own, not something this machine set.
        return {"vision": True, "context": None, "detail": f"{name} API, takes images"}
    try:
        if name == "lmstudio":
            return lmstudio_capabilities(settings)
        return ollama_capabilities(settings)
    except Exception as error:  # noqa: BLE001 - urllib, socket, JSON: no answer
        return {
            "vision": None,
            "context": None,
            "detail": reachable_message(name, error),
        }


def lmstudio_capabilities(settings: Settings) -> dict:
    """LM Studio answers `/api/v0/models` with the fields measured on this
    machine on 2026-09-10: `id`, `type` (`llm`, `vlm` or `embeddings`),
    `state` (`loaded` or `not-loaded`), `max_context_length` and, while the
    model is loaded, `loaded_context_length`. There is a `capabilities`
    list too, but it held `tool_use` and nothing else, not even for a model
    that reads pictures -- `type` is what answers the picture question."""
    wanted = model_name(settings)
    listing = fetch_json(rest_base(settings.config["lmstudio_url"]) + "/api/v0/models")
    entries = listing.get("data") or []
    if wanted:
        entry = next((e for e in entries if e.get("id") == wanted), None)
    else:
        entry = next((e for e in entries if e.get("state") == "loaded"), None)
    if entry is None:
        return {
            "vision": None,
            "context": None,
            "detail": f"lmstudio lists no model called {wanted or '(none loaded)'}",
        }
    # The loaded length is the one that has to hold the prompt; the maximum
    # is what the model could do if it were loaded with it.
    context = entry.get("loaded_context_length") or entry.get("max_context_length")
    return capability_line(entry.get("id", wanted), entry.get("type") == "vlm", context)


def ollama_capabilities(settings: Settings) -> dict:
    """Ollama answers `/api/show` with a `capabilities` list that names
    `vision`, and a `model_info` map whose context sits under an
    architecture key such as `qwen3.context_length`. Not measured: no
    ollama server ran on this machine on 2026-09-10, so this follows
    ollama's API document and the shape may differ."""
    wanted = model_name(settings)
    shown = fetch_json(
        rest_base(settings.config["ollama_url"]) + "/api/show", {"model": wanted}
    )
    info = shown.get("model_info") or {}
    context = next(
        (v for k, v in info.items() if k.endswith(".context_length") and v), None
    )
    return capability_line(
        wanted, "vision" in (shown.get("capabilities") or []), context
    )


def capability_line(model: str, vision: bool, context: int | None) -> dict:
    detail = f"{model}: {'vision' if vision else 'text only'}"
    if context:
        detail += f", context {context} tokens"
    return {"vision": vision, "context": context, "detail": detail}


def reasoning_hint(settings: Settings) -> dict:
    """The request extra that keeps a local thinking model from spending a
    whole answer on its reasoning. Thirteen picture requests took 815
    seconds that way (2026-09-10).

    Measured the same day against LM Studio with a qwen35 model, 80 output
    tokens each: `reasoning_effort: "none"` came back with the answer and 0
    reasoning tokens, while `reasoning: {"effort": "low"}`,
    `reasoning_effort: "low"` and a `/no_think` system line each still
    burned all 80 on thinking. A field the server does not know is ignored,
    not refused, so a model without the switch loses nothing.

    Ollama is not in here: no ollama server ran on this machine that day,
    and a field nobody measured is a guess, not a setting."""
    if backend(settings) == "lmstudio":
        return {"reasoning_effort": "none"}
    return {}


def no_vision(error: Exception) -> bool:
    """LM Studio answers a picture to a text model with 400 "The provided
    messages contain images, but <model> does not support image inputs"
    (2026-09-10). Every server words this differently, so the two halves
    are matched rather than the sentence."""
    text = str(error).lower()
    return "image" in text and "not support" in text


# openai, anthropic and httpx each name their own; the backends wrap all of
# them in an LlmError, so the name is what is left to go by. Importing the
# three SDKs here only to name an exception would be worse.
CONNECTION_ERRORS = frozenset(
    {
        "APIConnectionError",
        "APITimeoutError",
        "ConnectError",
        "ConnectTimeout",
        "PoolTimeout",
        "ReadError",
        "ReadTimeout",
        "RemoteProtocolError",
        "URLError",
    }
)


def is_connection_error(error: BaseException) -> bool:
    """Did the request fail on the wire rather than at the model? The cause
    chain under the LlmError is what tells a refused socket from a refused
    prompt."""
    seen: BaseException | None = error
    for _ in range(10):  # a cause chain can be a cycle; ten links are plenty
        if seen is None:
            return False
        if isinstance(seen, OSError):  # socket errors and everything under them
            return True
        if type(seen).__name__ in CONNECTION_ERRORS:
            return True
        seen = seen.__cause__ or seen.__context__
    return False


def record_cost(input_tokens: int, output_tokens: int, usd: float, seconds: float):
    """What the last request cost and how long it took. tokens/s is the
    number that tells a model loaded on the wrong device from a fast one;
    it is 0 when the request was too short to measure or the server counted
    no tokens."""
    rate = round(output_tokens / seconds, 1) if seconds > 0 and output_tokens else 0
    last_cost.update(
        input=input_tokens,
        output=output_tokens,
        usd=usd,
        seconds=round(seconds, 1),
        tokens_per_second=rate,
    )


def anthropic_client(settings: Settings):
    import anthropic

    key = settings.config["anthropic_api_key"]
    if not key and not os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        raise LlmError(
            "no Anthropic API key; put it in config.json as anthropic_api_key "
            "or set ANTHROPIC_API_KEY"
        )
    return anthropic.Anthropic(api_key=key or None, timeout=TIMEOUT_SECONDS)


def complete(
    instruction: str,
    data: str,
    schema: dict,
    settings: Settings,
    images: list[Path] | None = None,
    max_turns: int = 1,
) -> dict:
    """Run one structured request and return the validated object.

    With `claude`, `images` are read by the CLI's own Read tool; the
    instruction has to name them by path, and the call then needs more than
    one turn. The API backends receive them inline."""
    name = backend(settings)
    attempt = 0
    while True:
        attempt += 1
        try:
            if name == "claude":
                return complete_claude(
                    instruction, data, schema, settings, images, max_turns
                )
            if name == "anthropic":
                return complete_anthropic(instruction, data, schema, settings, images)
            return complete_openai(instruction, data, schema, settings, images)
        # A NoVisionError is not caught here: a second request does not give
        # the model eyes, and frames is waiting for it to keep the run alive.
        except LlmError as error:
            # A part of a long transcript failed once with an empty error
            # while the parts around it went through (2026-09-09), and one
            # lost part throws away every other request of that video. So:
            # one more try. A connection that dropped gets two, with a pause:
            # a server busy loading a model answers nothing for a while and
            # then answers again.
            wire = is_connection_error(error)
            limit = CONNECTION_ATTEMPTS if wire else ATTEMPTS
            if attempt >= limit:
                raise LlmError(f"{error} (after {attempt} attempts)") from error
            if wire:
                time.sleep(RETRY_PAUSE_SECONDS)


def complete_claude(
    instruction: str,
    data: str,
    schema: dict,
    settings: Settings,
    images: list[Path] | None,
    max_turns: int,
) -> dict:
    """The instruction travels as the argument, the data through stdin
    (Windows caps a command line at 32 KB, a transcript is longer), and
    `--json-schema` makes the CLI validate the answer before it returns."""
    command = [
        claude_binary(),
        "-p",
        instruction,
        "--model",
        model_name(settings),
        "--output-format",
        "json",
        "--json-schema",
        json.dumps(schema),
        "--no-session-persistence",
    ]
    # `--tools` names what exists at all; without it the model reached for a
    # tool when a prompt read like "read the README" and the one turn was
    # gone with `error_max_turns` (2026-09-09). `--allowedTools` only skips
    # the permission prompt for the tool that is there.
    if images:
        folders = sorted({str(p.parent) for p in images})
        command += ["--tools", "Read", "--allowedTools", "Read"]
        command += ["--max-turns", str(max(max_turns, 4))]
        for folder in folders:
            command += ["--add-dir", folder]
    else:
        command += ["--tools", "", "--max-turns", str(max_turns)]
    started = time.monotonic()
    try:
        run = subprocess.run(
            command,
            input=data,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise LlmError(f"claude gave no answer within {TIMEOUT_SECONDS}s") from error
    return parse_result(run.stdout, run.stderr, time.monotonic() - started)


def parse_result(stdout: str, stderr: str = "", seconds: float = 0.0) -> dict:
    """The CLI prints one JSON object; the structured answer sits in
    `structured_output`, an error in `result` with `is_error` set."""
    try:
        envelope = json.loads(stdout)
    except json.JSONDecodeError as error:
        raise LlmError(
            f"claude printed no JSON: {stderr.strip() or stdout[:200]}"
        ) from error
    if envelope.get("is_error"):
        text = str(envelope.get("result", ""))
        # An empty `result` happens; then only `subtype` says what went wrong.
        text = text.strip() or str(envelope.get("subtype") or "no reason given")
        hint = " Run `claude login` in a terminal." if "authenticate" in text else ""
        noise = f" ({stderr.strip()})" if stderr.strip() else ""
        raise LlmError(f"claude reported an error: {text}{hint}{noise}")
    usage = envelope.get("usage") or {}
    record_cost(
        sum(
            usage.get(key, 0)
            for key in (
                "input_tokens",
                "cache_creation_input_tokens",
                "cache_read_input_tokens",
            )
        ),
        usage.get("output_tokens", 0),
        envelope.get("total_cost_usd", 0.0),
        seconds,
    )
    structured = envelope.get("structured_output")
    if isinstance(structured, dict):
        return structured
    result = envelope.get("result")
    if isinstance(result, dict):
        return result
    if isinstance(result, str):
        try:
            return json.loads(result)
        except json.JSONDecodeError:
            pass
    raise LlmError("claude returned no structured output")


def image_part(path: Path, style: str) -> dict:
    """One image as the API wants it: `anthropic` or `openai` style."""
    media = mimetypes.guess_type(path.name)[0] or "image/png"
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    if style == "anthropic":
        return {
            "type": "image",
            "source": {"type": "base64", "media_type": media, "data": data},
        }
    return {"type": "image_url", "image_url": {"url": f"data:{media};base64,{data}"}}


def complete_anthropic(
    instruction: str,
    data: str,
    schema: dict,
    settings: Settings,
    images: list[Path] | None,
) -> dict:
    import anthropic

    client = anthropic_client(settings)
    content = [image_part(p, "anthropic") for p in images or []]
    content.append({"type": "text", "text": data})
    try:
        response = client.messages.create(
            model=model_name(settings),
            max_tokens=MAX_OUTPUT_TOKENS,
            system=instruction,
            messages=[{"role": "user", "content": content}],
            output_config={"format": {"type": "json_schema", "schema": schema}},
        )
    except anthropic.AnthropicError as error:
        raise LlmError(f"anthropic: {error}") from error
    usage = response.usage
    last_cost.update(
        input=usage.input_tokens
        + (getattr(usage, "cache_creation_input_tokens", 0) or 0)
        + (getattr(usage, "cache_read_input_tokens", 0) or 0),
        output=usage.output_tokens,
        # The API does not price the answer; the tokens are what is known.
        usd=0.0,
    )
    text = next((b.text for b in response.content if b.type == "text"), "")
    return loads(text, "anthropic")


def complete_openai(
    instruction: str,
    data: str,
    schema: dict,
    settings: Settings,
    images: list[Path] | None,
) -> dict:
    """OpenAI itself, or LM Studio and Ollama through the same protocol."""
    import openai

    name = backend(settings)
    model = model_name(settings)
    if not model:
        raise LlmError(check(settings) or f"no model set for {name}")
    key, url = endpoint(settings)
    client = openai.OpenAI(api_key=key, base_url=url, timeout=TIMEOUT_SECONDS)
    content: list[dict] = [image_part(p, "openai") for p in images or []]
    content.append({"type": "text", "text": data})
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": instruction},
                {"role": "user", "content": content},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "result", "schema": schema, "strict": True},
            },
        )
    except openai.OpenAIError as error:
        raise LlmError(reachable_message(name, error)) from error
    choice = response.choices[0]
    if getattr(choice.message, "refusal", None):
        raise LlmError(f"{name} refused: {choice.message.refusal}")
    usage = response.usage
    last_cost.update(
        input=usage.prompt_tokens if usage else 0,
        output=usage.completion_tokens if usage else 0,
        usd=0.0,
    )
    if not (choice.message.content or "").strip():
        # LM Studio answered with nothing when the prompt was longer than
        # the context the model was loaded with (2026-09-09, 8192 tokens
        # against a 13 KB transcript). A thinking model spends thousands
        # of tokens before the JSON, so the context has to hold both.
        raise LlmError(
            f"{name} returned an empty answer (finish_reason "
            f"{choice.finish_reason}, {last_cost['input']} prompt tokens); "
            "a local model needs a context window that holds the prompt "
            "and its thinking, load it with 32768 tokens or more"
        )
    return loads(choice.message.content, name)


def loads(text: str, name: str) -> dict:
    """The answer as an object. A local model sometimes wraps its JSON in a
    code fence although a schema was asked for; the fence goes."""
    body = text.strip()
    if body.startswith("```"):
        body = body.split("\n", 1)[1] if "\n" in body else ""
        body = body.rsplit("```", 1)[0]
    try:
        result = json.loads(body)
    except json.JSONDecodeError as error:
        raise LlmError(f"{name} returned no JSON: {text[:200]!r}") from error
    if not isinstance(result, dict):
        raise LlmError(f"{name} returned {type(result).__name__}, not an object")
    return result


def totals(entries: list[dict]) -> dict:
    """What a video cost: the requests of one run added up."""
    return {
        "requests": len(entries),
        "input": sum(e.get("input", 0) for e in entries),
        "output": sum(e.get("output", 0) for e in entries),
        "usd": round(sum(e.get("usd", 0.0) for e in entries), 4),
    }
