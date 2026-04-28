from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class SessionRepo:
    """Wraps GitPython for the rollback model from README §5.

    Every executor step is a commit on `teak/session-{timestamp}`. Rejecting a
    step calls `git reset HEAD~1` on the same branch. Approving the session
    means the user merges or cherry-picks back onto their working branch.
    """

    project_root: Path
    branch_prefix: str = "teak/session-"

    def start_session_branch(self) -> str:
        """Create and check out a new session branch; return its name."""
        raise NotImplementedError

    def commit_step(self, message: str) -> str:
        """Stage all changes and commit. Returns the new commit sha."""
        raise NotImplementedError(message)

    def reset_last(self) -> None:
        """`git reset --hard HEAD~1` on the session branch."""
        raise NotImplementedError

    def diff_summary(self) -> str:
        """Return a short summary of the diff between session branch and base."""
        raise NotImplementedError
