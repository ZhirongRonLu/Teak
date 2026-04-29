from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import git
import pytest

from teak.config import TeakConfig
from teak.flow.graph import (
    _route_after_plan_approval,
    _route_after_step_review,
    _route_after_verifier,
)
from teak.flow.nodes import step_review, verifier
from teak.flow.nodes.verifier import detect_default_command
from teak.flow.state import PlanStep, SessionState
from teak.session.handoff import (
    Handoff,
    load_last_handoff,
    parse_handoff_payload,
    persist_handoff,
)


# ---- routing helpers --------------------------------------------------------


def _state(**overrides) -> SessionState:
    base = {"task": "x", "plan": [PlanStep(title="s1", rationale="")]}
    base.update(overrides)
    return SessionState(**base)


def test_route_after_plan_approval_empty_plan_ends() -> None:
    from langgraph.graph import END

    s = _state(plan=[])
    assert _route_after_plan_approval(s) == END


def test_route_after_plan_approval_routes_to_step_runner() -> None:
    s = _state()
    assert _route_after_plan_approval(s) == "step_runner"


def test_route_after_step_review_kept_change_runs_verifier() -> None:
    s = _state(last_commit_sha="abc")
    assert _route_after_step_review(s) == "verifier"


def test_route_after_step_review_no_commit_advances() -> None:
    s = _state(last_commit_sha="", current_step=0)
    assert _route_after_step_review(s) == "step_runner"


def test_route_after_step_review_no_more_steps_goes_to_brain_updater() -> None:
    s = _state(last_commit_sha="", current_step=1)  # plan has 1 step → done
    assert _route_after_step_review(s) == "brain_updater"


def test_route_after_verifier_failure_with_retry_loops() -> None:
    s = _state(last_commit_sha="", last_failure="boom")
    assert _route_after_verifier(s) == "step_runner"


def test_route_after_verifier_pass_advances() -> None:
    s = _state(current_step=1, last_failure="")
    assert _route_after_verifier(s) == "brain_updater"


# ---- handoff parse + persist + load ----------------------------------------


def test_parse_handoff_requires_summary() -> None:
    with pytest.raises(ValueError):
        parse_handoff_payload('{"summary": ""}', branch="b")


def test_parse_handoff_extracts_lists() -> None:
    payload = json.dumps(
        {"summary": "did stuff", "pending": ["a", "b"], "decisions": ["c"]}
    )
    h = parse_handoff_payload(payload, branch="teak/x", created_at="2026-04-28T00:00:00")
    assert h.summary == "did stuff"
    assert h.pending == ["a", "b"]
    assert h.decisions == ["c"]
    assert h.branch == "teak/x"


def test_handoff_to_prompt_includes_sections() -> None:
    h = Handoff(
        created_at="2026-04-28T00:00:00",
        branch="teak/session-1",
        summary="fixed login flow",
        pending=["update docs"],
        decisions=["kept blocking IO"],
    )
    text = h.to_prompt()
    assert "fixed login flow" in text
    assert "Pending:" in text
    assert "Decisions:" in text


def test_handoff_persist_and_load_roundtrip(tmp_path: Path) -> None:
    cfg = TeakConfig.for_project(tmp_path)
    state = SessionState(task="t", branch="teak/session-1", diffs=["abc123"])
    handoff = Handoff(
        created_at="2026-04-28T00:00:00",
        branch="teak/session-1",
        summary="did the thing",
        pending=["a"],
        decisions=["b"],
    )
    persist_handoff(handoff, cfg, state)

    loaded = load_last_handoff(cfg)
    assert loaded is not None
    assert loaded.summary == "did the thing"
    assert loaded.pending == ["a"]
    assert loaded.decisions == ["b"]


def test_load_handoff_missing_db_returns_none(tmp_path: Path) -> None:
    cfg = TeakConfig.for_project(tmp_path)
    assert load_last_handoff(cfg) is None


# ---- step_review reset on rejection -----------------------------------------


def _make_repo(tmp_path: Path) -> "git.Repo":
    repo = git.Repo.init(tmp_path)
    repo.config_writer().set_value("user", "email", "test@example.com").release()
    repo.config_writer().set_value("user", "name", "Test").release()
    (tmp_path / "a.txt").write_text("first\n")
    repo.index.add(["a.txt"])
    repo.index.commit("init")
    return repo


def test_step_review_advance_when_no_commit(tmp_path: Path, monkeypatch) -> None:
    from teak.vcs.repo import SessionRepo

    _make_repo(tmp_path)
    repo = SessionRepo(project_root=tmp_path)
    repo.start_session_branch()
    node = step_review.make_node(repo)

    state = SessionState(task="x", plan=[PlanStep("s", "")], last_commit_sha="")
    out = node(state)
    assert out["current_step"] == 1
    assert out["last_commit_sha"] == ""


