import pytest
import tempfile
from pathlib import Path
from codetree.graph.store import GraphStore
from codetree.graph.models import SymbolNode, Edge


@pytest.fixture
def store():
    with tempfile.TemporaryDirectory() as tmp:
        s = GraphStore(tmp)
        s.open()
        yield s
        s.close()


class TestGraphStoreSchema:
    def test_creates_database_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = GraphStore(tmp)
            s.open()
            assert (Path(tmp) / ".codetree" / "graph.db").exists()
            s.close()

    def test_schema_version_stored(self, store):
        val = store.get_meta("schema_version")
        assert val == "1"

    def test_idempotent_open(self, store):
        # Opening twice should not fail
        store.close()
        store.open()
        assert store.get_meta("schema_version") == "1"


class TestSymbolCRUD:
    def test_upsert_and_get_symbol(self, store):
        sym = SymbolNode(
            qualified_name="calc.py::Calculator",
            name="Calculator",
            kind="class",
            file_path="calc.py",
            start_line=1,
            end_line=20,
        )
        store.upsert_symbol(sym)
        result = store.get_symbol("calc.py::Calculator")
        assert result is not None
        assert result.name == "Calculator"
        assert result.kind == "class"
        assert result.start_line == 1

    def test_upsert_overwrites(self, store):
        sym = SymbolNode(
            qualified_name="calc.py::add",
            name="add",
            kind="function",
            file_path="calc.py",
            start_line=1,
        )
        store.upsert_symbol(sym)
        sym.start_line = 10
        store.upsert_symbol(sym)
        result = store.get_symbol("calc.py::add")
        assert result.start_line == 10

    def test_get_missing_symbol(self, store):
        assert store.get_symbol("nonexistent") is None

    def test_symbols_by_name(self, store):
        store.upsert_symbol(SymbolNode("a.py::add", "add", "function", "a.py", 1))
        store.upsert_symbol(SymbolNode("b.py::add", "add", "function", "b.py", 5))
        store.upsert_symbol(SymbolNode("c.py::sub", "sub", "function", "c.py", 1))
        results = store.symbols_by_name("add")
        assert len(results) == 2
        assert {r.file_path for r in results} == {"a.py", "b.py"}

    def test_symbols_by_file(self, store):
        store.upsert_symbol(SymbolNode("a.py::Foo", "Foo", "class", "a.py", 1))
        store.upsert_symbol(SymbolNode("a.py::bar", "bar", "function", "a.py", 10))
        store.upsert_symbol(SymbolNode("b.py::baz", "baz", "function", "b.py", 1))
        results = store.symbols_by_file("a.py")
        assert len(results) == 2

    def test_delete_symbols_for_file(self, store):
        store.upsert_symbol(SymbolNode("a.py::Foo", "Foo", "class", "a.py", 1))
        store.upsert_symbol(SymbolNode("b.py::Bar", "Bar", "class", "b.py", 1))
        store.delete_symbols_for_file("a.py")
        assert store.get_symbol("a.py::Foo") is None
        assert store.get_symbol("b.py::Bar") is not None


class TestEdgeCRUD:
    def test_upsert_and_get_edges(self, store):
        store.upsert_edge(Edge("a.py::foo", "b.py::bar", "CALLS"))
        edges = store.edges_from("a.py::foo")
        assert len(edges) == 1
        assert edges[0].target_qn == "b.py::bar"
        assert edges[0].type == "CALLS"

    def test_edges_to(self, store):
        store.upsert_edge(Edge("a.py::foo", "b.py::bar", "CALLS"))
        store.upsert_edge(Edge("c.py::baz", "b.py::bar", "CALLS"))
        edges = store.edges_to("b.py::bar")
        assert len(edges) == 2

    def test_edges_filtered_by_type(self, store):
        store.upsert_edge(Edge("a.py::foo", "b.py::bar", "CALLS"))
        store.upsert_edge(Edge("a.py::foo", "b.py::bar", "IMPORTS"))
        assert len(store.edges_from("a.py::foo", edge_type="CALLS")) == 1
        assert len(store.edges_from("a.py::foo")) == 2

    def test_delete_edges_for_file(self, store):
        store.upsert_edge(Edge("a.py::foo", "b.py::bar", "CALLS"))
        store.upsert_edge(Edge("c.py::baz", "d.py::qux", "CALLS"))
        store.delete_edges_for_file("a.py")
        assert len(store.edges_from("a.py::foo")) == 0
        assert len(store.edges_from("c.py::baz")) == 1

    def test_delete_edges_for_file_removes_incoming_edges(self, store):
        store.upsert_edge(Edge("b.py::caller", "a.py::foo", "CALLS"))
        store.delete_edges_for_file("a.py")
        assert store.edges_to("a.py::foo") == []

    def test_delete_edges_for_file_is_exact_not_like_pattern(self, store):
        # '_' is a LIKE wildcard and LIKE folds ASCII case — neither may leak.
        store.upsert_edge(Edge("my_file.py::foo", "x.py::bar", "CALLS"))
        store.upsert_edge(Edge("myXfile.py::foo", "x.py::bar", "CALLS"))
        store.upsert_edge(Edge("My_File.py::foo", "x.py::bar", "CALLS"))
        store.upsert_edge(Edge("my_file.py.bak::foo", "x.py::bar", "CALLS"))
        store.delete_edges_for_file("my_file.py")
        assert store.edges_from("my_file.py::foo") == []
        assert len(store.edges_from("myXfile.py::foo")) == 1
        assert len(store.edges_from("My_File.py::foo")) == 1
        assert len(store.edges_from("my_file.py.bak::foo")) == 1


