"""
Comprehensive tests for all four MCP server tools:
  get_file_skeleton, get_symbol, find_references, get_call_graph

Tests cover output format, line number accuracy, multi-language support,
edge cases (missing files/symbols), and cross-file scenarios.
"""
import re
import pytest
from codetree.server import create_server


def _tool(mcp, name):
    key = f"tool:{name}@"
    tool = mcp.local_provider._components.get(key)
    if tool is None:
        raise KeyError(f"Tool '{name}' not registered. Keys: {list(mcp.local_provider._components)}")
    return tool.fn


# ─── get_file_skeleton ────────────────────────────────────────────────────────

class TestGetFileSkeleton:

    # — content correctness —

    def test_finds_class(self, sample_repo):
        fn = _tool(create_server(str(sample_repo)), "get_file_skeleton")
        assert "Calculator" in fn(file_path="calculator.py")

    def test_finds_methods(self, sample_repo):
        fn = _tool(create_server(str(sample_repo)), "get_file_skeleton")
        result = fn(file_path="calculator.py")
        assert "add" in result
        assert "divide" in result

    def test_finds_top_level_function(self, sample_repo):
        fn = _tool(create_server(str(sample_repo)), "get_file_skeleton")
        assert "helper" in fn(file_path="calculator.py")

    # — output format —

    def test_class_uses_class_keyword(self, sample_repo):
        fn = _tool(create_server(str(sample_repo)), "get_file_skeleton")
        result = fn(file_path="calculator.py")
        assert "class Calculator" in result
        # Must not fall through to "def"
        assert not any("def Calculator" in line for line in result.splitlines())

    def test_method_shows_parent_class(self, sample_repo):
        fn = _tool(create_server(str(sample_repo)), "get_file_skeleton")
        result = fn(file_path="calculator.py")
        assert "(in Calculator)" in result

    def test_params_included_in_output(self, sample_repo):
        fn = _tool(create_server(str(sample_repo)), "get_file_skeleton")
        result = fn(file_path="calculator.py")
        assert "(self, a, b)" in result

    def test_line_numbers_present(self, sample_repo):
        fn = _tool(create_server(str(sample_repo)), "get_file_skeleton")
        result = fn(file_path="calculator.py")
        assert "→ line" in result

    def test_class_at_correct_line(self, sample_repo):
        fn = _tool(create_server(str(sample_repo)), "get_file_skeleton")
        result = fn(file_path="calculator.py")
        # Calculator is the first line of calculator.py
        assert "class Calculator → line 1" in result

    def test_top_level_function_line_accurate(self, sample_repo):
        fn = _tool(create_server(str(sample_repo)), "get_file_skeleton")
        result = fn(file_path="calculator.py")
        # helper() is at line 10: class(1) add(2) body(3) blank(4)
        # divide(5) body(6,7,8) blank(9) helper(10)
        assert "→ line 10" in result

    def test_entries_sorted_by_line(self, sample_repo):
        fn = _tool(create_server(str(sample_repo)), "get_file_skeleton")
        result = fn(file_path="calculator.py")
        nums = [int(m) for m in re.findall(r"→ line (\d+)", result)]
        assert len(nums) >= 3
        assert nums == sorted(nums)

    # — unknown file —

    def test_unknown_file_returns_not_found(self, sample_repo):
        fn = _tool(create_server(str(sample_repo)), "get_file_skeleton")
        result = fn(file_path="nonexistent.py")
        assert "not found" in result.lower()

    # — struct / interface keywords —

    def test_rust_struct_uses_struct_keyword(self, multi_lang_repo):
        fn = _tool(create_server(str(multi_lang_repo)), "get_file_skeleton")
        result = fn(file_path="config.rs")
        assert "struct Config" in result
        assert not any("def Config" in line for line in result.splitlines())

    def test_rust_impl_method_shown(self, multi_lang_repo):
        fn = _tool(create_server(str(multi_lang_repo)), "get_file_skeleton")
        result = fn(file_path="config.rs")
        assert "new" in result
        assert "(in Config)" in result

    def test_go_struct_uses_struct_keyword(self, multi_lang_repo):
        fn = _tool(create_server(str(multi_lang_repo)), "get_file_skeleton")
        result = fn(file_path="server.go")
        assert "struct Server" in result

    def test_go_interface_uses_interface_keyword(self, multi_lang_repo):
        fn = _tool(create_server(str(multi_lang_repo)), "get_file_skeleton")
        result = fn(file_path="server.go")
        assert "interface Handler" in result

    def test_go_function_shown(self, multi_lang_repo):
        fn = _tool(create_server(str(multi_lang_repo)), "get_file_skeleton")
        result = fn(file_path="server.go")
        assert "NewServer" in result

    # — JavaScript / TypeScript —

    def test_js_arrow_functions_visible(self, multi_lang_repo):
        fn = _tool(create_server(str(multi_lang_repo)), "get_file_skeleton")
        result = fn(file_path="utils.js")
        assert "double" in result
        assert "triple" in result

    def test_js_exported_function_visible(self, multi_lang_repo):
        fn = _tool(create_server(str(multi_lang_repo)), "get_file_skeleton")
        result = fn(file_path="utils.js")
        assert "greet" in result

    def test_ts_interface_uses_interface_keyword(self, multi_lang_repo):
        fn = _tool(create_server(str(multi_lang_repo)), "get_file_skeleton")
        result = fn(file_path="types.ts")
        assert "interface Shape" in result

    def test_ts_class_visible(self, multi_lang_repo):
        fn = _tool(create_server(str(multi_lang_repo)), "get_file_skeleton")
        result = fn(file_path="types.ts")
        assert "class Circle" in result

    def test_ts_arrow_function_visible(self, multi_lang_repo):
        fn = _tool(create_server(str(multi_lang_repo)), "get_file_skeleton")
        result = fn(file_path="types.ts")
        assert "makeCircle" in result

    # — Python decorators —

    def test_decorated_method_visible(self, rich_py_repo):
        fn = _tool(create_server(str(rich_py_repo)), "get_file_skeleton")
        result = fn(file_path="services.py")
        assert "validate" in result
        assert "(in UserService)" in result

    def test_decorated_class_visible(self, rich_py_repo):
        fn = _tool(create_server(str(rich_py_repo)), "get_file_skeleton")
        result = fn(file_path="models.py")
        assert "class User" in result


