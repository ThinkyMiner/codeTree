# codetree Tools Guide

> Complete reference for all 23 MCP tools with real-world examples.
> **Keep this doc updated whenever tools are added, changed, or removed.**

---

## Group 1: Understand Structure (5 tools)

*"What's in this file? Show me this function."*

### 1. `get_file_skeleton(file_path, format?)`

Shows all classes, functions, methods, and their doc comments WITHOUT showing the bodies.

```
Agent: get_file_skeleton("src/codetree/indexer.py")

Returns:
class Indexer → line 15
  "Discovers and indexes source files."
  def __init__(self, root: str) (in Indexer) → line 16
  def build(self, cached_mtimes: dict) (in Indexer) → line 25
    "Build the index, skipping unchanged files."
  def get_skeleton(self, file_path: str) (in Indexer) → line 45
  def get_symbol(self, file_path: str, name: str) (in Indexer) → line 52
```

**Why it matters:** An agent sees the entire structure of a 500-line file in ~15 lines. It knows what exists, where it is, and what it does — without reading a single function body. This is the 25x token savings.

**Compact mode:** Pass `format="compact"` for even fewer tokens:
```
cls Indexer:15 # Discovers and indexes source files.
.__init__(self,root:str):16
.build(self,cached_mtimes:dict):25 # Build the index, skipping unchanged files.
.get_skeleton(self,file_path:str):45
```

---

### 2. `get_symbol(file_path, symbol_name)`

Once the agent knows WHAT exists from the skeleton, it can grab just the function it needs.

```
Agent: get_symbol("src/codetree/indexer.py", "build")

Returns:
# src/codetree/indexer.py:25
def build(self, cached_mtimes=None):
    """Build the index, skipping unchanged files."""
    for py_file in sorted(self._root.rglob("*")):
        rel_path = str(py_file.relative_to(self._root))
        if self._should_skip(py_file):
            continue
        ...
```

**Why it matters:** Instead of reading the entire file (say 400 lines), the agent reads only the 20 lines of this one function.

---

### 3. `get_skeletons(file_paths, format?)`

Batch version — scan multiple files in one call.

```
Agent: get_skeletons(["src/codetree/server.py", "src/codetree/cache.py"])

Returns:
=== src/codetree/server.py ===
def create_server(root: str) → line 7
  def get_file_skeleton(file_path: str, format: str) → line 115
  def get_symbol(file_path: str, symbol_name: str) → line 131
  ...

=== src/codetree/cache.py ===
class Cache → line 8
  def __init__(self, root: str) (in Cache) → line 9
  def load(self) (in Cache) → line 15
  def save(self) (in Cache) → line 25
```

**Why it matters:** When an agent is exploring a new codebase, it can scan all core files in one shot to build a mental map.

---

### 4. `get_symbols(symbols)`

Batch source retrieval — grab multiple functions at once.

```
Agent: get_symbols([
    {"file_path": "src/codetree/cache.py", "symbol_name": "load"},
    {"file_path": "src/codetree/cache.py", "symbol_name": "save"}
])

Returns both function bodies in one response.
```

---

### 5. `get_imports(file_path)`

Shows what a file depends on.

```
Agent: get_imports("src/codetree/server.py")

Returns:
Imports in src/codetree/server.py:
  1: from fastmcp import FastMCP
  2: from pathlib import Path
  3: from .indexer import Indexer
  4: from .cache import Cache
```

**Why it matters:** Agent instantly knows the dependency chain without reading the file.

---

## Group 2: Navigate Relationships (3 tools)

*"Who uses this? What does this call? What breaks if I change it?"*

### 6. `find_references(symbol_name)`

Find every usage of a symbol across the entire repo.

```
Agent: find_references("Indexer")

Returns:
References to 'Indexer':
  src/codetree/server.py:19
  src/codetree/server.py:20
  tests/test_indexer.py:12
  tests/test_indexer.py:25
```

**Why it matters:** Before renaming a function or changing its API, the agent knows exactly what will break.

---

### 7. `get_call_graph(file_path, function_name)`

Shows what a function calls and what calls it.

```
Agent: get_call_graph("src/codetree/indexer.py", "build")

Returns:
Call graph for 'build':

  build calls:
    → _should_skip
    → _register_file
    → get_skeleton

  build is called by:
    ← src/codetree/server.py:20
```

**Why it matters:** Agent understands the flow — "build" orchestrates `_should_skip`, `_register_file`, `get_skeleton`, and is called from the server setup.

---

### 8. `get_blast_radius(file_path, symbol_name)`

If I change this function, what breaks?

