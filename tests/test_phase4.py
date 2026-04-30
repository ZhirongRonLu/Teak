from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from teak.bench import BenchResult, load_tasks, summarize, write_csv
from teak.config import TeakConfig
from teak.flow.state import SessionState
from teak.llm.budget import BudgetExceeded, BudgetTracker
from teak.llm.cache import build_cached_messages
from teak.llm.client import LLMClient, LLMResponse
from teak.llm.routing import TaskKind, choose_model
from teak.session.handoff import (
    Handoff,
    aggregate_usage,
    load_all_handoffs,
    persist_handoff,
)


# ---- prompt caching ---------------------------------------------------------


def test_build_cached_messages_marks_brain_prefix() -> None:
    msgs = build_cached_messages(
        cached_prefix="BRAIN",
        instructions="ROLE",
        user_messages=[{"role": "user", "content": "hi"}],
    )
    assert msgs[0]["role"] == "system"
    blocks = msgs[0]["content"]
    assert blocks[0]["text"] == "BRAIN"
    assert blocks[0]["cache_control"] == {"type": "ephemeral"}
    assert blocks[1]["text"] == "ROLE"
    assert "cache_control" not in blocks[1]
    assert msgs[1] == {"role": "user", "content": "hi"}


def test_build_cached_messages_omits_blank_prefix() -> None:
    msgs = build_cached_messages(
        cached_prefix="",
        instructions="ROLE",
        user_messages=[{"role": "user", "content": "hi"}],
    )
    assert len(msgs[0]["content"]) == 1
    assert msgs[0]["content"][0]["text"] == "ROLE"


def test_build_cached_messages_requires_some_text() -> None:
    with pytest.raises(ValueError):
        build_cached_messages(cached_prefix="", instructions="", user_messages=[])


# ---- budget tracker ---------------------------------------------------------


def test_fraction_spent_clamped_to_one() -> None:
    t = BudgetTracker(budget_usd=1.0, spent_usd=2.0)
    assert t.fraction_spent() == 1.0


def test_pre_check_raises_when_estimate_exceeds() -> None:
    t = BudgetTracker(budget_usd=1.0, spent_usd=0.9)
    with pytest.raises(BudgetExceeded):
        t.pre_check(0.5)


def test_pre_check_passes_within_remaining() -> None:
    t = BudgetTracker(budget_usd=1.0, spent_usd=0.5)
    t.pre_check(0.3)  # no raise


def test_warned_flag_persists() -> None:
    t = BudgetTracker(budget_usd=1.0, spent_usd=0.85)
    assert t.warned is False
    t.warned = True
    assert t.warned is True


# ---- routing ----------------------------------------------------------------


def test_choose_model_for_summarize() -> None:
    assert choose_model(TaskKind.SUMMARIZE, default="big", planner="cheap") == "cheap"


def test_llmclient_routes_planner_for_plan_kind() -> None:
    client = LLMClient(default_model="big", planner_model="cheap")
    assert client._pick_model(None, TaskKind.PLAN) == "cheap"
    assert client._pick_model(None, TaskKind.GENERATE_CODE) == "big"


def test_llmclient_explicit_model_overrides_routing() -> None:
    client = LLMClient(default_model="big", planner_model="cheap")
    assert client._pick_model("override", TaskKind.PLAN) == "override"


def test_llmclient_downshift_when_budget_pressed() -> None:
    tracker = BudgetTracker(budget_usd=1.0, spent_usd=0.99)
    client = LLMClient(default_model="big", planner_model="cheap", tracker=tracker)
    assert client._apply_downshift("big") == "cheap"


def test_llmclient_no_downshift_when_no_tracker() -> None:
    client = LLMClient(default_model="big", planner_model="cheap")
    assert client._apply_downshift("big") == "big"


# ---- LLMClient call path with mocked litellm --------------------------------


def _fake_response(prompt_tokens=100, completion_tokens=50, cache_read=0, cache_creation=0):
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content='{"ok": true}'))]
    resp.usage = MagicMock(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cache_read_input_tokens=cache_read,
        cache_creation_input_tokens=cache_creation,
    )
    return resp


