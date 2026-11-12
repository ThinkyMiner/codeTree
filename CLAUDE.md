# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

codetree is a Python MCP (Model Context Protocol) server that gives coding agents structured code understanding via tree-sitter. Instead of reading entire files, an agent can ask "what classes are in this file?" or "what does this function call?" and get precise, structured answers.

It exposes **23 tools** over MCP:

### Structural Analysis Tools (13)

| Tool | Purpose | Returns |
|------|---------|---------|
| `get_file_skeleton(file_path, format?)` | Classes, functions, methods with line numbers + doc comments; `format="compact"` omits doc lines | `class Foo → line 5`, `"A calculator."`, `  def bar(x, y) (in Foo) → line 7` |
| `get_symbol(file_path, symbol_name)` | Full source of a function/class | `# path:line\n<source code>` |
| `find_references(symbol_name)` | All usages across the repo | `  file.py:12`, `  other.py:34` |
| `get_call_graph(file_path, function_name)` | What it calls + what calls it | `→ callee`, `← file.py:20` |
| `get_imports(file_path)` | Import/use statements with line numbers | `  1: import os`, `  2: from pathlib import Path` |
| `get_skeletons(file_paths, format?)` | Skeletons for multiple files in one call; `format="compact"` omits doc lines | `=== calc.py ===\nclass Foo → line 1` |
| `get_symbols(symbols)` | Full source of multiple symbols | `# calc.py:1\nclass Foo:` |
| `get_complexity(file_path, function_name)` | Cyclomatic complexity of a function | `Complexity of foo() in calc.py: 5\n  if: 2, for: 1` |
| `find_dead_code(file_path?)` | Symbols defined but never referenced | `Dead code in calc.py:\n  function unused() → line 15` |
| `get_blast_radius(file_path, symbol_name)` | Transitive impact analysis | `Direct callers:\n  main.py: run() → line 4` |
| `detect_clones(file_path?, min_lines?)` | Duplicate/near-duplicate functions | `Clone group 1 (2 functions, 12 lines each):` |
| `search_symbols(query?, type?, parent?, ..., format?)` | Flexible symbol search; `format="compact"` omits doc lines | `calc.py: class Calculator → line 1` |
| `find_tests(file_path, symbol_name)` | Find test functions for a symbol | `test_calc.py: test_add() → line 3  (name match)` |

### Graph & Onboarding Tools (10)

| Tool | Purpose | Returns |
|------|---------|---------|
| `index_status()` | Indexing progress, graph freshness and stats (never blocks) | `{graph_exists, files, symbols, edges, last_indexed_at, status, files_discovered, files_indexed, index_ready, graph_ready, startup_seconds?, error?}` |
| `get_repository_map(max_items?)` | Compact repo overview for agent onboarding | `{languages, entry_points, hotspots, start_here, test_roots, stats}` |
| `resolve_symbol(query, kind?, path_hint?)` | Disambiguate short symbol names into qualified matches | `{matches: [{qualified_name, name, kind, file, line}]}` |
| `search_graph(query?, kind?, file_pattern?, ...)` | Structured graph search with pagination and degree filtering | `{total, results: [{qualified_name, kind, in_degree, out_degree}]}` |
| `get_change_impact(symbol_query?, diff_scope?)` | Git-aware change impact with risk classification | `{changed_symbols, impact: {CRITICAL, HIGH, MEDIUM}, affected_tests}` |
| `analyze_dataflow(file_path, function_name, mode?, depth?)` | Variable dataflow (`mode="flow"`), taint analysis (`"taint"`), or cross-function taint (`"cross_taint"`) | `{variables, sinks}` or `{paths: [{verdict, risk}]}` |
| `find_hot_paths(top_n?)` | High-complexity × high-call-count optimization targets | `file:line — name (complexity=N, callers=M, score=S)` |
| `get_dependency_graph(file_path?, format?)` | File-level dependency graph as Mermaid or list | `graph LR\n  main.py --> calc.py` |
| `git_history(mode?, file_path?, top_n?, since?, min_commits?)` | Git blame (`mode="blame"`), file churn (`"churn"`), or change coupling (`"coupling"`) | Author summary, churn list, or coupled file pairs |
| `suggest_docs(file_path?, symbol_name?)` | Find undocumented functions with context for doc generation | `file:line — name(params), calls: [...], callers: [...]` |

`get_file_skeleton` also warns about syntax errors (`WARNING: File has syntax errors — skeleton may be incomplete`).

All `file_path` arguments are **relative to the repo root** (e.g., `"src/main.py"`).

## Supported Languages

