from __future__ import annotations

import sqlite3
import struct
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Optional


@dataclass
class FileRecord:
    path: Path
    sha256: str
    mtime_ns: int
    language: Optional[str]


@dataclass
class SymbolRecord:
    """One row of the `symbols` table."""

    id: int
    file: str  # path relative to project root, or absolute string
    name: str
    kind: str
    parent: Optional[str]
    start_line: int
    end_line: int
    body: str


def _serialize_vec(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


class VectorStore:
    """SQLite + sqlite-vec wrapper.

    Owns four logical stores:
      - `files`: path -> hash, mtime, language (used to detect staleness)
      - `symbols` + `vec_symbols`: parsed symbols + their embeddings
      - `imports`, `calls`: graph edges, scoped per file
      - `sessions`: history, token usage, handoff summaries
    """

    BASE_SCHEMA = """
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
        parent      TEXT,
        start_line  INTEGER NOT NULL,
        end_line    INTEGER NOT NULL,
        body        TEXT NOT NULL DEFAULT '',
        FOREIGN KEY (file) REFERENCES files(path) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_symbols_file ON symbols(file);
    CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(name);
    CREATE TABLE IF NOT EXISTS imports (
        file        TEXT NOT NULL,
        statement   TEXT NOT NULL,
        FOREIGN KEY (file) REFERENCES files(path) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_imports_file ON imports(file);
    CREATE TABLE IF NOT EXISTS calls (
        file        TEXT NOT NULL,
        caller      TEXT NOT NULL,
        callee      TEXT NOT NULL,
        FOREIGN KEY (file) REFERENCES files(path) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_calls_caller ON calls(caller);
    CREATE INDEX IF NOT EXISTS idx_calls_callee ON calls(callee);
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
    CREATE TABLE IF NOT EXISTS meta (
        key         TEXT PRIMARY KEY,
        value       TEXT NOT NULL
    );
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._dim: Optional[int] = None
        self._embedder_name: Optional[str] = None
        self._vec_loaded = False

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            self._load_vec_extension(conn)
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _load_vec_extension(self, conn: sqlite3.Connection) -> None:
        try:
            import sqlite_vec
        except ImportError:
            return
        try:
            conn.enable_load_extension(True)
            sqlite_vec.load(conn)
            conn.enable_load_extension(False)
            self._vec_loaded = True
        except sqlite3.OperationalError:
            self._vec_loaded = False

    def initialize(self, dim: int, embedder_name: str) -> None:
        """Create tables and the vec0 virtual table for `dim`-dimensional embeddings.

        If the existing vec table was created with a different dim or for a
        different embedder, it is dropped and recreated. Symbols persist; their
        vectors are simply re-embedded next time the indexer runs.
        """
        self._dim = dim
        self._embedder_name = embedder_name

        with self.connect() as conn:
            conn.executescript(self.BASE_SCHEMA)
            existing_dim = self._read_meta(conn, "embedder_dim")
            existing_name = self._read_meta(conn, "embedder_name")

            recreate = (
                existing_dim != str(dim)
                or existing_name != embedder_name
                or not self._vec_table_exists(conn)
            )

            if recreate:
                conn.execute("DROP TABLE IF EXISTS vec_symbols")
                if self._vec_loaded:
                    conn.execute(
                        f"CREATE VIRTUAL TABLE vec_symbols USING vec0(embedding float[{dim}])"
                    )
                self._write_meta(conn, "embedder_dim", str(dim))
                self._write_meta(conn, "embedder_name", embedder_name)

    @staticmethod
    def _read_meta(conn: sqlite3.Connection, key: str) -> Optional[str]:
        row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    @staticmethod
    def _write_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
        conn.execute(
            "INSERT INTO meta(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )

    @staticmethod
    def _vec_table_exists(conn: sqlite3.Connection) -> bool:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('table','virtual table') "
            "AND name='vec_symbols'"
        ).fetchone()
        return row is not None

    # ---- file CRUD --------------------------------------------------------

    def upsert_file(self, record: FileRecord) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO files(path, sha256, mtime_ns, language) VALUES(?, ?, ?, ?) "
                "ON CONFLICT(path) DO UPDATE SET "
                "sha256=excluded.sha256, mtime_ns=excluded.mtime_ns, language=excluded.language",
                (str(record.path), record.sha256, record.mtime_ns, record.language),
            )

    def get_file(self, path: str) -> Optional[FileRecord]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT path, sha256, mtime_ns, language FROM files WHERE path=?",
                (path,),
            ).fetchone()
        if row is None:
            return None
        return FileRecord(Path(row[0]), row[1], row[2], row[3])

    def delete_file(self, path: str) -> None:
        with self.connect() as conn:
            symbol_ids = [
                r[0] for r in conn.execute(
                    "SELECT id FROM symbols WHERE file=?", (path,)
                ).fetchall()
            ]
            conn.execute("DELETE FROM files WHERE path=?", (path,))
            self._delete_vectors(conn, symbol_ids)

    def list_files(self) -> list[FileRecord]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT path, sha256, mtime_ns, language FROM files"
            ).fetchall()
        return [FileRecord(Path(r[0]), r[1], r[2], r[3]) for r in rows]

    # ---- symbol + edge replace --------------------------------------------

    def replace_for_file(
        self,
        file_path: str,
        symbols: list[tuple[str, str, Optional[str], int, int, str]],
        symbol_embeddings: list[list[float]],
        imports: list[str],
        calls: list[tuple[str, str]],
    ) -> list[int]:
        """Atomic-ish replace of all artifacts derived from `file_path`.

        Each symbol tuple is (name, kind, parent, start_line, end_line, body).
        Returns the new symbol IDs in the order they were inserted.
        """
        if len(symbols) != len(symbol_embeddings):
            raise ValueError("symbols and embeddings length mismatch")

        with self.connect() as conn:
            old_ids = [
                r[0] for r in conn.execute(
                    "SELECT id FROM symbols WHERE file=?", (file_path,)
                ).fetchall()
            ]
            conn.execute("DELETE FROM symbols WHERE file=?", (file_path,))
            conn.execute("DELETE FROM imports WHERE file=?", (file_path,))
            conn.execute("DELETE FROM calls WHERE file=?", (file_path,))
            self._delete_vectors(conn, old_ids)

            new_ids: list[int] = []
            for (name, kind, parent, start, end, body), vec in zip(
                symbols, symbol_embeddings
            ):
                cur = conn.execute(
                    "INSERT INTO symbols(file, name, kind, parent, start_line, end_line, body) "
                    "VALUES(?, ?, ?, ?, ?, ?, ?)",
                    (file_path, name, kind, parent, start, end, body),
                )
                sid = int(cur.lastrowid)
                new_ids.append(sid)
                if self._vec_loaded and vec:
                    conn.execute(
                        "INSERT INTO vec_symbols(rowid, embedding) VALUES(?, ?)",
                        (sid, _serialize_vec(vec)),
                    )

            conn.executemany(
                "INSERT INTO imports(file, statement) VALUES(?, ?)",
                [(file_path, stmt) for stmt in imports],
            )
            conn.executemany(
                "INSERT INTO calls(file, caller, callee) VALUES(?, ?, ?)",
                [(file_path, c[0], c[1]) for c in calls],
            )
            return new_ids

    def _delete_vectors(self, conn: sqlite3.Connection, ids: Iterable[int]) -> None:
        ids = list(ids)
        if not ids or not self._vec_loaded:
            return
        if not self._vec_table_exists(conn):
            return
        placeholders = ",".join("?" for _ in ids)
        conn.execute(f"DELETE FROM vec_symbols WHERE rowid IN ({placeholders})", ids)

    # ---- queries ----------------------------------------------------------

    def get_symbols(self, ids: Iterable[int]) -> list[SymbolRecord]:
        ids = list(ids)
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT id, file, name, kind, parent, start_line, end_line, body "
                f"FROM symbols WHERE id IN ({placeholders})",
                ids,
            ).fetchall()
        order = {sid: i for i, sid in enumerate(ids)}
        records = [
            SymbolRecord(
                id=row[0],
                file=row[1],
                name=row[2],
                kind=row[3],
                parent=row[4],
                start_line=row[5],
                end_line=row[6],
                body=row[7],
            )
            for row in rows
        ]
        records.sort(key=lambda r: order.get(r.id, len(order)))
        return records

    def get_symbols_by_name(self, name: str) -> list[SymbolRecord]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT id, file, name, kind, parent, start_line, end_line, body "
                "FROM symbols WHERE name=?",
                (name,),
            ).fetchall()
        return [
            SymbolRecord(*row) for row in rows
        ]

    def all_calls(self) -> list[tuple[str, str, str]]:
        with self.connect() as conn:
            return list(conn.execute("SELECT file, caller, callee FROM calls").fetchall())

    def all_imports(self) -> list[tuple[str, str]]:
        with self.connect() as conn:
            return list(conn.execute("SELECT file, statement FROM imports").fetchall())

    def query_similar(self, embedding: list[float], k: int = 10) -> list[tuple[int, float]]:
        """Top-k symbol IDs nearest to `embedding`. Returns (id, distance) pairs."""
        if not self._vec_loaded or self._dim is None:
            return []
        with self.connect() as conn:
            if not self._vec_table_exists(conn):
                return []
            rows = conn.execute(
                "SELECT rowid, distance FROM vec_symbols "
                "WHERE embedding MATCH ? AND k = ? ORDER BY distance",
                (_serialize_vec(embedding), int(k)),
            ).fetchall()
        return [(int(r[0]), float(r[1])) for r in rows]

    def stats(self) -> dict[str, int]:
        with self.connect() as conn:
            files = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
            symbols = conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0]
            calls = conn.execute("SELECT COUNT(*) FROM calls").fetchone()[0]
            imports = conn.execute("SELECT COUNT(*) FROM imports").fetchone()[0]
        return {
            "files": int(files),
            "symbols": int(symbols),
            "calls": int(calls),
            "imports": int(imports),
        }
