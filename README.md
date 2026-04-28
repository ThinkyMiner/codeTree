[![MseeP.ai Security Assessment Badge](https://mseep.net/pr/thinkyminer-codetree-badge.png)](https://mseep.ai/app/thinkyminer-codetree)

# codetree

[![Tests](https://github.com/ThinkyMiner/codeTree/actions/workflows/test.yml/badge.svg)](https://github.com/ThinkyMiner/codeTree/actions/workflows/test.yml)
[![PyPI](https://img.shields.io/pypi/v/mcp-server-codetree)](https://pypi.org/project/mcp-server-codetree/)
[![Python](https://img.shields.io/pypi/pyversions/mcp-server-codetree)](https://pypi.org/project/mcp-server-codetree/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**Stop feeding entire files to your AI agent.**

codetree is an [MCP](https://modelcontextprotocol.io/) server that gives coding agents structured code understanding via [tree-sitter](https://tree-sitter.github.io/) — so they ask precise questions instead of reading thousands of lines. 23 tools, 10 languages, ~1 second startup. No vector DB, no embedding model, no config.

## Quick Start

**Prerequisite:** Install [uv](https://docs.astral.sh/uv/getting-started/installation/) if you don't have it (`curl -LsSf https://astral.sh/uv/install.sh | sh`).

Then `cd` into any project and run:

```bash
claude mcp add codetree -- uvx --from mcp-server-codetree codetree --root .
```

That's it. The `.` means "this project." Your agent now has structured code understanding.

> Not using Claude Code? See [Editor Setup](#editor-setup) for Cursor, VS Code, Windsurf, and Claude Desktop.

## Before / After

### Before codetree — agent reads the raw file:

```python
$ cat calculator.py
import math
from typing import Optional

class Calculator:
    """A scientific calculator with memory."""

    def __init__(self):
        self.memory = 0
        self.history = []

    def add(self, a: float, b: float) -> float:
        """Add two numbers."""
        result = a + b
        self.history.append(('add', a, b, result))
        return result

    def divide(self, a: float, b: float) -> Optional[float]:
        """Divide a by b, returns None on zero division."""
        if b == 0:
            return None
        result = a / b
        self.history.append(('divide', a, b, result))
        return result

    # ... 200 more lines of methods ...
```

**Tokens consumed: ~2,000+ for the full file**

### After codetree — agent asks for the skeleton:

```
class Calculator → line 4
  "A scientific calculator with memory."
  def __init__(self) (in Calculator) → line 7
  def add(self, a: float, b: float) (in Calculator) → line 11
    "Add two numbers."
  def divide(self, a: float, b: float) (in Calculator) → line 17
    "Divide a by b, returns None on zero division."
  def sqrt(self, x: float) (in Calculator) → line 24
    "Square root using math.sqrt."
```

**Tokens consumed: ~80. That's a 25x reduction.**

The agent sees every class, method, and docstring — with line numbers — without reading a single function body. When it needs the full source of `divide`, it calls `get_symbol("calculator.py", "divide")` and gets just those 6 lines.

## 23 Tools

### Understand Structure

| Tool | Purpose |
|------|---------|
| `get_file_skeleton(file_path)` | Classes, functions, methods with line numbers + doc comments |
| `get_symbol(file_path, symbol_name)` | Full source of a function or class |
| `get_skeletons(file_paths)` | Batch skeletons for multiple files |
| `get_symbols(symbols)` | Batch source for multiple symbols |
| `get_imports(file_path)` | Import statements with line numbers |

### Navigate Relationships

| Tool | Purpose |
|------|---------|
| `find_references(symbol_name)` | All usages of a symbol across the repo |
| `get_call_graph(file_path, function_name)` | What a function calls + what calls it |
| `get_blast_radius(file_path, symbol_name)` | Transitive impact — what breaks if you change this |

### Analyze Quality

| Tool | Purpose |
|------|---------|
| `get_complexity(file_path, function_name)` | Cyclomatic complexity breakdown |
| `find_dead_code(file_path?)` | Symbols defined but never referenced |
| `detect_clones(file_path?, min_lines?)` | Duplicate / near-duplicate functions |

### Inspect & Search

| Tool | Purpose |
|------|---------|
| `search_symbols(query?, type?, parent?)` | Flexible symbol search with filters |
| `find_tests(file_path, symbol_name)` | Find test functions for a symbol |

### Onboarding & Graph

| Tool | Purpose |
|------|---------|
| `index_status()` | Graph index freshness and stats |
| `get_repository_map(max_items?)` | Compact repo overview: languages, entry points, hotspots |
| `resolve_symbol(query, kind?, path_hint?)` | Disambiguate short name into ranked qualified matches |
| `search_graph(query?, kind?, file_pattern?)` | Graph search with degree filters and pagination |

### Change & Dataflow

| Tool | Purpose |
|------|---------|
| `get_change_impact(symbol_query?, diff_scope?)` | Impact analysis via symbol or git diff, with risk levels |
| `analyze_dataflow(file_path, function_name, mode?)` | Variable dataflow, taint analysis, or cross-function taint tracing |

### Visualization & History

| Tool | Purpose |
|------|---------|
| `find_hot_paths(top_n?)` | High-complexity × high-call-count optimization targets |
| `get_dependency_graph(file_path?, format?)` | File-level dependency graph as Mermaid or list |
| `git_history(mode?, file_path?, top_n?)` | Git blame, file churn, or change coupling analysis |
| `suggest_docs(file_path?, symbol_name?)` | Find undocumented functions with context for doc generation |

> `get_file_skeleton`, `get_skeletons`, and `search_symbols` accept `format="compact"` for even fewer tokens.

## Supported Languages

| Language | Extensions |
|----------|------------|
| Python | `.py` |
| JavaScript | `.js`, `.jsx` |
| TypeScript | `.ts` |
| TSX | `.tsx` |
| Go | `.go` |
| Rust | `.rs` |
| Java | `.java` |
| C | `.c`, `.h` |
| C++ | `.cpp`, `.cc`, `.cxx`, `.hpp`, `.hh` |
| Ruby | `.rb` |

## Editor Setup

The `--root` flag tells codetree which project to analyze. Use `.` for the current directory, or a full path.

### Claude Code

`cd` into your project, then:

```bash
claude mcp add codetree -- uvx --from mcp-server-codetree codetree --root .
```

### Cursor

Add to `.cursor/mcp.json` in your project:

```json
{
  "mcpServers": {
    "codetree": {
      "command": "uvx",
      "args": ["--from", "mcp-server-codetree", "codetree", "--root", "${workspaceFolder}"]
    }
  }
}
```

### VS Code (Copilot)

Add to `.vscode/mcp.json` in your project:

```json
{
  "servers": {
    "codetree": {
      "command": "uvx",
      "args": ["--from", "mcp-server-codetree", "codetree", "--root", "${workspaceFolder}"]
    }
  }
}
```

### Windsurf

Add to `~/.codeium/windsurf/mcp_config.json`:

```json
{
  "mcpServers": {
    "codetree": {
      "command": "uvx",
      "args": ["--from", "mcp-server-codetree", "codetree", "--root", "${workspaceFolder}"]
    }
  }
}
```

### Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "codetree": {
      "command": "uvx",
      "args": ["--from", "mcp-server-codetree", "codetree", "--root", "/path/to/your/project"]
    }
  }
}
```

> Claude Desktop doesn't support `${workspaceFolder}`, so use a full path here.

## Why codetree?

| Alternative | Limitation | codetree |
|-------------|-----------|----------|
| **Reading files directly** | Burns tokens, no structure, no relationships | 25x token reduction, structured output |
| **grep / ripgrep** | Text only, no AST awareness, no call graphs | Understands code structure, not just text |
| **LSP servers** | Heavyweight, stateful, language-specific setup | One command, 10 languages, stateless MCP |
| **SCIP / LSIF indexers** | Slow builds, complex setup, huge indexes | ~1s startup, JSON cache, zero config |
| **AST-only tools** | Raw trees are verbose and hard for agents | Pre-structured output designed for agents |

## Architecture

```
Agent (Claude, Copilot, Cursor, etc.)
    │ MCP (stdio)
    ▼
codetree server (FastMCP)
    │
    ├── Indexer → LanguagePlugin → tree-sitter → structured results
    │   Cache (.codetree/index.json, mtime-based)
    │
    └── Graph Layer → SQLite (.codetree/graph.db)
        Persistent symbols + edges, incremental updates
        Change impact, dataflow, taint analysis
```

| Module | Responsibility |
|--------|---------------|
| `server.py` | FastMCP server — defines all 23 tools |
| `indexer.py` | File discovery, plugin dispatch, definition index |
| `cache.py` | Skeleton cache with mtime invalidation |
| `registry.py` | Maps file extensions to language plugins |
| `languages/` | One plugin per language (Python, JS, TS, Go, Rust, Java, C, C++, Ruby) |
| `graph/store.py` | SQLite persistence for symbols and edges |
| `graph/builder.py` | Incremental graph builder (sha256 change detection) |
| `graph/queries.py` | Repository map, symbol resolution, change impact, hot paths, dependency graph, doc suggestions |
| `graph/dataflow.py` | Intra- and cross-function dataflow and taint analysis |
| `graph/git_analysis.py` | Git blame, churn, change coupling analysis |

## Adding a Language

1. `pip install tree-sitter-LANG` and add to `pyproject.toml`
2. Copy `src/codetree/languages/_template.py` to `languages/yourlang.py`
3. Implement the abstract methods
4. Register extensions in `registry.py`
5. Add tests

## Development

```bash
git clone https://github.com/ThinkyMiner/codeTree.git
cd codeTree
python -m venv .venv
source .venv/bin/activate
pip install -e .
pip install pytest

# Run all tests (~1058 tests, ~35s)
pytest

# Run a single test file
pytest tests/languages/test_python.py -v
```

## Contributing

Contributions welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for setup instructions and guidelines.
