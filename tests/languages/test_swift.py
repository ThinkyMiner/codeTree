from codetree.languages.swift import SwiftPlugin

PLUGIN = SwiftPlugin()

SAMPLE = b"""\
import Foundation

/// Adds and divides numbers.
class Calculator {
    func add(_ a: Int, to b: Int) -> Int {
        return a + b
    }

    func divide(_ a: Int, by b: Int) throws -> Int {
        guard b != 0 else { throw CalcError.divisionByZero }
        return a / b
    }
}

struct Helper {
    func run() -> Int {
        let calc = Calculator()
        return calc.add(1, to: 2)
    }
}

func topLevel(x: Int) -> Int { x * 2 }
"""


def test_skeleton_finds_types():
    result = PLUGIN.extract_skeleton(SAMPLE)
    assert {"type": "class", "name": "Calculator", "line": 4, "parent": None,
            "params": "", "doc": "Adds and divides numbers."} in result
    assert any(x["type"] == "struct" and x["name"] == "Helper" for x in result)


def test_skeleton_finds_methods_with_parent():
    result = PLUGIN.extract_skeleton(SAMPLE)
    add = next(x for x in result if x["name"] == "add")
    assert add["type"] == "method"
    assert add["parent"] == "Calculator"
    assert add["line"] == 5
    run = next(x for x in result if x["name"] == "run")
    assert run["parent"] == "Helper"


def test_skeleton_keeps_external_labels_in_params():
    result = PLUGIN.extract_skeleton(SAMPLE)
    add = next(x for x in result if x["name"] == "add")
    assert add["params"] == "(_ a: Int, to b: Int)"


def test_skeleton_finds_top_level_function():
    result = PLUGIN.extract_skeleton(SAMPLE)
    top = next(x for x in result if x["name"] == "topLevel")
    assert top["type"] == "function"
    assert top["parent"] is None
    assert top["params"] == "(x: Int)"


def test_skeleton_sorted_by_line():
    lines = [x["line"] for x in PLUGIN.extract_skeleton(SAMPLE)]
    assert lines == sorted(lines)


def test_extract_symbol_finds_class():
    source, line = PLUGIN.extract_symbol_source(SAMPLE, "Calculator")
    assert source.startswith("class Calculator {")
    assert line == 4


def test_extract_symbol_finds_method():
    source, line = PLUGIN.extract_symbol_source(SAMPLE, "divide")
    assert source.startswith("func divide(")
    assert "guard b != 0" in source
    assert line == 9


def test_extract_symbol_returns_none_for_missing():
    assert PLUGIN.extract_symbol_source(SAMPLE, "nonexistent") is None


def test_extract_calls_in_function():
    assert PLUGIN.extract_calls_in_function(SAMPLE, "run") == ["Calculator", "add"]


def test_extract_calls_missing_function():
    assert PLUGIN.extract_calls_in_function(SAMPLE, "nonexistent") == []


def test_extract_symbol_usages():
    usages = PLUGIN.extract_symbol_usages(SAMPLE, "Calculator")
    assert [u["line"] for u in usages] == [4, 17]


def test_extract_imports():
    assert PLUGIN.extract_imports(SAMPLE) == [{"line": 1, "text": "import Foundation"}]


def test_complexity_counts_guard():
    result = PLUGIN.compute_complexity(SAMPLE, "divide")
    assert result == {"total": 2, "breakdown": {"guard": 1}}


def test_check_syntax():
    assert PLUGIN.check_syntax(SAMPLE) is False
    assert PLUGIN.check_syntax(b"class Foo {\n    func bar( {\n}\n") is True
