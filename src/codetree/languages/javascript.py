from tree_sitter import Language, Parser
import tree_sitter_javascript as tsjs
from .base import LanguagePlugin, _matches, _fill_docs_from_siblings, _query, CachedParser

_LANGUAGE = Language(tsjs.language())
_PARSER = CachedParser(Parser(_LANGUAGE))


def _parse(source: bytes):
    return _PARSER.parse(source)


def _arrow_params(fn_node) -> str:
    """Extract params text from an arrow_function or function_expression node.

    Handles three forms:
      (a, b) => ...  →  formal_parameters node  →  "(a, b)"
      a => ...       →  bare identifier          →  "(a)"
      () => ...      →  formal_parameters node   →  "()"
    """
    for child in fn_node.children:
        if child.type == "formal_parameters":
            return child.text.decode("utf-8", errors="replace")
        if child.type == "identifier":
            return f"({child.text.decode('utf-8', errors='replace')})"
    return "()"


class JavaScriptPlugin(LanguagePlugin):
    extensions = (".js", ".jsx")
    _lang = _LANGUAGE
    _parser = _PARSER

    def _get_language(self):
        return self._lang

    def _get_parser(self):
        return self._parser

    def extract_skeleton(self, source: bytes) -> list[dict]:
        lang = self._get_language()
        tree = self._get_parser().parse(source)
        results = []

        # Top-level classes — plain and exported (export class Foo {})
        for q_str in [
            "(program (class_declaration name: (identifier) @name) @def)",
            "(program (export_statement (class_declaration name: (identifier) @name) @def))",
        ]:
            for _, m in _matches(_query(lang, q_str), tree.root_node):
                results.append({
                    "type": "class",
                    "name": m["name"].text.decode("utf-8", errors="replace"),
                    "line": m["name"].start_point[0] + 1,
                    "parent": None,
                    "params": "",
                })

        # Methods inside classes
        q = _query(lang, """
            (class_declaration
                name: (identifier) @class_name
                body: (class_body
                    (method_definition
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

        # Top-level function declarations: function foo() {}
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

        # export default/named function foo() {} and export function* gen() {}
        for q_str in [
            """(program (export_statement
                (function_declaration
                    name: (identifier) @name
                    parameters: (formal_parameters) @params) @def))""",
            """(program (export_statement
                (generator_function_declaration
                    name: (identifier) @name
                    parameters: (formal_parameters) @params) @def))""",
        ]:
            for _, m in _matches(_query(lang, q_str), tree.root_node):
                results.append({
                    "type": "function",
                    "name": m["name"].text.decode("utf-8", errors="replace"),
                    "line": m["name"].start_point[0] + 1,
                    "parent": None,
                    "params": m["params"].text.decode("utf-8", errors="replace"),
                })

        # Generator functions: function* gen() {}
        q = _query(lang, """
            (program (generator_function_declaration
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
            "(class_declaration name: (identifier) @name) @def",
            "(export_statement (function_declaration name: (identifier) @name) @def)",
            "(export_statement (class_declaration name: (identifier) @name) @def)",
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

        # function/class/generator declarations (plain and exported)
        for q_str in [
            "(function_declaration name: (identifier) @name) @def",
            "(class_declaration name: (identifier) @name) @def",
            "(generator_function_declaration name: (identifier) @name) @def",
            "(export_statement (function_declaration name: (identifier) @name) @def)",
            "(export_statement (class_declaration name: (identifier) @name) @def)",
            "(export_statement (generator_function_declaration name: (identifier) @name) @def)",
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

        # Methods inside classes (method_definition)
        q = _query(lang, "(method_definition name: (property_identifier) @name) @def")
        for _, m in _matches(q, tree.root_node):
            if m["name"].text.decode("utf-8", errors="replace") == name:
                node = m["def"]
                return (
                    source[node.start_byte:node.end_byte].decode("utf-8", errors="replace"),
                    node.start_point[0] + 1,
                )

        return None

    def extract_calls_in_function(self, source: bytes, fn_name: str) -> list[str]:
        lang = self._get_language()
        tree = self._get_parser().parse(source)
        fn_node = None

        # function_declaration and generator_function_declaration (plain and exported)
        for q_str in [
            "(function_declaration name: (identifier) @name) @def",
            "(generator_function_declaration name: (identifier) @name) @def",
            "(export_statement (function_declaration name: (identifier) @name) @def)",
            "(export_statement (generator_function_declaration name: (identifier) @name) @def)",
        ]:
            for _, m in _matches(_query(lang, q_str), tree.root_node):
                if m["name"].text.decode("utf-8", errors="replace") == fn_name:
                    fn_node = m["def"]
                    break
            if fn_node:
                break

        # const/let foo = () => {} (plain and exported)
        if fn_node is None:
            for q_str in [
                """(variable_declarator
                    name: (identifier) @name
                    value: [(arrow_function) @def (function_expression) @def])""",
            ]:
                for _, m in _matches(_query(lang, q_str), tree.root_node):
                    if m["name"].text.decode("utf-8", errors="replace") == fn_name:
                        fn_node = m["def"]
                        break
                if fn_node:
                    break

        # Methods inside classes
        if fn_node is None:
            q = _query(lang, "(method_definition name: (property_identifier) @name) @def")
            for _, m in _matches(q, tree.root_node):
                if m["name"].text.decode("utf-8", errors="replace") == fn_name:
                    fn_node = m["def"]
                    break

        if fn_node is None:
            return []

        q_call = _query(lang, """
            (call_expression function: [
                (identifier) @called
                (member_expression property: (property_identifier) @called)
            ])
        """)
        q_new = _query(lang, "(new_expression constructor: (identifier) @called)")
        calls = set()
        for _, m in _matches(q_call, fn_node):
            calls.add(m["called"].text.decode("utf-8", errors="replace"))
        for _, m in _matches(q_new, fn_node):
            calls.add(m["called"].text.decode("utf-8", errors="replace"))
        return sorted(calls)

    def extract_symbol_usages(self, source: bytes, name: str) -> list[dict]:
        lang = self._get_language()
        tree = self._get_parser().parse(source)
        q = _query(lang, f'((identifier) @name (#eq? @name "{name}"))')
        usages = []
        for _, m in _matches(q, tree.root_node):
            node = m["name"]
            usages.append({"line": node.start_point[0] + 1, "col": node.start_point[1]})
        return usages

    def extract_imports(self, source: bytes) -> list[dict]:
        lang = self._get_language()
        tree = self._get_parser().parse(source)
        results = []
        q = _query(lang, "(program (import_statement) @imp)")
        for _, m in _matches(q, tree.root_node):
            node = m["imp"]
            results.append({
                "line": node.start_point[0] + 1,
                "text": node.text.decode("utf-8", errors="replace").strip(),
            })
        results.sort(key=lambda x: x["line"])
        return results

    def compute_complexity(self, source: bytes, fn_name: str) -> dict | None:
        lang = self._get_language()
        tree = self._get_parser().parse(source)
        fn_node = None

        for q_str in [
            "(function_declaration name: (identifier) @name) @def",
            "(generator_function_declaration name: (identifier) @name) @def",
            "(export_statement (function_declaration name: (identifier) @name) @def)",
            "(export_statement (generator_function_declaration name: (identifier) @name) @def)",
        ]:
            for _, m in _matches(_query(lang, q_str), tree.root_node):
                if m["name"].text.decode("utf-8", errors="replace") == fn_name:
                    fn_node = m["def"]
                    break
            if fn_node:
                break

        if fn_node is None:
            for q_str in [
                """(variable_declarator
                    name: (identifier) @name
                    value: [(arrow_function) @def (function_expression) @def])""",
            ]:
                for _, m in _matches(_query(lang, q_str), tree.root_node):
                    if m["name"].text.decode("utf-8", errors="replace") == fn_name:
                        fn_node = m["def"]
                        break
                if fn_node:
                    break

        if fn_node is None:
            q = _query(lang, "(method_definition name: (property_identifier) @name) @def")
            for _, m in _matches(q, tree.root_node):
                if m["name"].text.decode("utf-8", errors="replace") == fn_name:
                    fn_node = m["def"]
                    break

        if fn_node is None:
            return None

        branch_map = {
            "if_statement": "if",
            "for_statement": "for",
            "for_in_statement": "for_in",
            "while_statement": "while",
            "do_statement": "do_while",
            "switch_case": "case",
            "catch_clause": "catch",
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
        lang = self._get_language()
        tree = self._get_parser().parse(source)

        # Find the function node by name
        fn_node = None
        for q_str in [
            "(export_statement declaration: (function_declaration name: (identifier) @name) @def)",
            "(function_declaration name: (identifier) @name) @def",
            "(export_statement declaration: (generator_function_declaration name: (identifier) @name) @def)",
            "(generator_function_declaration name: (identifier) @name) @def",
            "(method_definition name: (property_identifier) @name) @def",
        ]:
            for _, m in _matches(_query(lang, q_str), tree.root_node):
                if m["name"].text.decode("utf-8", errors="replace") == fn_name:
                    fn_node = m["def"]
                    break
            if fn_node:
                break

        # Also look for arrow/function expression: const foo = () => {}
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

        # Extract parameters from formal_parameters
        for child in fn_node.children:
            if child.type == "formal_parameters":
                for param in child.children:
                    if param.type == "identifier":
                        _add(param.text.decode("utf-8", errors="replace"),
                             param.start_point[0] + 1, kind="parameter")
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
                                # Look for type annotation (TS only, but harmless here)
                                var_type = ""
                                for sib in child.children:
                                    if sib.type == "type_annotation":
                                        t = sib.text.decode("utf-8", errors="replace")
                                        # Strip leading ": " prefix
                                        if t.startswith(": "):
                                            t = t[2:]
                                        elif t.startswith(":"):
                                            t = t[1:].strip()
                                        var_type = t
                                        break
                                _add(name, sub.start_point[0] + 1, var_type=var_type)
                                break
            elif node.type == "for_in_statement":
                # for (const item of data) or for (const key in obj)
                # The loop variable identifier is a direct child of for_in_statement
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

    def check_syntax(self, source: bytes) -> bool:
        return self._get_parser().parse(source).root_node.has_error
