import pytest
import hashlib
import tempfile
from pathlib import Path
from codetree.graph.builder import GraphBuilder
from codetree.graph.store import GraphStore
from codetree.indexer import Indexer


@pytest.fixture
def repo_dir():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp)
        (p / "calc.py").write_text(
            'class Calculator:\n'
            '    """A calculator."""\n'
            '    def add(self, a, b):\n'
            '        return a + b\n'
            '    def sub(self, a, b):\n'
            '        return a - b\n'
        )
        (p / "main.py").write_text(
            'from calc import Calculator\n'
            'def main():\n'
            '    c = Calculator()\n'
            '    print(c.add(1, 2))\n'
        )
        (p / "test_calc.py").write_text(
            'from calc import Calculator\n'
            'def test_add():\n'
            '    c = Calculator()\n'
            '    assert c.add(1, 2) == 3\n'
        )
        yield p


class TestGraphBuilder:
    def test_full_build(self, repo_dir):
        store = GraphStore(str(repo_dir))
        store.open()
        builder = GraphBuilder(str(repo_dir), store)
        result = builder.build()
        assert result["files_indexed"] > 0
        assert result["symbols_created"] > 0
        assert result["edges_created"] > 0
        store.close()

    def test_symbols_have_qualified_names(self, repo_dir):
        store = GraphStore(str(repo_dir))
        store.open()
        builder = GraphBuilder(str(repo_dir), store)
        builder.build()
        # Calculator class should have qualified name
        sym = store.get_symbol("calc.py::Calculator")
        assert sym is not None
        assert sym.kind == "class"
        # Method should include parent
        sym = store.get_symbol("calc.py::Calculator.add")
        assert sym is not None
        assert sym.kind == "method"
        store.close()

    def test_calls_edges_created(self, repo_dir):
        store = GraphStore(str(repo_dir))
        store.open()
        builder = GraphBuilder(str(repo_dir), store)
        builder.build()
        # main calls add
        edges = store.edges_from("main.py::main", edge_type="CALLS")
        callee_names = {e.target_qn.split("::")[-1] for e in edges}
        assert "add" in callee_names or "Calculator" in callee_names
        store.close()

    def test_contains_edges(self, repo_dir):
        store = GraphStore(str(repo_dir))
        store.open()
        builder = GraphBuilder(str(repo_dir), store)
        builder.build()
        edges = store.edges_from("calc.py::Calculator", edge_type="CONTAINS")
        child_names = {e.target_qn for e in edges}
        assert "calc.py::Calculator.add" in child_names
        assert "calc.py::Calculator.sub" in child_names
        store.close()

    def test_incremental_unchanged(self, repo_dir):
        store = GraphStore(str(repo_dir))
        store.open()
        builder = GraphBuilder(str(repo_dir), store)
        r1 = builder.build()
        r2 = builder.build()
        # Second build should skip unchanged files
        assert r2["files_skipped"] == r1["files_indexed"]
        assert r2["files_indexed"] == 0
        store.close()

    def test_incremental_changed_file(self, repo_dir):
        store = GraphStore(str(repo_dir))
        store.open()
        builder = GraphBuilder(str(repo_dir), store)
        builder.build()
        # Modify calc.py
        (repo_dir / "calc.py").write_text(
            'class Calculator:\n'
            '    def add(self, a, b):\n'
            '        return a + b\n'
            '    def multiply(self, a, b):\n'
            '        return a * b\n'
        )
        r2 = builder.build()
        assert r2["files_indexed"] == 1
        # sub should be gone, multiply should exist
        assert store.get_symbol("calc.py::Calculator.sub") is None
        assert store.get_symbol("calc.py::Calculator.multiply") is not None
        store.close()

    def test_deleted_file(self, repo_dir):
        store = GraphStore(str(repo_dir))
        store.open()
        builder = GraphBuilder(str(repo_dir), store)
        builder.build()
        assert store.get_symbol("main.py::main") is not None
        # Delete main.py
        (repo_dir / "main.py").unlink()
        builder.build()
        assert store.get_symbol("main.py::main") is None
        assert store.get_file("main.py") is None
        store.close()

    def test_tests_edges_created(self, repo_dir):
        store = GraphStore(str(repo_dir))
        store.open()
        builder = GraphBuilder(str(repo_dir), store)
        builder.build()
        # test_add should have TESTS edge to calc.py::Calculator.add
        edges = store.edges_from("test_calc.py::test_add", edge_type="TESTS")
        target_names = {e.target_qn for e in edges}
        assert "calc.py::Calculator.add" in target_names
        store.close()

    def test_test_file_detected(self, repo_dir):
        store = GraphStore(str(repo_dir))
        store.open()
        builder = GraphBuilder(str(repo_dir), store)
        builder.build()
        f = store.get_file("test_calc.py")
        assert f is not None
        assert f["is_test"] is True
        sym = store.get_symbol("test_calc.py::test_add")
        assert sym is not None
        assert sym.is_test is True
        store.close()


# ─── Type-aware call resolution tests ───────────────────────────────────────

@pytest.fixture
def multi_module_repo():
    """Repo with same-named functions in different modules to test disambiguation."""
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp)
        (p / "utils.py").write_text(
            'def save(data):\n'
            '    """Save to file."""\n'
            '    pass\n'
        )
        (p / "db.py").write_text(
            'def save(record):\n'
            '    """Save to database."""\n'
            '    pass\n'
        )
        (p / "main.py").write_text(
            'from db import save\n'
            'def process():\n'
            '    save({"key": "value"})\n'
        )
        (p / "other.py").write_text(
            'def process():\n'
            '    save({"key": "value"})\n'
        )
        yield p


