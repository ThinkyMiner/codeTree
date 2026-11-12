from tree_sitter import Language, Parser
import tree_sitter_ruby as tsruby
from .base import LanguagePlugin, _matches, _fill_docs_from_siblings, _query, CachedParser

_LANGUAGE = Language(tsruby.language())
_PARSER = CachedParser(Parser(_LANGUAGE))


def _parse(source: bytes):
    return _PARSER.parse(source)


class RubyPlugin(LanguagePlugin):
    extensions = (".rb",)

    def extract_skeleton(self, source: bytes) -> list[dict]:
        tree = _parse(source)
        results = []

        # Classes
        q = _query(_LANGUAGE, "(program (class name: (constant) @name) @def)")
        for _, m in _matches(q, tree.root_node):
            results.append({
                "type": "class",
                "name": m["name"].text.decode("utf-8", errors="replace"),
                "line": m["name"].start_point[0] + 1,
                "parent": None,
                "params": "",
            })

        # Modules (treated as class for skeleton purposes)
        q = _query(_LANGUAGE, "(program (module name: (constant) @name) @def)")
        for _, m in _matches(q, tree.root_node):
            results.append({
                "type": "class",
                "name": m["name"].text.decode("utf-8", errors="replace"),
                "line": m["name"].start_point[0] + 1,
                "parent": None,
                "params": "",
            })

        # Instance methods inside classes (with params)
        q = _query(_LANGUAGE, """
            (class
                name: (constant) @class_name
                (body_statement
                    (method
                        name: (identifier) @method_name
                        parameters: (method_parameters) @params)))
        """)
        for _, m in _matches(q, tree.root_node):
            results.append({
                "type": "method",
                "name": m["method_name"].text.decode("utf-8", errors="replace"),
                "line": m["method_name"].start_point[0] + 1,
                "parent": m["class_name"].text.decode("utf-8", errors="replace"),
                "params": m["params"].text.decode("utf-8", errors="replace"),
            })

        # Instance methods inside classes (no params)
        q = _query(_LANGUAGE, """
            (class
                name: (constant) @class_name
                (body_statement
                    (method
                        name: (identifier) @method_name) @mdef))
        """)
        for _, m in _matches(q, tree.root_node):
            method_node = m["mdef"]
            # Skip if it has params (already matched above)
            if not any(child.type == "method_parameters" for child in method_node.children):
                results.append({
                    "type": "method",
                    "name": m["method_name"].text.decode("utf-8", errors="replace"),
                    "line": m["method_name"].start_point[0] + 1,
                    "parent": m["class_name"].text.decode("utf-8", errors="replace"),
                    "params": "",
                })

        # Singleton methods in classes (def self.foo) — with params
        q = _query(_LANGUAGE, """
            (class
                name: (constant) @class_name
                (body_statement
                    (singleton_method
                        name: (identifier) @method_name
                        parameters: (method_parameters) @params)))
        """)
        for _, m in _matches(q, tree.root_node):
            results.append({
                "type": "method",
                "name": m["method_name"].text.decode("utf-8", errors="replace"),
                "line": m["method_name"].start_point[0] + 1,
                "parent": m["class_name"].text.decode("utf-8", errors="replace"),
                "params": m["params"].text.decode("utf-8", errors="replace"),
            })

        # Singleton methods in classes — no params
        q = _query(_LANGUAGE, """
            (class
                name: (constant) @class_name
                (body_statement
                    (singleton_method
                        name: (identifier) @method_name) @mdef))
        """)
        for _, m in _matches(q, tree.root_node):
            method_node = m["mdef"]
            if not any(child.type == "method_parameters" for child in method_node.children):
                results.append({
                    "type": "method",
                    "name": m["method_name"].text.decode("utf-8", errors="replace"),
                    "line": m["method_name"].start_point[0] + 1,
                    "parent": m["class_name"].text.decode("utf-8", errors="replace"),
                    "params": "",
                })

        # Singleton methods in modules — with params
        q = _query(_LANGUAGE, """
            (module
                name: (constant) @class_name
                (body_statement
                    (singleton_method
                        name: (identifier) @method_name
                        parameters: (method_parameters) @params)))
        """)
        for _, m in _matches(q, tree.root_node):
            results.append({
                "type": "method",
                "name": m["method_name"].text.decode("utf-8", errors="replace"),
                "line": m["method_name"].start_point[0] + 1,
                "parent": m["class_name"].text.decode("utf-8", errors="replace"),
                "params": m["params"].text.decode("utf-8", errors="replace"),
            })

        # Singleton methods in modules — no params
        q = _query(_LANGUAGE, """
            (module
                name: (constant) @class_name
                (body_statement
                    (singleton_method
                        name: (identifier) @method_name) @mdef))
        """)
        for _, m in _matches(q, tree.root_node):
            method_node = m["mdef"]
            if not any(child.type == "method_parameters" for child in method_node.children):
                results.append({
                    "type": "method",
                    "name": m["method_name"].text.decode("utf-8", errors="replace"),
                    "line": m["method_name"].start_point[0] + 1,
                    "parent": m["class_name"].text.decode("utf-8", errors="replace"),
                    "params": "",
                })

        # Instance methods in modules — with params
        q = _query(_LANGUAGE, """
            (module
                name: (constant) @class_name
                (body_statement
                    (method
                        name: (identifier) @method_name
                        parameters: (method_parameters) @params)))
        """)
        for _, m in _matches(q, tree.root_node):
            results.append({
                "type": "method",
                "name": m["method_name"].text.decode("utf-8", errors="replace"),
                "line": m["method_name"].start_point[0] + 1,
                "parent": m["class_name"].text.decode("utf-8", errors="replace"),
                "params": m["params"].text.decode("utf-8", errors="replace"),
            })

        # Instance methods in modules — no params
        q = _query(_LANGUAGE, """
            (module
                name: (constant) @class_name
                (body_statement
                    (method
                        name: (identifier) @method_name) @mdef))
        """)
        for _, m in _matches(q, tree.root_node):
            method_node = m["mdef"]
            if not any(child.type == "method_parameters" for child in method_node.children):
                results.append({
                    "type": "method",
                    "name": m["method_name"].text.decode("utf-8", errors="replace"),
                    "line": m["method_name"].start_point[0] + 1,
                    "parent": m["class_name"].text.decode("utf-8", errors="replace"),
                    "params": "",
                })

        # Top-level functions (method at program level) — with params
        q = _query(_LANGUAGE, "(program (method name: (identifier) @name parameters: (method_parameters) @params) @def)")
        for _, m in _matches(q, tree.root_node):
            results.append({
                "type": "function",
                "name": m["name"].text.decode("utf-8", errors="replace"),
                "line": m["name"].start_point[0] + 1,
                "parent": None,
                "params": m["params"].text.decode("utf-8", errors="replace"),
            })

        # Top-level functions — no params
        q = _query(_LANGUAGE, "(program (method name: (identifier) @name) @def)")
        for _, m in _matches(q, tree.root_node):
            method_node = m["def"]
            if not any(child.type == "method_parameters" for child in method_node.children):
                results.append({
                    "type": "function",
                    "name": m["name"].text.decode("utf-8", errors="replace"),
                    "line": m["name"].start_point[0] + 1,
                    "parent": None,
                    "params": "",
                })

        # Fill doc fields
        for item in results:
            item.setdefault("doc", "")
        _fill_docs_from_siblings(results, tree.root_node, _LANGUAGE, [
            "(program (class name: (constant) @name) @def)",
            "(program (module name: (constant) @name) @def)",
            "(program (method name: (identifier) @name) @def)",
        ])

        # Deduplicate
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

        # Classes and modules
        for q_str in [
            "(class name: (constant) @name) @def",
            "(module name: (constant) @name) @def",
        ]:
            for _, m in _matches(_query(_LANGUAGE, q_str), tree.root_node):
                if m["name"].text.decode("utf-8", errors="replace") == name:
                    node = m["def"]
                    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace"), node.start_point[0] + 1

        # Methods (instance and singleton)
        for q_str in [
            "(method name: (identifier) @name) @def",
            "(singleton_method name: (identifier) @name) @def",
        ]:
            for _, m in _matches(_query(_LANGUAGE, q_str), tree.root_node):
                if m["name"].text.decode("utf-8", errors="replace") == name:
                    node = m["def"]
                    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace"), node.start_point[0] + 1

        return None

    def extract_calls_in_function(self, source: bytes, fn_name: str) -> list[str]:
        tree = _parse(source)
        fn_node = None
        for q_str in [
            "(method name: (identifier) @name) @def",
            "(singleton_method name: (identifier) @name) @def",
        ]:
            for _, m in _matches(_query(_LANGUAGE, q_str), tree.root_node):
                if m["name"].text.decode("utf-8", errors="replace") == fn_name:
                    fn_node = m["def"]
                    break
            if fn_node:
                break
        if fn_node is None:
            return []

        q = _query(_LANGUAGE, "(call method: (identifier) @called)")
        calls = set()
        for _, m in _matches(q, fn_node):
            calls.add(m["called"].text.decode("utf-8", errors="replace"))
        return sorted(calls)

    def extract_symbol_usages(self, source: bytes, name: str) -> list[dict]:
        tree = _parse(source)
        usages = []
        seen = set()
        for node_type in ("identifier", "constant"):
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
        q = _query(_LANGUAGE, "(program (call method: (identifier) @method arguments: (argument_list (string) @path)) @imp)")
        for _, m in _matches(q, tree.root_node):
            method = m["method"].text.decode("utf-8", errors="replace")
            if method in ("require", "require_relative"):
                node = m["imp"]
                results.append({
                    "line": node.start_point[0] + 1,
                    "text": node.text.decode("utf-8", errors="replace").strip(),
                })
        results.sort(key=lambda x: x["line"])
        return results

    def check_syntax(self, source: bytes) -> bool:
        return _parse(source).root_node.has_error

    def _get_parser(self):
        return _PARSER

    def _get_language(self):
        return _LANGUAGE

    def extract_variables(self, source: bytes, fn_name: str) -> list[dict]:
        tree = _parse(source)

        # Find method node (instance, singleton, or top-level)
        fn_node = None
        for q_str in [
            "(method name: (identifier) @name) @def",
            "(singleton_method name: (identifier) @name) @def",
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

        # Extract parameters from method_parameters
        for child in fn_node.children:
            if child.type == "method_parameters":
                for param in child.children:
                    if param.type == "identifier":
                        _add(param.text.decode("utf-8", errors="replace"),
                             param.start_point[0] + 1, kind="parameter")
                    elif param.type == "optional_parameter":
                        for sub in param.children:
                            if sub.type == "identifier":
                                _add(sub.text.decode("utf-8", errors="replace"),
                                     sub.start_point[0] + 1, kind="parameter")
                                break
                    elif param.type == "splat_parameter":
                        for sub in param.children:
                            if sub.type == "identifier":
                                _add(sub.text.decode("utf-8", errors="replace"),
                                     sub.start_point[0] + 1, kind="parameter")
                                break
                    elif param.type == "hash_splat_parameter":
                        for sub in param.children:
                            if sub.type == "identifier":
                                _add(sub.text.decode("utf-8", errors="replace"),
                                     sub.start_point[0] + 1, kind="parameter")
                                break
                    elif param.type == "keyword_parameter":
                        for sub in param.children:
                            if sub.type == "identifier":
                                _add(sub.text.decode("utf-8", errors="replace"),
                                     sub.start_point[0] + 1, kind="parameter")
                                break
                break

        # Walk the method body for local assignments and block params
        def walk(node):
            if node.type == "assignment":
                # x = expr — LHS is first child
                lhs = node.children[0] if node.children else None
                if lhs and lhs.type == "identifier":
                    _add(lhs.text.decode("utf-8", errors="replace"),
                         lhs.start_point[0] + 1)
            elif node.type == "for":
                # for item in collection — pattern is the loop variable
                for child in node.children:
                    if child.type == "identifier":
                        _add(child.text.decode("utf-8", errors="replace"),
                             child.start_point[0] + 1, kind="loop_var")
                        break
            elif node.type == "block_parameters":
                # |x, y| in blocks
                for child in node.children:
                    if child.type == "identifier":
                        _add(child.text.decode("utf-8", errors="replace"),
                             child.start_point[0] + 1, kind="loop_var")
            for child in node.children:
                walk(child)

        # Walk the body_statement (or direct children if no body_statement)
        for child in fn_node.children:
            if child.type == "body_statement":
                walk(child)
                break
            elif child.type not in ("identifier", "method_parameters", "end"):
                walk(child)

        return results

    def compute_complexity(self, source: bytes, fn_name: str) -> dict | None:
        tree = _parse(source)
        fn_node = None
        for q_str in [
            "(method name: (identifier) @name) @def",
            "(singleton_method name: (identifier) @name) @def",
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
            "if": "if",
            "unless": "unless",
            "while": "while",
            "until": "until",
            "for": "for",
            "when": "when",
            "elsif": "elsif",
            "if_modifier": "if",
            "unless_modifier": "unless",
            "while_modifier": "while",
            "until_modifier": "until",
        }
        counts: dict[str, int] = {}
        def walk(node):
            if node.type in branch_map and node.named_child_count > 0:
                label = branch_map[node.type]
                counts[label] = counts.get(label, 0) + 1
            elif node.type == "binary" and node.children:
                for child in node.children:
                    if child.type in ("and", "or", "&&", "||"):
                        counts[child.type] = counts.get(child.type, 0) + 1
            for child in node.children:
                walk(child)
        walk(fn_node)
        total = 1 + sum(counts.values())
        return {"total": total, "breakdown": counts}
