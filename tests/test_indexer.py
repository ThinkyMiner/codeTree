"""
Comprehensive tests for the Indexer:
  build(), get_skeleton(), get_symbol(), find_references(), get_call_graph()

Tests cover multi-language indexing, directory exclusions, relative paths,
line number accuracy, and cross-file analysis.
"""
import pytest
from pathlib import Path
from codetree.indexer import Indexer


# ─── build() — file discovery ─────────────────────────────────────────────────

class TestIndexerBuild:

    def test_indexes_python_files(self, sample_repo):
        idx = Indexer(str(sample_repo))
        idx.build()
        assert "calculator.py" in [p.name for p in idx.files]

    def test_ignores_txt_files(self, sample_repo):
        (sample_repo / "notes.txt").write_text("hello")
        idx = Indexer(str(sample_repo))
        idx.build()
        assert "notes.txt" not in [p.name for p in idx.files]

    def test_ignores_json_files(self, sample_repo):
        (sample_repo / "package.json").write_text("{}")
        idx = Indexer(str(sample_repo))
        idx.build()
        assert "package.json" not in [p.name for p in idx.files]

    def test_skips_node_modules(self, tmp_path):
        (tmp_path / "app.js").write_text("const x = () => 1;")
        nm = tmp_path / "node_modules" / "lib"
        nm.mkdir(parents=True)
        (nm / "index.js").write_text("const y = () => 2;")
        idx = Indexer(str(tmp_path))
        idx.build()
        assert not any("node_modules" in k for k in idx._index)

    def test_skips_venv(self, tmp_path):
        (tmp_path / "app.py").write_text("def main(): pass")
        venv = tmp_path / ".venv" / "lib"
        venv.mkdir(parents=True)
        (venv / "util.py").write_text("def venv_fn(): pass")
        idx = Indexer(str(tmp_path))
        idx.build()
        assert not any(".venv" in k for k in idx._index)

    def test_skips_pycache(self, tmp_path):
        (tmp_path / "app.py").write_text("def main(): pass")
        cache = tmp_path / "__pycache__"
        cache.mkdir()
        (cache / "app.cpython-311.pyc").write_bytes(b"fake")
        idx = Indexer(str(tmp_path))
        idx.build()
        assert not any("__pycache__" in k for k in idx._index)

    def test_indexes_files_in_subdirectories(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "utils.py").write_text("def helper(): pass")
        idx = Indexer(str(tmp_path))
        idx.build()
        assert "src/utils.py" in idx._index

    def test_paths_are_relative_not_absolute(self, tmp_path):
        (tmp_path / "app.py").write_text("def main(): pass")
        idx = Indexer(str(tmp_path))
        idx.build()
        for key in idx._index:
            assert not key.startswith("/"), f"Expected relative path, got: {key}"

    def test_indexes_multiple_languages(self, multi_lang_repo):
        idx = Indexer(str(multi_lang_repo))
        idx.build()
        exts = {Path(k).suffix for k in idx._index}
        assert ".py" in exts
        assert ".js" in exts
        assert ".ts" in exts
        assert ".go" in exts
        assert ".rs" in exts

    def test_skips_excluded_path(self, tmp_path):
        (tmp_path / "app.py").write_text("def main(): pass")
        vendored = tmp_path / "third_party" / "lib"
        vendored.mkdir(parents=True)
        (vendored / "util.py").write_text("def vendored_fn(): pass")
        idx = Indexer(str(tmp_path), exclude=["third_party"])
        idx.build()
        assert list(idx._index) == ["app.py"]

    def test_excluded_path_is_a_prefix_from_root(self, tmp_path):
        for rel in ("docs/gen", "docs/generated", "src/docs/gen"):
            d = tmp_path / rel
            d.mkdir(parents=True)
            (d / "mod.py").write_text("def fn(): pass")
        idx = Indexer(str(tmp_path), exclude=["docs/gen/"])
        idx.build()
        assert sorted(idx._index) == ["docs/generated/mod.py", "src/docs/gen/mod.py"]

    def test_exclude_accepts_absolute_path_under_root(self, tmp_path):
        (tmp_path / "app.py").write_text("def main(): pass")
        vendored = tmp_path / "third_party"
        vendored.mkdir()
        (vendored / "util.py").write_text("def vendored_fn(): pass")
        idx = Indexer(str(tmp_path), exclude=[str(vendored)])
        idx.build()
        assert list(idx._index) == ["app.py"]

    @pytest.mark.parametrize("bad", ["../elsewhere", "src/../third_party", "/outside/the/root"])
    def test_exclude_rejects_path_it_cannot_match(self, tmp_path, bad):
        with pytest.raises(ValueError, match="--exclude"):
            Indexer(str(tmp_path), exclude=[bad])

    def test_skips_git_directory(self, tmp_path):
        (tmp_path / "app.py").write_text("def main(): pass")
        git = tmp_path / ".git" / "hooks"
        git.mkdir(parents=True)
        (git / "pre-commit").write_text("#!/bin/sh")
        (git / "helper.py").write_text("def hook(): pass")
        idx = Indexer(str(tmp_path))
        idx.build()
        assert not any(".git" in k for k in idx._index)