```
Agent: get_blast_radius("src/codetree/indexer.py", "get_skeleton")

Returns:
Blast radius for get_skeleton() in src/codetree/indexer.py:

Direct callers:
  src/codetree/server.py: get_file_skeleton() → line 122
  src/codetree/server.py: get_skeletons() → line 222

Indirect callers (depth 2):
  (any functions that call get_file_skeleton or get_skeletons)

Dependencies (what it calls):
  src/codetree/indexer.py: _index() → line 30

Impact summary: 4 functions in 2 files may be affected
```

**Why it matters:** Before making a change, the agent knows the full ripple effect. Critical for safe refactoring.

---

## Group 3: Analyze Quality (3 tools)

*"Is this function too complex? Is there dead code? Are there duplicates?"*

### 9. `get_complexity(file_path, function_name)`

Cyclomatic complexity — how many paths through the code?

```
Agent: get_complexity("src/codetree/indexer.py", "build")

Returns:
Complexity of build() in src/codetree/indexer.py: 8
  if: 3, for: 2, and: 1, try: 1
```

**Why it matters:** Complexity > 10 is a red flag. Agent can identify functions that need refactoring.

---

### 10. `find_dead_code(file_path?)`

Find functions that exist but nobody calls.

```
Agent: find_dead_code("src/codetree/indexer.py")

Returns:
Dead code in src/codetree/indexer.py:
  function _old_helper() → line 150
  function _debug_dump() → line 200

Summary: 2 dead symbols across 1 file
```

**Why it matters:** Agent can confidently suggest deleting unused code.

---

### 11. `detect_clones(file_path?, min_lines?)`

Find copy-pasted functions (even with renamed variables).

```
Agent: detect_clones()

Returns:
Clone group 1 (2 functions, 15 lines each):
  src/utils.py: validate_email() → line 20
  src/helpers.py: check_email() → line 45

Summary: 1 clone group, 2 functions
```

**Why it matters:** Agent spots duplication and can suggest extracting a shared function.

---

## Group 4: Inspect & Search (2 tools)

*"Find me all classes without docs. What tests cover this?"*

### 12. `search_symbols(query?, type?, parent?, has_doc?, min_complexity?, language?, format?)`

Flexible search across the whole repo.

```
Agent: search_symbols(type="method", parent="Indexer", has_doc=False)

Returns:
Search results:
  src/codetree/indexer.py: method _should_skip (in Indexer) → line 30
  src/codetree/indexer.py: method _register_file (in Indexer) → line 40

Found 2 symbols
```

**Why it matters:** "Show me all methods in Indexer that have no docstring" — powerful for documentation audits or understanding a class.

---

### 13. `find_tests(file_path, symbol_name)`

What tests cover this function?

```
Agent: find_tests("src/codetree/cache.py", "load")

Returns:
Tests for load() in src/codetree/cache.py:
  tests/test_cache.py: test_load_empty() → line 15  (name match)
  tests/test_cache.py: test_load_existing() → line 25  (name match)
  tests/test_cache.py: test_cache_roundtrip() → line 40  (direct reference)

Found 3 tests
```

**Why it matters:** Before changing a function, the agent knows what tests to run and whether coverage exists.

---

## Group 5: Onboarding & Graph (4 tools)

*"I just landed in this repo. Where do I start?"*

### 14. `index_status()`

Is the graph up to date — and is the server still indexing?

```
Agent: index_status()

Returns:
{
  "graph_exists": true,
  "files": 42,
  "symbols": 315,
  "edges": 580,
  "last_indexed_at": "1741622400.0",
  "status": "ready",
  "files_discovered": 42,
  "files_indexed": 42,
  "index_ready": true,
  "graph_ready": true,
  "startup_seconds": 0.8
}
```

The server indexes in the background, so this tool never blocks. While it is
still working, `status` is `starting`, `discovering`, `indexing` (with
`files_indexed` / `files_discovered` progress) or `building_graph`; it ends as
`ready`, or `error` with an `error` message if indexing or the graph build
failed. While a graph rebuild runs, `files` / `symbols` / `edges` /
`last_indexed_at` describe the last committed graph. Single-file tools
(`get_file_skeleton`, `get_symbol`, `get_imports`, `get_skeletons`,
`get_symbols`, `get_complexity`, `analyze_dataflow` flow/taint) answer
immediately; repo-wide and graph tools wait up to 20 s (`CODETREE_WAIT_TIMEOUT`
to change it), then return a "still building" message — retry, or poll
`index_status`.

---

### 15. `get_repository_map(max_items?)`

The "onboarding" tool — one call gives the agent a complete overview.

