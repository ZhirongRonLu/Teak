import pytest

from teak.flow.nodes.planner import _parse_plan


def test_parse_plain_json() -> None:
    text = '{"steps": [{"title": "x", "rationale": "y", "target_files": ["a.py"]}]}'
    steps, notes = _parse_plan(text)
    assert len(steps) == 1
    assert steps[0].title == "x"
    assert steps[0].target_files == ["a.py"]
    assert notes == ""


def test_parse_json_inside_fence() -> None:
    text = '```json\n{"steps": [], "notes": "nothing to do"}\n```'
    steps, notes = _parse_plan(text)
    assert steps == []
    assert notes == "nothing to do"


def test_parse_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        _parse_plan("not json at all")


def test_parse_rejects_non_list_steps() -> None:
    with pytest.raises(ValueError):
        _parse_plan('{"steps": "oops"}')


def test_parse_fills_defaults_for_missing_step_fields() -> None:
    steps, _ = _parse_plan('{"steps": [{}]}')
    assert len(steps) == 1
    assert steps[0].title == "step 1"
    assert steps[0].rationale == ""
    assert steps[0].target_files == []
