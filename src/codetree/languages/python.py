from tree_sitter import Language, Parser
import tree_sitter_python as tspython
from .base import LanguagePlugin, _matches, _clean_doc, _query, CachedParser

_LANGUAGE = Language(tspython.language())
_PARSER = CachedParser(Parser(_LANGUAGE))


def _parse(source: bytes):
    return _PARSER.parse(source)


def _fn_params(fn_node) -> str:
    """Extract params text from a function_definition node."""
    for child in fn_node.children:
        if child.type == "parameters":
            return child.text.decode("utf-8", errors="replace")
    return "()"


class PythonPlugin(LanguagePlugin):
    extensions = (".py",)

    def extract_skeleton(self, source: bytes) -> list[dict]:
        tree = _parse(source)
        results = []

        # Top-level classes — plain and decorated
        for q_str in [
            "(module (class_definition name: (identifier) @name) @def)",
            "(module (decorated_definition (class_definition name: (identifier) @name)) @def)",
        ]:
            for _, m in _matches(_query(_LANGUAGE, q_str), tree.root_node):
                results.append({
                    "type": "class",
                    "name": m["name"].text.decode("utf-8", errors="replace"),
                    "line": m["name"].start_point[0] + 1,
                    "parent": None,
                    "params": "",
                })

        # Methods inside classes — plain and decorated
        for q_str in [
            """(class_definition
                name: (identifier) @class_name
                body: (block
                    (function_definition
                        name: (identifier) @method_name
                        parameters: (parameters) @params)))""",
            """(class_definition
                name: (identifier) @class_name
                body: (block
                    (decorated_definition
                        (function_definition
                            name: (identifier) @method_name
                            parameters: (parameters) @params))))""",
        ]:
            for _, m in _matches(_query(_LANGUAGE, q_str), tree.root_node):
                results.append({
                    "type": "method",
                    "name": m["method_name"].text.decode("utf-8", errors="replace"),
                    "line": m["method_name"].start_point[0] + 1,
                    "parent": m["class_name"].text.decode("utf-8", errors="replace"),
                    "params": m["params"].text.decode("utf-8", errors="replace"),
                })

        # Top-level functions — plain and decorated
        for q_str in [
            """(module (function_definition
                name: (identifier) @name
                parameters: (parameters) @params))""",
            """(module (decorated_definition
                (function_definition
                    name: (identifier) @name
                    parameters: (parameters) @params)) @def)""",
        ]:
            for _, m in _matches(_query(_LANGUAGE, q_str), tree.root_node):
                results.append({
                    "type": "function",
                    "name": m["name"].text.decode("utf-8", errors="replace"),
                    "line": m["name"].start_point[0] + 1,
                    "parent": None,
                    "params": m["params"].text.decode("utf-8", errors="replace"),
                })

        # Set default doc field
        for item in results:
            item["doc"] = ""

        # Fill doc fields — Python docstrings are first string in function/class body
        for q_str in [
            '(class_definition name: (identifier) @name body: (block (expression_statement (string) @doc)))',
            '(function_definition name: (identifier) @name body: (block (expression_statement (string) @doc)))',
        ]:
            for _, m in _matches(_query(_LANGUAGE, q_str), tree.root_node):
                name = m["name"].text.decode("utf-8", errors="replace")
                line = m["name"].start_point[0] + 1
                doc_text = m["doc"].text.decode("utf-8", errors="replace")
                for q in ('"""', "'''"):
                    if doc_text.startswith(q) and doc_text.endswith(q):
                        doc_text = doc_text[3:-3]
                        break
                first_line = doc_text.strip().splitlines()[0].strip() if doc_text.strip() else ""
                for item in results:
                    if item["name"] == name and item["line"] == line:
                        item["doc"] = first_line
                        break

        # Deduplicate by (name, line) — queries can overlap on edge cases
        seen = set()
        deduped = []
        for item in results:
            key = (item["name"], item["line"])
            if key not in seen:
                seen.add(key)
                deduped.append(item)

        deduped.sort(key=lambda x: x["line"])
        return deduped

    def extract_symbol_source(self, source: bytes, name: str) -> tuple[str, int] | None:
        tree = _parse(source)
        for node_type in ("function_definition", "class_definition"):
            # Decorated definition first — return full decorated_definition (includes decorator)
            q = _query(_LANGUAGE, f"(decorated_definition ({node_type} name: (identifier) @name)) @def")
            for _, m in _matches(q, tree.root_node):
                if m["name"].text.decode("utf-8", errors="replace") == name:
                    node = m["def"]
                    return (
                        source[node.start_byte:node.end_byte].decode("utf-8", errors="replace"),
                        node.start_point[0] + 1,
                    )
            # Plain definition (not decorated)
            q = _query(_LANGUAGE, f"({node_type} name: (identifier) @name) @def")
            for _, m in _matches(q, tree.root_node):
                if m["name"].text.decode("utf-8", errors="replace") == name:
                    node = m["def"]
                    return (
                        source[node.start_byte:node.end_byte].decode("utf-8", errors="replace"),
                        node.start_point[0] + 1,
                    )
        return None

    def extract_calls_in_function(self, source: bytes, fn_name: str) -> list[str]:
        tree = _parse(source)
        fn_node = None
        # Search plain and decorated function definitions
        for q_str in [
            "(function_definition name: (identifier) @name) @def",
            "(decorated_definition (function_definition name: (identifier) @name)) @def",
        ]:
            for _, m in _matches(_query(_LANGUAGE, q_str), tree.root_node):
                if m["name"].text.decode("utf-8", errors="replace") == fn_name:
                    fn_node = m["def"]
                    break
            if fn_node is not None:
                break
        if fn_node is None:
            return []
        q = _query(_LANGUAGE, """
            (call function: [
                (identifier) @called
                (attribute attribute: (identifier) @called)
            ])
        """)
        calls = set()
        for _, m in _matches(q, fn_node):
            calls.add(m["called"].text.decode("utf-8", errors="replace"))
        return sorted(calls)

    def extract_symbol_usages(self, source: bytes, name: str) -> list[dict]:
        tree = _parse(source)
        q = _query(_LANGUAGE, f'((identifier) @name (#eq? @name "{name}"))')
        usages = []
        for _, m in _matches(q, tree.root_node):
            node = m["name"]
            usages.append({"line": node.start_point[0] + 1, "col": node.start_point[1]})
        return usages

    def extract_imports(self, source: bytes) -> list[dict]:
        tree = _parse(source)
        results = []
        for q_str in [
            "(module (import_statement) @imp)",
            "(module (import_from_statement) @imp)",
            "(module (future_import_statement) @imp)",
        ]:
            for _, m in _matches(_query(_LANGUAGE, q_str), tree.root_node):
                node = m["imp"]
                results.append({
                    "line": node.start_point[0] + 1,
                    "text": node.text.decode("utf-8", errors="replace").strip(),
                })
        results.sort(key=lambda x: x["line"])
        return results

    def compute_complexity(self, source: bytes, fn_name: str) -> dict | None:
        tree = _parse(source)
        fn_node = None
        for q_str in [
            "(function_definition name: (identifier) @name) @def",
            "(decorated_definition (function_definition name: (identifier) @name)) @def",
        ]:
            for _, m in _matches(_query(_LANGUAGE, q_str), tree.root_node):
                if m["name"].text.decode("utf-8", errors="replace") == fn_name:
                    fn_node = m["def"]
                    break
            if fn_node is not None:
                break
        if fn_node is None:
            return None

        branch_map = {
            "if_statement": "if",
            "elif_clause": "elif",
            "for_statement": "for",
            "while_statement": "while",
            "except_clause": "except",
            "with_statement": "with",
            "boolean_operator": "boolean_op",
        }
        counts: dict[str, int] = {}

        def walk(node):
            if node.type in branch_map:
                label = branch_map[node.type]
                counts[label] = counts.get(label, 0) + 1
            for child in node.children:
                walk(child)

        walk(fn_node)
        total = 1 + sum(counts.values())
        return {"total": total, "breakdown": counts}

    def extract_variables(self, source: bytes, fn_name: str) -> list[dict]:
        tree = _parse(source)

        # Find the function node (handles decorated functions too)
        fn_node = None
        for q_str in [
            "(decorated_definition definition: (function_definition name: (identifier) @name) @def)",
            "(function_definition name: (identifier) @name) @def",
        ]:
            for _, m in _matches(_query(_LANGUAGE, q_str), tree.root_node):
                if m["name"].text.decode("utf-8", errors="replace") == fn_name:
                    fn_node = m["def"]
                    break
            if fn_node:
                break
        if fn_node is None:
            return []

        results = []
        seen = set()

        def _add(name, line, var_type="", kind="local"):
            if name not in seen and name not in ("self", "cls"):
                seen.add(name)
                results.append({"name": name, "line": line, "type": var_type, "kind": kind})

        # Find actual function_definition node (may be inside decorated_definition)
        actual_fn = fn_node
        if fn_node.type == "decorated_definition":
            for child in fn_node.children:
                if child.type == "function_definition":
                    actual_fn = child
                    break

        # Extract parameters
        params_node = None
        for child in actual_fn.children:
            if child.type == "parameters":
                params_node = child
                break
        if params_node:
            for child in params_node.children:
                if child.type == "identifier":
                    name = child.text.decode("utf-8", errors="replace")
                    _add(name, child.start_point[0] + 1, kind="parameter")
                elif child.type in ("default_parameter", "typed_parameter", "typed_default_parameter"):
                    for sub in child.children:
                        if sub.type == "identifier":
                            name = sub.text.decode("utf-8", errors="replace")
                            var_type = ""
                            for sib in child.children:
                                if sib.type == "type":
                                    var_type = sib.text.decode("utf-8", errors="replace")
                                    break
                            _add(name, sub.start_point[0] + 1, var_type=var_type, kind="parameter")
                            break
                elif child.type in ("list_splat_pattern", "dictionary_splat_pattern"):
                    for sub in child.children:
                        if sub.type == "identifier":
                            _add(sub.text.decode("utf-8", errors="replace"),
                                 sub.start_point[0] + 1, kind="parameter")
                            break

        # Walk the function body for local assignments and loop vars
        def walk(node):
            if node.type == "assignment":
                # Only capture simple identifier targets (not self.x)
                target = node.children[0] if node.children else None
                if target and target.type == "identifier":
                    name = target.text.decode("utf-8", errors="replace")
                    var_type = ""
                    for child in node.children:
                        if child.type == "type":
                            var_type = child.text.decode("utf-8", errors="replace")
                            break
                    _add(name, target.start_point[0] + 1, var_type=var_type)
            elif node.type == "for_statement":
                # Loop variable: for X in ...
                for child in node.children:
                    if child.type == "identifier":
                        _add(child.text.decode("utf-8", errors="replace"),
                             child.start_point[0] + 1, kind="loop_var")
                        break
            for child in node.children:
                walk(child)

        # Find the function body (block)
        for child in actual_fn.children:
            if child.type == "block":
                walk(child)
                break

        return results

    def check_syntax(self, source: bytes) -> bool:
        return _parse(source).root_node.has_error

    def _get_parser(self):
        return _PARSER

    def _get_language(self):
        return _LANGUAGE
