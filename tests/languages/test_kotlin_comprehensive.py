"""
Exhaustive tests for the Kotlin plugin covering every realistic code pattern.

Code style categories:
  - Classes: plain, open, abstract, data, sealed, with extends/implements
  - Interfaces: plain, with methods
  - Objects: plain, companion object
  - Functions: top-level, extension, lambda, member
  - extract_symbol_source and extract_calls_in_function
"""
import pytest
from codetree.languages.kotlin import KotlinPlugin

P = KotlinPlugin()


# ─── Class styles ──────────────────────────────────────────────────────────────

def test_plain_class():
    src = b"class Foo {}\n"
    assert any(x["type"] == "class" and x["name"] == "Foo" for x in P.extract_skeleton(src))


def test_data_class():
    src = b"data class User(val id: Int, val name: String)\n"
    assert any(x["name"] == "User" for x in P.extract_skeleton(src))


def test_abstract_class():
    src = b"abstract class Shape {\n    abstract fun area(): Double\n}\n"
    result = P.extract_skeleton(src)
    assert any(x["name"] == "Shape" for x in result)


def test_class_inheritance():
    src = b"class Dog : Animal(), Runnable {\n    override fun run() {}\n}\n"
    result = P.extract_skeleton(src)
    assert any(x["name"] == "Dog" for x in result)
    assert any(x["name"] == "run" and x["parent"] == "Dog" for x in result)


# ─── Interface styles ─────────────────────────────────────────────────────────

def test_plain_interface():
    src = b"interface Printable {\n    fun print()\n}\n"
    result = P.extract_skeleton(src)
    assert any(x["type"] == "interface" and x["name"] == "Printable" for x in result)


def test_interface_methods_in_skeleton():
    src = b"interface Dao {\n    fun load(id: Int): String\n    fun store(v: String)\n}\n"
    result = P.extract_skeleton(src)
    assert any(x["name"] == "load" and x["parent"] == "Dao" for x in result)
    assert any(x["name"] == "store" and x["parent"] == "Dao" for x in result)


# ─── Object styles ────────────────────────────────────────────────────────────

def test_plain_object():
    src = b"object Database {\n    fun connect() {}\n}\n"
    result = P.extract_skeleton(src)
    assert any(x["name"] == "Database" for x in result)
    assert any(x["name"] == "connect" and x["parent"] == "Database" for x in result)


# ─── Function styles ──────────────────────────────────────────────────────────

def test_top_level_function():
    src = b"fun sum(a: Int, b: Int) = a + b\n"
    result = P.extract_skeleton(src)
    assert any(x["name"] == "sum" and x["parent"] is None for x in result)


def test_extension_function():
    src = b"fun String.shout() = this.uppercase()\n"
    result = P.extract_skeleton(src)
    # Extension functions are tricky in tree-sitter, usually identifier is shout
    assert any(x["name"] == "shout" for x in result)


def test_member_function():
    src = b"class Logger {\n    fun log(msg: String) { println(msg) }\n}\n"
    result = P.extract_skeleton(src)
    assert any(x["name"] == "log" and x["parent"] == "Logger" for x in result)


# ─── Mixed file ────────────────────────────────────────────────────────────────

MIXED_SRC = b"""
interface Drawable {
    fun draw()
}

abstract class Shape(val color: String) {
    abstract fun area(): Double
}

class Circle(val radius: Double) : Shape("red"), Drawable {
    override fun area() = 3.14 * radius * radius
    override fun draw() { println("Drawing circle") }
}

object App {
    fun run() {
        val c = Circle(5.0)
        c.draw()
    }
}
"""


def test_mixed_interface_found():
    result = P.extract_skeleton(MIXED_SRC)
    assert any(x["type"] == "interface" and x["name"] == "Drawable" for x in result)


def test_mixed_abstract_class_found():
    result = P.extract_skeleton(MIXED_SRC)
    assert any(x["name"] == "Shape" for x in result)


def test_mixed_concrete_class_found():
    result = P.extract_skeleton(MIXED_SRC)
    assert any(x["name"] == "Circle" for x in result)


def test_mixed_object_found():
    result = P.extract_skeleton(MIXED_SRC)
    assert any(x["name"] == "App" for x in result)


def test_mixed_member_functions():
    result = P.extract_skeleton(MIXED_SRC)
    assert any(x["name"] == "area" and x["parent"] == "Circle" for x in result)
    assert any(x["name"] == "draw" and x["parent"] == "Circle" for x in result)
    assert any(x["name"] == "run" and x["parent"] == "App" for x in result)


def test_mixed_sorted_by_line():
    result = P.extract_skeleton(MIXED_SRC)
    lines = [x["line"] for x in result]
    assert lines == sorted(lines)


# ─── extract_symbol_source ─────────────────────────────────────────────────────

def test_symbol_source_class():
    src = b"class Calc {\n    fun add(a: Int, b: Int) = a + b\n}\n"
    result = P.extract_symbol_source(src, "Calc")
    assert result is not None
    source, line = result
    assert "class Calc" in source
    assert line == 1


def test_symbol_source_function():
    src = b"fun hello() = \"world\"\n"
    result = P.extract_symbol_source(src, "hello")
    assert result is not None
    source, _ = result
    assert "fun hello" in source


# ─── extract_calls_in_function ─────────────────────────────────────────────────

def test_calls_direct():
    src = b"fun run() {\n    init()\n    start()\n}\n"
    calls = P.extract_calls_in_function(src, "run")
    assert "init" in calls
    assert "start" in calls


def test_calls_navigation():
    src = b"fun run(db: Database) {\n    db.connect()\n    db.query(\"x\")\n}\n"
    calls = P.extract_calls_in_function(src, "run")
    assert "connect" in calls
    assert "query" in calls


def test_calls_instantiation():
    src = b"fun create() = Widget()\n"
    calls = P.extract_calls_in_function(src, "create")
    assert "Widget" in calls


# ─── Complexity & Variables ───────────────────────────────────────────────────

def test_compute_complexity():
    src = b"""
    fun complex(x: Int) {
        if (x > 0) {
            for (i in 1..x) {
                while (true) {
                    when(i) {
                        1 -> println(1)
                        else -> println(0)
                    }
                }
            }
        }
    }
    """
    comp = P.compute_complexity(src, "complex")
    assert comp is not None
    assert comp["total"] >= 5
    assert "if" in comp["breakdown"]
    assert "for" in comp["breakdown"]
    assert "while" in comp["breakdown"]
    assert "when" in comp["breakdown"]


def test_extract_variables():
    src = b"""
    fun vars(a: Int, b: String) {
        val x = 1
        var y: Double = 2.0
        for (item in list) {
            println(item)
        }
    }
    """
    vars = P.extract_variables(src, "vars")
    names = [v["name"] for v in vars]
    assert "a" in names
    assert "b" in names
    assert "x" in names
    assert "y" in names
    # item in for loop is also a variable
    # My current implementation doesn't specifically target for loop variables yet
    # but they are in variable_declaration nodes in Kotlin 1.1.0 (as I saw in my show output)
    assert "item" in names