| Extension(s) | Plugin | Key node types |
|---|---|---|
| `.py` | PythonPlugin | `function_definition`, `class_definition`, `decorated_definition` |
| `.js`, `.jsx` | JavaScriptPlugin | `function_declaration`, `class_declaration`, `arrow_function`, `generator_function_declaration` |
| `.ts` | TypeScriptPlugin | `function_declaration`, `class_declaration`, `abstract_class_declaration`, `interface_declaration`, `type_alias_declaration` |
| `.tsx` | TSXPlugin | Same as TS, uses `tsts.language_tsx()` |
| `.go` | GoPlugin | `function_declaration`, `method_declaration`, `struct_type`, `interface_type` |
| `.rs` | RustPlugin | `function_item`, `struct_item`, `enum_item`, `trait_item`, `impl_item` |
| `.java` | JavaPlugin | `class_declaration`, `interface_declaration`, `enum_declaration`, `method_declaration`, `constructor_declaration` |
| `.c`, `.h` | CPlugin | `function_definition`, `struct_specifier`, `type_definition` |
| `.cpp`, `.cc`, `.cxx`, `.hpp`, `.hh` | CppPlugin | `class_specifier`, `function_definition`, `struct_specifier`, `namespace_definition` |
| `.rb` | RubyPlugin | `class`, `module`, `method`, `singleton_method` |

## Commands

```bash
# Activate venv (required before all commands)
source .venv/bin/activate

# Run all tests (~1200 tests, ~20s)
pytest

# Run a single test file
pytest tests/languages/test_python.py -v

# Run a single test
pytest tests/languages/test_python.py::test_skeleton_finds_class -v

# Run only comprehensive tests for one language
pytest tests/languages/test_rust_comprehensive.py -v

# Run the MCP server
codetree --root /path/to/repo

# Install in dev mode
pip install -e .
```

No linter or formatter is configured.

## Architecture

```
MCP tool call → server.py → indexer.py → FileEntry.plugin → tree-sitter parse → structured result
                         → graph/ package → SQLite .codetree/graph.db → onboarding, search, impact, dataflow
```

### Core modules (`src/codetree/`)

| File | Responsibility |
|---|---|
| `server.py` | FastMCP 3.1.0 server — defines the 23 tools; each tool asks `IndexState` for the data it needs (single-file → on-demand parse, repo-wide → full index, graph → SQLite graph). Language-unaware. |
| `index_state.py` | `IndexState` — owns the index lifecycle: discovery → indexing (skeleton cache) → graph build, in a background thread when run as `codetree` (`create_server(root, background=True)`), synchronously by default (tests). Exposes `files_ready`/`index_ready`/`graph_ready` events, bounded waits (`WAIT_TIMEOUT`, env `CODETREE_WAIT_TIMEOUT`), progress and errors for `index_status`. Exposed to tests as `mcp._codetree_state`. |
| `indexer.py` | Discovers files, stores a `FileEntry` per file (with its plugin + `has_errors` flag), routes all queries through the stored plugin. Builds a definition index and lazy call graph for dead code, blast radius, and clone detection. Discovers files with `git ls-files` (tracked files always; untracked non-ignored files minus `SKIP_DIRS`; nested worktrees/repos/submodules excluded), falling back to an `os.walk` that prunes `SKIP_DIRS` (`.venv`, `node_modules`, `__pycache__`, `.git`, etc.) and nested worktrees. |
| `cache.py` | `.codetree/index.json` — stores pre-computed skeletons with mtime-based invalidation. Language-unaware. |
| `registry.py` | Maps file extensions → plugin instances. The **only** place languages are registered. |

### Graph layer (`src/codetree/graph/`)

| File | Responsibility |
|---|---|
| `models.py` | `SymbolNode`, `Edge` dataclasses and `make_qualified_name()` — the data model for the persistent graph. |
| `store.py` | `GraphStore` — SQLite CRUD for symbols, edges, files, meta tables. Stores graph at `.codetree/graph.db`. |
| `builder.py` | `GraphBuilder` — Incremental graph build from indexer data. Uses sha256 content hashing to skip unchanged files. Creates CALLS (with import-aware weight), CONTAINS, and IMPORTS edges. |
| `queries.py` | `GraphQueries` — `repository_map()`, `resolve_symbol()`, `search_graph()`, `change_impact()`, `find_hot_paths()`, `get_dependency_graph()`, `suggest_docs()`. Powers the onboarding/search/impact/visualization tools. |
| `dataflow.py` | `extract_dataflow()`, `extract_taint_paths()`, `extract_cross_function_taint()` — Intra- and cross-function variable flow tracking and security taint analysis using tree-sitter AST. |
| `git_analysis.py` | `get_blame()`, `get_churn()`, `get_change_coupling()` — Git history analysis tools. |

