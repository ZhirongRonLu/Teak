from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from teak.brain.bootstrapper import bootstrap_brain
from teak.brain.manager import (
    BRAIN_FILES,
    BrainManager,
    ConventionViolation,
    parse_violations,
)
from teak.brain.templates import (
    _read_filesystem_template,
    list_templates,
    load_template,
    user_template_dir,
)
from teak.config import TeakConfig
from teak.context.embedder import HashEmbedder, LiteLLMEmbedder, choose_embedder
from teak.flow.nodes import convention_check
from teak.flow.state import PlanStep, SessionState


# ---- detect_violations / parser --------------------------------------------


def test_parse_violations_empty_object() -> None:
    assert parse_violations('{"violations": []}') == []


def test_parse_violations_extracts_entries() -> None:
    raw = json.dumps(
        {
            "violations": [
                {"step_index": 1, "rule": "no direct DB", "detail": "uses ORM in view"},
                {"step_index": 2, "rule": "context-first", "detail": "missing ctx"},
            ]
        }
    )
    out = parse_violations(raw)
    assert [v.rule for v in out] == ["no direct DB", "context-first"]
    assert all(isinstance(v, ConventionViolation) for v in out)


def test_parse_violations_skips_blank_entries() -> None:
    raw = json.dumps(
        {"violations": [{"step_index": 0, "rule": "", "detail": ""}]}
    )
    assert parse_violations(raw) == []


def test_parse_violations_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        parse_violations("nope")


class _StubClient:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls: list[dict] = []

    def complete_cached(
        self,
        *,
        cached_prefix,
        instructions,
        user_messages,
        json_mode=False,
        kind=None,
        model=None,
    ):
        self.calls.append(
            {"cached_prefix": cached_prefix, "instructions": instructions}
        )
        resp = MagicMock()
        resp.text = self.text
        resp.tokens_in = resp.tokens_out = 1
        resp.cost_usd = 0.0
        resp.cache_read_tokens = resp.cache_creation_tokens = 0
        return resp


def test_detect_violations_returns_empty_without_brain(tmp_path: Path) -> None:
    cfg = TeakConfig.for_project(tmp_path)
    manager = BrainManager(cfg)  # no files written
    client = _StubClient(json.dumps({"violations": []}))
    out = manager.detect_violations(["do thing"], client)
    assert out == []
    assert client.calls == []  # short-circuited; no LLM call


def test_detect_violations_calls_llm_when_brain_present(tmp_path: Path) -> None:
    bootstrap_brain(tmp_path, template="python-cli")
    cfg = TeakConfig.for_project(tmp_path)
    manager = BrainManager(cfg)

    payload = json.dumps(
        {
            "violations": [
                {"step_index": 0, "rule": "no print in lib", "detail": "uses print"}
            ]
        }
    )
    client = _StubClient(payload)
    out = manager.detect_violations(["add print() to library code"], client)
    assert len(out) == 1 and out[0].rule == "no print in lib"
    assert "## CONVENTIONS.md" in client.calls[0]["cached_prefix"]


# ---- convention_check node --------------------------------------------------


def test_convention_check_node_no_brain(tmp_path: Path) -> None:
    cfg = TeakConfig.for_project(tmp_path)
    brain = BrainManager(cfg)
    client = MagicMock()
    node = convention_check.make_node(client, brain)
    state = SessionState(task="t", plan=[PlanStep("s", "")])
    assert node(state) == {}


def test_convention_check_node_returns_failures_on_flag(tmp_path: Path) -> None:
    bootstrap_brain(tmp_path, template="python-cli")
    cfg = TeakConfig.for_project(tmp_path)
    brain = BrainManager(cfg)

    class _MockBrain:
        def exists(self) -> bool:
            return True

        def detect_violations(self, descriptions, client):
            return [
                ConventionViolation(
                    step_index=0, rule="rule one", detail="bad"
                )
            ]

    node = convention_check.make_node(MagicMock(), _MockBrain())
    state = SessionState(task="t", plan=[PlanStep("s1", "r1")])
    out = node(state)
    assert out["test_failures"] and "rule one" in out["test_failures"][0]


