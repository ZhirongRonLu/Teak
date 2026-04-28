from pathlib import Path

from teak.config import TeakConfig, find_project_root


def test_for_project_layout(tmp_path: Path) -> None:
    cfg = TeakConfig.for_project(tmp_path)
    assert cfg.teak_dir == tmp_path / ".teak"
    assert cfg.brain_dir == tmp_path / ".teak" / "brain"
    assert cfg.db_path == tmp_path / ".teak" / "teak.db"
    assert cfg.templates_dir == tmp_path / ".teak" / "templates"


def test_find_project_root_walks_up(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    nested = project / "a" / "b"
    nested.mkdir(parents=True)
    (project / ".teak").mkdir()

    assert find_project_root(nested) == project


def test_find_project_root_falls_back_to_cwd(tmp_path: Path) -> None:
    assert find_project_root(tmp_path) == tmp_path