### Plugin system (`src/codetree/languages/`)

| File | Responsibility |
|---|---|
| `base.py` | `LanguagePlugin` ABC with 5 abstract methods + `check_syntax()`, `compute_complexity()`, `normalize_source_for_clones()`, `get_ast_sexp()` defaults + shared `_matches()`, `_clean_doc()`, `_fill_docs_from_siblings()` helpers |
| `python.py` | PythonPlugin |
| `javascript.py` | JavaScriptPlugin (also provides `_arrow_params()` used by TS) |
| `typescript.py` | TypeScriptPlugin + TSXPlugin |
| `go.py` | GoPlugin |
| `rust.py` | RustPlugin |
| `java.py` | JavaPlugin |
| `c.py` | CPlugin |
| `cpp.py` | CppPlugin (inherits CPlugin) |
| `ruby.py` | RubyPlugin |
| `_template.py` | Boilerplate for adding new languages |

Each plugin implements:
1. **`extract_skeleton(source: bytes) -> list[dict]`** — top-level classes/functions/methods with `{type, name, line, parent, params, doc}`
2. **`extract_symbol_source(source: bytes, name: str) -> tuple[str, int] | None`** — full source text + start line
3. **`extract_calls_in_function(source: bytes, fn_name: str) -> list[str]`** — sorted callee names
4. **`extract_symbol_usages(source: bytes, name: str) -> list[dict]`** — all occurrences with `{line, col}`
5. **`extract_imports(source: bytes) -> list[dict]`** — import statements with `{line, text}`
6. **`check_syntax(source: bytes) -> bool`** — True if file has syntax errors (non-abstract, default False)
7. **`compute_complexity(source: bytes, fn_name: str) -> dict | None`** — cyclomatic complexity `{total, breakdown}` (non-abstract, default None)
8. **`normalize_source_for_clones(source: bytes) -> str`** — AST-normalized source for clone detection (non-abstract, default in base; requires `_get_parser()`)
9. **`get_ast_sexp(source: bytes, symbol_name?, max_depth?) -> str | None`** — S-expression AST output (non-abstract, default in base; requires `_get_parser()`)
10. **`extract_variables(source: bytes, fn_name: str) -> list[dict]`** — local variables with `{name, line, type, kind}` (non-abstract, default `[]`)

### Test structure (`tests/`)

| File | What it tests |
|---|---|
| `test_server.py` | Original 4 MCP tools via FastMCP, output format, line accuracy, cross-language |
| `test_indexer.py` | Build, skip-dirs, skeleton/symbol/refs/callgraph through indexer layer |
| `test_file_discovery.py` | git-based discovery (.gitignore, nested worktrees/repos, submodules), walk fallback, stale cache entries |
| `test_parse_cache.py` | Memoized query compilation and per-thread parse-tree cache |
| `test_async_startup.py` | Background indexing: non-blocking startup, on-demand single-file tools, "still building" messages, failure handling |
| `test_cache.py` | Cache load/save/invalidation |
| `tests/languages/test_<lang>.py` | Per-language core tests |
| `tests/languages/test_<lang>_comprehensive.py` | Exhaustive code pattern coverage per language |
| `test_new_features.py` | Method extraction, Rust traits/enums, Java enums, TS type aliases, indexer fixes |
| `test_edge_cases.py` | Empty files, syntax errors, comment-only files, unicode, nested code |
| `test_server_new_types.py` | MCP server formatting of trait/enum/type skeleton types |
| `test_imports.py` | Import extraction per-language + `get_imports` MCP tool |
| `test_docstrings.py` | Doc comment extraction per-language + skeleton doc display |
| `test_syntax_errors.py` | Syntax error detection per-language + skeleton warning |
| `test_dead_code.py` | Definition index, `find_dead_code` indexer method + MCP tool |
| `test_blast_radius.py` | Lazy call graph, `get_blast_radius` indexer method + MCP tool |
| `test_clones.py` | Clone normalization, `detect_clones` indexer method + MCP tool |
| `test_ast.py` | `get_ast_sexp` plugin method + `get_ast` indexer method |
| `test_search.py` | `search_symbols` indexer method + MCP tool |
| `test_token_opt.py` | Compact format for skeleton/search tools |
| `test_importance.py` | PageRank symbol importance (indexer-level) |
| `test_discovery.py` | Test function discovery |
| `test_variables.py` | Variable extraction per-language + indexer integration |
| `test_graph_store.py` | SQLite graph store CRUD — symbols, edges, files, meta, stats |
| `test_graph_builder.py` | Incremental graph builder — full build, incremental, changed/deleted files, test detection |
| `test_graph_queries.py` | Graph queries — repository map, resolve symbol, search graph |
| `test_onboarding_tools.py` | MCP tools: index_status, get_repository_map, resolve_symbol, search_graph |
| `test_change_impact.py` | Change impact — symbol-based, git-diff-based, transitive callers, risk classification |
| `test_dataflow.py` | Dataflow engine — variable tracking, dependency edges, taint sources/sinks, cross-function taint |
| `test_dataflow_tools.py` | MCP tool: analyze_dataflow (flow, taint, cross_taint modes) |
| `test_git_analysis.py` | Git blame, churn, change coupling — analysis functions + `git_history` MCP tool |
| `test_doc_suggestions.py` | Auto-documentation suggestions — undocumented function detection + context assembly |

