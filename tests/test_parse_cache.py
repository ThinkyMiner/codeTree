"""Tests for the compiled-query cache and the per-thread parse-tree cache."""

import threading
from collections import OrderedDict

from tree_sitter import Language, Parser
import tree_sitter_python as tspython

from codetree.languages import base
from codetree.languages.base import CachedParser, _query
from codetree.languages.python import PythonPlugin

_LANG = Language(tspython.language())


def test_query_is_compiled_once_per_pattern():
    pattern = "(function_definition name: (identifier) @name) @def"
    assert _query(_LANG, pattern) is _query(_LANG, pattern)


def test_query_cache_is_bounded(monkeypatch):
    monkeypatch.setattr(base, "_QUERY_CACHE_MAX", 3)
    monkeypatch.setattr(base, "_QUERY_CACHE", OrderedDict())  # leave the shared cache intact
    for index in range(10):
        _query(_LANG, f'((identifier) @name (#eq? @name "n{index}"))')
    assert len(base._QUERY_CACHE) == 3


def test_cached_parser_reuses_tree_for_same_source():
    parser = CachedParser(Parser(_LANG))
    source = b"def foo():\n    pass\n"
    assert parser.parse(source) is parser.parse(bytes(source))


def test_cached_parser_never_returns_stale_tree():
    parser = CachedParser(Parser(_LANG))
    first = parser.parse(b"def foo():\n    pass\n")
    second = parser.parse(b"def bar():\n    pass\n")
    assert first is not second
    assert b"bar" in second.root_node.text


def test_cached_parser_is_bounded():
    parser = CachedParser(Parser(_LANG))
    for index in range(CachedParser._MAX_TREES + 5):
        parser.parse(f"x{index} = 1\n".encode())
    assert len(parser._local.trees) == CachedParser._MAX_TREES


def test_cached_parser_does_not_share_trees_across_threads():
    parser = CachedParser(Parser(_LANG))
    source = b"def foo():\n    pass\n"
    main_tree = parser.parse(source)
    other = {}
    thread = threading.Thread(target=lambda: other.setdefault("tree", parser.parse(source)))
    thread.start()
    thread.join()
    assert other["tree"] is not main_tree


def test_plugin_results_unchanged_when_calls_hit_cache():
    plugin = PythonPlugin()
    source = b"def a():\n    b()\n    c()\n\ndef b():\n    c()\n\ndef c():\n    pass\n"
    assert plugin.extract_calls_in_function(source, "a") == ["b", "c"]
    assert plugin.extract_calls_in_function(source, "b") == ["c"]
    assert plugin.extract_calls_in_function(source, "c") == []
    assert [item["name"] for item in plugin.extract_skeleton(source)] == ["a", "b", "c"]


_JS_SOURCE = b"""
function foo() { fromDeclaration(); }
const arrow = () => { fromArrow(); };
class Widget {
  foo() { fromMethod(); }
  render() { fromRender(); }
}
"""


def _fresh_definition_maps(monkeypatch):
    monkeypatch.setattr(base, "_DEFINITIONS_LOCAL", threading.local())


def test_js_call_lookups_scan_the_tree_once_per_pattern(monkeypatch):
    from codetree.languages.javascript import JavaScriptPlugin, _CALLABLE_PATTERNS

    _fresh_definition_maps(monkeypatch)
    root_scans = []
    real_matches = base._matches

    def counting_matches(query, node):
        root_scans.append(node)
        return real_matches(query, node)

    monkeypatch.setattr(base, "_matches", counting_matches)
    plugin = JavaScriptPlugin()
    for name in ("foo", "arrow", "render", "missing"):
        plugin.extract_calls_in_function(_JS_SOURCE, name)
    assert len(root_scans) == len(_CALLABLE_PATTERNS)


def test_js_call_lookup_keeps_first_definition_order():
    from codetree.languages.javascript import JavaScriptPlugin

    plugin = JavaScriptPlugin()
    # A declaration shadows a same-named method, as the per-name scan did.
    assert plugin.extract_calls_in_function(_JS_SOURCE, "foo") == ["fromDeclaration"]
    assert plugin.extract_calls_in_function(_JS_SOURCE, "arrow") == ["fromArrow"]
    assert plugin.extract_calls_in_function(_JS_SOURCE, "render") == ["fromRender"]
    assert plugin.extract_calls_in_function(_JS_SOURCE, "missing") == []


def test_definition_maps_are_bounded(monkeypatch):
    from codetree.languages.javascript import JavaScriptPlugin

    _fresh_definition_maps(monkeypatch)
    monkeypatch.setattr(base, "_DEFINITIONS_MAX", 2)
    plugin = JavaScriptPlugin()
    for index in range(5):
        plugin.extract_calls_in_function(f"function f{index}() {{ g(); }}\n".encode(), f"f{index}")
    assert len(base._DEFINITIONS_LOCAL.maps) == 2


def test_python_call_lookups_scan_the_tree_once_per_pattern(monkeypatch):
    from codetree.languages.python import _CALLABLE_PATTERNS

    _fresh_definition_maps(monkeypatch)
    root_scans = []
    real_matches = base._matches

    def counting_matches(query, node):
        root_scans.append(node)
        return real_matches(query, node)

    monkeypatch.setattr(base, "_matches", counting_matches)
    plugin = PythonPlugin()
    source = b"@decorated\ndef a():\n    b()\n\ndef b():\n    c()\n\ndef c():\n    pass\n"
    assert plugin.extract_calls_in_function(source, "a") == ["b"]
    assert plugin.extract_calls_in_function(source, "b") == ["c"]
    assert plugin.extract_calls_in_function(source, "missing") == []
    assert len(root_scans) == len(_CALLABLE_PATTERNS)