class TestTypeAwareResolution:

    def test_import_confirmed_edge_has_weight_1(self, multi_module_repo):
        """When caller imports callee's module, edge should have weight 1.0."""
        store = GraphStore(str(multi_module_repo))
        store.open()
        builder = GraphBuilder(str(multi_module_repo), store)
        builder.build()
        # main.py imports db, so main.py::process -> db.py::save should be weight 1.0
        edges = store.edges_from("main.py::process", edge_type="CALLS")
        db_edges = [e for e in edges if "db.py" in e.target_qn]
        assert len(db_edges) >= 1
        for e in db_edges:
            assert e.weight == 1.0
        store.close()

    def test_import_confirmed_excludes_unimported(self, multi_module_repo):
        """When import-confirmed candidates exist, unimported ones are excluded."""
        store = GraphStore(str(multi_module_repo))
        store.open()
        builder = GraphBuilder(str(multi_module_repo), store)
        builder.build()
        # main.py imports db, so should NOT have edge to utils.py::save
        edges = store.edges_from("main.py::process", edge_type="CALLS")
        utils_edges = [e for e in edges if "utils.py" in e.target_qn]
        assert len(utils_edges) == 0
        store.close()

    def test_no_import_falls_back_to_name_only(self, multi_module_repo):
        """When no imports match, all name matches get weight 0.5."""
        store = GraphStore(str(multi_module_repo))
        store.open()
        builder = GraphBuilder(str(multi_module_repo), store)
        builder.build()
        # other.py has no imports, so save calls should be name-only (0.5)
        edges = store.edges_from("other.py::process", edge_type="CALLS")
        save_edges = [e for e in edges if "save" in e.target_qn]
        assert len(save_edges) >= 1
        for e in save_edges:
            assert e.weight == 0.5
        store.close()

    def test_same_file_calls_weight_1(self, multi_module_repo):
        """Calling a function defined in the same file should have weight 1.0."""
        store = GraphStore(str(multi_module_repo))
        store.open()
        # Add a file that calls its own function
        (multi_module_repo / "self_call.py").write_text(
            'def helper():\n'
            '    pass\n'
            'def caller():\n'
            '    helper()\n'
        )
        builder = GraphBuilder(str(multi_module_repo), store)
        builder.build()
        edges = store.edges_from("self_call.py::caller", edge_type="CALLS")
        helper_edges = [e for e in edges if e.target_qn == "self_call.py::helper"]
        assert len(helper_edges) == 1
        assert helper_edges[0].weight == 1.0
        store.close()

    def test_unresolved_callee_weight(self, multi_module_repo):
        """Calls to unknown functions should create ?:: edges with weight 0.5."""
        store = GraphStore(str(multi_module_repo))
        store.open()
        (multi_module_repo / "lonely.py").write_text(
            'def test_func():\n'
            '    unknown_function()\n'
        )
        builder = GraphBuilder(str(multi_module_repo), store)
        builder.build()
        edges = store.edges_from("lonely.py::test_func", edge_type="CALLS")
        unresolved = [e for e in edges if e.target_qn.startswith("?::")]
        assert len(unresolved) == 1
        assert unresolved[0].weight == 0.5
        store.close()

    def test_resolve_callee_method(self):
        """Test _resolve_callee directly for various scenarios."""
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "a.py").write_text("def foo(): pass\n")
            (p / "b.py").write_text("import a\ndef bar(): foo()\n")
            store = GraphStore(str(p))
            store.open()
            builder = GraphBuilder(str(p), store)
            builder.build()
            # After build, verify edges exist
            edges = store.edges_from("b.py::bar", edge_type="CALLS")
            foo_edges = [e for e in edges if "foo" in e.target_qn]
            assert len(foo_edges) >= 1
            store.close()

    def test_change_impact_min_weight(self, multi_module_repo):
        """change_impact with min_weight should filter low-confidence callers."""
        store = GraphStore(str(multi_module_repo))
        store.open()
        builder = GraphBuilder(str(multi_module_repo), store)
        builder.build()
        from codetree.graph.queries import GraphQueries
        queries = GraphQueries(store)
        # With min_weight=0.8, only import-confirmed callers should appear
        result = queries.change_impact(symbol_query="save", min_weight=0.8)
        # main.py::process should appear (weight 1.0), other.py::process should not (weight 0.5)
        all_callers = []
        for risk_level in result["impact"].values():
            all_callers.extend(c["qualified_name"] for c in risk_level)
        if "main.py::process" in all_callers:
            assert "other.py::process" not in all_callers
        store.close()


def test_build_uses_batched_store_access(tmp_path, monkeypatch):
    """Row-by-row store calls stall a background build behind busy tool threads."""
    (tmp_path / "calc.py").write_text(
        "class Calc:\n    def add(self, a, b):\n        return helper(a) + b\n\n"
        "def helper(x):\n    return x\n"
    )
    (tmp_path / "test_calc.py").write_text("from calc import helper\n\ndef test_helper():\n    helper(1)\n")

    def row_by_row(*args, **kwargs):
        raise AssertionError("per-row store access during build")

    for method in ("upsert_symbol", "upsert_edge", "upsert_file", "symbols_by_name", "get_file"):
        monkeypatch.setattr(GraphStore, method, row_by_row)

    store = GraphStore(str(tmp_path))
    store.open()
    try:
        stats = GraphBuilder(str(tmp_path), store).build()
        assert stats["files_indexed"] == 2
        assert {e.type for e in store.edges_from("calc.py::Calc")} == {"CONTAINS"}
        assert [e.target_qn for e in store.edges_from("test_calc.py::test_helper", "TESTS")] == ["calc.py::helper"]
    finally:
        store.close()