```
Agent: get_repository_map()

Returns:
{
  "languages": {"py": 30, "js": 8, "ts": 4},
  "major_paths": ["src/codetree/", "tests/", "src/codetree/languages/"],
  "entry_points": ["src/codetree/server.py::create_server"],
  "hotspots": [
    {"name": "Indexer", "kind": "class", "file": "src/codetree/indexer.py", "degree": 25},
    {"name": "LanguagePlugin", "kind": "class", "file": "src/codetree/languages/base.py", "degree": 18}
  ],
  "start_here": ["src/codetree/server.py::create_server", "src/codetree/indexer.py::Indexer"],
  "test_roots": ["tests/"],
  "stats": {"files": 42, "symbols": 315, "edges": 580}
}
```

**Why it matters:** An agent drops into a repo it has never seen, calls this once, and instantly knows: what languages, where the code lives, what's important, where to start reading.

---

### 16. `resolve_symbol(query, kind?, path_hint?, limit?)`

"I see `add` mentioned. Which `add`?"

```
Agent: resolve_symbol("add")

Returns:
{
  "query": "add",
  "matches": [
    {"qualified_name": "src/calc.py::Calculator.add", "kind": "method", "file": "src/calc.py", "line": 11},
    {"qualified_name": "src/math_utils.py::add", "kind": "function", "file": "src/math_utils.py", "line": 5},
    {"qualified_name": "tests/test_calc.py::TestCalc.test_add", "kind": "method", "is_test": true}
  ]
}
```

**Why it matters:** In a large codebase, `add` might exist in 10 places. This ranks them by relevance (non-test, most connected, path match).

---

### 17. `search_graph(query?, kind?, file_pattern?, relationship?, direction?, min_degree?, max_degree?, limit?, offset?)`

Graph-powered search with connectivity filters.

```
Agent: search_graph(kind="class", min_degree=10)

Returns:
{
  "total": 3,
  "results": [
    {"qualified_name": "src/codetree/indexer.py::Indexer", "kind": "class", "in_degree": 15, "out_degree": 12},
    {"qualified_name": "src/codetree/languages/base.py::LanguagePlugin", "kind": "class", "in_degree": 18, "out_degree": 2}
  ]
}
```

**Why it matters:** "Show me all highly-connected classes" finds the architectural backbone. `max_degree=0` finds isolated/dead code.

---

## Group 6: Change, Dataflow & Git (6 tools)

*"What breaks if I change this? Is this function secure? What changed recently?"*

### 18. `get_change_impact(symbol_query?, diff_scope?, depth?)`

Risk analysis before making changes.

```
# By symbol name:
Agent: get_change_impact(symbol_query="get_skeleton")

# Or by git diff:
Agent: get_change_impact(diff_scope="working")   # uncommitted changes
Agent: get_change_impact(diff_scope="staged")     # staged changes
Agent: get_change_impact(diff_scope="HEAD~1")     # last commit

Returns:
{
  "changed_symbols": [{"qualified_name": "indexer.py::Indexer.get_skeleton", "name": "get_skeleton"}],
  "impact": {
    "CRITICAL": [{"name": "get_file_skeleton", "file": "server.py", "hop": 1}],
    "HIGH": [{"name": "get_skeletons", "file": "server.py", "hop": 2}]
  },
  "affected_tests": [{"name": "test_skeleton_finds_class", "file": "test_server.py"}]
}
```

**Why it matters:** Before committing, the agent sees: "This change is CRITICAL risk — it directly affects `get_file_skeleton`. Run these 3 tests." Git-aware mode analyzes impact of uncommitted work.

---

### 19. `analyze_dataflow(file_path, function_name, mode?, depth?)`

Unified dataflow and security analysis. Three modes in one tool:

**mode="flow"** (default) — How does data flow through a function?

```
Agent: analyze_dataflow("app.py", "handle_request")

Returns:
{
  "variables": [
    {"name": "user_input", "line": 5, "depends_on": [], "source_expr": "request.args.get('q')"},
    {"name": "query", "line": 6, "depends_on": ["user_input"], "source_expr": "build_query(user_input)"},
    {"name": "result", "line": 7, "depends_on": ["query"], "source_expr": "db.execute(query)"}
  ],
  "flow_chains": [["user_input", "query", "result"]],
  "sources": [{"expr": "request.args.get('q')", "line": 5, "kind": "external_input"}],
  "sinks": [{"expr": "db.execute(query)", "line": 7, "kind": "database"}]
}
```

**mode="taint"** — Is untrusted data reaching dangerous operations?

```
Agent: analyze_dataflow("app.py", "handle_request", mode="taint")

Returns:
{
  "paths": [
    {
      "verdict": "UNSAFE",
      "chain": ["user_input", "query", "db.execute(query)"],
      "sanitizer": null,
      "risk": "SQL injection"
    }
  ]
}
```

