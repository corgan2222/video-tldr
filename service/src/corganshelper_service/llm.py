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
ATTEMPTS = 2
START_HINT = {
    "lmstudio": "start the server in LM Studio or run `lms server start`",
    "ollama": "run `ollama serve`",
}


# What the last answer cost. The CLI reports it per request and the
# milestone asks what a video costs, so `analyze` reads it after each
# call. ponytail: one slot, the service runs one request at a time.
last_cost: dict = {}


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
    return {"ok": True, "detail": f"{name} at {endpoint(settings)[1]}, model {model}"}


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
    # A part of a long transcript failed once with an empty error while the
    # parts around it went through (2026-09-09), and one lost part throws
    # away every other request of that video. So: one more try.
    for attempt in range(ATTEMPTS):
        try:
            if name == "claude":
                return complete_claude(
                    instruction, data, schema, settings, images, max_turns
                )
            if name == "anthropic":
                return complete_anthropic(instruction, data, schema, settings, images)
            return complete_openai(instruction, data, schema, settings, images)
        except LlmError:
            if attempt == ATTEMPTS - 1:
                raise


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
    return parse_result(run.stdout, run.stderr)


def parse_result(stdout: str, stderr: str = "") -> dict:
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
    last_cost.update(
        input=sum(
            usage.get(key, 0)
            for key in (
                "input_tokens",
                "cache_creation_input_tokens",
                "cache_read_input_tokens",
            )
        ),
        output=usage.get("output_tokens", 0),
        usd=envelope.get("total_cost_usd", 0.0),
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
