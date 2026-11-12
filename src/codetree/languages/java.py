from tree_sitter import Language, Parser
import tree_sitter_java as tsjava
from .base import LanguagePlugin, _matches, _fill_docs_from_siblings, _query, CachedParser

_LANGUAGE = Language(tsjava.language())
_PARSER = CachedParser(Parser(_LANGUAGE))


def _parse(source: bytes):
    return _PARSER.parse(source)


class JavaPlugin(LanguagePlugin):
    extensions = (".java",)

    def extract_skeleton(self, source: bytes) -> list[dict]:
        tree = _parse(source)
        results = []

        # Top-level classes
        q = _query(_LANGUAGE, "(program (class_declaration name: (identifier) @name) @def)")
        for _, m in _matches(q, tree.root_node):
            results.append({
                "type": "class",
                "name": m["name"].text.decode("utf-8", errors="replace"),
                "line": m["name"].start_point[0] + 1,
                "parent": None,
                "params": "",
            })

        # Methods inside classes
        q = _query(_LANGUAGE, """
            (class_declaration
                name: (identifier) @class_name
                body: (class_body
                    (method_declaration
                        name: (identifier) @method_name
                        parameters: (formal_parameters) @params)))
        """)
        for _, m in _matches(q, tree.root_node):
            results.append({
                "type": "method",
                "name": m["method_name"].text.decode("utf-8", errors="replace"),
                "line": m["method_name"].start_point[0] + 1,
                "parent": m["class_name"].text.decode("utf-8", errors="replace"),
                "params": m["params"].text.decode("utf-8", errors="replace"),
            })

        # Constructors inside classes
        q = _query(_LANGUAGE, """
            (class_declaration
                name: (identifier) @class_name
                body: (class_body
                    (constructor_declaration
                        name: (identifier) @ctor_name
                        parameters: (formal_parameters) @params)))
        """)
        for _, m in _matches(q, tree.root_node):
            results.append({
                "type": "method",
                "name": m["ctor_name"].text.decode("utf-8", errors="replace"),
                "line": m["ctor_name"].start_point[0] + 1,
                "parent": m["class_name"].text.decode("utf-8", errors="replace"),
                "params": m["params"].text.decode("utf-8", errors="replace"),
            })

        # Interfaces (top-level)
        q = _query(_LANGUAGE, "(program (interface_declaration name: (identifier) @name) @def)")
        for _, m in _matches(q, tree.root_node):
            results.append({
                "type": "interface",
                "name": m["name"].text.decode("utf-8", errors="replace"),
                "line": m["name"].start_point[0] + 1,
                "parent": None,
                "params": "",
            })

        # Enums (top-level)
        q = _query(_LANGUAGE, "(program (enum_declaration name: (identifier) @name) @def)")
        for _, m in _matches(q, tree.root_node):
            results.append({
                "type": "enum",
                "name": m["name"].text.decode("utf-8", errors="replace"),
                "line": m["name"].start_point[0] + 1,
                "parent": None,
                "params": "",
            })

        # Methods inside enums (live under enum_body > enum_body_declarations)
        q = _query(_LANGUAGE, """
            (enum_declaration
                name: (identifier) @class_name
                body: (enum_body
                    (enum_body_declarations
                        (method_declaration
                            name: (identifier) @method_name
                            parameters: (formal_parameters) @params))))
        """)
        for _, m in _matches(q, tree.root_node):
            results.append({
                "type": "method",
                "name": m["method_name"].text.decode("utf-8", errors="replace"),
                "line": m["method_name"].start_point[0] + 1,
                "parent": m["class_name"].text.decode("utf-8", errors="replace"),
                "params": m["params"].text.decode("utf-8", errors="replace"),
            })

        # Methods inside interfaces
        q = _query(_LANGUAGE, """
            (interface_declaration
                name: (identifier) @class_name
                body: (interface_body
                    (method_declaration
                        name: (identifier) @method_name
                        parameters: (formal_parameters) @params)))
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
            "(class_declaration name: (identifier) @name) @def",
            "(interface_declaration name: (identifier) @name) @def",
            "(enum_declaration name: (identifier) @name) @def",
            "(method_declaration name: (identifier) @name) @def",
        ])

        results.sort(key=lambda x: x["line"])
        return results

    def extract_symbol_source(self, source: bytes, name: str) -> tuple[str, int] | None:
        tree = _parse(source)

        # Classes, interfaces, and enums
        for q_str in [
            "(class_declaration name: (identifier) @name) @def",
            "(interface_declaration name: (identifier) @name) @def",
            "(enum_declaration name: (identifier) @name) @def",
        ]:
            for _, m in _matches(_query(_LANGUAGE, q_str), tree.root_node):
                if m["name"].text.decode("utf-8", errors="replace") == name:
                    node = m["def"]
                    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace"), node.start_point[0] + 1

        # Methods
        q = _query(_LANGUAGE, "(method_declaration name: (identifier) @name) @def")
        for _, m in _matches(q, tree.root_node):
            if m["name"].text.decode("utf-8", errors="replace") == name:
                node = m["def"]
                return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace"), node.start_point[0] + 1

        # Constructors
        q = _query(_LANGUAGE, "(constructor_declaration name: (identifier) @name) @def")
        for _, m in _matches(q, tree.root_node):
            if m["name"].text.decode("utf-8", errors="replace") == name:
                node = m["def"]
                return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace"), node.start_point[0] + 1

        return None

    def extract_calls_in_function(self, source: bytes, fn_name: str) -> list[str]:
        tree = _parse(source)
        fn_node = None
        for q_str in [
            "(method_declaration name: (identifier) @name) @def",
            "(constructor_declaration name: (identifier) @name) @def",
        ]:
            for _, m in _matches(_query(_LANGUAGE, q_str), tree.root_node):
                if m["name"].text.decode("utf-8", errors="replace") == fn_name:
                    fn_node = m["def"]
                    break
            if fn_node:
                break
        if fn_node is None:
            return []
        calls = set()
        # Method calls
        q = _query(_LANGUAGE, "(method_invocation name: (identifier) @called)")
        for _, m in _matches(q, fn_node):
            calls.add(m["called"].text.decode("utf-8", errors="replace"))
        # Object creation (new Calculator())
        q = _query(_LANGUAGE, "(object_creation_expression type: (type_identifier) @called)")
        for _, m in _matches(q, fn_node):
            calls.add(m["called"].text.decode("utf-8", errors="replace"))
        return sorted(calls)

    def extract_symbol_usages(self, source: bytes, name: str) -> list[dict]:
        tree = _parse(source)
        usages = []
        seen = set()
        # Search both identifier and type_identifier nodes to cover value and
        # type positions (e.g. `Calculator calc = ...` uses type_identifier,
        # while method names use identifier).
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
        q = _query(_LANGUAGE, "(program (import_declaration) @imp)")
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
        for q_str in [
            "(method_declaration name: (identifier) @name) @def",
            "(constructor_declaration name: (identifier) @name) @def",
        ]:
            for _, m in _matches(_query(_LANGUAGE, q_str), tree.root_node):
                if m["name"].text.decode("utf-8", errors="replace") == fn_name:
                    fn_node = m["def"]
                    break
            if fn_node:
                break
        if fn_node is None:
            return None

        branch_map = {
            "if_statement": "if",
            "for_statement": "for",
            "enhanced_for_statement": "for_each",
            "while_statement": "while",
            "do_statement": "do_while",
            "catch_clause": "catch",
            "switch_block_statement_group": "case",
            "ternary_expression": "ternary",
        }
        counts: dict[str, int] = {}

        def walk(node):
            if node.type in branch_map:
                label = branch_map[node.type]
                counts[label] = counts.get(label, 0) + 1
            elif node.type == "binary_expression":
                for child in node.children:
                    if child.type in ("&&", "||"):
                        counts[child.type] = counts.get(child.type, 0) + 1
            for child in node.children:
                walk(child)

        walk(fn_node)
        total = 1 + sum(counts.values())
        return {"total": total, "breakdown": counts}

    def extract_variables(self, source: bytes, fn_name: str) -> list[dict]:
        tree = _parse(source)

        # Find method or constructor node
        fn_node = None
        for q_str in [
            "(method_declaration name: (identifier) @name) @def",
            "(constructor_declaration name: (identifier) @name) @def",
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
            if name not in seen:
                seen.add(name)
                results.append({"name": name, "line": line, "type": var_type, "kind": kind})

        # Extract parameters from formal_parameters
        for child in fn_node.children:
            if child.type == "formal_parameters":
                for param in child.children:
                    if param.type == "formal_parameter":
                        type_text = ""
                        id_node = None
                        for sub in param.children:
                            if sub.type == "identifier":
                                id_node = sub
                            elif sub.type not in (",", "(", ")", " "):
                                type_text = sub.text.decode("utf-8", errors="replace")
                        if id_node:
                            _add(id_node.text.decode("utf-8", errors="replace"),
                                 id_node.start_point[0] + 1, var_type=type_text, kind="parameter")
                break

        # Walk the method body
        def walk(node):
            if node.type == "local_variable_declaration":
                # Extract type from first non-declarator, non-semicolon child
                type_text = ""
                for child in node.children:
                    if child.type not in ("variable_declarator", ";"):
                        type_text = child.text.decode("utf-8", errors="replace")
                        break
                for child in node.children:
                    if child.type == "variable_declarator":
                        for sub in child.children:
                            if sub.type == "identifier":
                                _add(sub.text.decode("utf-8", errors="replace"),
                                     sub.start_point[0] + 1, var_type=type_text)
                                break
            elif node.type == "enhanced_for_statement":
                # for (Type item : collection) — find type then identifier
                type_text = ""
                id_node = None
                for child in node.children:
                    if child.type in ("integral_type", "floating_point_type",
                                      "type_identifier", "generic_type", "array_type"):
                        type_text = child.text.decode("utf-8", errors="replace")
                    elif child.type == "identifier" and type_text and id_node is None:
                        id_node = child
                if id_node:
                    _add(id_node.text.decode("utf-8", errors="replace"),
                         id_node.start_point[0] + 1, kind="loop_var")
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