# ─── get_symbol ───────────────────────────────────────────────────────────────

class TestGetSymbol:

    # — return value format —

    def test_header_has_filepath_colon_line(self, sample_repo):
        fn = _tool(create_server(str(sample_repo)), "get_symbol")
        result = fn(file_path="calculator.py", symbol_name="helper")
        assert result.startswith("# calculator.py:")

    def test_line_in_header_is_accurate(self, sample_repo):
        fn = _tool(create_server(str(sample_repo)), "get_symbol")
        result = fn(file_path="calculator.py", symbol_name="helper")
        # helper starts at line 10
        assert "# calculator.py:10" in result

    def test_class_line_in_header_accurate(self, sample_repo):
        fn = _tool(create_server(str(sample_repo)), "get_symbol")
        result = fn(file_path="calculator.py", symbol_name="Calculator")
        assert "# calculator.py:1" in result

    def test_method_line_in_header_accurate(self, sample_repo):
        fn = _tool(create_server(str(sample_repo)), "get_symbol")
        result = fn(file_path="calculator.py", symbol_name="add")
        assert "# calculator.py:2" in result

    # — source completeness —

    def test_function_body_included(self, sample_repo):
        fn = _tool(create_server(str(sample_repo)), "get_symbol")
        result = fn(file_path="calculator.py", symbol_name="helper")
        assert "def helper" in result
        assert "Calculator()" in result
        assert "calc.add(1, 2)" in result

    def test_full_class_body_included(self, sample_repo):
        fn = _tool(create_server(str(sample_repo)), "get_symbol")
        result = fn(file_path="calculator.py", symbol_name="Calculator")
        assert "class Calculator" in result
        assert "def add" in result       # method bodies inside class
        assert "def divide" in result

    def test_decorated_function_includes_decorator(self, rich_py_repo):
        fn = _tool(create_server(str(rich_py_repo)), "get_symbol")
        result = fn(file_path="services.py", symbol_name="validate")
        assert "@staticmethod" in result
        assert "def validate" in result

    def test_js_arrow_function_retrievable(self, multi_lang_repo):
        fn = _tool(create_server(str(multi_lang_repo)), "get_symbol")
        result = fn(file_path="utils.js", symbol_name="greet")
        assert "greet" in result

    def test_ts_arrow_function_retrievable(self, multi_lang_repo):
        fn = _tool(create_server(str(multi_lang_repo)), "get_symbol")
        result = fn(file_path="types.ts", symbol_name="makeCircle")
        assert "makeCircle" in result

    # — not found —

    def test_missing_symbol_returns_not_found(self, sample_repo):
        fn = _tool(create_server(str(sample_repo)), "get_symbol")
        result = fn(file_path="calculator.py", symbol_name="nonexistent")
        assert "not found" in result.lower()

    def test_missing_file_returns_not_found(self, sample_repo):
        fn = _tool(create_server(str(sample_repo)), "get_symbol")
        result = fn(file_path="ghost.py", symbol_name="anything")
        assert "not found" in result.lower()