# ─── get_skeleton() ───────────────────────────────────────────────────────────

class TestIndexerSkeleton:

    def test_python_class_and_methods(self, sample_repo):
        idx = Indexer(str(sample_repo))
        idx.build()
        skeleton = idx.get_skeleton("calculator.py")
        names = [item["name"] for item in skeleton]
        assert "Calculator" in names
        assert "add" in names
        assert "divide" in names
        assert "helper" in names

    def test_method_has_correct_parent(self, sample_repo):
        idx = Indexer(str(sample_repo))
        idx.build()
        skeleton = idx.get_skeleton("calculator.py")
        add = next(item for item in skeleton if item["name"] == "add")
        assert add["parent"] == "Calculator"

    def test_skeleton_sorted_by_line(self, sample_repo):
        idx = Indexer(str(sample_repo))
        idx.build()
        skeleton = idx.get_skeleton("calculator.py")
        lines = [item["line"] for item in skeleton]
        assert lines == sorted(lines)

    def test_js_arrow_functions_indexed(self, multi_lang_repo):
        idx = Indexer(str(multi_lang_repo))
        idx.build()
        names = [item["name"] for item in idx.get_skeleton("utils.js")]
        assert "double" in names
        assert "triple" in names
        assert "greet" in names

    def test_ts_interface_indexed(self, multi_lang_repo):
        idx = Indexer(str(multi_lang_repo))
        idx.build()
        skeleton = idx.get_skeleton("types.ts")
        assert any(item["type"] == "interface" and item["name"] == "Shape" for item in skeleton)

    def test_ts_class_and_arrow_indexed(self, multi_lang_repo):
        idx = Indexer(str(multi_lang_repo))
        idx.build()
        names = [item["name"] for item in idx.get_skeleton("types.ts")]
        assert "Circle" in names
        assert "makeCircle" in names

    def test_go_struct_and_interface_indexed(self, multi_lang_repo):
        idx = Indexer(str(multi_lang_repo))
        idx.build()
        skeleton = idx.get_skeleton("server.go")
        types = {item["name"]: item["type"] for item in skeleton}
        assert types.get("Server") == "struct"
        assert types.get("Handler") == "interface"
        assert "NewServer" in types

    def test_rust_struct_and_method_indexed(self, multi_lang_repo):
        idx = Indexer(str(multi_lang_repo))
        idx.build()
        skeleton = idx.get_skeleton("config.rs")
        names = [item["name"] for item in skeleton]
        assert "Config" in names
        assert "new" in names
        assert "default_config" in names

    def test_python_decorated_class_indexed(self, rich_py_repo):
        idx = Indexer(str(rich_py_repo))
        idx.build()
        skeleton = idx.get_skeleton("models.py")
        assert any(item["type"] == "class" and item["name"] == "User" for item in skeleton)

    def test_python_decorated_method_indexed(self, rich_py_repo):
        idx = Indexer(str(rich_py_repo))
        idx.build()
        names = [item["name"] for item in idx.get_skeleton("services.py")]
        assert "validate" in names

    def test_empty_list_for_unknown_file(self, sample_repo):
        idx = Indexer(str(sample_repo))
        idx.build()
        assert idx.get_skeleton("nonexistent.py") == []


# ─── get_symbol() ─────────────────────────────────────────────────────────────

class TestIndexerGetSymbol:

    def test_returns_source_and_line(self, sample_repo):
        idx = Indexer(str(sample_repo))
        idx.build()
        result = idx.get_symbol("calculator.py", "add")
        assert result is not None
        source, line = result
        assert "def add" in source

    def test_line_number_is_one_based(self, sample_repo):
        idx = Indexer(str(sample_repo))
        idx.build()
        _, line = idx.get_symbol("calculator.py", "Calculator")
        assert line == 1

    def test_method_line_accurate(self, sample_repo):
        idx = Indexer(str(sample_repo))
        idx.build()
        _, line = idx.get_symbol("calculator.py", "add")
        assert line == 2

    def test_function_line_accurate(self, sample_repo):
        idx = Indexer(str(sample_repo))
        idx.build()
        _, line = idx.get_symbol("calculator.py", "helper")
        assert line == 10

    def test_class_source_includes_body(self, sample_repo):
        idx = Indexer(str(sample_repo))
        idx.build()
        source, _ = idx.get_symbol("calculator.py", "Calculator")
        assert "def add" in source
        assert "def divide" in source

    def test_decorated_function_includes_decorator(self, rich_py_repo):
        idx = Indexer(str(rich_py_repo))
        idx.build()
        source, _ = idx.get_symbol("services.py", "validate")
        assert "@staticmethod" in source
        assert "def validate" in source

    def test_returns_none_for_missing_symbol(self, sample_repo):
        idx = Indexer(str(sample_repo))
        idx.build()
        assert idx.get_symbol("calculator.py", "nonexistent") is None

    def test_returns_none_for_missing_file(self, sample_repo):
        idx = Indexer(str(sample_repo))
        idx.build()
        assert idx.get_symbol("missing.py", "anything") is None


