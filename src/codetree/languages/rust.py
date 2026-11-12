from tree_sitter import Language, Parser
import tree_sitter_rust as tsrust
from .base import LanguagePlugin, _matches, _fill_docs_from_siblings, _query, CachedParser

_LANGUAGE = Language(tsrust.language())
_PARSER = CachedParser(Parser(_LANGUAGE))


def _parse(source: bytes):
    return _PARSER.parse(source)


class RustPlugin(LanguagePlugin):
    extensions = (".rs",)

    def extract_skeleton(self, source: bytes) -> list[dict]:
        tree = _parse(source)
        results = []

        # Structs
        q = _query(_LANGUAGE, "(source_file (struct_item name: (type_identifier) @name) @def)")
        for _, m in _matches(q, tree.root_node):
            results.append({
                "type": "struct",
                "name": m["name"].text.decode("utf-8", errors="replace"),
                "line": m["name"].start_point[0] + 1,
                "parent": None,
                "params": "",
            })

        # Enums
        q = _query(_LANGUAGE, "(source_file (enum_item name: (type_identifier) @name) @def)")
        for _, m in _matches(q, tree.root_node):
            results.append({
                "type": "enum",
                "name": m["name"].text.decode("utf-8", errors="replace"),
                "line": m["name"].start_point[0] + 1,
                "parent": None,
                "params": "",
            })

        # Traits
        q = _query(_LANGUAGE, "(source_file (trait_item name: (type_identifier) @name) @def)")
        for _, m in _matches(q, tree.root_node):
            results.append({
                "type": "trait",
                "name": m["name"].text.decode("utf-8", errors="replace"),
                "line": m["name"].start_point[0] + 1,
                "parent": None,
                "params": "",
            })

        # Methods inside impl blocks (both direct impl and trait impl)
        q = _query(_LANGUAGE, """
            (impl_item
                type: (type_identifier) @class_name
                body: (declaration_list
                    (function_item
                        name: (identifier) @method_name
                        parameters: (parameters) @params) @method_def))
        """)
        for _, m in _matches(q, tree.root_node):
            results.append({
                "type": "method",
                "name": m["method_name"].text.decode("utf-8", errors="replace"),
                "line": m["method_name"].start_point[0] + 1,
                "parent": m["class_name"].text.decode("utf-8", errors="replace"),
                "params": m["params"].text.decode("utf-8", errors="replace"),
            })

        # Method signatures inside traits (fn without body)
        q = _query(_LANGUAGE, """
            (trait_item
                name: (type_identifier) @trait_name
                body: (declaration_list
                    (function_signature_item
                        name: (identifier) @method_name
                        parameters: (parameters) @params)))
        """)
        for _, m in _matches(q, tree.root_node):
            results.append({
                "type": "method",
                "name": m["method_name"].text.decode("utf-8", errors="replace"),
                "line": m["method_name"].start_point[0] + 1,
                "parent": m["trait_name"].text.decode("utf-8", errors="replace"),
                "params": m["params"].text.decode("utf-8", errors="replace"),
            })

        # Default method implementations inside traits (fn with body)
        q = _query(_LANGUAGE, """
            (trait_item
                name: (type_identifier) @trait_name
                body: (declaration_list
                    (function_item
                        name: (identifier) @method_name
                        parameters: (parameters) @params) @method_def))
        """)
        for _, m in _matches(q, tree.root_node):
            results.append({
                "type": "method",
                "name": m["method_name"].text.decode("utf-8", errors="replace"),
                "line": m["method_name"].start_point[0] + 1,
                "parent": m["trait_name"].text.decode("utf-8", errors="replace"),
                "params": m["params"].text.decode("utf-8", errors="replace"),
            })

        # Top-level functions (direct children of source_file)
        q = _query(_LANGUAGE, """
            (source_file
                (function_item
                    name: (identifier) @name
                    parameters: (parameters) @params) @def)
        """)
        for _, m in _matches(q, tree.root_node):
            results.append({
                "type": "function",
                "name": m["name"].text.decode("utf-8", errors="replace"),
                "line": m["name"].start_point[0] + 1,
                "parent": None,
                "params": m["params"].text.decode("utf-8", errors="replace"),
            })

        # Fill doc fields from preceding comments
        for item in results:
            item.setdefault("doc", "")
        _fill_docs_from_siblings(results, tree.root_node, _LANGUAGE, [
            "(source_file (function_item name: (identifier) @name) @def)",
            "(source_file (struct_item name: (type_identifier) @name) @def)",
            "(source_file (enum_item name: (type_identifier) @name) @def)",
            "(source_file (trait_item name: (type_identifier) @name) @def)",
        ])

        # Deduplicate by (name, line)
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

        # Functions (top-level and inside impl blocks)
        q = _query(_LANGUAGE, "(function_item name: (identifier) @name) @def")
        for _, m in _matches(q, tree.root_node):
            if m["name"].text.decode("utf-8", errors="replace") == name:
                node = m["def"]
                return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace"), node.start_point[0] + 1

        # Structs, enums, and traits
        for q_str in [
            "(struct_item name: (type_identifier) @name) @def",
            "(enum_item name: (type_identifier) @name) @def",
            "(trait_item name: (type_identifier) @name) @def",
        ]:
            q = _query(_LANGUAGE, q_str)
            for _, m in _matches(q, tree.root_node):
                if m["name"].text.decode("utf-8", errors="replace") == name:
                    node = m["def"]
                    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace"), node.start_point[0] + 1

        return None

    def extract_calls_in_function(self, source: bytes, fn_name: str) -> list[str]:
        tree = _parse(source)
        fn_node = None
        q = _query(_LANGUAGE, "(function_item name: (identifier) @name) @def")
        for _, m in _matches(q, tree.root_node):
            if m["name"].text.decode("utf-8", errors="replace") == fn_name:
                fn_node = m["def"]
                break
        if fn_node is None:
            return []
        q = _query(_LANGUAGE, """
            (call_expression function: [
                (identifier) @called
                (field_expression field: (field_identifier) @called)
                (scoped_identifier name: (identifier) @called)
            ])
        """)
        calls = set()
        for _, m in _matches(q, fn_node):
            calls.add(m["called"].text.decode("utf-8", errors="replace"))
        return sorted(calls)

    def extract_symbol_usages(self, source: bytes, name: str) -> list[dict]:
        tree = _parse(source)
        usages = []
        seen = set()
        # Search both identifier and type_identifier nodes to cover value and
        # type positions (e.g. `let calc = Calculator;` uses identifier,
        # while `impl Calculator` uses type_identifier).
        for node_type in ("identifier", "type_identifier"):
            q = _query(_LANGUAGE, f'(({node_type}) @name (#eq? @name "{name}"))')
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
        q = _query(_LANGUAGE, "(source_file (use_declaration) @imp)")
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
        q = _query(_LANGUAGE, "(function_item name: (identifier) @name) @def")
        for _, m in _matches(q, tree.root_node):
            if m["name"].text.decode("utf-8", errors="replace") == fn_name:
                fn_node = m["def"]
                break
        if fn_node is None:
            return None

        branch_map = {
            "if_expression": "if",
            "for_expression": "for",
            "while_expression": "while",
            "match_arm": "match_arm",
            "try_expression": "try",
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

        # Find function node
        fn_node = None
        for _, m in _matches(_query(_LANGUAGE, "(function_item name: (identifier) @name) @def"), tree.root_node):
            if m["name"].text.decode("utf-8", errors="replace") == fn_name:
                fn_node = m["def"]
                break
        if fn_node is None:
            return []

        results = []
        seen = set()

        def _add(name, line, var_type="", kind="local"):
            if name not in seen and name != "_":
                seen.add(name)
                results.append({"name": name, "line": line, "type": var_type, "kind": kind})

        # Extract parameters from (parameters) node
        for child in fn_node.children:
            if child.type == "parameters":
                for param in child.children:
                    if param.type == "parameter":
                        type_text = ""
                        id_node = None
                        for sub in param.children:
                            if sub.type == "identifier":
                                id_node = sub
                            elif sub.type in ("primitive_type", "type_identifier",
                                              "scoped_type_identifier", "generic_type",
                                              "reference_type", "array_type", "abstract_type"):
                                type_text = sub.text.decode("utf-8", errors="replace")
                        if id_node:
                            _add(id_node.text.decode("utf-8", errors="replace"),
                                 id_node.start_point[0] + 1, var_type=type_text, kind="parameter")
                break

        # Walk the function body
        def walk(node):
            if node.type == "let_declaration":
                # let x: Type = expr  or  let x = expr
                id_node = None
                type_text = ""
                for child in node.children:
                    if child.type == "identifier":
                        id_node = child
                    elif child.type in ("type_identifier", "primitive_type",
                                        "scoped_type_identifier", "generic_type",
                                        "reference_type"):
                        type_text = child.text.decode("utf-8", errors="replace")
                if id_node:
                    _add(id_node.text.decode("utf-8", errors="replace"),
                         id_node.start_point[0] + 1, var_type=type_text)
            elif node.type == "for_expression":
                # for item in iter { }  — first identifier child is the loop var
                for child in node.children:
                    if child.type == "identifier":
                        _add(child.text.decode("utf-8", errors="replace"),
                             child.start_point[0] + 1, kind="loop_var")
                        break
            for child in node.children:
                walk(child)

        for child in fn_node.children:
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