Fixtures in `conftest.py`: `sample_repo` (Python-only), `rich_py_repo` (decorators/dataclasses), `multi_lang_repo` (5 languages).

## tree-sitter 0.25.x API

The tree-sitter Python bindings have breaking changes from older docs:
- Use `Query(LANGUAGE, "...")` not `LANGUAGE.query(...)` — in plugins, call the memoized `_query(LANGUAGE, "...")` from `languages/base.py` instead (compiling a Query costs more than parsing a file)
- Wrap module parsers as `_PARSER = CachedParser(Parser(_LANGUAGE))` so repeated calls on the same source reuse the tree
- Use `QueryCursor(query).matches(node)` not `query.matches(node)`
- Match captures are `list[Node]` — unwrap with `nodes[0]` or use the shared `_matches()` helper from `languages/base.py`
- All `.decode()` calls must use `errors="replace"`

## Language-Specific Gotchas

- **Python:** Decorated functions/classes are wrapped in `decorated_definition` — query both decorated and plain patterns. Check `decorated_definition` FIRST in `extract_symbol_source` to include decorator lines. `from __future__` is `future_import_statement` (not `import_from_statement`). Docstrings are in the function body (`expression_statement > string`), unlike all other languages where doc comments are `prev_named_sibling`.
- **JavaScript:** `new Foo()` is a `new_expression`, not `call_expression`. Exported classes wrap in `export_statement`. Generators use `generator_function_declaration`. Arrow functions: `lexical_declaration → arrow_function`. JSDoc `/** */` is a `comment` node (same type as `//`).
- **TypeScript:** Class names use `type_identifier` (not `identifier`). Grammar API: `tsts.language_typescript()` / `tsts.language_tsx()`. Abstract classes use `abstract_class_declaration` (separate from `class_declaration`). Same `export_statement` wrapping as JS.
- **Go/Rust/Java:** Struct/type names are `type_identifier` — search both `identifier` and `type_identifier` in usage queries.
- **Go:** Each `//` line is a separate `comment` node. Multi-line doc comments require walking back through consecutive `comment` siblings.
- **Rust:** Associated function calls (`Server::new()`) use `scoped_identifier name: (identifier)` in `call_expression`. Trait method signatures use `function_signature_item` (not `function_item`). Enums use `enum_item`. Each `///` line is a separate `line_comment` node (same walk-back needed as Go).
- **Java:** Constructors use `constructor_declaration` (not `method_declaration`). Interfaces use `interface_declaration` with methods in `interface_body`. Enum methods live under `enum_body > enum_body_declarations > method_declaration` (not directly in `enum_body`). Javadoc `/** */` is `block_comment` as `prev_named_sibling`.
- **C:** Root node is `translation_unit`. Functions use `function_definition → function_declarator → identifier`. Structs use `struct_specifier → type_identifier`. Typedef structs use `type_definition → type_identifier`. Includes use `preproc_include`. Doc comments are `///` comments as `prev_named_sibling`.
- **C++:** Inherits from CPlugin. Classes use `class_specifier → type_identifier`. Methods inside classes use `field_identifier` (not `identifier`). Namespaces use `namespace_definition → namespace_identifier`. Also searches `using_declaration` for imports.
- **Ruby:** Root node is `program`. Classes/modules use `constant` for names (not `identifier`). Methods without params don't have a `method_parameters` child. Singleton methods (`def self.foo`) use `singleton_method` node. Imports are `call` nodes where method is `require`/`require_relative`.

## Adding a New Language

1. `pip install tree-sitter-LANG` and add to `pyproject.toml`
2. Copy `src/codetree/languages/_template.py` → `languages/LANG.py`, implement 5 abstract methods + `check_syntax`
3. Register in `registry.py`
4. Add tests (use existing `tests/languages/test_python.py` as reference)

## Key Conventions