def test_llmclient_records_cache_tokens() -> None:
    client = LLMClient(default_model="anthropic/claude-haiku-4-5")
    with patch("teak.llm.client.litellm") as fake:
        fake.completion.return_value = _fake_response(
            prompt_tokens=200,
            completion_tokens=80,
            cache_read=150,
            cache_creation=40,
        )
        fake.completion_cost.return_value = 0.001
        fake.token_counter.side_effect = AttributeError  # not used without tracker
        out = client.complete(
            [{"role": "user", "content": "hi"}], kind=TaskKind.GENERATE_CODE
        )
    assert isinstance(out, LLMResponse)
    assert out.cache_read_tokens == 150
    assert out.cache_creation_tokens == 40
    assert client.total_cache_read_tokens == 150
    assert client.total_cache_creation_tokens == 40
    assert client.total_tokens_in == 200


def test_llmclient_preflight_blocks_overrun() -> None:
    tracker = BudgetTracker(budget_usd=0.001, spent_usd=0.0009)
    client = LLMClient(
        default_model="anthropic/claude-haiku-4-5", tracker=tracker
    )
    with patch("teak.llm.client.litellm") as fake:
        fake.token_counter.return_value = 1000
        fake.cost_per_token.return_value = (0.01, 0.005)
        with pytest.raises(BudgetExceeded):
            client.complete([{"role": "user", "content": "x"}])


# ---- dashboard aggregation --------------------------------------------------


def _handoff(**overrides) -> Handoff:
    base = dict(
        created_at="2026-04-29T00:00:00",
        branch="teak/x",
        summary="did stuff",
    )
    base.update(overrides)
    return Handoff(**base)


def test_aggregate_usage_sums_across_handoffs() -> None:
    a = _handoff(tokens_in=100, tokens_out=50, cost_usd=0.01, cache_read_tokens=80)
    b = _handoff(tokens_in=200, tokens_out=80, cost_usd=0.02, cache_read_tokens=180)
    agg = aggregate_usage([a, b])
    assert agg["sessions"] == 2
    assert agg["tokens_in"] == 300
    assert agg["tokens_out"] == 130
    assert agg["cost_usd"] == pytest.approx(0.03)
    assert agg["cache_read_tokens"] == 260
    assert agg["cache_hit_ratio"] == pytest.approx(260 / 300)


def test_aggregate_usage_handles_empty() -> None:
    agg = aggregate_usage([])
    assert agg["sessions"] == 0
    assert agg["cache_hit_ratio"] == 0.0


def test_load_all_handoffs_round_trip(tmp_path: Path) -> None:
    cfg = TeakConfig.for_project(tmp_path)
    state = SessionState(task="t", branch="teak/session-1")
    persist_handoff(_handoff(branch="teak/session-1", tokens_in=100), cfg, state)
    persist_handoff(_handoff(branch="teak/session-2", tokens_in=200), cfg, state)
    loaded = load_all_handoffs(cfg)
    assert [h.branch for h in loaded] == ["teak/session-1", "teak/session-2"]
    assert loaded[0].tokens_in == 100
    assert loaded[1].tokens_in == 200


# ---- bench harness ----------------------------------------------------------


def test_load_tasks_supports_named_object(tmp_path: Path) -> None:
    f = tmp_path / "tasks.json"
    f.write_text(
        json.dumps(
            {
                "tasks": [
                    {"name": "n1", "project_path": "/p", "task": "do x"},
                    {"name": "n2", "project_path": "/q", "task": "do y", "base_ref": "v1"},
                ]
            }
        )
    )
    tasks = load_tasks(f)
    assert [t.name for t in tasks] == ["n1", "n2"]
    assert tasks[1].base_ref == "v1"


def test_load_tasks_supports_bare_list(tmp_path: Path) -> None:
    f = tmp_path / "tasks.json"
    f.write_text(json.dumps([{"name": "n1", "project_path": "/p", "task": "do x"}]))
    assert load_tasks(f)[0].name == "n1"


def test_summarize_groups_by_mode() -> None:
    rs = [
        BenchResult(task="t1", mode="teak", tokens_in=100, cost_usd=0.01),
        BenchResult(task="t2", mode="teak", tokens_in=200, cost_usd=0.02),
        BenchResult(task="t1", mode="naive", tokens_in=1000, cost_usd=0.10),
    ]
    out = summarize(rs)
    assert out["teak"]["tokens_in"] == 300
    assert out["naive"]["tokens_in"] == 1000
    assert out["naive"]["cost_usd"] == pytest.approx(0.10)


def test_write_csv_round_trip(tmp_path: Path) -> None:
    rs = [
        BenchResult(task="t1", mode="teak", tokens_in=100, tokens_out=50, cost_usd=0.01),
    ]
    out = tmp_path / "r.csv"
    write_csv(rs, out)
    text = out.read_text()
    assert "task,mode" in text
    assert "t1,teak,100,50" in text
