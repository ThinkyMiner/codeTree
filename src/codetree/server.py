from collections.abc import Iterable
from fastmcp import FastMCP
from pathlib import Path
from .indexer import Indexer
from .cache import Cache


def create_server(root: str, exclude: Iterable[str] = ()) -> FastMCP:
    mcp = FastMCP("codetree")
    root_path = Path(root)

    def _validate_path(file_path: str | None, _root: Path = root_path) -> str | None:
        """Return an error string if file_path escapes the repo root, else None."""
        if not file_path:
            return None  # Optional paths — let downstream handle None/empty
        # Reject absolute paths immediately (OS-specific safety before resolve)
        if Path(file_path).is_absolute():
            return f"Error: path '{file_path}' must be relative to the repo root — access denied"
        try:
            candidate = (_root / file_path).resolve()
            candidate.relative_to(_root.resolve())
            return None  # Within bounds
        except ValueError:
            return f"Error: path '{file_path}' is outside the repo root — access denied"

    # Load cache
    cache = Cache(root)
    cache.load()

    # Build index, skipping unchanged files
    cached_mtimes = {
        k: v["mtime"] for k, v in (cache._data or {}).items()
    }
    indexer = Indexer(root, exclude=exclude)
    indexer.build(cached_mtimes=cached_mtimes)

    # Inject cached entries for unchanged files (skip ignored dirs)
    indexed = {str(f.relative_to(root_path)) for f in indexer.files}
    for rel_path, entry_data in (cache._data or {}).items():
        if indexer._should_skip(Path(rel_path)):
            continue
        if rel_path not in indexed:
            py_file = root_path / rel_path
            if py_file.exists():
                mtime = py_file.stat().st_mtime
                if cache.is_valid(rel_path, mtime):
                    indexer.inject_cached(
                        rel_path=rel_path,
                        py_file=py_file,
                        source=py_file.read_bytes(),
                        skeleton=entry_data.get("skeleton", []),
                        mtime=mtime,
                    )

    # Rebuild definition index once after all injections (DATA-01, DATA-02, DATA-03 fix)
    indexer._rebuild_definitions()

    # Save updated cache
    for rel_path, file_entry in indexer._index.items():
        cache.set(rel_path, {
            "mtime": file_entry.mtime,
            "skeleton": file_entry.skeleton,
        })
    cache.save()

    # ── Build persistent graph ───────────────────────────────────────────
    import atexit
    from .graph.store import GraphStore
    from .graph.builder import GraphBuilder
    from .graph.queries import GraphQueries

    graph_store = GraphStore(root)
    graph_store.open()
    atexit.register(graph_store.close)
    graph_builder = GraphBuilder(root, graph_store)
    graph_builder.build(indexer=indexer)
    graph_queries = GraphQueries(graph_store)

    # ── Skeleton formatting helpers ──────────────────────────────────────────
    _TYPE_ABBREV = {
        "class": "cls", "struct": "str", "interface": "ifc",
        "trait": "trt", "enum": "enm", "type": "typ",
        "function": "fn", "method": "mth",
    }

    def _format_skeleton(skeleton, fmt="full", has_errors=False):
        if fmt == "compact":
            return _format_skeleton_compact(skeleton)
        return _format_skeleton_full(skeleton, has_errors)

    def _format_skeleton_full(skeleton, has_errors=False):
        lines = []
        if has_errors:
            lines.append("WARNING: File has syntax errors — skeleton may be incomplete\n")
        for item in skeleton:
            kind = item["type"]
            if kind in ("class", "struct", "interface", "trait", "enum", "type"):
                lines.append(f"{kind} {item['name']} → line {item['line']}")
            else:
                prefix = "  " if item["parent"] else ""
                parent_info = f" (in {item['parent']})" if item["parent"] else ""
                lines.append(f"{prefix}def {item['name']}{item['params']}{parent_info} → line {item['line']}")
            doc = item.get("doc", "")
            if doc:
                indent = "  " if item.get("parent") else ""
                extra = "  " if kind not in ("class", "struct", "interface", "trait", "enum", "type") else ""
                lines.append(f"{indent}{extra}\"{doc}\"")
        return "\n".join(lines)

    def _format_skeleton_compact(skeleton):
        lines = []
        for item in skeleton:
            kind = item["type"]
            abbrev = _TYPE_ABBREV.get(kind, kind[:3])
            name = item["name"]
            line = item["line"]
            doc = item.get("doc", "")
            doc_suffix = f" # {doc}" if doc else ""

            if kind in ("class", "struct", "interface", "trait", "enum", "type"):
                lines.append(f"{abbrev} {name}:{line}{doc_suffix}")
            elif item.get("parent"):
                # Method: dot prefix, strip param spaces
                params = item["params"].replace(", ", ",")
                lines.append(f".{name}{params}:{line}{doc_suffix}")
            else:
                # Top-level function
                params = item["params"].replace(", ", ",")
                lines.append(f"{abbrev} {name}{params}:{line}{doc_suffix}")
        return "\n".join(lines)

    @mcp.tool()
    def get_file_skeleton(file_path: str, format: str = "full") -> str:
        """Get all classes and function signatures in a source file without their bodies.

        Args:
            file_path: path relative to the repo root (e.g., "src/main.py" or "calculator.py")
            format: "full" (default, verbose, includes syntax warnings) or "compact" (abbreviated, fewer tokens, no syntax warnings)
        """
        if err := _validate_path(file_path):
            return err
        skeleton = indexer.get_skeleton(file_path)
        if not skeleton:
            return f"File not found or empty: {file_path}"

        entry = indexer._index.get(file_path)
        has_errors = entry.has_errors if entry else False
        return _format_skeleton(skeleton, fmt=format, has_errors=has_errors)

    @mcp.tool()
    def get_symbol(file_path: str, symbol_name: str) -> str:
        """Get the full source code of a specific function or class by name.

        Args:
            file_path: path relative to the repo root (e.g., "src/main.py" or "calculator.py")
            symbol_name: name of the function or class to retrieve
        """
        if err := _validate_path(file_path):
            return err
        result = indexer.get_symbol(file_path, symbol_name)
        if result is None:
            return f"Symbol '{symbol_name}' not found in {file_path}"
        source, line = result
        return f"# {file_path}:{line}\n{source}"

    @mcp.tool()
    def find_references(symbol_name: str) -> str:
        """Find all usages of a symbol across the entire repo.

        Args:
            symbol_name: name of the symbol to search for; results include
                file paths relative to the repo root (e.g., "src/main.py")
        """
        refs = indexer.find_references(symbol_name)
        if not refs:
            return f"No references found for '{symbol_name}'"
        lines = [f"References to '{symbol_name}':"]
        for ref in refs:
            lines.append(f"  {ref['file']}:{ref['line']}")
        return "\n".join(lines)

    @mcp.tool()
    def get_call_graph(file_path: str, function_name: str) -> str:
        """Get what a function calls and what calls it across the repo.

        Args:
            file_path: path relative to the repo root (e.g., "src/main.py" or "calculator.py")
            function_name: name of the function to inspect

        Note:
            Callee names listed under "calls" can be located with
            find_references(symbol_name) to find where they are defined.
        """
        if err := _validate_path(file_path):
            return err
        graph = indexer.get_call_graph(file_path, function_name)
        lines = [f"Call graph for '{function_name}':"]

        if graph["calls"]:
            lines.append(f"\n  {function_name} calls:")
            for c in graph["calls"]:
                lines.append(f"    → {c}")
        else:
            lines.append(f"\n  {function_name} calls: (nothing detected)")

        if graph["callers"]:
            lines.append(f"\n  {function_name} is called by:")
            for caller in graph["callers"]:
                lines.append(f"    ← {caller['file']}:{caller['line']}")
        else:
            lines.append(f"\n  {function_name} is called by: (no callers found)")

        return "\n".join(lines)

    @mcp.tool()
    def get_imports(file_path: str) -> str:
        """Get import/use statements from a source file.

        Args:
            file_path: path relative to the repo root (e.g., "src/main.py" or "calculator.py")
        """
        if err := _validate_path(file_path):
            return err
        entry = indexer._index.get(file_path)
        if entry is None:
            return f"File not found: {file_path}"
        imports = entry.plugin.extract_imports(entry.source)
        if not imports:
            return f"No imports found in {file_path}"
        lines = [f"Imports in {file_path}:"]
        for imp in imports:
            lines.append(f"  {imp['line']}: {imp['text']}")
        return "\n".join(lines)

    @mcp.tool()
    def get_skeletons(file_paths: list[str], format: str = "full") -> str:
        """Get skeletons for multiple files in one call.

        Args:
            file_paths: list of paths relative to the repo root
            format: "full" (default) or "compact" (abbreviated)
        """
        if not file_paths:
            return "No files requested."
        parts = []
        for fp in file_paths:
            parts.append(f"=== {fp} ===")
            if err := _validate_path(fp):
                parts.append(err)
                parts.append("")
                continue
            skeleton = indexer.get_skeleton(fp)
            if not skeleton:
                parts.append(f"File not found or empty: {fp}")
                parts.append("")
                continue
            entry = indexer._index.get(fp)
            has_errors = entry.has_errors if entry else False
            parts.append(_format_skeleton(skeleton, fmt=format, has_errors=has_errors))
            parts.append("")
        return "\n".join(parts).rstrip()

    @mcp.tool()
    def get_symbols(symbols: list[dict]) -> str:
        """Get the full source code of multiple symbols in one call.

        Args:
            symbols: list of {"file_path": "...", "symbol_name": "..."} dicts
        """
        if not symbols:
            return "No symbols requested."
        parts = []
        for item in symbols:
            fp = item.get("file_path", "")
            name = item.get("symbol_name", "")
            if err := _validate_path(fp):
                parts.append(f"=== {fp} ===")
                parts.append(err)
                parts.append("")
                continue
            result = indexer.get_symbol(fp, name)
            if result is None:
                parts.append(f"Symbol '{name}' not found in {fp}")
            else:
                source, line = result
                parts.append(f"# {fp}:{line}\n{source}")
        return "\n\n".join(parts)

    @mcp.tool()
    def get_complexity(file_path: str, function_name: str) -> str:
        """Get cyclomatic complexity of a function.

        Args:
            file_path: path relative to the repo root (e.g., "src/main.py" or "calculator.py")
            function_name: name of the function to analyze
        """
        if err := _validate_path(file_path):
            return err
        entry = indexer._index.get(file_path)
        if entry is None:
            return f"File not found: {file_path}"
        result = entry.plugin.compute_complexity(entry.source, function_name)
        if result is None:
            return f"Function '{function_name}' not found in {file_path}"
        breakdown = result["breakdown"]
        line = f"Complexity of {function_name}() in {file_path}: {result['total']}"
        if breakdown:
            parts = [f"{k}: {v}" for k, v in sorted(breakdown.items())]
            line += f"\n  {', '.join(parts)}"
        return line

    @mcp.tool()
    def find_dead_code(file_path: str | None = None) -> str:
        """Find symbols that are defined but never referenced elsewhere in the repo.

        Args:
            file_path: optional — if given, only check this file. Otherwise scans entire repo.
        """
        if file_path is not None:
            if err := _validate_path(file_path):
                return err
        if file_path and file_path not in indexer._index:
            return f"File not found: {file_path}"
        dead = indexer.find_dead_code(file_path=file_path)
        if not dead:
            scope = file_path if file_path else "the repo"
            return f"No dead code found in {scope}."
        by_file: dict[str, list] = {}
        for item in dead:
            by_file.setdefault(item["file"], []).append(item)
        lines = []
        for fp, items in sorted(by_file.items()):
            lines.append(f"Dead code in {fp}:")
            for item in items:
                parent = f"{item['parent']}." if item.get("parent") else ""
                lines.append(f"  {item['type']} {parent}{item['name']}() → line {item['line']}")
        total = len(dead)
        file_count = len(by_file)
        lines.append(f"\nSummary: {total} dead symbol{'s' if total != 1 else ''} across {file_count} file{'s' if file_count != 1 else ''}")
        return "\n".join(lines)

    @mcp.tool()
    def get_blast_radius(file_path: str, symbol_name: str) -> str:
        """Find all functions transitively affected if a symbol is changed.

        Shows direct and indirect callers (what breaks) and dependencies (what it relies on).

        Args:
            file_path: path relative to the repo root
            symbol_name: name of the function/method to analyze
        """
        if err := _validate_path(file_path):
            return err
        if file_path not in indexer._index:
            return f"File not found: {file_path}"
        result = indexer.get_blast_radius(file_path, symbol_name)
        lines = [f"Blast radius for {symbol_name}() in {file_path}:"]

        callers = result["callers"]
        if callers:
            by_depth: dict[int, list] = {}
            for c in callers:
                by_depth.setdefault(c["depth"], []).append(c)
            for depth in sorted(by_depth):
                label = "Direct callers" if depth == 1 else f"Indirect callers (depth {depth})"
                lines.append(f"\n{label}:")
                for c in by_depth[depth]:
                    lines.append(f"  {c['file']}: {c['name']}() → line {c['line']}")
        else:
            lines.append("\nCallers: (none — no functions call this)")

        calls = result["calls"]
        if calls:
            lines.append("\nDependencies (what it calls):")
            for c in calls:
                lines.append(f"  {c['file']}: {c['name']}() → line {c['line']}")
        else:
            lines.append("\nDependencies: (none — leaf function)")

        total_affected = len(callers)
        affected_files = len(set(c["file"] for c in callers))
        lines.append(f"\nImpact summary: {total_affected} function{'s' if total_affected != 1 else ''} in {affected_files} file{'s' if affected_files != 1 else ''} may be affected")
        return "\n".join(lines)

    @mcp.tool()
    def detect_clones(file_path: str | None = None, min_lines: int = 5) -> str:
        """Find duplicate or near-duplicate functions in the repo.

        Detects Type 1 (exact copies) and Type 2 (copies with renamed variables).

        Args:
            file_path: optional — if given, find clones of functions in this file.
            min_lines: minimum function line count to consider (default 5).
        """
        if file_path is not None:
            if err := _validate_path(file_path):
                return err
        clones = indexer.detect_clones(file_path=file_path, min_lines=min_lines)
        if not clones:
            scope = file_path if file_path else "the repo"
            return f"No clones found in {scope} (min_lines={min_lines})."
        lines = []
        for i, group in enumerate(clones, 1):
            count = len(group["functions"])
            lc = group["line_count"]
            lines.append(f"Clone group {i} ({count} functions, {lc} lines each):")
            for fn in group["functions"]:
                lines.append(f"  {fn['file']}: {fn['name']}() → line {fn['line']}")
        total_groups = len(clones)
        total_fns = sum(len(g["functions"]) for g in clones)
        lines.append(f"\nSummary: {total_groups} clone group{'s' if total_groups != 1 else ''}, {total_fns} functions")
        return "\n".join(lines)

    @mcp.tool()
    def search_symbols(query: str | None = None, type: str | None = None,
                       parent: str | None = None, has_doc: bool | None = None,
                       min_complexity: int | None = None,
                       language: str | None = None,
                       format: str = "full") -> str:
        """Search for symbols across the repo with flexible filters.

        All parameters optional — combine for powerful filtering.

        Args:
            query: case-insensitive substring match on symbol name
            type: exact match on type (function, class, method, struct, etc.)
            parent: case-insensitive substring match on parent class name
            has_doc: True = only symbols with doc, False = only without
            min_complexity: minimum cyclomatic complexity
            language: filter by file extension without dot (e.g., "py", "js", "go")
            format: "full" (default) or "compact" (abbreviated)
        """
        results = indexer.search_symbols(
            query=query, type=type, parent=parent,
            has_doc=has_doc, min_complexity=min_complexity, language=language,
        )
        if not results:
            filters = []
            if query: filters.append(f'query="{query}"')
            if type: filters.append(f'type="{type}"')
            if parent: filters.append(f'parent="{parent}"')
            if has_doc is not None: filters.append(f'has_doc={has_doc}')
            if min_complexity: filters.append(f'min_complexity={min_complexity}')
            if language: filters.append(f'language="{language}"')
            return f"No symbols found matching {', '.join(filters) if filters else 'criteria'}."

        if format == "compact":
            lines = []
            for r in results:
                doc_suffix = f" # {r['doc']}" if r["doc"] else ""
                if r["parent"]:
                    params = r.get("params", "").replace(", ", ",")
                    lines.append(f"{r['file']}:.{r['name']}{params}:{r['line']}{doc_suffix}")
                else:
                    abbrev = _TYPE_ABBREV.get(r["type"], r["type"][:3])
                    lines.append(f"{r['file']}:{abbrev} {r['name']}:{r['line']}{doc_suffix}")
            lines.append(f"\n{len(results)} results")
            return "\n".join(lines)

        lines = ["Search results:"]
        for r in results:
            parent_info = f" (in {r['parent']})" if r["parent"] else ""
            lines.append(f"  {r['file']}: {r['type']} {r['name']}{parent_info} → line {r['line']}")
            if r["doc"]:
                lines.append(f"    \"{r['doc']}\"")
        lines.append(f"\nFound {len(results)} symbol{'s' if len(results) != 1 else ''}")
        return "\n".join(lines)

    @mcp.tool()
    def find_tests(file_path: str, symbol_name: str) -> str:
        """Find test functions associated with a symbol.

        Searches by naming convention (test_<name>), direct reference,
        and file convention (test_<module>). Results ranked by confidence.

        Args:
            file_path: path relative to the repo root
            symbol_name: name of the function/class to find tests for
        """
        if err := _validate_path(file_path):
            return err
        if file_path not in indexer._index:
            return f"File not found: {file_path}"
        tests = indexer.find_tests(file_path, symbol_name)
        if not tests:
            return f"No tests found for '{symbol_name}' in {file_path}."
        lines = [f"Tests for {symbol_name}() in {file_path}:"]
        for t in tests:
            lines.append(f"  {t['file']}: {t['name']}() → line {t['line']}  ({t['reason']})")
        lines.append(f"\nFound {len(tests)} test{'s' if len(tests) != 1 else ''}")
        return "\n".join(lines)

    # ── Graph-backed onboarding tools ────────────────────────────────────────

    @mcp.tool()
    def index_status() -> dict:
        """Report on graph index freshness and stats."""
        stats = graph_store.stats()
        last = graph_store.get_meta("last_indexed_at")
        return {
            "graph_exists": True,
            **stats,
            "last_indexed_at": last,
        }

    @mcp.tool()
    def get_repository_map(max_items: int = 5) -> dict:
        """Get a compact overview of the repository for onboarding.

        Returns languages, entry points, hotspots, recommended start_here symbols,
        and stats — everything an agent needs to orient in an unfamiliar repo.

        Args:
            max_items: maximum items per section (default 5)
        """
        return graph_queries.repository_map(max_items=max_items)

    @mcp.tool()
    def resolve_symbol(query: str, kind: str | None = None,
                       path_hint: str | None = None, limit: int = 10) -> dict:
        """Disambiguate a short symbol name into ranked qualified matches.

        Resolves ambiguous names like 'add' to specific qualified symbols
        ranked by relevance (path match, non-test preference, centrality).

        Args:
            query: symbol name to resolve
            kind: filter by type (function, class, method, etc.)
            path_hint: prefer results from files matching this path
            limit: max results (default 10)
        """
        results = graph_queries.resolve_symbol(query, kind=kind, path_hint=path_hint, limit=limit)
        return {
            "query": query,
            "matches": [
                {
                    "qualified_name": r.qualified_name,
                    "name": r.name,
                    "kind": r.kind,
                    "file": r.file_path,
                    "line": r.start_line,
                    "is_test": r.is_test,
                }
                for r in results
            ],
        }

    @mcp.tool()
    def search_graph(query: str | None = None, kind: str | None = None,
                     file_pattern: str | None = None, relationship: str | None = None,
                     direction: str | None = None, min_degree: int | None = None,
                     max_degree: int | None = None, limit: int = 10, offset: int = 0) -> dict:
        """Search the code graph with flexible filters and pagination.

        Args:
            query: case-insensitive substring match on symbol name
            kind: exact type filter (function, class, method, struct, etc.)
            file_pattern: substring match on file path
            relationship: edge type filter (CALLS, IMPORTS, CONTAINS)
            direction: "inbound" or "outbound" (used with relationship)
            min_degree: minimum total connections
            max_degree: maximum total connections (0 = isolated/dead code)
            limit: max results per page (default 10)
            offset: pagination offset (default 0)
        """
        return graph_queries.search_graph(
            query=query, kind=kind, file_pattern=file_pattern,
            relationship=relationship, direction=direction,
            min_degree=min_degree, max_degree=max_degree,
            limit=limit, offset=offset,
        )

    @mcp.tool()
    def get_change_impact(symbol_query: str | None = None,
                          diff_scope: str | None = None, depth: int = 3) -> dict:
        """Analyze impact of a change — by explicit symbol or git diff.

        Shows direct/transitive callers with risk classification and affected tests.

        Args:
            symbol_query: symbol name to analyze (e.g., "add")
            diff_scope: "working" (uncommitted), "staged", or "HEAD~1" for git-based analysis
            depth: max hop depth (default 3)
        """
        return graph_queries.change_impact(
            symbol_query=symbol_query,
            diff_scope=diff_scope,
            root=root,
            depth=depth,
        )

    # ── Dataflow & taint analysis ────────────────────────────────────────────

    @mcp.tool()
    def analyze_dataflow(file_path: str, function_name: str,
                         mode: str = "flow", depth: int = 3) -> dict:
        """Analyze variable dataflow and security taint paths in a function.

        Args:
            file_path: path relative to the repo root
            function_name: name of the function to analyze
            mode: "flow" (variable dataflow), "taint" (source→sink taint paths),
                  or "cross_taint" (cross-function taint tracing)
            depth: max cross-function depth for cross_taint mode (default 3)
        """
        from .graph.dataflow import extract_dataflow, extract_taint_paths, extract_cross_function_taint

        if err := _validate_path(file_path):
            return {"error": err}

        if mode == "cross_taint":
            if file_path not in indexer._index:
                return {"error": f"File not found: {file_path}"}
            return extract_cross_function_taint(indexer, file_path, function_name, depth=depth)

        entry = indexer._index.get(file_path)
        if entry is None:
            return {"error": f"File not found: {file_path}"}

        if mode == "taint":
            result = extract_taint_paths(entry.plugin, entry.source, function_name)
        else:
            result = extract_dataflow(entry.plugin, entry.source, function_name)

        if result is None:
            return {"error": f"Function '{function_name}' not found in {file_path}"}
        return result

    @mcp.tool()
    def find_hot_paths(top_n: int = 10) -> str:
        """Find high-leverage optimization targets by combining complexity and call frequency.

        Returns functions ranked by hot_score = complexity * inbound_call_count.
        Functions with high scores are called often AND complex — prime optimization targets.

        Args:
            top_n: max results to return (default 10)
        """
        results = graph_queries.find_hot_paths(indexer, top_n=top_n)
        if not results:
            return "No hot paths found (no functions with both callers and complexity)."
        lines = ["Hot path analysis (complexity × call frequency):"]
        for i, r in enumerate(results, 1):
            lines.append(
                f"  {i}. {r['file']}: {r['name']}() → line {r['line']}  "
                f"(score={r['hot_score']}, complexity={r['complexity']}, calls={r['inbound_calls']})"
            )
        lines.append(f"\nTop {len(results)} optimization targets")
        return "\n".join(lines)

    @mcp.tool()
    def get_dependency_graph(file_path: str | None = None,
                              format: str = "mermaid") -> str:
        """Get the file dependency graph as Mermaid syntax or a list.

        Shows which files import which other files, useful for understanding
        module structure and identifying circular dependencies.

        Args:
            file_path: optional — show only dependencies involving this file
            format: "mermaid" (default, Mermaid.js flowchart) or "list"
        """
        if file_path is not None:
            if err := _validate_path(file_path):
                return err
        result = graph_queries.get_dependency_graph(file_path=file_path, format=format)
        summary = f"\n\n{result['nodes']} files, {result['edges']} import edges"
        return result["content"] + summary

    @mcp.tool()
    def git_history(mode: str = "blame", file_path: str | None = None,
                    top_n: int = 20, since: str | None = None,
                    min_commits: int = 3) -> str:
        """Analyze git history: blame, churn, or change coupling.

        Args:
            mode: "blame" (per-line attribution), "churn" (most-changed files),
                  or "coupling" (files that change together)
            file_path: required for blame, optional filter for coupling
            top_n: max results for churn/coupling (default 20)
            since: date filter for churn (e.g., "6 months ago")
            min_commits: minimum co-change count for coupling (default 3)
        """
        from .graph.git_analysis import get_blame as _get_blame
        from .graph.git_analysis import get_churn as _get_churn
        from .graph.git_analysis import get_change_coupling as _get_change_coupling

        if file_path is not None:
            if err := _validate_path(file_path):
                return err

        if mode == "blame":
            if not file_path:
                return "file_path is required for blame mode."
            result = _get_blame(root, file_path)
            if not result["lines"]:
                return f"No blame data for {file_path} (file not in git or no commits)."
            lines = [f"Blame for {file_path}:"]
            lines.append(f"\nAuthors:")
            for author, count in result["summary"]["authors"].items():
                lines.append(f"  {author}: {count} lines")
            lines.append(f"\nTotal: {result['summary']['total_lines']} lines")
            return "\n".join(lines)

        elif mode == "churn":
            results = _get_churn(root, top_n=top_n, since=since)
            if not results:
                return "No churn data found (no git history or no matching files)."
            lines = ["File churn (most changed files):"]
            for i, r in enumerate(results, 1):
                lines.append(
                    f"  {i}. {r['file']}  ({r['commits']} commits, "
                    f"+{r['additions']}/-{r['deletions']})"
                )
            lines.append(f"\nTop {len(results)} most-changed files")
            return "\n".join(lines)

        elif mode == "coupling":
            results = _get_change_coupling(root, file_path=file_path, top_n=top_n, min_commits=min_commits)
            if not results:
                return "No change coupling found (not enough co-changing files)."
            lines = ["Change coupling (files that change together):"]
            for r in results:
                lines.append(
                    f"  {r['file_a']} ↔ {r['file_b']}  "
                    f"({r['co_commits']} co-commits, coupling={r['coupling_ratio']})"
                )
            lines.append(f"\n{len(results)} coupled file pairs")
            return "\n".join(lines)

        else:
            return f"Unknown mode '{mode}'. Use 'blame', 'churn', or 'coupling'."

    @mcp.tool()
    def suggest_docs(file_path: str | None = None,
                     symbol_name: str | None = None) -> str:
        """Find undocumented functions and assemble context for writing docs.

        Args:
            file_path: optional — scope to a specific file
            symbol_name: optional — scope to a specific symbol name
        """
        if file_path is not None:
            if err := _validate_path(file_path):
                return err
        results = graph_queries.suggest_docs(indexer, file_path=file_path, symbol_name=symbol_name)
        if not results:
            return "No undocumented functions found."
        lines = ["Undocumented functions needing docs:"]
        for r in results:
            parent_str = f" (in {r['parent']})" if r.get("parent") else ""
            lines.append(f"\n  {r['file']}:{r['line']} — {r['name']}({r['params']}){parent_str}")
            if r["callees"]:
                lines.append(f"    Calls: {', '.join(r['callees'])}")
            if r["callers"]:
                lines.append(f"    Called by: {', '.join(r['callers'])}")
            if r["variables"]:
                var_strs = [f"{v['name']}: {v['type']}" if v['type'] else v['name'] for v in r["variables"]]
                lines.append(f"    Variables: {', '.join(var_strs)}")
        lines.append(f"\n{len(results)} undocumented functions found")
        return "\n".join(lines)

    return mcp


def run(root: str, exclude: Iterable[str] = ()):
    mcp = create_server(root, exclude=exclude)
    mcp.run()
