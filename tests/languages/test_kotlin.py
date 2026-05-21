import pytest
from codetree.languages.kotlin import KotlinPlugin

PLUGIN = KotlinPlugin()

SAMPLE = b"""\
class Calculator {
    fun add(a: Int, b: Int): Int {
        return a + b
    }
    fun divide(a: Int, b: Int): Int {
        if (b == 0) throw IllegalArgumentException("div by zero")
        return a / b
    }
}

object Helper {
    fun run(): Int {
        val calc = Calculator()
        return calc.add(1, 2)
    }
}

fun topLevel(x: Int) = x * 2
"""


def test_skeleton_finds_classes_and_objects():
    result = PLUGIN.extract_skeleton(SAMPLE)
    names = [item["name"] for item in result]
    assert "Calculator" in names
    assert "Helper" in names


def test_skeleton_finds_methods():
    result = PLUGIN.extract_skeleton(SAMPLE)
    names = [item["name"] for item in result]
    assert "add" in names
    assert "divide" in names
    assert "run" in names


def test_skeleton_finds_top_level_function():
    result = PLUGIN.extract_skeleton(SAMPLE)
    names = [item["name"] for item in result]
    assert "topLevel" in names


def test_skeleton_method_has_parent():
    result = PLUGIN.extract_skeleton(SAMPLE)
    add = next(item for item in result if item["name"] == "add")
    assert add["parent"] == "Calculator"
    run = next(item for item in result if item["name"] == "run")
    assert run["parent"] == "Helper"


def test_extract_symbol_finds_class():
    result = PLUGIN.extract_symbol_source(SAMPLE, "Calculator")
    assert result is not None
    source, _ = result
    assert "class Calculator" in source


def test_extract_symbol_finds_method():
    result = PLUGIN.extract_symbol_source(SAMPLE, "add")
    assert result is not None
    source, _ = result
    assert "fun add" in source


def test_extract_symbol_returns_none_for_missing():
    assert PLUGIN.extract_symbol_source(SAMPLE, "nonexistent") is None


def test_extract_calls_in_function():
    calls = PLUGIN.extract_calls_in_function(SAMPLE, "run")
    # For Kotlin, it should find 'add'
    assert "add" in calls


def test_extract_symbol_usages():
    usages = PLUGIN.extract_symbol_usages(SAMPLE, "Calculator")
    assert len(usages) >= 2  # Definition + instantiation


def test_kts_support():
    kts_sample = b"""
    fun buildConfig() {
        println("building...")
    }
    """
    result = PLUGIN.extract_skeleton(kts_sample)
    assert any(x["name"] == "buildConfig" for x in result)
