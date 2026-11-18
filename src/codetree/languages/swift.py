from tree_sitter import Language, Parser
import tree_sitter_swift as tsswift
from .base import LanguagePlugin, _matches, _clean_doc, _query, CachedParser

_LANGUAGE = Language(tsswift.language())
_PARSER = CachedParser(Parser(_LANGUAGE))

_TYPE_KINDS = {
    "class": "class",
    "actor": "actor",
    "struct": "struct",
    "enum": "enum",
    "protocol": "interface",
}
_KEYWORD_FUNCTIONS = {
    "init_declaration": "init",
    "deinit_declaration": "deinit",
    "subscript_declaration": "subscript",
}
_FUNCTION_QUERY = """
[
    (function_declaration)
    (protocol_function_declaration)
    (property_declaration computed_value: (computed_property))
] @def
"""


def _parse(source: bytes):
    return _PARSER.parse(source)


def _text(node) -> str:
    return node.text.decode("utf-8", errors="replace")


def _type_name_node(node):
    name = node.child_by_field_name("name")
    if name is not None and name.type == "user_type":
        # extension Outer.Inner → Inner
        ids = [c for c in name.children if c.type == "type_identifier"]
        if ids:
            return ids[-1]
    return name


def _function_name_node(node):
    if node.type in _KEYWORD_FUNCTIONS:
        for child in node.children:
            if child.type == _KEYWORD_FUNCTIONS[node.type]:
                return child
        return None
    if node.type == "property_declaration":
        pattern = node.child_by_field_name("name")
        return pattern.child_by_field_name("bound_identifier") if pattern else None
    return node.child_by_field_name("name")


def _params(node, source: bytes) -> str:
    # Parameters are direct children between the declaration's own parens.
    open_paren = None
    for child in node.children:
        if child.type == "(" and open_paren is None:
            open_paren = child
        elif child.type == ")" and open_paren is not None:
            return source[open_paren.start_byte:child.end_byte].decode("utf-8", errors="replace")
    return ""


def _doc(node) -> str:
    # Only /// and /** */ are doc comments; plain // (e.g. `// MARK: -`) is skipped.
    doc = ""
    start = node.start_point[0]
    prev = node.prev_named_sibling
    while (prev is not None and prev.type in ("comment", "multiline_comment")
           and prev.end_point[0] + 1 >= start):
        text = _text(prev)
        if text.startswith("///") or text.startswith("/**"):
            doc = _clean_doc(text)
        start = prev.start_point[0]
        prev = prev.prev_named_sibling
    return doc


def _attributes(node) -> set[str]:
    names = set()
    for child in node.children:
        if child.type == "modifiers":
            for mod in child.children:
                if mod.type == "attribute":
                    user_type = next((c for c in mod.children if c.type == "user_type"), None)
                    if user_type is not None:
                        names.add(_text(user_type))
    return names


def _inherits_test_case(node) -> bool:
    for child in node.children:
        if child.type == "inheritance_specifier":
            if "Test" in _text(child):
                return True
    return False


def _find_function(root, name: str):
    for node_type, keyword in _KEYWORD_FUNCTIONS.items():
        if name == keyword:
            for _, m in _matches(_query(_LANGUAGE, f"({node_type}) @def"), root):
                return m["def"]
            return None
    for _, m in _matches(_query(_LANGUAGE, _FUNCTION_QUERY), root):
        name_node = _function_name_node(m["def"])
        if name_node is not None and _text(name_node) == name:
            return m["def"]
    return None