class TestTransactions:
    def test_rollback_discards_uncommitted_writes(self, store):
        store.upsert_edge(Edge("kept.py::a", "x.py::b", "CALLS"))
        store.begin()
        store.upsert_edge(Edge("dropped.py::a", "x.py::b", "CALLS"))
        store.rollback()
        assert len(store.edges_from("kept.py::a")) == 1
        assert store.edges_from("dropped.py::a") == []
        assert store._in_transaction is False


class TestFileCRUD:
    def test_upsert_and_get_file(self, store):
        store.upsert_file("calc.py", sha256="abc123", language="py", is_test=False)
        result = store.get_file("calc.py")
        assert result is not None
        assert result["sha256"] == "abc123"

    def test_get_missing_file(self, store):
        assert store.get_file("nope.py") is None

    def test_delete_file(self, store):
        store.upsert_file("calc.py", sha256="abc", language="py", is_test=False)
        store.delete_file("calc.py")
        assert store.get_file("calc.py") is None

    def test_all_files(self, store):
        store.upsert_file("a.py", sha256="a", language="py", is_test=False)
        store.upsert_file("b.py", sha256="b", language="py", is_test=True)
        files = store.all_files()
        assert len(files) == 2


class TestMeta:
    def test_set_and_get_meta(self, store):
        store.set_meta("tool_version", "0.2.0")
        assert store.get_meta("tool_version") == "0.2.0"

    def test_get_missing_meta(self, store):
        assert store.get_meta("nonexistent") is None


class TestStats:
    def test_stats(self, store):
        store.upsert_symbol(SymbolNode("a.py::foo", "foo", "function", "a.py", 1))
        store.upsert_symbol(SymbolNode("a.py::bar", "bar", "function", "a.py", 5))
        store.upsert_edge(Edge("a.py::foo", "a.py::bar", "CALLS"))
        store.upsert_file("a.py", sha256="x", language="py", is_test=False)
        stats = store.stats()
        assert stats["files"] == 1
        assert stats["symbols"] == 2
        assert stats["edges"] == 1


class TestBatchWrites:
    def test_upsert_edges_last_duplicate_wins_like_row_by_row(self, store):
        store.upsert_edges([
            Edge("a.py::f", "b.py::g", "CALLS", weight=0.5),
            Edge("a.py::f", "b.py::g", "CALLS", weight=1.0),
        ])
        assert [e.weight for e in store.edges_from("a.py::f")] == [1.0]

    def test_batches_larger_than_one_statement(self, store):
        syms = [SymbolNode(f"m.py::f{i}", f"f{i}", "function", "m.py", i + 1, None) for i in range(500)]
        edges = [Edge(f"m.py::f{i}", f"m.py::f{i + 1}", "CALLS") for i in range(499)]
        store.upsert_symbols(syms)
        store.upsert_edges(edges)
        assert store.stats()["symbols"] == 500
        assert store.stats()["edges"] == 499

    def test_symbols_by_name_map_matches_symbols_by_name(self, store):
        store.upsert_symbols([
            SymbolNode("b.py::add", "add", "function", "b.py", 1, None),
            SymbolNode("a.py::add", "add", "function", "a.py", 3, None),
            SymbolNode("a.py::sub", "sub", "function", "a.py", 5, None),
        ])
        by_name = store.symbols_by_name_map()
        for name in ("add", "sub"):
            assert [s.qualified_name for s in by_name[name]] == [
                s.qualified_name for s in store.symbols_by_name(name)
            ]

    def test_empty_batches_are_noops(self, store):
        store.upsert_symbols([])
        store.upsert_edges([])
        store.upsert_files([])
        assert store.stats() == {"files": 0, "symbols": 0, "edges": 0}