# ─── find_references ──────────────────────────────────────────────────────────

class TestFindReferences:

    # — cross-file coverage —

    def test_finds_refs_in_multiple_files(self, sample_repo):
        fn = _tool(create_server(str(sample_repo)), "find_references")
        result = fn(symbol_name="Calculator")
        assert "calculator.py" in result
        assert "main.py" in result

    # — output format —

    def test_output_has_file_colon_line_format(self, sample_repo):
        fn = _tool(create_server(str(sample_repo)), "find_references")
        result = fn(symbol_name="Calculator")
        assert re.search(r"calculator\.py:\d+", result)
        assert re.search(r"main\.py:\d+", result)

    def test_definition_site_line_accurate(self, sample_repo):
        fn = _tool(create_server(str(sample_repo)), "find_references")
        result = fn(symbol_name="Calculator")
        # Calculator class defined at line 1 in calculator.py
        assert "calculator.py:1" in result

    def test_usage_site_line_accurate(self, sample_repo):
        fn = _tool(create_server(str(sample_repo)), "find_references")
        result = fn(symbol_name="Calculator")
        # Calculator used at line 4 in main.py (calc = Calculator())
        assert "main.py:4" in result

    # — multiple refs in same file —

    def test_multiple_refs_in_same_file_all_reported(self, rich_py_repo):
        fn = _tool(create_server(str(rich_py_repo)), "find_references")
        result = fn(symbol_name="UserService")
        # UserService appears at line 3 (class def) and line 12 (usage)
        services_hits = re.findall(r"services\.py:(\d+)", result)
        assert len(services_hits) >= 2

    def test_find_refs_across_language_files(self, multi_lang_repo):
        fn = _tool(create_server(str(multi_lang_repo)), "find_references")
        result = fn(symbol_name="add")
        assert "calc.py" in result

    # — no results —

    def test_unknown_symbol_returns_no_references_message(self, sample_repo):
        fn = _tool(create_server(str(sample_repo)), "find_references")
        result = fn(symbol_name="SymbolThatDoesNotExistAnywhere")
        assert "no references" in result.lower()


# ─── get_call_graph ───────────────────────────────────────────────────────────

