from __future__ import annotations

import json
from pathlib import Path

import pytest

from teak.brain.bootstrapper import (
    _parse_brain_payload,
    bootstrap_brain,
    survey_codebase,
)
from teak.brain.manager import BRAIN_FILES, BrainManager, parse_brain_update
from teak.brain.templates import list_templates, load_template
from teak.config import TeakConfig


class _StubClient:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls: list[list[dict]] = []

    def complete(self, messages, *, model=None, json_mode=False, kind=None):
        self.calls.append(messages)
        return _StubResp(self.text)

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
        # Reconstruct an equivalent flat message list for assertion convenience.
        system = "\n\n".join(p for p in (cached_prefix, instructions) if p)
        flat = [{"role": "system", "content": system}] + list(user_messages)
        self.calls.append(flat)
        return _StubResp(self.text)


class _StubResp:
    def __init__(self, text: str) -> None:
        self.text = text
        self.tokens_in = 1
        self.tokens_out = 1
        self.cost_usd = 0.0
        self.cache_read_tokens = 0
        self.cache_creation_tokens = 0
        self.model = "stub"


def _make_project(tmp_path: Path) -> Path:
    project = tmp_path / "proj"
    (project / "src" / "app").mkdir(parents=True)
    (project / "node_modules" / "junk").mkdir(parents=True)
    (project / ".venv" / "lib").mkdir(parents=True)
    (project / "README.md").write_text("# proj\n\nCool tool.\n", encoding="utf-8")
    (project / "pyproject.toml").write_text("[project]\nname='proj'\n", encoding="utf-8")
    (project / "src" / "app" / "main.py").write_text("def main():\n    return 1\n", encoding="utf-8")
    (project / "node_modules" / "junk" / "evil.js").write_text("haha", encoding="utf-8")
    (project / ".venv" / "lib" / "x.py").write_text("noise", encoding="utf-8")
    return project


def test_survey_codebase_skips_vendored_dirs(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    survey = survey_codebase(project)

    flat_tree = " ".join(survey.tree)
    assert "node_modules" not in flat_tree
    assert ".venv" not in flat_tree
    assert "src/app/main.py" in survey.tree
    assert "pyproject.toml" in survey.manifests
    assert survey.readme is not None and "Cool tool" in survey.readme
    assert "src/app/main.py" in survey.source_snippets


def test_survey_to_prompt_contains_sections(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    text = survey_codebase(project).to_prompt()
    assert "## README" in text
    assert "## Manifests" in text
    assert "## File tree" in text
    assert "## Source snippets" in text


def test_parse_brain_payload_requires_all_files() -> None:
    payload = {name: f"# {name}\n\nbody\n" for name in BRAIN_FILES}
    parsed = _parse_brain_payload(json.dumps(payload))
    assert parsed == payload


def test_parse_brain_payload_rejects_missing_file() -> None:
    payload = {name: "x" for name in BRAIN_FILES[:-1]}
    with pytest.raises(ValueError):
        _parse_brain_payload(json.dumps(payload))


def test_parse_brain_payload_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        _parse_brain_payload("nope")


def test_bootstrap_brain_with_template_writes_files(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    manager = bootstrap_brain(project, template="python-cli")
    assert manager.exists()
    arch = (project / ".teak" / "brain" / "ARCHITECTURE.md").read_text()
    assert "Architecture" in arch


def test_bootstrap_brain_with_llm_uses_payload(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    payload = {name: f"# {name}\n\nbody for {name}\n" for name in BRAIN_FILES}
    client = _StubClient(json.dumps(payload))

    manager = bootstrap_brain(project, client=client)

    assert manager.exists()
    for name in BRAIN_FILES:
        assert manager.files[name].read() == payload[name]
    # The bootstrapper made one LLM call.
    assert len(client.calls) == 1
    user_msg = client.calls[0][1]["content"]
    assert "## README" in user_msg


def test_list_and_load_templates() -> None:
    names = {t.name for t in list_templates()}
    assert "python-cli" in names
    tpl = load_template("python-cli")
    assert "ARCHITECTURE.md" in tpl.files


def test_load_unknown_template_raises() -> None:
    with pytest.raises(KeyError):
        load_template("does-not-exist")


def test_cached_system_prompt_includes_brain_files(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    bootstrap_brain(project, template="python-cli")
    manager = BrainManager(TeakConfig.for_project(project))

    text = manager.cached_system_prompt()
    for name in BRAIN_FILES:
        assert f"## {name}" in text
    assert "Teak" in text  # system.md preamble survives


def test_cached_system_prompt_when_brain_missing(tmp_path: Path) -> None:
    manager = BrainManager(TeakConfig.for_project(tmp_path))
    text = manager.cached_system_prompt()
    assert "no project brain initialized" in text


def test_parse_brain_update_empty_object() -> None:
    assert parse_brain_update('{"updates": {}}') == {}


def test_parse_brain_update_returns_only_known_files() -> None:
    payload = json.dumps({"updates": {"MEMORY.md": "# Memory\n\nnew\n"}})
    parsed = parse_brain_update(payload)
    assert parsed == {"MEMORY.md": "# Memory\n\nnew\n"}


def test_parse_brain_update_rejects_unknown_file() -> None:
    payload = json.dumps({"updates": {"NOTES.md": "x"}})
    with pytest.raises(ValueError):
        parse_brain_update(payload)


def test_parse_brain_update_rejects_non_string() -> None:
    payload = json.dumps({"updates": {"MEMORY.md": 123}})
    with pytest.raises(ValueError):
        parse_brain_update(payload)


def test_apply_updates_writes_files(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    bootstrap_brain(project, template="python-cli")
    manager = BrainManager(TeakConfig.for_project(project))

    manager.apply_updates({"MEMORY.md": "# Memory\n\nnew note\n"})
    assert manager.files["MEMORY.md"].read() == "# Memory\n\nnew note\n"


def test_apply_updates_unknown_key(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    bootstrap_brain(project, template="python-cli")
    manager = BrainManager(TeakConfig.for_project(project))

    with pytest.raises(KeyError):
        manager.apply_updates({"NOTES.md": "x"})


def test_propose_updates_passes_brain_and_diff(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    bootstrap_brain(project, template="python-cli")
    manager = BrainManager(TeakConfig.for_project(project))

    client = _StubClient(json.dumps({"updates": {"MEMORY.md": "# Memory\n\nupd\n"}}))
    out = manager.propose_updates("README.md | 1 +", client)

    assert out == {"MEMORY.md": "# Memory\n\nupd\n"}
    user_msg = client.calls[0][1]["content"]
    assert "current_brain" in user_msg
    assert "diff_summary" in user_msg