def test_convention_check_node_clean_returns_empty(tmp_path: Path) -> None:
    class _MockBrain:
        def exists(self) -> bool:
            return True

        def detect_violations(self, descriptions, client):
            return []

    node = convention_check.make_node(MagicMock(), _MockBrain())
    state = SessionState(task="t", plan=[PlanStep("s1", "r1")])
    assert node(state) == {}


# ---- filesystem templates ---------------------------------------------------


def test_filesystem_template_loads(tmp_path: Path) -> None:
    tdir = tmp_path / "my-stack"
    tdir.mkdir()
    (tdir / "template.json").write_text(
        json.dumps({"name": "my-stack", "description": "custom"})
    )
    for filename in BRAIN_FILES:
        (tdir / filename).write_text(f"# {filename}\nbody\n")

    tpl = _read_filesystem_template(tdir)
    assert tpl is not None
    assert tpl.name == "my-stack"
    assert tpl.description == "custom"
    assert "ARCHITECTURE.md" in tpl.files


def test_filesystem_template_with_no_brain_files_returns_none(tmp_path: Path) -> None:
    tdir = tmp_path / "junk"
    tdir.mkdir()
    (tdir / "template.json").write_text(json.dumps({"name": "junk"}))
    assert _read_filesystem_template(tdir) is None


def test_list_templates_includes_built_ins() -> None:
    names = {t.name for t in list_templates()}
    assert {"python-cli", "django-rest", "next-monorepo", "go-microservice"} <= names


def test_user_template_overrides_builtin(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "teak.brain.templates.user_template_dir", lambda: tmp_path
    )
    override_dir = tmp_path / "python-cli"
    override_dir.mkdir()
    (override_dir / "template.json").write_text(
        json.dumps({"name": "python-cli", "description": "custom override"})
    )
    for filename in BRAIN_FILES:
        (override_dir / filename).write_text("custom\n")

    loaded = load_template("python-cli")
    assert loaded.description == "custom override"


def test_load_unknown_template_lists_alternatives() -> None:
    with pytest.raises(KeyError) as excinfo:
        load_template("does-not-exist")
    assert "available" in str(excinfo.value)


def test_install_into_writes_all_files(tmp_path: Path) -> None:
    tpl = load_template("go-microservice")
    target = tmp_path / "brain"
    tpl.install_into(target)
    for filename in BRAIN_FILES:
        assert (target / filename).is_file()


# ---- embedder selection -----------------------------------------------------


def test_choose_embedder_prefers_explicit_env(monkeypatch) -> None:
    monkeypatch.setenv("TEAK_EMBEDDING_MODEL", "ollama/mxbai-embed-large")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    e = choose_embedder()
    assert isinstance(e, LiteLLMEmbedder)
    assert e.model == "ollama/mxbai-embed-large"
    assert e.dim == 1024  # guessed


def test_choose_embedder_picks_ollama_when_host_set(monkeypatch) -> None:
    monkeypatch.delenv("TEAK_EMBEDDING_MODEL", raising=False)
    monkeypatch.setenv("OLLAMA_HOST", "http://localhost:11434")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("VOYAGE_API_KEY", raising=False)
    e = choose_embedder()
    assert isinstance(e, LiteLLMEmbedder)
    assert e.model.startswith("ollama/")


def test_choose_embedder_falls_back_to_hash(monkeypatch) -> None:
    for var in ("TEAK_EMBEDDING_MODEL", "OLLAMA_HOST", "TEAK_PREFER_OLLAMA",
                "OPENAI_API_KEY", "VOYAGE_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    assert isinstance(choose_embedder(), HashEmbedder)