**mode="cross_taint"** — Cross-function taint tracing through call boundaries:

```
Agent: analyze_dataflow("app.py", "handle_request", mode="cross_taint", depth=3)

Returns taint paths that follow data across function calls, up to the specified depth.
```

**Why it matters:** One tool covers all dataflow needs. `flow` mode traces variable dependencies. `taint` mode flags unsanitized paths from untrusted sources to dangerous sinks. `cross_taint` mode follows taint across function boundaries. Knows about common sanitizers (html.escape, parameterize, int/float casting) and gives SAFE/UNSAFE verdicts.

---

### 20. `find_hot_paths(top_n?)`

High-complexity functions that are also heavily called — the best optimization targets.

```
Agent: find_hot_paths(top_n=5)

Returns:
src/codetree/indexer.py:25 — build (complexity=8, callers=5, score=40)
src/codetree/languages/python.py:30 — extract_skeleton (complexity=12, callers=3, score=36)
```

**Why it matters:** Agent identifies where optimization effort will have the greatest payoff — functions that are both complex and frequently called.

---

### 21. `get_dependency_graph(file_path?, format?)`

File-level dependency graph showing which files import which.

```
Agent: get_dependency_graph(format="mermaid")

Returns:
graph LR
  main.py --> calc.py
  main.py --> utils.py
  calc.py --> math_helpers.py
```

**Why it matters:** Agent sees the architectural structure — which modules depend on which, where circular dependencies exist.

---

### 22. `git_history(mode, file_path?, top_n?, since?, min_commits?)`

Unified git history analysis. Three modes in one tool:

**mode="blame"** — Per-line git blame with author summary:

```
Agent: git_history(mode="blame", file_path="src/codetree/server.py")

Returns:
line 1: author (commit, date) code
line 2: author (commit, date) code
...
```

**mode="churn"** — Most-changed files by commit count:

```
Agent: git_history(mode="churn", top_n=5)

Returns:
file (N commits, +A/-D lines)
```

**mode="coupling"** — Files that change together (temporal coupling):

```
Agent: git_history(mode="coupling", file_path="src/codetree/server.py", min_commits=3)

Returns:
a.py <-> b.py (N co-commits, ratio=0.8)
```

**Why it matters:** One tool for all git history questions. `blame` shows who wrote what. `churn` identifies hotspots that change frequently. `coupling` reveals hidden dependencies — files that always change together likely have a relationship worth understanding.

---

### 23. `suggest_docs(file_path?, symbol_name?)`

Find undocumented functions with enough context to generate documentation.

```
Agent: suggest_docs("src/codetree/indexer.py")

Returns:
src/codetree/indexer.py:30 — _should_skip(path), calls: [is_hidden, match], callers: [build]
src/codetree/indexer.py:40 — _register_file(path), calls: [get_plugin], callers: [build]
```

**Why it matters:** Agent finds functions that need docs and gets the context (what they call, who calls them) to write accurate docstrings without reading the full source.

---

## Quick Reference

| # | Tool | One-liner |
|---|------|-----------|
| 1 | `get_file_skeleton` | See all classes/functions without reading bodies |
| 2 | `get_symbol` | Read one specific function's full source |
| 3 | `get_skeletons` | Scan multiple files at once |
| 4 | `get_symbols` | Read multiple functions at once |
| 5 | `get_imports` | What does this file depend on? |
| 6 | `find_references` | Who uses this symbol? |
| 7 | `get_call_graph` | What does this call / what calls it? |
| 8 | `get_blast_radius` | What breaks if I change this? |
| 9 | `get_complexity` | How complex is this function? |
| 10 | `find_dead_code` | What code is never used? |
| 11 | `detect_clones` | What code is duplicated? |
| 12 | `search_symbols` | Find symbols by name/type/parent/doc/complexity |
| 13 | `find_tests` | What tests cover this function? |
| 14 | `index_status` | Is the graph up to date? |
| 15 | `get_repository_map` | One-call repo overview for onboarding |
| 16 | `resolve_symbol` | Which "add" do you mean? |
| 17 | `search_graph` | Graph search with connectivity filters |
| 18 | `get_change_impact` | Risk analysis before changes |
| 19 | `analyze_dataflow` | Variable flow, taint analysis, cross-function taint |
| 20 | `find_hot_paths` | High-complexity, high-call-count optimization targets |
| 21 | `get_dependency_graph` | File-level dependency graph as Mermaid or list |
| 22 | `git_history` | Git blame, churn, and change coupling |
| 23 | `suggest_docs` | Find undocumented functions with context |