- Plugin classes: `{Lang}Plugin` (e.g., `PythonPlugin`, `GoPlugin`)
- Module-level parser/language globals: `_PARSER`, `_LANGUAGE`
- Skeleton results are deduplicated by `(name, line)` and sorted by line number
- File discovery: in a git work tree, tracked files (`git ls-files --cached`) are always indexed — `.gitignore` decides, so a tracked `build/` or `env/` is indexed — while untracked non-ignored files (`--others --exclude-standard`) also skip `SKIP_DIRS`, so an un-ignored `.venv`/`node_modules` is never crawled. Nested worktrees such as `.claude/worktrees/`, nested repos and submodules never leak in, and `.codetree/` is always excluded. Outside git (no repo, git missing or refusing the repo, root ignored), the walk prunes `SKIP_DIRS` (`.venv`, `node_modules`, `__pycache__`, `.git`, …) and directories whose `.git` is a file (worktrees, submodules) — without this, crawling `.venv` causes Claude Code timeout. Only discovered files are re-injected from the cache, which also stores each file's `has_errors` flag.
- FastMCP tool access in tests: `mcp.local_provider._components[f"tool:{name}@"].fn`
- **Doc sync rule**: When tools are added, removed, or changed, update all 5 doc files: `README.md`, `TOOLS_GUIDE.md`, `LANDING_PAGE.md`, `CLAUDE.md`, `AGENTS.md`

<!-- GSD:project-start source:PROJECT.md -->
## Project

**codetree Production Hardening**

codetree is a Python MCP server that gives coding agents structured code understanding via tree-sitter. This hardening effort fixes critical and high-priority bugs discovered during a codebase audit — issues that cause agents to receive wrong data, crash the server, or expose security holes.

**Core Value:** Every MCP tool call returns correct, trustworthy data — agents can rely on codetree without worrying about stale state, silent failures, or wrong results.

### Constraints

- **Testing**: All fixes must have tests; existing 1070 tests must continue passing
- **Backward compat**: No changes to MCP tool signatures (agents already use them)
- **Performance**: Server startup must stay under ~2s for typical repos
<!-- GSD:project-end -->

<!-- GSD:stack-start source:codebase/STACK.md -->
## Technology Stack

## Languages
- Python 3.10+ - Core application language; MCP server and all indexing/analysis logic
- Python (`.py`)
- JavaScript/JSX (`.js`, `.jsx`)
- TypeScript (`.ts`)
- TypeScript JSX (`.tsx`)
- Go (`.go`)
- Rust (`.rs`)
- Java (`.java`)
- C (`.c`, `.h`)
- C++ (`.cpp`, `.cc`, `.cxx`, `.hpp`, `.hh`)
- Ruby (`.rb`)
## Runtime
- Python 3.10+ as base interpreter
- Standard library modules: `pathlib`, `json`, `subprocess`, `sqlite3`, `argparse`, `atexit`, `hashlib`, `re`, `dataclasses`
- pip (standard Python package manager)
- Optional: `uv` for faster installation (recommended in README for Quick Start)
- Lockfile: `.venv/` contains installed packages; no `requirements.txt` or `pyproject.lock` committed
## Frameworks
- FastMCP 3.x (`>=3.0.0`, which runs sync tools in a thread pool — required for background indexing) - MCP (Model Context Protocol) server framework
- tree-sitter 0.23.0+ - AST parsing library (language-agnostic)
- pytest (via GitHub Actions workflow, not explicitly in pyproject.toml dependencies but installed in CI)
- hatchling (build backend)
## Key Dependencies
- tree-sitter (0.23.0+) - Core AST parsing; blocks everything else
- fastmcp (3.0.0+) - MCP server registration and tool transport
- tree-sitter-python, tree-sitter-javascript, tree-sitter-typescript, tree-sitter-go, tree-sitter-rust, tree-sitter-java, tree-sitter-c, tree-sitter-cpp, tree-sitter-ruby
## Configuration
- No explicit environment variables required for normal operation
- `.codetree/` directory created in repository root for persistent data:
- Startup: Command-line argument `--root /path/to/repo` specifies target codebase (default: current directory)
- `pyproject.toml` - Single source of truth for dependencies, project metadata, build config
- Python wheel built via hatchling (not in committed dist/)
- CLI entrypoint: `codetree = "codetree.__main__:main"`
## Platform Requirements
- Python 3.10+ interpreter
- pip or uv for package installation
- `.venv/` virtual environment (created and activated via `source .venv/bin/activate`)
- Git for accessing codebase metadata (used by `git_analysis.py` module)
- ~150MB disk for installed dependencies (tree-sitter + language grammars)
- Python 3.10+ on target system
- No external services or databases required — SQLite is embedded
- Runs as stdio-based MCP server in agent/IDE contexts (Claude Code, Cursor, VS Code, Windsurf)
- Network: Optional — git history analysis uses local `git` command; no outbound network calls
- Memory: ~50-100MB for typical codebases; scales with repository size
- CPU: Single-threaded analysis; no async I/O (subprocess calls are blocking)
## Storage Model
- `.codetree/index.json` - JSON text file in target repo (human-readable, git-ignored)
- `.codetree/graph.db` - SQLite 3 database (binary, git-ignored)
- No cloud storage, no S3, no vector DB
- Cache invalidated on file modification time (mtime) changes
- Graph rebuilt incrementally on changes (sha256 content hashing)
- Both are .gitignore'd to avoid committing analysis artifacts
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->
## Conventions

