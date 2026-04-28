from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


@dataclass
class FileRecord:
    path: Path
    sha256: str
    mtime_ns: int
    language: str | None


class VectorStore:
    """SQLite + sqlite-vec wrapper.

    Owns three logical stores:
      - `files`: path -> hash, mtime, language (used to detect staleness)
      - `symbols`: parsed symbols + their embeddings
      - `sessions`: history, token usage, handoff summaries
    """

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS files (
        path        TEXT PRIMARY KEY,
        sha256      TEXT NOT NULL,
        mtime_ns    INTEGER NOT NULL,
        language    TEXT
    );
    CREATE TABLE IF NOT EXISTS symbols (
        id          INTEGER PRIMARY KEY,
        file        TEXT NOT NULL,
        name        TEXT NOT NULL,
        kind        TEXT NOT NULL,
        start_line  INTEGER NOT NULL,
        end_line    INTEGER NOT NULL,
        FOREIGN KEY (file) REFERENCES files(path) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS sessions (
        id          INTEGER PRIMARY KEY,
        started_at  TEXT NOT NULL,
        ended_at    TEXT,
        branch      TEXT NOT NULL,
        tokens_in   INTEGER NOT NULL DEFAULT 0,
        tokens_out  INTEGER NOT NULL DEFAULT 0,
        cost_usd    REAL NOT NULL DEFAULT 0.0,
        handoff     TEXT
    );
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            yield conn
            conn.commit()
        finally:
            conn.close()

    def initialize(self) -> None:
        """Create tables and load the sqlite-vec extension."""
        raise NotImplementedError

    def upsert_file(self, record: FileRecord) -> None:
        raise NotImplementedError(record)

    def query_similar(self, embedding: list[float], k: int = 10) -> list[int]:
        """Return the top-k symbol IDs nearest to `embedding`."""
        raise NotImplementedError(k)
