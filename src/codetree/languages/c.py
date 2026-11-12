from tree_sitter import Language, Parser
import tree_sitter_c as tsc
from .base import LanguagePlugin, _matches, _fill_docs_from_siblings, _query, CachedParser

_LANGUAGE = Language(tsc.language())
_PARSER = CachedParser(Parser(_LANGUAGE))


def _parse(source: bytes):
    return _PARSER.parse(source)


class CPlugin(LanguagePlugin):
    extensions = (".c", ".h")

    def _get_language(self):
        return _LANGUAGE

    def _get_parser(self):
        return _PARSER

    def extract_skeleton(self, source: bytes) -> list[dict]:
        tree = _parse(source)
        results = []

        # Named structs with body (struct Foo { ... })
        q = _query(_LANGUAGE, "(struct_specifier name: (type_identifier) @name body: (field_declaration_list)) @def")
        for _, m in _matches(q, tree.root_node):
            results.append({
                "type": "struct",
                "name": m["name"].text.decode("utf-8", errors="replace"),
                "line": m["name"].start_point[0] + 1,
                "parent": None,
                "params": "",
            })

        # Typedef structs: typedef struct { ... } Name;
        q = _query(_LANGUAGE, "(type_definition declarator: (type_identifier) @name) @def")
        for _, m in _matches(q, tree.root_node):
            results.append({
                "type": "struct",
                "name": m["name"].text.decode("utf-8", errors="replace"),
                "line": m["name"].start_point[0] + 1,
                "parent": None,
                "params": "",
            })

        # Functions
        q = _query(_LANGUAGE, """
            (translation_unit
                (function_definition
                    declarator: (function_declarator
                        declarator: (identifier) @name
                        parameters: (parameter_list) @params)) @def)
        """)
        for _, m in _matches(q, tree.root_node):
            results.append({
                "type": "function",
                "name": m["name"].text.decode("utf-8", errors="replace"),
                "line": m["name"].start_point[0] + 1,
                "parent": None,
                "params": m["params"].text.decode("utf-8", errors="replace"),
            })

        # Fill doc fields
        for item in results:
            item.setdefault("doc", "")
        _fill_docs_from_siblings(results, tree.root_node, _LANGUAGE, [
            "(function_definition declarator: (function_declarator declarator: (identifier) @name)) @def",
            "(struct_specifier name: (type_identifier) @name) @def",
            "(type_definition declarator: (type_identifier) @name) @def",
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

        # Functions
        q = _query(_LANGUAGE, "(function_definition declarator: (function_declarator declarator: (identifier) @name)) @def")
        for _, m in _matches(q, tree.root_node):
            if m["name"].text.decode("utf-8", errors="replace") == name:
                node = m["def"]
                return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace"), node.start_point[0] + 1

        # Structs
        q = _query(_LANGUAGE, "(struct_specifier name: (type_identifier) @name body: (field_declaration_list)) @def")
        for _, m in _matches(q, tree.root_node):
            if m["name"].text.decode("utf-8", errors="replace") == name:
                node = m["def"]
                return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace"), node.start_point[0] + 1

        # Typedef structs
        q = _query(_LANGUAGE, "(type_definition declarator: (type_identifier) @name) @def")
        for _, m in _matches(q, tree.root_node):
            if m["name"].text.decode("utf-8", errors="replace") == name:
                node = m["def"]
                return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace"), node.start_point[0] + 1

        return None

    def extract_calls_in_function(self, source: bytes, fn_name: str) -> list[str]:
        tree = _parse(source)
        fn_node = None
        q = _query(_LANGUAGE, "(function_definition declarator: (function_declarator declarator: (identifier) @name)) @def")
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
        for node_type in ("identifier", "type_identifier", "field_identifier"):
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
        q = _query(_LANGUAGE, "(translation_unit (preproc_include) @imp)")
        for _, m in _matches(q, tree.root_node):
            node = m["imp"]
            results.append({
                "line": node.start_point[0] + 1,
                "text": node.text.decode("utf-8", errors="replace").strip(),
            })
        results.sort(key=lambda x: x["line"])
        return results

    def check_syntax(self, source: bytes) -> bool:
        return _parse(source).root_node.has_error

    def extract_variables(self, source: bytes, fn_name: str) -> list[dict]:
        tree = _parse(source)

        # Find function node
        fn_node = None
        q = _query(_LANGUAGE, "(function_definition declarator: (function_declarator declarator: (identifier) @name)) @def")
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

        # Extract parameters from parameter_list
        for child in fn_node.children:
            if child.type == "function_declarator":
                for sub in child.children:
                    if sub.type == "parameter_list":
                        for param in sub.children:
                            if param.type == "parameter_declaration":
                                # Last identifier/pointer child is the name
                                id_node = None
                                type_parts = []
                                for pc in param.children:
                                    if pc.type == "identifier":
                                        id_node = pc
                                    elif pc.type == "pointer_declarator":
                                        # int *p — name is inside pointer_declarator
                                        for ppc in pc.children:
                                            if ppc.type == "identifier":
                                                id_node = ppc
                                    elif pc.type not in (",", "(", ")"):
                                        type_parts.append(pc.text.decode("utf-8", errors="replace"))
                                if id_node:
                                    _add(id_node.text.decode("utf-8", errors="replace"),
                                         id_node.start_point[0] + 1,
                                         var_type=" ".join(type_parts), kind="parameter")
                break

        # Walk the function body for declarations and loop vars
        def walk(node):
            if node.type == "declaration":
                # e.g. int x = 1; or int x, y;
                type_text = ""
                for child in node.children:
                    if child.type in ("primitive_type", "type_identifier", "sized_type_specifier"):
                        type_text = child.text.decode("utf-8", errors="replace")
                        break
                for child in node.children:
                    if child.type == "init_declarator":
                        for sub in child.children:
                            if sub.type == "identifier":
                                _add(sub.text.decode("utf-8", errors="replace"),
                                     sub.start_point[0] + 1, var_type=type_text)
                                break
                            elif sub.type == "pointer_declarator":
                                for ppc in sub.children:
                                    if ppc.type == "identifier":
                                        _add(ppc.text.decode("utf-8", errors="replace"),
                                             ppc.start_point[0] + 1, var_type=type_text)
                                        break
                                break
                    elif child.type == "identifier":
                        # Declaration without initializer: int x;
                        _add(child.text.decode("utf-8", errors="replace"),
                             child.start_point[0] + 1, var_type=type_text)
            elif node.type == "for_statement":
                # for (int i = 0; ...) — the init part is a declaration
                for child in node.children:
                    if child.type == "declaration":
                        type_text = ""
                        for sub in child.children:
                            if sub.type in ("primitive_type", "type_identifier", "sized_type_specifier"):
                                type_text = sub.text.decode("utf-8", errors="replace")
                                break
                        for sub in child.children:
                            if sub.type == "init_declarator":
                                for ssub in sub.children:
                                    if ssub.type == "identifier":
                                        _add(ssub.text.decode("utf-8", errors="replace"),
                                             ssub.start_point[0] + 1, var_type=type_text, kind="loop_var")
                                        break
                                break
                        break
            for child in node.children:
                walk(child)

        for child in fn_node.children:
            if child.type == "compound_statement":
                walk(child)
                break

        return results

    def compute_complexity(self, source: bytes, fn_name: str) -> dict | None:
        tree = _parse(source)
        fn_node = None
        q = _query(_LANGUAGE, "(function_definition declarator: (function_declarator declarator: (identifier) @name)) @def")
        for _, m in _matches(q, tree.root_node):
            if m["name"].text.decode("utf-8", errors="replace") == fn_name:
                fn_node = m["def"]
                break
        if fn_node is None:
            return None

        branch_map = {
            "if_statement": "if",
            "for_statement": "for",
            "while_statement": "while",
            "do_statement": "do_while",
            "case_statement": "case",
        }
        counts: dict[str, int] = {}
        def walk(node):
            if node.type in branch_map:
                label = branch_map[node.type]
                counts[label] = counts.get(label, 0) + 1
            elif node.type == "binary_expression":
                op = None
                for child in node.children:
                    if child.type in ("&&", "||"):
                        op = child.type
                if op:
                    counts[op] = counts.get(op, 0) + 1
            for child in node.children:
                walk(child)
        walk(fn_node)
        total = 1 + sum(counts.values())
        return {"total": total, "breakdown": counts}