def test_step_review_reject_resets(tmp_path: Path, monkeypatch) -> None:
    from teak.vcs.repo import SessionRepo

    _make_repo(tmp_path)
    repo = SessionRepo(project_root=tmp_path)
    repo.start_session_branch()
    # Make a commit on the session branch so reset_last has something to undo.
    (tmp_path / "b.txt").write_text("second\n")
    sha = repo.commit_step("teak: new file")
    assert sha

    monkeypatch.setattr("teak.flow.nodes.step_review.Prompt.ask", lambda *a, **k: "r")

    node = step_review.make_node(repo)
    state = SessionState(
        task="x",
        plan=[PlanStep("s", "")],
        diffs=[sha],
        last_commit_sha=sha,
    )
    out = node(state)
    assert out["last_commit_sha"] == ""
    assert out["diffs"] == []
    # b.txt should be gone after the reset
    assert not (tmp_path / "b.txt").exists()


def test_step_review_accept_keeps_commit(tmp_path: Path, monkeypatch) -> None:
    from teak.vcs.repo import SessionRepo

    _make_repo(tmp_path)
    repo = SessionRepo(project_root=tmp_path)
    repo.start_session_branch()
    (tmp_path / "b.txt").write_text("second\n")
    sha = repo.commit_step("teak: new file")
    assert sha

    monkeypatch.setattr("teak.flow.nodes.step_review.Prompt.ask", lambda *a, **k: "a")

    node = step_review.make_node(repo)
    state = SessionState(
        task="x",
        plan=[PlanStep("s", "")],
        diffs=[sha],
        last_commit_sha=sha,
    )
    out = node(state)
    assert out["last_commit_sha"] == sha
    assert (tmp_path / "b.txt").exists()


# ---- verifier ---------------------------------------------------------------


def test_verifier_no_command_advances() -> None:
    repo = MagicMock()
    node = verifier.make_node(repo, Path("/tmp"))
    state = SessionState(task="x", plan=[PlanStep("s", "")], current_step=0)
    out = node(state)
    assert out["current_step"] == 1
    assert out["last_failure"] == ""


def test_verifier_pass_advances(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        verifier,
        "_run_command",
        lambda cmd, cwd: (0, "ok"),
    )
    repo = MagicMock()
    node = verifier.make_node(repo, tmp_path)
    state = SessionState(
        task="x",
        plan=[PlanStep("s", "")],
        current_step=0,
        verifier_command="pytest",
        last_commit_sha="abc",
    )
    out = node(state)
    assert out["current_step"] == 1
    assert out["last_failure"] == ""


def test_verifier_fail_with_retry_resets_and_loops(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        verifier,
        "_run_command",
        lambda cmd, cwd: (1, "boom"),
    )
    repo = MagicMock()
    node = verifier.make_node(repo, tmp_path)
    state = SessionState(
        task="x",
        plan=[PlanStep("s", "")],
        current_step=0,
        verifier_command="pytest",
        last_commit_sha="abc",
        diffs=["abc"],
        max_step_retries=2,
        step_attempts={0: 1},  # already used one attempt
    )
    out = node(state)
    assert out["last_failure"] == "boom"
    assert out["last_commit_sha"] == ""
    assert out["diffs"] == []
    repo.reset_last.assert_called_once()


def test_verifier_fail_exhausted_revert_default(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(verifier, "_run_command", lambda cmd, cwd: (1, "boom"))
    monkeypatch.setattr("teak.flow.nodes.verifier.Prompt.ask", lambda *a, **k: "r")

    repo = MagicMock()
    node = verifier.make_node(repo, tmp_path)
    state = SessionState(
        task="x",
        plan=[PlanStep("s1", ""), PlanStep("s2", "")],
        current_step=0,
        verifier_command="pytest",
        last_commit_sha="abc",
        diffs=["abc"],
        max_step_retries=2,
        step_attempts={0: 2},  # already exhausted
    )
    out = node(state)
    assert out["current_step"] == 1
    assert out["last_commit_sha"] == ""
    repo.reset_last.assert_called_once()


def test_detect_default_command_finds_pytest(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\ntestpaths = ['tests']\n"
    )
    assert detect_default_command(tmp_path) == "pytest -q"


def test_detect_default_command_finds_npm_test(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"test": "vitest"}}))
    assert detect_default_command(tmp_path) == "npm test --silent"


def test_detect_default_command_unknown(tmp_path: Path) -> None:
    assert detect_default_command(tmp_path) == ""


def test_run_command_handles_missing_binary(tmp_path: Path) -> None:
    code, output = verifier._run_command("definitely-not-a-real-cmd-xyz", tmp_path)
    assert code != 0
    assert "not found" in output or output == "" or "No such" in output
