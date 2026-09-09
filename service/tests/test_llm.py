import json

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
