import json
from types import SimpleNamespace

import pytest

from corganshelper_service.llm import LlmError, parse_result


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


def test_a_failed_request_is_tried_once_more(monkeypatch):
    from corganshelper_service import llm

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
    assert llm.complete("i", "d", {}) == {"kind": "a"}
    assert len(calls) == 2


def test_what_a_run_cost_is_read_from_the_envelope_and_added_up():
    from corganshelper_service.llm import last_cost, totals

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
        )
    )
    assert last_cost == {"input": 17, "output": 7, "usd": 0.25}
    assert totals([dict(last_cost), dict(last_cost)]) == {
        "requests": 2,
        "input": 34,
        "output": 14,
        "usd": 0.5,
    }
