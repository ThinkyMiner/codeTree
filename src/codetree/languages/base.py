import threading
from abc import ABC, abstractmethod
from collections import OrderedDict

from tree_sitter import Query, QueryCursor


# Compiling a tree-sitter Query costs several milliseconds (more than parsing a
# whole file), so compiled queries are memoized per (language, pattern).
# Bounded because some patterns interpolate a symbol name.
_QUERY_CACHE_MAX = 2048
_QUERY_CACHE: "OrderedDict[tuple[int, str], tuple[object, Query]]" = OrderedDict()
_QUERY_CACHE_LOCK = threading.Lock()


def _query(lang, pattern: str) -> Query:
    """Return a compiled Query for (lang, pattern), compiling it at most once."""
    key = (id(lang), pattern)
    with _QUERY_CACHE_LOCK:
        hit = _QUERY_CACHE.get(key)
        if hit is not None:
            _QUERY_CACHE.move_to_end(key)
            return hit[1]
    query = Query(lang, pattern)
    with _QUERY_CACHE_LOCK:
        # Keep a reference to lang so its id() cannot be reused while cached.
        _QUERY_CACHE[key] = (lang, query)
        if len(_QUERY_CACHE) > _QUERY_CACHE_MAX:
            _QUERY_CACHE.popitem(last=False)
    return query


class CachedParser:
    """Wrap a tree-sitter Parser and reuse trees for recently parsed sources.

    Graph building and call-graph construction ask the same plugin about many
    functions of one file in a row; without this every call re-parses the file.
    The cache is per thread (trees are not shared across threads) and keyed by
    the source bytes, so a changed file can never return a stale tree. It only
    needs to cover consecutive calls on one file, so it stays tiny: every
    FastMCP worker thread holds its own copy.
    """

    _MAX_TREES = 2

    def __init__(self, parser):
        self._parser = parser
        self._local = threading.local()

    def parse(self, source: bytes):
        trees = getattr(self._local, "trees", None)
        if trees is None:
            trees = self._local.trees = OrderedDict()
        tree = trees.get(source)
        if tree is not None:
            trees.move_to_end(source)
            return tree
        tree = self._parser.parse(source)
        trees[source] = tree
        if len(trees) > self._MAX_TREES:
            trees.popitem(last=False)
        return tree


def _clean_doc(text: str) -> str:
    """Extract the first meaningful line from a doc comment."""
    lines = text.strip().splitlines()
    for line in lines:
        stripped = line.strip().lstrip("/*#!> ").rstrip("*/").strip()
        if stripped:
            return stripped
    return ""


def _fill_docs_from_siblings(results: list[dict], tree_root, lang, queries: list[str]) -> None:
    """Fill 'doc' field in skeleton items by checking prev_named_sibling of definition nodes.

    For multi-line doc comments (Go //, Rust ///), walks back through consecutive
    comment siblings with no blank lines between them to find the first line.
    For block comments (Java/JS /** */), the whole comment is a single node.
    """
    comment_types = ("comment", "line_comment", "block_comment")
    for q_str in queries:
        for _, m in _matches(_query(lang, q_str), tree_root):
            node = m["def"]
            name = m["name"].text.decode("utf-8", errors="replace")
            line = m["name"].start_point[0] + 1
            prev = node.prev_named_sibling
            doc = ""
            if prev and prev.type in comment_types:
                # Walk back through consecutive comment siblings to find the first one
                first_comment = prev
                while True:
                    pp = first_comment.prev_named_sibling
                    if pp and pp.type in comment_types:
                        # Consecutive = no blank lines between them
                        if pp.end_point[0] + 1 >= first_comment.start_point[0]:
                            first_comment = pp
                            continue
                    break
                doc = _clean_doc(first_comment.text.decode("utf-8", errors="replace"))
            for item in results:
                if item["name"] == name and item["line"] == line:
                    item["doc"] = doc
                    break


def _matches(query: Query, node) -> list[tuple[int, dict]]:
    """Run a query and return matches with captures unwrapped to single nodes.

    In tree-sitter 0.25.x, each capture value is a list of nodes.
    This helper unwraps to a single node (first element) for convenience.
    """
    cursor = QueryCursor(query)
    result = []
    for pattern_idx, match in cursor.matches(node):
        unwrapped = {
            name: nodes[0] if isinstance(nodes, list) and nodes else nodes
            for name, nodes in match.items()
        }
        result.append((pattern_idx, unwrapped))
    return result