class SwiftPlugin(LanguagePlugin):
    extensions = (".swift",)

    def extract_skeleton(self, source: bytes) -> list[dict]:
        tree = _parse(source)
        results = []

        def add(sym_type, name_node, decl, parent, params="", is_test=False):
            item = {
                "type": sym_type,
                "name": _text(name_node),
                "line": name_node.start_point[0] + 1,
                "parent": parent,
                "params": params,
                "doc": _doc(decl),
            }
            if is_test:
                item["is_test"] = True
            results.append(item)

        def walk(container, parent, in_test_case):
            for node in container.children:
                if node.type in ("class_declaration", "protocol_declaration"):
                    name_node = _type_name_node(node)
                    if name_node is None:
                        continue
                    kind = node.child_by_field_name("declaration_kind")
                    kind = _text(kind) if kind else ""
                    # Like Rust `impl Foo`: an extension is not a symbol, its members are
                    if kind != "extension":
                        add(_TYPE_KINDS.get(kind, "class"), name_node, node, parent)
                    body = node.child_by_field_name("body")
                    if body is not None:
                        walk(body, _text(name_node), _inherits_test_case(node))
                elif node.type == "typealias_declaration":
                    name_node = node.child_by_field_name("name")
                    if name_node is not None:
                        add("type", name_node, node, parent)
                elif node.type == "enum_entry":
                    for child in node.children:
                        if child.type == "simple_identifier":
                            add("case", child, node, parent)
                        elif child.type == "enum_type_parameters" and results:
                            results[-1]["params"] = _text(child)
                elif (node.type in ("function_declaration", "protocol_function_declaration")
                      or node.type in _KEYWORD_FUNCTIONS
                      or (node.type == "property_declaration"
                          and node.child_by_field_name("computed_value") is not None)):
                    name_node = _function_name_node(node)
                    if name_node is None:
                        continue
                    name = _text(name_node)
                    params = _params(node, source)
                    is_test = "Test" in _attributes(node) or (
                        in_test_case and node.type == "function_declaration"
                        and name.startswith("test") and params == "()"
                    )
                    add("method" if parent else "function", name_node, node, parent, params, is_test)

        walk(tree.root_node, None, False)

        results.sort(key=lambda x: x["line"])
        return results

    def extract_symbol_source(self, source: bytes, name: str) -> tuple[str, int] | None:
        tree = _parse(source)

        # Prefer the type's own declaration over its extensions
        extension = None
        q = _query(_LANGUAGE, "[(class_declaration) (protocol_declaration) (typealias_declaration)] @def")
        for _, m in _matches(q, tree.root_node):
            node = m["def"]
            name_node = _type_name_node(node)
            if name_node is None or _text(name_node) != name:
                continue
            kind = node.child_by_field_name("declaration_kind")
            if kind is not None and _text(kind) == "extension":
                extension = extension or node
                continue
            return _text(node), node.start_point[0] + 1

        node = extension or _find_function(tree.root_node, name)
        if node is None:
            return None
        return _text(node), node.start_point[0] + 1

    def extract_calls_in_function(self, source: bytes, fn_name: str) -> list[str]:
        fn_node = _find_function(_parse(source).root_node, fn_name)
        if fn_node is None:
            return []

        calls = set()
        q = _query(_LANGUAGE, """
            [
                (call_expression . (simple_identifier) @called)
                (call_expression . (navigation_expression
                    suffix: (navigation_suffix suffix: (simple_identifier) @called)))
                (call_expression . (prefix_expression target: (simple_identifier) @called))
                (constructor_expression constructed_type: (user_type) @called)
            ]
        """)
        for _, m in _matches(q, fn_node):
            node = m["called"]
            if node.type == "user_type":
                node = [c for c in node.children if c.type == "type_identifier"][-1]
            name = _text(node)
            # super.init() / .init() would resolve to every init in the repo
            if name != "init":
                calls.add(name)
        return sorted(calls)

    def extract_symbol_usages(self, source: bytes, name: str) -> list[dict]:
        tree = _parse(source)
        usages = []
        seen = set()
        for node_type in ("simple_identifier", "type_identifier"):
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
        q = _query(_LANGUAGE, "(import_declaration) @imp")
        for _, m in _matches(q, tree.root_node):
            node = m["imp"]
            results.append({
                "line": node.start_point[0] + 1,
                "text": _text(node).strip(),
            })
        results.sort(key=lambda x: x["line"])
        return results

    def compute_complexity(self, source: bytes, fn_name: str) -> dict | None:
        fn_node = _find_function(_parse(source).root_node, fn_name)
        if fn_node is None:
            return None

        branch_map = {
            "if_statement": "if",
            "guard_statement": "guard",
            "for_statement": "for",
            "while_statement": "while",
            "repeat_while_statement": "repeat",
            "catch_block": "catch",
            "ternary_expression": "ternary",
            "nil_coalescing_expression": "??",
        }
        counts: dict[str, int] = {}

        def walk(node):
            label = branch_map.get(node.type)
            if label is None and node.type == "switch_entry":
                if any(c.type == "case" for c in node.children):
                    label = "case"
            elif label is None and node.type in ("&&", "||"):
                label = node.type
            if label is not None:
                counts[label] = counts.get(label, 0) + 1
            for child in node.children:
                walk(child)

        walk(fn_node)
        total = 1 + sum(counts.values())
        return {"total": total, "breakdown": counts}

    def extract_variables(self, source: bytes, fn_name: str) -> list[dict]:
        fn_node = _find_function(_parse(source).root_node, fn_name)
        if fn_node is None:
            return []

        results = []
        seen = set()

        def _add(name_node, var_type="", kind="local"):
            name = _text(name_node)
            if name != "_" and name not in seen:
                seen.add(name)
                results.append({
                    "name": name,
                    "line": name_node.start_point[0] + 1,
                    "type": var_type,
                    "kind": kind,
                })

        for child in fn_node.children:
            if child.type == "parameter":
                names = child.children_by_field_name("name")
                if names:
                    _add(names[0], _text(names[1]) if len(names) > 1 else "", "parameter")

        q = _query(_LANGUAGE, """
            [
                (lambda_parameter name: (simple_identifier) @name)
                (pattern bound_identifier: (simple_identifier) @name)
                (pattern (simple_identifier) @name)
                (if_statement bound_identifier: (simple_identifier) @name)
                (guard_statement bound_identifier: (simple_identifier) @name)
                (while_statement bound_identifier: (simple_identifier) @name)
            ] @def
        """)
        for _, m in _matches(q, fn_node):
            node = m["def"]
            if node.type == "lambda_parameter":
                _add(m["name"], kind="parameter")
                continue
            if node.type != "pattern":
                _add(m["name"])
                continue
            owner = node.parent
            while owner is not None and owner.type == "pattern":
                owner = owner.parent
            if owner is None or owner == fn_node:
                continue
            is_bound = node.child_by_field_name("bound_identifier") == m["name"]
            # Unbound identifiers are tuple elements, or enum case names in `case .a(let s)`
            if not is_bound and owner.type not in ("property_declaration", "for_statement"):
                continue
            if owner.type == "for_statement":
                _add(m["name"], kind="loop_var")
            elif owner.type == "property_declaration":
                annotation = next((c for c in owner.children if c.type == "type_annotation"), None)
                type_node = annotation.child_by_field_name("name") if annotation else None
                _add(m["name"], _text(type_node) if type_node else "")
            else:
                _add(m["name"])

        results.sort(key=lambda x: x["line"])
        return results

    def check_syntax(self, source: bytes) -> bool:
        return _parse(source).root_node.has_error

    def _get_parser(self):
        return _PARSER

    def _get_language(self):
        return _LANGUAGE
