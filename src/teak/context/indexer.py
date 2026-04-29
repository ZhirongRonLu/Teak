from __future__ import annotations

import hashlib
import threading
import time
from pathlib import Path
from typing import Iterable, Optional

from teak.brain.bootstrapper import _SKIP_DIR_NAMES
from teak.config import TeakConfig
from teak.context.embedder import Embedder, choose_embedder
from teak.context.parser import language_for, parse_file
from teak.context.storage import FileRecord, VectorStore


class Indexer:
    """Incremental, watchdog-driven indexer.

    Responsibilities:
      - Walk the project once on `bootstrap()` and populate the store.
      - Subscribe to filesystem events and re-index only changed files.
      - Compare file hashes against the store to skip no-op updates.
      - Run in a background thread; never block the UI.
    """

    def __init__(
        self,
        config: TeakConfig,
        store: VectorStore,
        embedder: Optional[Embedder] = None,
    ) -> None:
        self.config = config
        self.store = store
        self.embedder: Embedder = embedder or choose_embedder()
        self._observer = None
        self._initialized = False

    # ---- one-time setup ---------------------------------------------------

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        self.store.initialize(dim=self.embedder.dim, embedder_name=self.embedder.name)
        self._initialized = True

    # ---- filesystem walk --------------------------------------------------

    def _iter_source_files(self) -> Iterable[Path]:
        root = self.config.project_root
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            rel_parts = path.relative_to(root).parts
            if any(part in _SKIP_DIR_NAMES for part in rel_parts[:-1]):
                continue
            if language_for(path) is None:
                continue
            yield path

    def bootstrap(self) -> dict[str, int]:
        """Walk the project once and ensure the store is current.

        Returns a small report: {"indexed": int, "skipped": int, "removed": int}.
        """
        self._ensure_initialized()

        seen: set[str] = set()
        indexed = 0
        skipped = 0

        for path in self._iter_source_files():
            rel = self._rel(path)
            seen.add(rel)
            if self._is_unchanged(path, rel):
                skipped += 1
                continue
            self._index_one(path)
            indexed += 1

        # Drop stale records for files that disappeared.
        removed = 0
        for record in self.store.list_files():
            rel = str(record.path)
            if rel not in seen:
                self.store.delete_file(rel)
                removed += 1

        return {"indexed": indexed, "skipped": skipped, "removed": removed}

    def reindex(self, paths: Iterable[Path]) -> dict[str, int]:
        """Re-index a specific set of paths (after a watcher event)."""
        self._ensure_initialized()
        indexed = 0
        skipped = 0
        removed = 0
        for path in paths:
            if not path.is_file():
                rel = self._rel(path)
                if self.store.get_file(rel) is not None:
                    self.store.delete_file(rel)
                    removed += 1
                continue
            if language_for(path) is None:
                continue
            rel = self._rel(path)
            if self._is_unchanged(path, rel):
                skipped += 1
                continue
            self._index_one(path)
            indexed += 1
        return {"indexed": indexed, "skipped": skipped, "removed": removed}

    # ---- core ops ---------------------------------------------------------

    def _index_one(self, path: Path) -> None:
        rel = self._rel(path)
        sha = self.hash_file(path)
        try:
            mtime_ns = path.stat().st_mtime_ns
        except OSError:
            mtime_ns = 0

        parse = parse_file(path)
        bodies = [s.body or s.name for s in parse.symbols]
        embeddings = self.embedder.embed(bodies) if bodies else []

        self.store.upsert_file(
            FileRecord(
                path=Path(rel),
                sha256=sha,
                mtime_ns=mtime_ns,
                language=parse.language or language_for(path),
            )
        )
        symbol_rows = [
            (s.name, s.kind, s.parent, s.start_line, s.end_line, s.body)
            for s in parse.symbols
        ]
        self.store.replace_for_file(
            file_path=rel,
            symbols=symbol_rows,
            symbol_embeddings=embeddings,
            imports=parse.imports,
            calls=parse.calls,
        )

    def _is_unchanged(self, path: Path, rel: str) -> bool:
        existing = self.store.get_file(rel)
        if existing is None:
            return False
        return existing.sha256 == self.hash_file(path)

    def _rel(self, path: Path) -> str:
        try:
            return str(path.resolve().relative_to(self.config.project_root.resolve()))
        except ValueError:
            return str(path)

    @staticmethod
    def hash_file(path: Path) -> str:
        h = hashlib.sha256()
        try:
            with path.open("rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    h.update(chunk)
        except OSError:
            return ""
        return h.hexdigest()

    # ---- watchdog ---------------------------------------------------------

    def start(self, debounce_seconds: float = 0.5) -> None:
        """Begin watching the project for file changes (background thread)."""
        if self._observer is not None:
            return
        try:
            from watchdog.events import FileSystemEventHandler
            from watchdog.observers import Observer
        except ImportError:
            return

        pending: set[Path] = set()
        lock = threading.Lock()
        last_event = [time.monotonic()]

        indexer = self

        class _Handler(FileSystemEventHandler):
            def on_any_event(self, event) -> None:  # type: ignore[override]
                if event.is_directory:
                    return
                p = Path(getattr(event, "src_path", "")).resolve()
                if not p:
                    return
                rel_parts = p.relative_to(indexer.config.project_root.resolve()).parts \
                    if p.is_relative_to(indexer.config.project_root.resolve()) else p.parts
                if any(part in _SKIP_DIR_NAMES for part in rel_parts[:-1]):
                    return
                if language_for(p) is None:
                    return
                with lock:
                    pending.add(p)
                    last_event[0] = time.monotonic()

        observer = Observer()
        observer.schedule(_Handler(), str(self.config.project_root), recursive=True)
        observer.daemon = True
        observer.start()
        self._observer = observer

        stop = threading.Event()

        def _flusher() -> None:
            while not stop.is_set():
                time.sleep(debounce_seconds / 2)
                with lock:
                    quiet = (time.monotonic() - last_event[0]) >= debounce_seconds
                    if pending and quiet:
                        batch = list(pending)
                        pending.clear()
                    else:
                        batch = []
                if batch:
                    try:
                        self.reindex(batch)
                    except Exception:
                        pass

        flusher = threading.Thread(target=_flusher, name="teak-indexer", daemon=True)
        flusher.start()
        self._stop_event = stop
        self._flusher = flusher

    def stop(self) -> None:
        if self._observer is None:
            return
        self._observer.stop()
        self._observer.join(timeout=2)
        self._observer = None
        if hasattr(self, "_stop_event"):
            self._stop_event.set()
