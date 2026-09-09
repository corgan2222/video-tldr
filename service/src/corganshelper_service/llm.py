"""One door to the language model: `claude -p` from the Claude Code CLI.

The owner's subscription pays for it, so there is no API key to keep. The
instruction travels as the argument, the data through stdin (Windows caps a
command line at 32 KB, a transcript is longer), and `--json-schema` makes
the CLI validate the answer before it returns.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

DEFAULT_MODEL = "sonnet"
TIMEOUT_SECONDS = 600
ATTEMPTS = 2


class LlmError(Exception):
    """The CLI did not return a usable answer; the message says why."""


def model_name() -> str:
    return os.environ.get("CORGANSHELPER_MODEL", DEFAULT_MODEL)


def claude_binary() -> str:
    found = shutil.which("claude")
    if found is None:
        raise LlmError("the claude CLI is not on the PATH; install Claude Code first")
    return found


def complete(
    instruction: str,
    data: str,
    schema: dict,
    images: list[Path] | None = None,
    max_turns: int = 1,
) -> dict:
    """Run one structured request and return the validated object.

    `images` are read by the CLI's own Read tool; the instruction has to name
    them by path, and the call then needs more than one turn."""
    command = [
        claude_binary(),
        "-p",
        instruction,
        "--model",
        model_name(),
        "--output-format",
        "json",
        "--json-schema",
        json.dumps(schema),
        "--no-session-persistence",
    ]
    if images:
        folders = sorted({str(p.parent) for p in images})
        command += ["--allowedTools", "Read", "--max-turns", str(max(max_turns, 4))]
        for folder in folders:
            command += ["--add-dir", folder]
    else:
        command += ["--max-turns", str(max_turns)]
    # A part of a long transcript failed once with an empty error while the
    # parts around it went through (2026-09-09), and one lost part throws
    # away every other request of that video. So: one more try.
    for attempt in range(ATTEMPTS):
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
            return parse_result(run.stdout, run.stderr)
        except subprocess.TimeoutExpired as error:
            raise LlmError(
                f"claude gave no answer within {TIMEOUT_SECONDS}s"
            ) from error
        except LlmError:
            if attempt == ATTEMPTS - 1:
                raise


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
