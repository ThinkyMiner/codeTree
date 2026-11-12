from tree_sitter import Language, Parser
import tree_sitter_typescript as tsts
from .javascript import JavaScriptPlugin, _arrow_params
from .base import _matches, _fill_docs_from_siblings, _query, CachedParser

_TS_LANGUAGE = Language(tsts.language_typescript())
_TS_PARSER = CachedParser(Parser(_TS_LANGUAGE))
_TSX_LANGUAGE = Language(tsts.language_tsx())
_TSX_PARSER = CachedParser(Parser(_TSX_LANGUAGE))


class TypeScriptPlugin(JavaScriptPlugin):
    """TypeScript plugin — inherits JS logic, overrides queries for TS grammar differences.

    Key differences from JS grammar:
    - Class names are 'type_identifier' nodes (not 'identifier')
    - Interface declarations use 'type_identifier' for names
    - Symbol usages must match both 'identifier' and 'type_identifier'
    """

    extensions = (".ts",)
    _lang = _TS_LANGUAGE
    _parser = _TS_PARSER

    def extract_skeleton(self, source: bytes) -> list[dict]:
        lang = self._get_language()
        tree = self._get_parser().parse(source)
        results = []

        # Top-level classes — plain and exported (export class Foo {})
        for q_str in [
            "(program (class_declaration name: (type_identifier) @name) @def)",
            "(program (export_statement (class_declaration name: (type_identifier) @name) @def))",
        ]:
            for _, m in _matches(_query(lang, q_str), tree.root_node):
                results.append({
                    "type": "class",
                    "name": m["name"].text.decode("utf-8", errors="replace"),
                    "line": m["name"].start_point[0] + 1,
                    "parent": None,
                    "params": "",
                })

        # Abstract classes — plain and exported (abstract class Base {})
        for q_str in [
            "(program (abstract_class_declaration name: (type_identifier) @name) @def)",
            "(program (export_statement (abstract_class_declaration name: (type_identifier) @name) @def))",
        ]:
            for _, m in _matches(_query(lang, q_str), tree.root_node):
                results.append({
                    "type": "class",
                    "name": m["name"].text.decode("utf-8", errors="replace"),
                    "line": m["name"].start_point[0] + 1,
                    "parent": None,
                    "params": "",
                })

        # Methods inside regular and abstract classes
        for q_str in [
            """(class_declaration
                name: (type_identifier) @class_name
                body: (class_body
                    (method_definition
                        name: (property_identifier) @method_name
                        parameters: (formal_parameters) @params)))""",
            """(abstract_class_declaration
                name: (type_identifier) @class_name
                body: (class_body
                    (method_definition
                        name: (property_identifier) @method_name
                        parameters: (formal_parameters) @params)))""",
        ]:
            for _, m in _matches(_query(lang, q_str), tree.root_node):
                results.append({
                    "type": "method",
                    "name": m["method_name"].text.decode("utf-8", errors="replace"),
                    "line": m["method_name"].start_point[0] + 1,
                    "parent": m["class_name"].text.decode("utf-8", errors="replace"),
                    "params": m["params"].text.decode("utf-8", errors="replace"),
                })

        # Abstract method signatures (no body, e.g. abstract doWork(): void;)
        q = _query(lang, """
            (abstract_class_declaration
                name: (type_identifier) @class_name
                body: (class_body
                    (abstract_method_signature
                        name: (property_identifier) @method_name
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

        # Top-level function declarations (same as JS — uses identifier)
        q = _query(lang, """
            (program (function_declaration
                name: (identifier) @name
                parameters: (formal_parameters) @params))
        """)
        for _, m in _matches(q, tree.root_node):
            results.append({
                "type": "function",
                "name": m["name"].text.decode("utf-8", errors="replace"),
                "line": m["name"].start_point[0] + 1,
                "parent": None,
                "params": m["params"].text.decode("utf-8", errors="replace"),
            })

        # TypeScript interfaces — plain and exported (export interface Foo {})
        for q_str in [
            "(program (interface_declaration name: (type_identifier) @name) @def)",
            "(program (export_statement (interface_declaration name: (type_identifier) @name) @def))",
        ]:
            for _, m in _matches(_query(lang, q_str), tree.root_node):
                results.append({
                    "type": "interface",
                    "name": m["name"].text.decode("utf-8", errors="replace"),
                    "line": m["name"].start_point[0] + 1,
                    "parent": None,
                    "params": "",
                })

        # TypeScript type aliases — plain and exported (type Foo = ...)
        for q_str in [
            "(program (type_alias_declaration name: (type_identifier) @name) @def)",
            "(program (export_statement (type_alias_declaration name: (type_identifier) @name) @def))",
        ]:
            for _, m in _matches(_query(lang, q_str), tree.root_node):
                results.append({
                    "type": "type",
                    "name": m["name"].text.decode("utf-8", errors="replace"),
                    "line": m["name"].start_point[0] + 1,
                    "parent": None,
                    "params": "",
                })

        # export default function foo() {}
        q = _query(lang, """
            (program (export_statement
                (function_declaration
                    name: (identifier) @name
                    parameters: (formal_parameters) @params) @def))
        """)
        for _, m in _matches(q, tree.root_node):
            results.append({
                "type": "function",
                "name": m["name"].text.decode("utf-8", errors="replace"),
                "line": m["name"].start_point[0] + 1,
                "parent": None,
                "params": m["params"].text.decode("utf-8", errors="replace"),
            })

        # const/let foo = () => {} and const/let foo = function() {}
        # Both at module level and exported (export const foo = ...)
        for q_str in [
            """(program (lexical_declaration
                (variable_declarator
                    name: (identifier) @name
                    value: [(arrow_function) @fn (function_expression) @fn])))""",
            """(program (export_statement (lexical_declaration
                (variable_declarator
                    name: (identifier) @name
                    value: [(arrow_function) @fn (function_expression) @fn]))))""",
        ]:
            for _, m in _matches(_query(lang, q_str), tree.root_node):
                fn_node = m.get("fn")
                results.append({
                    "type": "function",
                    "name": m["name"].text.decode("utf-8", errors="replace"),
                    "line": m["name"].start_point[0] + 1,
                    "parent": None,
                    "params": _arrow_params(fn_node) if fn_node else "()",
                })

        # Fill doc fields from preceding comments
        for item in results:
            item.setdefault("doc", "")
        _fill_docs_from_siblings(results, tree.root_node, lang, [
            "(function_declaration name: (identifier) @name) @def",
            "(class_declaration name: (type_identifier) @name) @def",
            "(abstract_class_declaration name: (type_identifier) @name) @def",
            "(interface_declaration name: (type_identifier) @name) @def",
            "(type_alias_declaration name: (type_identifier) @name) @def",
            "(export_statement (function_declaration name: (identifier) @name) @def)",
            "(export_statement (class_declaration name: (type_identifier) @name) @def)",
            "(export_statement (interface_declaration name: (type_identifier) @name) @def)",
            "(export_statement (type_alias_declaration name: (type_identifier) @name) @def)",
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
        lang = self._get_language()
        tree = self._get_parser().parse(source)

        # function/class/abstract-class/interface declarations (plain and exported)
        for q_str in [
            "(function_declaration name: (identifier) @name) @def",
            "(class_declaration name: (type_identifier) @name) @def",
            "(abstract_class_declaration name: (type_identifier) @name) @def",
            "(interface_declaration name: (type_identifier) @name) @def",
            "(export_statement (function_declaration name: (identifier) @name) @def)",
            "(export_statement (class_declaration name: (type_identifier) @name) @def)",
            "(export_statement (abstract_class_declaration name: (type_identifier) @name) @def)",
            "(export_statement (interface_declaration name: (type_identifier) @name) @def)",
        ]:
            for _, m in _matches(_query(lang, q_str), tree.root_node):
                if m["name"].text.decode("utf-8", errors="replace") == name:
                    node = m["def"]
                    return (
                        source[node.start_byte:node.end_byte].decode("utf-8", errors="replace"),
                        node.start_point[0] + 1,
                    )

        # const/let foo = () => {} (plain and exported) — return full lexical_declaration
        for q_str in [
            """(lexical_declaration
                (variable_declarator
                    name: (identifier) @name
                    value: [(arrow_function) (function_expression)])) @def""",
            """(export_statement (lexical_declaration
                (variable_declarator
                    name: (identifier) @name
                    value: [(arrow_function) (function_expression)])) @def)""",
        ]:
            for _, m in _matches(_query(lang, q_str), tree.root_node):
                if m["name"].text.decode("utf-8", errors="replace") == name:
                    node = m["def"]
                    return (
                        source[node.start_byte:node.end_byte].decode("utf-8", errors="replace"),
                        node.start_point[0] + 1,
                    )

        # Type alias declarations (plain and exported)
        for q_str in [
            "(type_alias_declaration name: (type_identifier) @name) @def",
            "(export_statement (type_alias_declaration name: (type_identifier) @name) @def)",
        ]:
            for _, m in _matches(_query(lang, q_str), tree.root_node):
                if m["name"].text.decode("utf-8", errors="replace") == name:
                    node = m["def"]
                    return (
                        source[node.start_byte:node.end_byte].decode("utf-8", errors="replace"),
                        node.start_point[0] + 1,
                    )

        # Methods inside classes (method_definition and abstract_method_signature)
        for q_str in [
            "(method_definition name: (property_identifier) @name) @def",
            "(abstract_method_signature name: (property_identifier) @name) @def",
        ]:
            for _, m in _matches(_query(lang, q_str), tree.root_node):
                if m["name"].text.decode("utf-8", errors="replace") == name:
                    node = m["def"]
                    return (
                        source[node.start_byte:node.end_byte].decode("utf-8", errors="replace"),
                        node.start_point[0] + 1,
                    )

        return None

    def extract_variables(self, source: bytes, fn_name: str) -> list[dict]:
        lang = self._get_language()
        tree = self._get_parser().parse(source)

        # Find the function node by name (same patterns as JS but uses TS parser)
        fn_node = None
        for q_str in [
            "(export_statement declaration: (function_declaration name: (identifier) @name) @def)",
            "(function_declaration name: (identifier) @name) @def",
            "(method_definition name: (property_identifier) @name) @def",
        ]:
            for _, m in _matches(_query(lang, q_str), tree.root_node):
                if m["name"].text.decode("utf-8", errors="replace") == fn_name:
                    fn_node = m["def"]
                    break
            if fn_node:
                break

        # Arrow/function expressions
        if fn_node is None:
            q_str = "(variable_declarator name: (identifier) @name value: [(arrow_function) @def (function_expression) @def])"
            for _, m in _matches(_query(lang, q_str), tree.root_node):
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

        def _extract_type(node):
            """Extract type text from a type_annotation node, stripping the leading ': '."""
            t = node.text.decode("utf-8", errors="replace")
            if t.startswith(": "):
                return t[2:]
            if t.startswith(":"):
                return t[1:].strip()
            return t

        # Extract parameters from formal_parameters (TS uses required_parameter / optional_parameter)
        for child in fn_node.children:
            if child.type == "formal_parameters":
                for param in child.children:
                    if param.type == "identifier":
                        # Bare identifier parameter (no type)
                        _add(param.text.decode("utf-8", errors="replace"),
                             param.start_point[0] + 1, kind="parameter")
                    elif param.type in ("required_parameter", "optional_parameter"):
                        # TS typed parameter: identifier + type_annotation
                        param_name = None
                        param_type = ""
                        for sub in param.children:
                            if sub.type == "identifier" and param_name is None:
                                param_name = sub.text.decode("utf-8", errors="replace")
                            elif sub.type == "type_annotation":
                                param_type = _extract_type(sub)
                        if param_name:
                            _add(param_name, param.start_point[0] + 1,
                                 var_type=param_type, kind="parameter")
                    elif param.type == "assignment_pattern":
                        # default params: x = default
                        for sub in param.children:
                            if sub.type == "identifier":
                                _add(sub.text.decode("utf-8", errors="replace"),
                                     sub.start_point[0] + 1, kind="parameter")
                                break
                break

        # Walk the function body
        def walk(node):
            if node.type in ("lexical_declaration", "variable_declaration"):
                for child in node.children:
                    if child.type == "variable_declarator":
                        for sub in child.children:
                            if sub.type == "identifier":
                                name = sub.text.decode("utf-8", errors="replace")
                                var_type = ""
                                for sib in child.children:
                                    if sib.type == "type_annotation":
                                        var_type = _extract_type(sib)
                                        break
                                _add(name, sub.start_point[0] + 1, var_type=var_type)
                                break
            elif node.type == "for_in_statement":
                for child in node.children:
                    if child.type == "identifier":
                        _add(child.text.decode("utf-8", errors="replace"),
                             child.start_point[0] + 1, kind="loop_var")
                        break
            for child in node.children:
                walk(child)

        # Find the body (statement_block)
        for child in fn_node.children:
            if child.type == "statement_block":
                walk(child)
                break

        return results

    def extract_symbol_usages(self, source: bytes, name: str) -> list[dict]:
        lang = self._get_language()
        tree = self._get_parser().parse(source)

        usages = []
        seen = set()

        # Match both plain identifiers and type identifiers (class names appear as both)
        for node_kind in ("identifier", "type_identifier"):
            q = _query(lang, f'(({node_kind}) @name (#eq? @name "{name}"))')
            for _, m in _matches(q, tree.root_node):
                node = m["name"]
                key = (node.start_point[0], node.start_point[1])
                if key not in seen:
                    seen.add(key)
                    usages.append({"line": node.start_point[0] + 1, "col": node.start_point[1]})

        usages.sort(key=lambda x: (x["line"], x["col"]))
        return usages


class TSXPlugin(TypeScriptPlugin):
    """TSX plugin — same as TypeScript but uses the tsx grammar."""

    extensions = (".tsx",)
    _lang = _TSX_LANGUAGE
    _parser = _TSX_PARSER
