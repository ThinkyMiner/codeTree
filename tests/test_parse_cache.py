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
