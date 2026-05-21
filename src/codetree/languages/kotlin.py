from tree_sitter import Language, Parser, Query
import tree_sitter_kotlin as tskotlin
from .base import LanguagePlugin, _matches, _fill_docs_from_siblings

_LANGUAGE = Language(tskotlin.language())
_PARSER = Parser(_LANGUAGE)


def _parse(source: bytes):
    return _PARSER.parse(source)


class KotlinPlugin(LanguagePlugin):
    extensions = (".kt",)

    def extract_skeleton(self, source: bytes) -> list[dict]:
        tree = _parse(source)
        results = []

        # Top-level classes / interfaces (both use class_declaration)
        q = Query(_LANGUAGE, "(source_file (class_declaration (identifier) @name) @def)")
        for _, m in _matches(q, tree.root_node):
            node_def = m["def"]
            # Check if it's an interface
            sym_type = "class"
            for child in node_def.children:
                if child.type == "interface":
                    sym_type = "interface"
                    break

            results.append({
                "type": sym_type,
                "name": m["name"].text.decode("utf-8", errors="replace"),
                "line": m["name"].start_point[0] + 1,
                "parent": None,
                "params": "",
            })

        # Top-level objects
        q = Query(_LANGUAGE, "(source_file (object_declaration (identifier) @name) @def)")
        for _, m in _matches(q, tree.root_node):
            results.append({
                "type": "class",
                "name": m["name"].text.decode("utf-8", errors="replace"),
                "line": m["name"].start_point[0] + 1,
                "parent": None,
                "params": "",
            })

        # Top-level functions
        q = Query(_LANGUAGE, "(source_file (function_declaration (identifier) @name (function_value_parameters) @params) @def)")
        for _, m in _matches(q, tree.root_node):
            results.append({
                "type": "function",
                "name": m["name"].text.decode("utf-8", errors="replace"),
                "line": m["name"].start_point[0] + 1,
                "parent": None,
                "params": m["params"].text.decode("utf-8", errors="replace"),
            })

        # Methods inside classes/interfaces
        q = Query(_LANGUAGE, """
            (class_declaration
                (identifier) @class_name
                (class_body
                    (function_declaration
                        (identifier) @method_name
                        (function_value_parameters) @params)))
        """)
        for _, m in _matches(q, tree.root_node):
            results.append({
                "type": "method",
                "name": m["method_name"].text.decode("utf-8", errors="replace"),
                "line": m["method_name"].start_point[0] + 1,
                "parent": m["class_name"].text.decode("utf-8", errors="replace"),
                "params": m["params"].text.decode("utf-8", errors="replace"),
            })

        # Methods inside objects
        q = Query(_LANGUAGE, """
            (object_declaration
                (identifier) @class_name
                (class_body
                    (function_declaration
                        (identifier) @method_name
                        (function_value_parameters) @params)))
        """)
        for _, m in _matches(q, tree.root_node):
            results.append({
                "type": "method",
                "name": m["method_name"].text.decode("utf-8", errors="replace"),
                "line": m["method_name"].start_point[0] + 1,
                "parent": m["class_name"].text.decode("utf-8", errors="replace"),
                "params": m["params"].text.decode("utf-8", errors="replace"),
            })

        # Fill doc fields from preceding comments
        for item in results:
            item.setdefault("doc", "")
        _fill_docs_from_siblings(results, tree.root_node, _LANGUAGE, [
            "(class_declaration (identifier) @name) @def",
            "(object_declaration (identifier) @name) @def",
            "(function_declaration (identifier) @name) @def",
        ])

        results.sort(key=lambda x: x["line"])
        return results

    def extract_symbol_source(self, source: bytes, name: str) -> tuple[str, int] | None:
        tree = _parse(source)

        # Classes, objects
        for q_str in [
            "(class_declaration (identifier) @name) @def",
            "(object_declaration (identifier) @name) @def",
        ]:
            for _, m in _matches(Query(_LANGUAGE, q_str), tree.root_node):
                if m["name"].text.decode("utf-8", errors="replace") == name:
                    node = m["def"]
                    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace"), node.start_point[0] + 1

        # Functions/Methods
        q = Query(_LANGUAGE, "(function_declaration (identifier) @name) @def")
        for _, m in _matches(q, tree.root_node):
            if m["name"].text.decode("utf-8", errors="replace") == name:
                node = m["def"]
                return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace"), node.start_point[0] + 1

        return None

    def extract_calls_in_function(self, source: bytes, fn_name: str) -> list[str]:
        tree = _parse(source)
        fn_node = None
        q = Query(_LANGUAGE, "(function_declaration (identifier) @name) @def")
        for _, m in _matches(q, tree.root_node):
            if m["name"].text.decode("utf-8", errors="replace") == fn_name:
                fn_node = m["def"]
                break
        if fn_node is None:
            return []

        calls = set()
        # Method calls: foo(), foo.bar()
        q = Query(_LANGUAGE, """
            (call_expression
                [
                    (identifier) @called
                    (navigation_expression (identifier) @called)
                ])
        """)
        for _, m in _matches(q, fn_node):
            node = m["called"]
            if node.parent and node.parent.type == "navigation_expression":
                ids = [c for c in node.parent.children if c.type == "identifier"]
                if ids and node == ids[-1]:
                    calls.add(node.text.decode("utf-8", errors="replace"))
            else:
                calls.add(node.text.decode("utf-8", errors="replace"))

        return sorted(calls)

    def extract_symbol_usages(self, source: bytes, name: str) -> list[dict]:
        tree = _parse(source)
        usages = []
        seen = set()
        # Kotlin uses identifier for most things
        q = Query(_LANGUAGE, f'((identifier) @name (#eq? @name "{name}"))')
        for _, m in _matches(q, tree.root_node):
            node = m["name"]
            key = (node.start_point[0], node.start_point[1])
            if key not in seen:
                seen.add(key)
                usages.append({"line": node.start_point[0] + 1, "col": node.start_point[1]})

        usages.sort(key=lambda x: (x["line"], x["col"]))
        return usages

    def extract_imports(self, source: bytes) -> list[dict]:
        tree = _parse(source)
        results = []
        q = Query(_LANGUAGE, "(import) @imp")
        for _, m in _matches(q, tree.root_node):
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
        q = Query(_LANGUAGE, "(function_declaration (identifier) @name) @def")
        for _, m in _matches(q, tree.root_node):
            if m["name"].text.decode("utf-8", errors="replace") == fn_name:
                fn_node = m["def"]
                break
        if fn_node is None:
            return None

        branch_map = {
            "if_expression": "if",
            "for_statement": "for",
            "while_statement": "while",
            "do_while_statement": "do_while",
            "catch_block": "catch",
            "when_expression": "when",
            "when_entry": "case",
        }
        counts: dict[str, int] = {}

        def walk(node):
            if node.type in branch_map:
                label = branch_map[node.type]
                counts[label] = counts.get(label, 0) + 1
            elif node.type in ("&&", "||"):
                counts[node.type] = counts.get(node.type, 0) + 1
            for child in node.children:
                walk(child)

        walk(fn_node)
        total = 1 + sum(counts.values())
        return {"total": total, "breakdown": counts}

    def extract_variables(self, source: bytes, fn_name: str) -> list[dict]:
        tree = _parse(source)
        fn_node = None
        q = Query(_LANGUAGE, "(function_declaration (identifier) @name) @def")
        for _, m in _matches(q, tree.root_node):
            if m["name"].text.decode("utf-8", errors="replace") == fn_name:
                fn_node = m["def"]
                break
        if fn_node is None:
            return []

        results = []
        seen = set()

        def _add(name, line, var_type="", kind="local"):
            if name not in seen:
                seen.add(name)
                results.append({"name": name, "line": line, "type": var_type, "kind": kind})

        # Parameters
        q_params = Query(_LANGUAGE, "(parameter (identifier) @name (user_type)? @type)")
        for _, m in _matches(q_params, fn_node):
             type_text = m.get("type").text.decode("utf-8", errors="replace") if m.get("type") else ""
             _add(m["name"].text.decode("utf-8", errors="replace"),
                  m["name"].start_point[0] + 1,
                  var_type=type_text,
                  kind="parameter")

        # Local variables (val/var)
        q_vars = Query(_LANGUAGE, "(variable_declaration (identifier) @name (user_type)? @type)")
        for _, m in _matches(q_vars, fn_node):
            type_text = m.get("type").text.decode("utf-8", errors="replace") if m.get("type") else ""
            _add(m["name"].text.decode("utf-8", errors="replace"),
                 m["name"].start_point[0] + 1,
                 var_type=type_text,
                 kind="local")

        return results

    def check_syntax(self, source: bytes) -> bool:
        return _parse(source).root_node.has_error

    def _get_parser(self):
        return _PARSER

    def _get_language(self):
        return _LANGUAGE