## Naming Patterns
- Modules use lowercase with underscores: `indexer.py`, `registry.py`, `cache.py`
- Plugin modules follow pattern: `{language}.py` (e.g., `python.py`, `javascript.py`, `base.py`)
- Test files follow pattern: `test_{module}.py` (e.g., `test_indexer.py`, `test_server.py`)
- Template file for new code: `_template.py` as boilerplate
- Lowercase with underscores: `get_plugin()`, `extract_skeleton()`, `extract_symbol_source()`
- Private/internal functions prefixed with underscore: `_matches()`, `_clean_doc()`, `_should_skip()`
- Boolean predicates start with `is_` or `check_`: `check_syntax()`, `is_valid()`
- Getter functions use `get_` prefix: `get_skeleton()`, `get_symbol()`, `get_imports()`
- Setter functions use `set_` prefix: `set()` for simple assignment
- Extraction functions use `extract_` prefix: `extract_skeleton()`, `extract_calls_in_function()`
- MCP tool functions decorated with `@mcp.tool()` use clear action verbs: `get_file_skeleton()`, `find_references()`
- Lowercase with underscores: `file_entry`, `rel_path`, `source`, `skeleton`
- Class instances: `indexer`, `plugin`, `cache`, `store`
- Dictionaries/collections singular or plural as appropriate: `results`, `definitions`, `call_graph`
- Constants: UPPERCASE with underscores: `SKIP_DIRS`, `_EXCLUDED_NAMES`
- Module-level parser/language globals: `_PARSER`, `_LANGUAGE`
- Private instance variables: `_index`, `_definitions`, `_call_graph`, `_root`
- Loop counters use full names not `i`: `for rel_path, entry in ...` or `for item in skeleton:`
- Classes use PascalCase: `LanguagePlugin`, `FileEntry`, `Calculator`
- Plugin classes follow pattern: `{Language}Plugin` (e.g., `PythonPlugin`, `JavaScriptPlugin`, `GoPlugin`)
- Abstract base class: `LanguagePlugin` (ABC)
- Dataclass fields documented inline with type hints and brief purpose
- Type unions use modern syntax: `str | Path` not `Union[str, Path]`
## Code Style
- No automatic linter or formatter configured (`.eslintrc`, `.prettierrc`, `biome.json` not present)
- Implicit convention: 4-space indentation (Python standard)
- Line length: no strict limit enforced, but code is reasonably sized
- Imports grouped: standard library, third-party, local
- Blank lines: 2 between top-level definitions, 1 between methods
- No linting tool configured in `pyproject.toml`
- Code quality maintained through convention and testing
- Type hints are used throughout: `extract_skeleton(source: bytes) -> list[dict]`
## Import Organization
- No path aliases configured (no `jsconfig.json`, `tsconfig.json` paths)
- Relative imports used throughout: `from .indexer import ...`, `from ..graph.store import ...`
- All paths are relative to package root: `src/codetree/`
## Error Handling
- Graceful degradation: functions return `None` or empty list on error, not exceptions
- `extract_symbol_source(source, name) -> tuple[str, int] | None` returns None if symbol not found
- `get_plugin(path) -> LanguagePlugin | None` returns None for unsupported extensions
- `Cache.load()` catches `json.JSONDecodeError` and `OSError`, silently returns empty dict
- Skeleton parsing catches no exceptions — invalid syntax captured via `plugin.check_syntax()` flag
- String methods use `.decode("utf-8", errors="replace")` for safe UTF-8 handling across all languages
- File not found cases return user-friendly strings: `f"File not found: {file_path}"`, `f"Symbol '{symbol_name}' not found in {file_path}"`
- `_should_skip(path: Path) -> bool` checks directory names against `SKIP_DIRS` set
- `is_valid(rel_path, current_mtime) -> bool` verifies cache freshness by mtime matching
- Skeleton results deduplicated by `(name, line)` before returning
- All paths validated as relative using pattern matching: no absolute paths in results
## Logging
- Print-based debugging in utility functions
- No structured logging
- Docstrings used for user-facing documentation of tool behavior
## Comments
- Class docstrings describe purpose and key responsibilities
- Method docstrings describe what it does, args, return value, and any side effects
- Inline comments rare — code is self-documenting via clear naming
- Section separators used in large files: `# ── Section Name ──────────────────────────`
- Not used (Python codebase)
- Docstrings use triple quotes: `"""description."""`
- Parameter and return documentation in docstring body
## Function Design
- Functions are small and focused: 10-50 lines typical
- Extract helpers for complex operations: `_matches()`, `_fill_docs_from_siblings()`, `_clean_doc()`
- Core extraction methods in plugins are 50-150 lines (complex query logic)
- Main orchestration methods: `build()`, `create_server()` in 30-60 lines
- Positional parameters for required inputs: `extract_skeleton(source: bytes)`
- Keyword arguments with defaults for optional behavior: `format: str = "full"`
- Path parameters as `str | Path` for flexibility, converted to `Path` internally
- Multiple related params grouped: `extract_calls_in_function(source, fn_name)` not spread across calls
- Return meaningful types: `list[dict]`, `tuple[str, int] | None`, `dict[str, Any]`
- Return early on error/not-found: `if entry is None: return None`
- Return collections always (not None): `extract_calls_in_function() -> list[str]` (empty list if none)
- Tuples for related values: `extract_symbol_source() -> tuple[str, int] | None` (source + line)
## Module Design
- No explicit `__all__` lists; modules export all public (non-`_`) names
- Plugin classes instantiated at module level: `PythonPlugin()`, shared via registry
- Plugin registry: `PLUGINS: dict[str, LanguagePlugin]` in `registry.py`
- No barrel/index files (`__init__.py` is minimal)
- `src/codetree/__init__.py` is empty
- Language plugins imported individually: `from .languages.python import PythonPlugin`
- `indexer.py` — file discovery, parsing, skeleton building, cross-file analysis
- `languages/*.py` — language-specific AST parsing and extraction
- `server.py` — MCP tool registration and output formatting
- `cache.py` — skeleton caching with mtime invalidation
- `registry.py` — extension → plugin mapping
- `graph/*.py` — persistent graph building, queries, analysis
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->
## Architecture

