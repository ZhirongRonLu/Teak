from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import git


class DirtyWorkingTree(RuntimeError):
    """Raised when a session can't start because of uncommitted changes."""


@dataclass
class SessionRepo:
    """Wraps GitPython for the rollback model from README §5.

    Every executor step is a commit on `teak/session-{timestamp}`. Rejecting a
    step calls `git reset --hard HEAD~1` on the same branch. Approving the
    session means the user merges or cherry-picks back onto their working
    branch.
    """

    project_root: Path
    branch_prefix: str = "teak/session-"

    def __post_init__(self) -> None:
        self._repo = git.Repo(self.project_root)
        self._base_ref: str | None = None

    @property
    def repo(self) -> git.Repo:
        return self._repo

    def assert_clean(self) -> None:
        if self._repo.is_dirty(untracked_files=True):
            raise DirtyWorkingTree(
                "uncommitted changes in working tree; commit or stash before running teak"
            )

    def start_session_branch(self) -> str:
        self.assert_clean()
        self._base_ref = self._repo.head.commit.hexsha
        name = f"{self.branch_prefix}{int(time.time())}"
        new_branch = self._repo.create_head(name)
        new_branch.checkout()
        return name

    def commit_step(self, message: str) -> str:
        self._repo.git.add(A=True)
        if not self._repo.is_dirty(index=True, working_tree=False, untracked_files=False):
            return ""
        commit = self._repo.index.commit(message)
        return commit.hexsha

    def reset_last(self) -> None:
        self._repo.git.reset("--hard", "HEAD~1")

    def diff_summary(self) -> str:
        if self._base_ref is None:
            return ""
        return self._repo.git.diff(self._base_ref, "HEAD", "--stat")
