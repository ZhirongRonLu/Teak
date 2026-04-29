from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from teak.config import TeakConfig
from teak.context.embedder import HashEmbedder
from teak.context.graph import KnowledgeGraph, Symbol, load_graph_from_store
from teak.context.indexer import Indexer
from teak.context.parser import language_for, parse_file
from teak.context.rag import SubgraphRAG
from teak.context.storage import FileRecord, VectorStore


# ----------------------------- parser ---------------------------------------


def _write(path: Path, body: str) -> Path:
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return path


def test_language_for_known_extensions(tmp_path: Path) -> None:
    assert language_for(tmp_path / "a.py") == "python"
    assert language_for(tmp_path / "a.ts") == "typescript"
    assert language_for(tmp_path / "a.tsx") == "tsx"
    assert language_for(tmp_path / "a.js") == "javascript"
    assert language_for(tmp_path / "a.rs") == "rust"
    assert language_for(tmp_path / "a.go") == "go"
    assert language_for(tmp_path / "a.txt") is None


def test_parse_python_extracts_functions_classes_methods(tmp_path: Path) -> None:
    src = _write(
        tmp_path / "app.py",
        """
        import os
        from pathlib import Path

        def top_level(x):
            return helper(x)

        def helper(y):
            return y + 1

        class Thing:
            def method_a(self):
                return helper(1)
            def method_b(self):
                pass
        """,
    )

    fp = parse_file(src)
    names = {(s.name, s.kind, s.parent) for s in fp.symbols}

    assert ("top_level", "function", None) in names
    assert ("helper", "function", None) in names
    assert ("Thing", "class", None) in names
    assert ("method_a", "method", "Thing") in names
    assert ("method_b", "method", "Thing") in names

    assert "import os" in fp.imports
    assert any("from pathlib" in stmt for stmt in fp.imports)

    callers = {c[0] for c in fp.calls}
    callees = {c[1] for c in fp.calls}
    assert "top_level" in callers
    assert "helper" in callees


def test_parse_unsupported_returns_empty(tmp_path: Path) -> None:
    fp = parse_file(_write(tmp_path / "notes.txt", "just text\n"))
    assert fp.symbols == []
    assert fp.language == ""


# ----------------------------- storage --------------------------------------


def test_storage_initialize_creates_tables(tmp_path: Path) -> None:
    store = VectorStore(tmp_path / "x.db")
    store.initialize(dim=4, embedder_name="t")
    with store.connect() as conn:
        names = {
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','virtual table')"
            ).fetchall()
        }
    for required in ("files", "symbols", "imports", "calls", "sessions", "meta"):
        assert required in names


def test_storage_replace_for_file_and_query_similar(tmp_path: Path) -> None:
    store = VectorStore(tmp_path / "x.db")
    store.initialize(dim=4, embedder_name="t")

    store.upsert_file(FileRecord(Path("a.py"), "abc", 1, "python"))
    ids = store.replace_for_file(
        "a.py",
        symbols=[
            ("foo", "function", None, 1, 3, "def foo(): pass"),
            ("bar", "function", None, 5, 7, "def bar(): foo()"),
        ],
        symbol_embeddings=[[1.0, 0.0, 0.0, 0.0], [0.9, 0.1, 0.0, 0.0]],
        imports=["import os"],
        calls=[("bar", "foo")],
    )
    assert len(ids) == 2

    closest = store.query_similar([1.0, 0.0, 0.0, 0.0], k=2)
    assert closest[0][0] == ids[0]  # foo is the literal match
    assert {pair[0] for pair in closest} == set(ids)

    assert store.stats() == {"files": 1, "symbols": 2, "calls": 1, "imports": 1}


def test_storage_replace_clears_old_rows(tmp_path: Path) -> None:
    store = VectorStore(tmp_path / "x.db")
    store.initialize(dim=4, embedder_name="t")

    store.upsert_file(FileRecord(Path("a.py"), "abc", 1, "python"))
    store.replace_for_file(
        "a.py",
        symbols=[("foo", "function", None, 1, 1, "def foo(): pass")],
        symbol_embeddings=[[1.0, 0.0, 0.0, 0.0]],
        imports=["import os"],
        calls=[("foo", "bar")],
    )
    store.replace_for_file(
        "a.py",
        symbols=[("foo2", "function", None, 1, 1, "def foo2(): pass")],
        symbol_embeddings=[[0.0, 1.0, 0.0, 0.0]],
        imports=[],
        calls=[],
    )
    stats = store.stats()
    assert stats["symbols"] == 1
    assert stats["imports"] == 0
    assert stats["calls"] == 0


def test_storage_dim_change_drops_vec_table(tmp_path: Path) -> None:
    store = VectorStore(tmp_path / "x.db")
    store.initialize(dim=4, embedder_name="emb-a")
    store.upsert_file(FileRecord(Path("a.py"), "abc", 1, "python"))
    store.replace_for_file(
        "a.py",
        symbols=[("foo", "function", None, 1, 1, "def foo(): pass")],
        symbol_embeddings=[[1.0, 0.0, 0.0, 0.0]],
        imports=[],
        calls=[],
    )
    # Switch to a different embedder/dim — vec table should be recreated; the
    # symbols table still has the row but vector lookup returns nothing until
    # re-embedded.
    store2 = VectorStore(tmp_path / "x.db")
    store2.initialize(dim=8, embedder_name="emb-b")
    assert store2.query_similar([0.0] * 8, k=5) == []
    assert store2.stats()["symbols"] == 1


# ----------------------------- knowledge graph ------------------------------