class TestGetCallGraph:

    # — outbound calls —

    def test_shows_outbound_calls(self, sample_repo):
        fn = _tool(create_server(str(sample_repo)), "get_call_graph")
        result = fn(file_path="calculator.py", function_name="helper")
        assert "Calculator" in result
        assert "add" in result

    def test_outbound_calls_use_arrow_format(self, sample_repo):
        fn = _tool(create_server(str(sample_repo)), "get_call_graph")
        result = fn(file_path="calculator.py", function_name="helper")
        # Outbound calls rendered as "→ callee"
        assert re.search(r"→\s+Calculator", result)
        assert re.search(r"→\s+add", result)

    def test_function_with_no_calls_shows_nothing_detected(self, sample_repo):
        (sample_repo / "leaf.py").write_text("def leaf():\n    return 42\n")
        fn = _tool(create_server(str(sample_repo)), "get_call_graph")
        result = fn(file_path="leaf.py", function_name="leaf")
        assert "nothing detected" in result.lower()

    # — inbound callers —

    def test_shows_inbound_callers(self, sample_repo):
        fn = _tool(create_server(str(sample_repo)), "get_call_graph")
        result = fn(file_path="calculator.py", function_name="divide")
        assert "main.py" in result

    def test_caller_uses_left_arrow_format(self, sample_repo):
        fn = _tool(create_server(str(sample_repo)), "get_call_graph")
        result = fn(file_path="calculator.py", function_name="divide")
        # Callers rendered as "← file:line"
        assert re.search(r"←\s+main\.py:\d+", result)

    def test_caller_line_number_accurate(self, sample_repo):
        fn = _tool(create_server(str(sample_repo)), "get_call_graph")
        result = fn(file_path="calculator.py", function_name="divide")
        # divide called at line 5 in main.py: "result = calc.divide(10, 2)"
        assert "main.py:5" in result

    # — structure —

    def test_output_header_names_function(self, sample_repo):
        fn = _tool(create_server(str(sample_repo)), "get_call_graph")
        result = fn(file_path="calculator.py", function_name="helper")
        assert "helper" in result.splitlines()[0]

    def test_cross_file_callers_discovered(self, rich_py_repo):
        fn = _tool(create_server(str(rich_py_repo)), "get_call_graph")
        result = fn(file_path="models.py", function_name="get_user_by_email")
        # get_user_by_email is imported and potentially used in services.py
        assert "models.py" in result or "services.py" in result


# ─── exclude ──────────────────────────────────────────────────────────────────

class TestExclude:

    def _repo(self, tmp_path):
        (tmp_path / "app.py").write_text("def main(): pass\n")
        vendored = tmp_path / "third_party" / "lib"
        vendored.mkdir(parents=True)
        (vendored / "util.py").write_text("def vendored_fn(): pass\n")
        return tmp_path

    def test_excluded_path_is_not_served(self, tmp_path):
        repo = self._repo(tmp_path)
        fn = _tool(create_server(str(repo), exclude=["third_party"]), "get_file_skeleton")
        assert "main" in fn(file_path="app.py")
        assert "File not found" in fn(file_path="third_party/lib/util.py")

    def test_exclude_drops_previously_cached_file(self, tmp_path):
        repo = self._repo(tmp_path)
        fn = _tool(create_server(str(repo)), "get_file_skeleton")
        assert "vendored_fn" in fn(file_path="third_party/lib/util.py")
        fn = _tool(create_server(str(repo), exclude=["third_party"]), "get_file_skeleton")
        assert "File not found" in fn(file_path="third_party/lib/util.py")

    def test_cli_passes_exclude_to_run(self, tmp_path, monkeypatch):
        import sys
        import codetree.__main__ as cli
        calls = []
        monkeypatch.setattr(cli, "run", lambda root, exclude=(): calls.append((root, list(exclude))))
        monkeypatch.setattr(sys, "argv", [
            "codetree", "--root", str(tmp_path),
            "--exclude", "third_party", "--exclude", "docs/gen",
        ])
        cli.main()
        assert calls == [(str(tmp_path), ["third_party", "docs/gen"])]
