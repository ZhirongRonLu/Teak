from __future__ import annotations

from pathlib import Path
from typing import Iterable

from teak.config import TeakConfig
from teak.context.storage import VectorStore


class Indexer:
    """Incremental, watchdog-driven indexer.

    Responsibilities:
      - Walk the project once on `bootstrap()` and populate the store.
      - Subscribe to filesystem events and re-index only changed files.
      - Compare file hashes against the store to skip no-op updates.
      - Run in a background thread; never block the UI.
    """

    def __init__(self, config: TeakConfig, store: VectorStore) -> None:
        self.config = config
        self.store = store
        self._watcher = None  # set by start()

    def bootstrap(self) -> None:
        """Walk the project once and ensure the store is current."""
        raise NotImplementedError

    def start(self) -> None:
        """Begin watching the project for file changes (background thread)."""
        raise NotImplementedError

    def stop(self) -> None:
        """Stop the watcher."""
        raise NotImplementedError

    def reindex(self, paths: Iterable[Path]) -> None:
        raise NotImplementedError(paths)

    @staticmethod
    def hash_file(path: Path) -> str:
        raise NotImplementedError(path)