class LanguagePlugin(ABC):
    """Abstract base class for all language plugins.

    To add a new language, copy `languages/_template.py`, implement all
    4 abstract methods, and register your plugin in `registry.py`.
    """

    extensions: tuple[str, ...]  # e.g. (".py",) or (".js", ".jsx")

    @abstractmethod
    def extract_skeleton(self, source: bytes) -> list[dict]:
        """Return top-level symbols in the file.

        Each dict must have keys:
          - type: "class" | "function" | "method" | "struct" | "interface" | "trait" | "enum" | "type"
          - name: str
          - line: int (1-based)
          - parent: str | None  (class name for methods, None for top-level)
          - params: str  (parameter list as string, e.g. "(a, b)" or "")
        """

    @abstractmethod
    def extract_symbol_source(self, source: bytes, name: str) -> tuple[str, int] | None:
        """Return (source_text, start_line) for a named function/class.

        Returns None if the symbol is not found.
        start_line is 1-based.
        """

    @abstractmethod
    def extract_calls_in_function(self, source: bytes, fn_name: str) -> list[str]:
        """Return sorted list of function/method names called inside fn_name.

        Returns empty list if fn_name is not found.
        """

    @abstractmethod
    def extract_symbol_usages(self, source: bytes, name: str) -> list[dict]:
        """Return all occurrences of name as an identifier.

        Each dict has keys:
          - line: int (1-based)
          - col: int (0-based)

        Includes definition sites. Use find_references in the indexer for
        cross-file usage.
        """

    @abstractmethod
    def extract_imports(self, source: bytes) -> list[dict]:
        """Return import/use statements in the file.

        Each dict has keys:
          - line: int (1-based)
          - text: str (raw import statement text, stripped of trailing newline)
        """

    def extract_variables(self, source: bytes, fn_name: str) -> list[dict]:
        """Return local variables declared inside a function.

        Each dict has keys:
          - name: str (variable name)
          - line: int (1-based)
          - type: str (type annotation if present, else "")
          - kind: str ("local" | "parameter" | "loop_var")

        Default returns empty list. Override per language.
        """
        return []

    def compute_complexity(self, source: bytes, fn_name: str) -> dict | None:
        """Return cyclomatic complexity breakdown for a function.

        Returns None if function not found.
        Returns dict with keys:
          - total: int (cyclomatic complexity)
          - breakdown: dict[str, int] (readable_type -> count)
        """
        return None

    def check_syntax(self, source: bytes) -> bool:
        """Return True if the source has syntax errors."""
        return False

    def get_ast_sexp(self, source: bytes, symbol_name: str | None = None, max_depth: int = -1) -> str | None:
        """Return S-expression representation of the AST with line positions.

        Args:
            source: source code bytes
            symbol_name: if given, return AST for just this symbol
            max_depth: limit depth (-1 = unlimited)
        Returns:
            S-expression string, or None if symbol_name given but not found.
        """
        try:
            parser = self._get_parser()
        except AttributeError:
            return None

        tree = parser.parse(source)
        root = tree.root_node

        if symbol_name:
            result = self.extract_symbol_source(source, symbol_name)
            if result is None:
                return None
            _, start_line = result
            target_line = start_line - 1  # convert to 0-based

            def find_node(node, target_line):
                if node.start_point[0] == target_line and node.type not in ("module", "program", "translation_unit", "source_file"):
                    return node
                for child in node.children:
                    found = find_node(child, target_line)
                    if found:
                        return found
                return None

            found = find_node(root, target_line)
            if found is None:
                return None
            root = found

        def format_node(node, depth=0, current_depth=0):
            indent = "  " * depth
            pos = f"[{node.start_point[0]+1}:{node.start_point[1]}-{node.end_point[0]+1}:{node.end_point[1]}]"

            if max_depth >= 0 and current_depth > max_depth:
                return None

            if not node.children:
                text = node.text.decode("utf-8", errors="replace")
                if node.is_named:
                    return f"{indent}({node.type} {pos} {repr(text)})"
                else:
                    return f"{indent}{repr(text)}"

            if max_depth >= 0 and current_depth == max_depth:
                return f"{indent}({node.type} {pos} ...)"

            child_strs = []
            for child in node.children:
                cs = format_node(child, depth + 1, current_depth + 1)
                if cs:
                    child_strs.append(cs)

            if child_strs:
                children = "\n".join(child_strs)
                return f"{indent}({node.type} {pos}\n{children})"
            else:
                return f"{indent}({node.type} {pos})"

        return format_node(root)

    def normalize_source_for_clones(self, source: bytes) -> str:
        """Normalize source for clone detection.

        Replaces identifiers, strings, and numbers with placeholders
        so that structurally identical code with renamed variables
        produces the same normalized form.
        """
        try:
            parser = self._get_parser()
        except AttributeError:
            return source.decode("utf-8", errors="replace")

        tree = parser.parse(source)

        identifier_types = {
            "identifier", "type_identifier", "field_identifier",
            "property_identifier", "shorthand_property_identifier",
            "constant", "namespace_identifier",
        }
        string_types = {
            "string", "string_literal", "template_string",
            "raw_string_literal", "interpreted_string_literal",
            "string_content", "encapsed_string",
        }
        number_types = {
            "integer", "float", "number", "integer_literal",
            "float_literal", "decimal_integer_literal",
            "decimal_floating_point_literal",
        }
        comment_types = {"comment", "line_comment", "block_comment"}

        parts = []

        def walk(node):
            if node.type in comment_types:
                return
            if not node.children or node.type in identifier_types | string_types | number_types:
                if node.type in identifier_types:
                    parts.append("_ID_")
                elif node.type in string_types:
                    parts.append("_STR_")
                elif node.type in number_types:
                    parts.append("_NUM_")
                else:
                    parts.append(node.text.decode("utf-8", errors="replace"))
            else:
                for child in node.children:
                    walk(child)

        walk(tree.root_node)
        return " ".join(parts)