def test_graph_neighbors_bidirectional() -> None:
    g = KnowledgeGraph()
    g.add_symbol(Symbol("a", "function", Path("a.py"), 1, 2))
    g.add_symbol(Symbol("b", "function", Path("a.py"), 3, 4))
    g.add_symbol(Symbol("c", "function", Path("a.py"), 5, 6))
    g.add_call("a", "b")
    g.add_call("b", "c")

    assert g.neighbors("a", depth=1) == {"b"}
    assert g.neighbors("a", depth=2) == {"b", "c"}
    assert g.neighbors("c", depth=2) == {"b", "a"}  # reverse edges count


def test_subgraph_for_query_respects_budget() -> None:
    g = KnowledgeGraph()
    for n in "abcdef":
        g.add_symbol(Symbol(n, "function", Path("a.py"), 1, 1))
    for c in "bcdef":
        g.add_call("a", c)

    sub = g.subgraph_for_query(["a"], token_budget=10, chars_per_token=4)
    # token_budget=10 → char_budget=40. Each symbol body ~40 chars.
    assert "a" in sub.symbols
    assert len(sub.symbols) <= 2


def test_load_graph_from_store(tmp_path: Path) -> None:
    store = VectorStore(tmp_path / "x.db")
    store.initialize(dim=4, embedder_name="t")
    store.upsert_file(FileRecord(Path("a.py"), "abc", 1, "python"))
    store.replace_for_file(
        "a.py",
        symbols=[
            ("foo", "function", None, 1, 1, ""),
            ("bar", "function", None, 2, 2, ""),
        ],
        symbol_embeddings=[[1, 0, 0, 0], [0, 1, 0, 0]],
        imports=["import os"],
        calls=[("foo", "bar")],
    )

    g = load_graph_from_store(store)
    assert {"foo", "bar"} <= g.symbols.keys()
    assert "bar" in g.calls.get("foo", set())
    assert g.imports[Path("a.py")] == {"import os"}


# ----------------------------- indexer --------------------------------------


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "proj"
    project.mkdir()
    _write(
        project / "auth.py",
        """
        def login(user, password):
            token = hash_password(password)
            return token

        def hash_password(p):
            return p[::-1]
        """,
    )
    _write(project / "unrelated.py", "def cook_dinner():\n    return 'pasta'\n")
    return project


def test_indexer_bootstrap_then_skip(tmp_path: Path) -> None:
    project = _project(tmp_path)
    cfg = TeakConfig.for_project(project)
    store = VectorStore(cfg.db_path)
    indexer = Indexer(cfg, store, embedder=HashEmbedder())

    first = indexer.bootstrap()
    assert first["indexed"] == 2
    assert first["skipped"] == 0

    second = indexer.bootstrap()
    assert second["indexed"] == 0
    assert second["skipped"] == 2


def test_indexer_reindex_after_change(tmp_path: Path) -> None:
    project = _project(tmp_path)
    cfg = TeakConfig.for_project(project)
    store = VectorStore(cfg.db_path)
    indexer = Indexer(cfg, store, embedder=HashEmbedder())
    indexer.bootstrap()

    (project / "auth.py").write_text("def changed():\n    return 1\n", encoding="utf-8")
    report = indexer.reindex([project / "auth.py"])
    assert report["indexed"] == 1

    stats = store.stats()
    assert stats["files"] == 2
    # auth.py now has just one function
    assert stats["symbols"] == 2  # changed() + cook_dinner()


def test_indexer_skips_vendored_dirs(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    (project / "node_modules" / "pkg").mkdir(parents=True)
    (project / "node_modules" / "pkg" / "index.js").write_text("function x(){}", encoding="utf-8")
    (project / "src").mkdir()
    (project / "src" / "main.py").write_text("def keep(): pass\n", encoding="utf-8")

    cfg = TeakConfig.for_project(project)
    store = VectorStore(cfg.db_path)
    Indexer(cfg, store, embedder=HashEmbedder()).bootstrap()

    files = {str(r.path) for r in store.list_files()}
    assert files == {"src/main.py"}


# ----------------------------- RAG ------------------------------------------


def test_rag_retrieves_indexed_symbols(tmp_path: Path) -> None:
    project = _project(tmp_path)
    cfg = TeakConfig.for_project(project)
    store = VectorStore(cfg.db_path)
    embedder = HashEmbedder()
    Indexer(cfg, store, embedder=embedder).bootstrap()

    rag = SubgraphRAG(store, embedder)
    ctx = rag.retrieve("how does login work", token_budget=400)

    assert "login" in ctx.symbols
    assert any("def login" in snippet for snippet in ctx.snippets)
    assert ctx.estimated_tokens <= 400


def test_rag_returns_empty_when_index_empty(tmp_path: Path) -> None:
    cfg = TeakConfig.for_project(tmp_path)
    store = VectorStore(cfg.db_path)
    store.initialize(dim=HashEmbedder().dim, embedder_name=HashEmbedder().name)

    rag = SubgraphRAG(store, HashEmbedder())
    ctx = rag.retrieve("anything", token_budget=400)
    assert ctx.snippets == []


def test_rag_zero_budget_is_noop(tmp_path: Path) -> None:
    project = _project(tmp_path)
    cfg = TeakConfig.for_project(project)
    store = VectorStore(cfg.db_path)
    embedder = HashEmbedder()
    Indexer(cfg, store, embedder=embedder).bootstrap()

    ctx = SubgraphRAG(store, embedder).retrieve("query", token_budget=0)
    assert ctx.snippets == []


# ----------------------------- embedder -------------------------------------


def test_hash_embedder_deterministic_and_normalized() -> None:
    e = HashEmbedder(dim=64)
    a = e.embed(["hello world"])
    b = e.embed(["hello world"])
    assert a == b

    norm = sum(v * v for v in a[0]) ** 0.5
    assert pytest.approx(norm, rel=1e-6) == 1.0