# ─── find_references() ────────────────────────────────────────────────────────

class TestIndexerFindReferences:

    def test_finds_refs_across_files(self, sample_repo):
        idx = Indexer(str(sample_repo))
        idx.build()
        refs = idx.find_references("Calculator")
        files = {r["file"] for r in refs}
        assert "calculator.py" in files
        assert "main.py" in files

    def test_refs_have_line_numbers(self, sample_repo):
        idx = Indexer(str(sample_repo))
        idx.build()
        for ref in idx.find_references("Calculator"):
            assert ref["line"] >= 1

    def test_definition_site_included(self, sample_repo):
        idx = Indexer(str(sample_repo))
        idx.build()
        refs = idx.find_references("Calculator")
        calculator_lines = [r["line"] for r in refs if r["file"] == "calculator.py"]
        assert 1 in calculator_lines  # class defined at line 1

    def test_usage_site_included(self, sample_repo):
        idx = Indexer(str(sample_repo))
        idx.build()
        refs = idx.find_references("Calculator")
        main_lines = [r["line"] for r in refs if r["file"] == "main.py"]
        assert 4 in main_lines  # Calculator() at line 4 in main.py

    def test_multiple_refs_in_same_file(self, rich_py_repo):
        idx = Indexer(str(rich_py_repo))
        idx.build()
        refs = idx.find_references("UserService")
        services_refs = [r for r in refs if "services.py" in r["file"]]
        # Defined at line 3, used at line 12
        assert len(services_refs) >= 2

    def test_empty_list_for_unknown_symbol(self, sample_repo):
        idx = Indexer(str(sample_repo))
        idx.build()
        assert idx.find_references("AbsolutelyNobodyUsesThis") == []


# ─── get_call_graph() ─────────────────────────────────────────────────────────

class TestIndexerCallGraph:

    def test_outbound_calls_detected(self, sample_repo):
        idx = Indexer(str(sample_repo))
        idx.build()
        graph = idx.get_call_graph("calculator.py", "helper")
        assert "Calculator" in graph["calls"]
        assert "add" in graph["calls"]

    def test_calls_is_sorted_list(self, sample_repo):
        idx = Indexer(str(sample_repo))
        idx.build()
        graph = idx.get_call_graph("calculator.py", "helper")
        assert graph["calls"] == sorted(graph["calls"])

    def test_inbound_callers_detected(self, sample_repo):
        idx = Indexer(str(sample_repo))
        idx.build()
        graph = idx.get_call_graph("calculator.py", "divide")
        caller_files = {c["file"] for c in graph["callers"]}
        assert "main.py" in caller_files

    def test_caller_has_line_number(self, sample_repo):
        idx = Indexer(str(sample_repo))
        idx.build()
        graph = idx.get_call_graph("calculator.py", "divide")
        for caller in graph["callers"]:
            assert "line" in caller
            assert caller["line"] >= 1

    def test_caller_line_number_accurate(self, sample_repo):
        idx = Indexer(str(sample_repo))
        idx.build()
        graph = idx.get_call_graph("calculator.py", "divide")
        main_callers = [c for c in graph["callers"] if c["file"] == "main.py"]
        lines = [c["line"] for c in main_callers]
        # "result = calc.divide(10, 2)" is at line 5 in main.py
        assert 5 in lines

    def test_no_calls_returns_empty_list(self, sample_repo):
        (sample_repo / "leaf.py").write_text("def leaf():\n    return 42\n")
        idx = Indexer(str(sample_repo))
        idx.build()
        graph = idx.get_call_graph("leaf.py", "leaf")
        assert graph["calls"] == []

    def test_unknown_function_has_empty_calls(self, sample_repo):
        idx = Indexer(str(sample_repo))
        idx.build()
        graph = idx.get_call_graph("calculator.py", "nonexistent_fn")
        assert graph["calls"] == []

    def test_unknown_file_has_empty_calls(self, sample_repo):
        idx = Indexer(str(sample_repo))
        idx.build()
        graph = idx.get_call_graph("missing.py", "fn")
        assert graph["calls"] == []