## Pattern Overview
- **FastMCP 3.1.0 framework** - MCP tools exposed as JSON-RPC endpoints over stdio
- **Multi-language plugin system** - Tree-sitter-based parsers for 10 languages (Python, JavaScript, TypeScript, Go, Rust, Java, C, C++, Ruby)
- **Three-tier indexing** - File discovery → skeleton extraction → graph construction
- **Persistent SQLite graph** - `.codetree/graph.db` for cross-session analysis without re-parsing
- **Cache optimization** - `.codetree/index.json` with mtime-based invalidation to skip unchanged files
## Layers
- Purpose: Parse command-line arguments and invoke the server
- Location: `src/codetree/__main__.py`
- Contains: argparse setup, root directory resolution
- Triggers: Called by `codetree --root /path/to/repo` command
- Responsibilities: Accept `--root` argument, invoke `server.run()`
- Purpose: Expose 23 MCP tools over FastMCP protocol
- Location: `src/codetree/server.py`
- Contains: Tool definitions, result formatting, caching/indexing/graph initialization
- Depends on: Indexer, Cache, GraphStore, GraphQueries
- Used by: Claude Code via stdio MCP transport
- Key function: `create_server(root: str) → FastMCP`, `run(root: str)` entry point
- Purpose: Discover all supported files, extract symbol skeletons, build definition/call graphs
- Location: `src/codetree/indexer.py`
- Contains: `Indexer` class with methods for skeleton, symbol source, references, call graphs, dead code, blast radius, clones, search
- Depends on: Language plugins, registry
- Used by: Server, GraphBuilder
- Key dataclass: `FileEntry` (path, source, skeleton, mtime, language, plugin, has_errors)
- Purpose: Store pre-computed skeletons with modification time checks to skip unchanged files
- Location: `src/codetree/cache.py`
- Contains: `Cache` class (load, save, get, set, is_valid methods)
- Stores: `.codetree/index.json` (JSON dict of `rel_path → {mtime, skeleton}`)
- Used by: Server on startup to inject cached entries into indexer
- Purpose: Abstract language-specific AST parsing behind common interface
- Location: `src/codetree/languages/`
- Contains: 10 plugin classes inheriting from `LanguagePlugin` base
- Each plugin implements:
- Plugins: `PythonPlugin`, `JavaScriptPlugin`, `TypeScriptPlugin`, `TSXPlugin`, `GoPlugin`, `RustPlugin`, `JavaPlugin`, `CPlugin`, `CppPlugin`, `RubyPlugin`
- Purpose: Route files to correct language plugin
- Location: `src/codetree/registry.py`
- Contains: `PLUGINS` dict (extension → singleton plugin instance), `get_plugin(path) → LanguagePlugin | None`
- Used by: Indexer during file discovery
- Purpose: Build and query a persistent SQLite symbol graph for cross-session analysis
- Location: `src/codetree/graph/`
- Components:
## Data Flow
## State Management
- `_index: dict[rel_path → FileEntry]` - all indexed files (held in memory)
- `_definitions: dict[name → list[(file, line)]]` - definition locations for all symbols
- `_call_graph, _reverse_graph` - lazy-built, invalidated when files change
- `_call_graph_built: bool` - flag to defer call graph construction until first use
- Persistent SQLite database: `.codetree/graph.db`
- Tables: `meta`, `files`, `symbols`, `edges`, `file_symbols_index`
- Indices on: `symbols.name`, `symbols.file`, `symbols.kind`, `edges.source_qn`, `edges.target_qn`, `edges.type`
- Schema version tracked in `meta` table
- JSON file: `.codetree/index.json`
- Structure: `{rel_path → {mtime: float, skeleton: list[dict]}}`
- Invalidation: re-parse file if `stat().st_mtime` differs from cached mtime
## Key Abstractions
- Purpose: Define language-agnostic interface for code analysis
- Methods: 5 abstract (skeleton, symbol_source, calls, usages, imports) + 5 optional (syntax, complexity, variables, ast, normalize_for_clones)
- Example: `PythonPlugin` queries `function_definition` and `class_definition` tree-sitter nodes
- Pattern: Tree-sitter 0.25.x API with `Query()`, `QueryCursor()`, `_matches()` unwrapper
- Purpose: Hold all parsed information for a single file
- Fields: path, source (bytes), skeleton, mtime, language, plugin, has_errors
- Lifetime: Created during indexing, reused for all lookups without re-parsing
- Purpose: Define persistent graph schema
- SymbolNode: qualified_name, name, kind, file_path, start_line, end_line, parent_qn, doc, params, is_test, is_entry_point
- Edge: source_qn, target_qn, type (CALLS, IMPORTS, CONTAINS), weight
- Qualified names: `file_path::ClassName.method_name` or `file_path::function_name`
- Purpose: Execute AST queries via S-expression patterns
- Pattern: Define queries as strings: `(function_definition name: (identifier) @name)`
- Matches returned as dicts with capture names unwrapped to nodes
- Helper: `_matches(query, node)` in `languages/base.py` for convenient capture unwrapping
## Entry Points
- Location: `src/codetree/__main__.py::main()`
- Triggers: `codetree --root /path/to/repo`
- Responsibilities: Parse args, invoke `server.run(root)`
- **Structural:** `get_file_skeleton`, `get_symbol`, `find_references`, `get_call_graph`, `get_imports`, `get_skeletons`, `get_symbols`, `get_complexity`, `find_dead_code`, `get_blast_radius`, `detect_clones`, `search_symbols`, `find_tests`
- **Graph & Onboarding:** `index_status`, `get_repository_map`, `resolve_symbol`, `search_graph`, `get_change_impact`, `analyze_dataflow`, `find_hot_paths`, `get_dependency_graph`, `git_history`, `suggest_docs`
- All registered as `@mcp.tool()` decorators in `server.py`
## Error Handling
- File not found: `"File not found or empty: {file_path}"`
- Symbol not found: `"Symbol '{name}' not found in {file_path}"`
- Syntax error: Skeleton includes warning header if `entry.has_errors == True`
- Empty results: `"No {X} found..."`
## Cross-Cutting Concerns
- File paths: Checked for existence in indexer during build
- Symbol names: Case-sensitive searches; substring matching optional in `search_symbols`
- Imports: Extracted as raw text; no semantic resolution (cross-module imports tracked by edge weights)
- Skeleton cache: mtime-based invalidation per file
- Call graph: Lazy-built once, invalidated on file change via `_call_graph_built` flag
- Graph store: Content-hashed (sha256) per file to detect changes
- Import resolution: Graph builder caches file imports in `_file_imports` dict
- Excludes dunder methods (`__init__`, `__str__`, etc.), test functions, `__init__.py` exports
- Counts external references only (same-file definitions at definition line don't count as usage)
<!-- GSD:architecture-end -->

<!-- GSD:workflow-start source:GSD defaults -->
## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:
- `/gsd:quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd:debug` for investigation and bug fixing
- `/gsd:execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->

<!-- GSD:profile-start -->
## Developer Profile

> Profile not yet configured. Run `/gsd:profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
