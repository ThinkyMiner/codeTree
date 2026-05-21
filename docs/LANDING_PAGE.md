# codetree — Landing Page Content Document

> Give this document to whoever is building the landing page. It contains all copy, data, and technical details needed.

---

## 1. Hero Section

**Headline:**
Stop feeding entire files to your AI agent.

**Subheadline:**
codetree is an MCP server that gives coding agents structured code understanding via tree-sitter — so they ask precise questions instead of reading thousands of lines.

**One-liner pitch:**
Instead of `cat main.py` (500 lines, 12K tokens), your agent calls `get_file_skeleton("main.py")` and gets 15 lines of structured output.

**CTA:**
```bash
cd your-project
claude mcp add codetree -- uvx --from mcp-server-codetree codetree --root .
```

---

## 2. The Problem

Coding agents today understand code the same way a human greps through a codebase — raw text with no structure:

| What agents do today | What's wrong |
|---|---|
| Read entire files to find one function | Wastes context window tokens |
| Grep for function names across files | Misses structural relationships |
| Guess what a function calls | No call graph visibility |
| Can't tell what breaks if they change something | No impact analysis |
| Read the same boilerplate across similar functions | No deduplication awareness |
| Don't know which symbols matter most | No importance ranking |

**The cost:**
- Agents burn 10-50x more tokens than necessary
- They miss cross-file relationships
- They make changes without understanding blast radius
- They can't find tests for what they're modifying

---

## 3. The Solution

codetree sits between the agent and the repo, parsing every file with tree-sitter and exposing 23 structured tools over MCP.

**How it works:**
```
Agent asks a question
    ↓
MCP tool call (e.g., get_file_skeleton)
    ↓
codetree → tree-sitter parses the file
    ↓
Structured answer back to the agent
```

**Startup:** ~1 second. No vector DB, no embedding model, no separate daemon. Just `uvx --from mcp-server-codetree codetree`.

---

## 4. Before / After Comparison

### Before codetree (agent reads raw file):
```
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

    def sqrt(self, x: float) -> float:
        """Square root using math.sqrt."""
        result = math.sqrt(x)
        self.history.append(('sqrt', x, None, result))
        return result

    # ... 200 more lines of methods ...
```
**Tokens consumed: ~2,000+ for the full file**

### After codetree (agent asks for skeleton):
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

---

## 5. The 23 Tools

### Understand Structure

| Tool | What it does | Example |
|------|-------------|---------|
| `get_file_skeleton` | Classes + method signatures with line numbers and doc comments | See the before/after above |
| `get_symbol` | Full source of one function or class | `get_symbol("calc.py", "divide")` → returns just the function body |
| `get_skeletons` | Batch skeletons for multiple files | Scan 10 files in one call |
| `get_symbols` | Batch source for multiple symbols | Grab 5 functions at once |
| `get_imports` | Import statements with line numbers | See what a file depends on |

### Navigate Relationships

| Tool | What it does | Example |
|------|-------------|---------|
| `find_references` | Every usage of a symbol across the whole repo | "Who calls `add()`?" → 12 files |
| `get_call_graph` | What a function calls + what calls it | `divide` calls `validate` and is called from `main.py:20` |
| `get_blast_radius` | Transitive impact — what breaks if you change this | Change `add()` → affects 3 functions across 3 files |

### Analyze Quality

| Tool | What it does | Example |
|------|-------------|---------|
| `get_complexity` | Cyclomatic complexity breakdown | `calculate()` has complexity 5: 2 ifs, 1 for, 1 boolean, 1 with |
| `find_dead_code` | Symbols defined but never referenced | `unused_helper()` at line 15 — safe to delete |
| `detect_clones` | Duplicate/near-duplicate functions | 3 functions are copies with renamed variables |

### Inspect & Test

| Tool | What it does | Example |
|------|-------------|---------|
| `search_symbols` | Flexible search with filters (name, type, parent, doc, complexity, language) | "All methods in Calculator with no docstring" |
| `find_tests` | Find test functions for any symbol | `test_add()` and `test_add_negative()` cover `add()` |

### Onboarding & Graph

| Tool | What it does | Example |
|------|-------------|---------|
| `index_status` | Graph index freshness and stats | See how many files, symbols, and edges are indexed |
| `get_repository_map` | Compact repo overview for agent onboarding | Languages, entry points, hotspots, suggested starting points |
| `resolve_symbol` | Disambiguate a short name into ranked qualified matches | "add" → `calc.py::Calculator.add`, `math.py::add` |
| `search_graph` | Flexible graph search with degree filters and pagination | All functions with >5 inbound calls |

### Change, Dataflow & Git

| Tool | What it does | Example |
|------|-------------|---------|
| `get_change_impact` | Impact analysis via symbol name or git diff | Change `add()` → CRITICAL: 3 direct callers, HIGH: 5 transitive |
| `analyze_dataflow` | Variable flow, taint analysis, cross-function taint (3 modes) | `request.args` → `query` → `cursor.execute(query)` = UNSAFE (SQL injection) |
| `find_hot_paths` | High-complexity, high-call-count optimization targets | `build()` (complexity=8, callers=5, score=40) |
| `get_dependency_graph` | File-level dependency graph as Mermaid or list | `main.py --> calc.py --> math_helpers.py` |
| `git_history` | Git blame, churn, and change coupling (3 modes) | `server.py` changed 45 times; always changes with `indexer.py` |
| `suggest_docs` | Find undocumented functions with context for doc generation | `_should_skip(path)`, calls: [is_hidden], callers: [build] |

### Compact Mode

Three tools (`get_file_skeleton`, `get_skeletons`, `search_symbols`) accept `format="compact"` for even fewer tokens:

```
cls Calculator:4 # A scientific calculator.
.add(self,a:float,b:float):11 # Add two numbers.
.divide(self,a:float,b:float):17 # Divide a by b.
.sqrt(self,x:float):24 # Square root.
```

---

## 6. Supported Languages

11 languages. 17 file extensions. All backed by official tree-sitter grammars. Plus a persistent graph layer for onboarding, change impact, and security analysis.

| Language | Extensions |
|----------|-----------|
| Python | `.py` |
| JavaScript | `.js` `.jsx` |
| TypeScript | `.ts` |
| TSX | `.tsx` |
| Go | `.go` |
| Rust | `.rs` |
| Java | `.java` |
| C | `.c` `.h` |
| C++ | `.cpp` `.cc` `.cxx` `.hpp` `.hh` |
| Ruby | `.rb` |
| Kotlin | `.kt` |

Adding a new language is mechanical: copy a template file, implement 5 methods, register in one file, done.

---

## 7. Works With Every MCP Client

codetree speaks MCP over stdio — it works with any editor or tool that supports the Model Context Protocol.

The `--root` flag tells codetree which project to analyze. Use `.` for "this project" or a full path. IDE configs can use `${workspaceFolder}` to auto-target the open project.

### Claude Code
`cd` into your project, then:
```bash
claude mcp add codetree -- uvx --from mcp-server-codetree codetree --root .
```

### Cursor
```json
// .cursor/mcp.json
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
```json
// .vscode/mcp.json
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
```json
// ~/.codeium/windsurf/mcp_config.json
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
```json
// ~/Library/Application Support/Claude/claude_desktop_config.json
{
  "mcpServers": {
    "codetree": {
      "command": "uvx",
      "args": ["--from", "mcp-server-codetree", "codetree", "--root", "/path/to/your/project"]
    }
  }
}
```
> Claude Desktop doesn't support `${workspaceFolder}`, so use a full path.

---

## 8. Architecture (for a diagram on the page)

```
┌─────────────────────────────────────────────────┐
│  Agent (Claude, Copilot, Cursor, etc.)          │
│                                                 │
│  "What classes are in server.py?"               │
│  "What does add() call?"                        │
│  "What breaks if I change Indexer?"             │
└──────────────────┬──────────────────────────────┘
                   │ MCP (stdio)
                   ▼
┌─────────────────────────────────────────────────┐
│  codetree server (FastMCP)                      │
│                                                 │
│  23 tools │ Cache (.codetree/index.json)        │
│           │ mtime-based invalidation            │
└──────────────────┬──────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────┐
│  Indexer                                        │
│                                                 │
│  File discovery → Plugin dispatch → tree-sitter │
│  Definition index │ Call graph (lazy)           │
│  PageRank │ Clone detection │ Test discovery    │
└──────────────────┬──────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────┐
│  Language Plugins (one per language)             │
│                                                 │
│  Python │ JS │ TS │ Go │ Rust │ Java │ C │ C++ │ Ruby │ Kotlin │
│                                                 │
│  Each implements:                               │
│    extract_skeleton()                           │
│    extract_symbol_source()                      │
│    extract_calls_in_function()                  │
│    extract_symbol_usages()                      │
│    extract_imports()                            │
│    + compute_complexity, check_syntax, etc.     │
└──────────────────┬──────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────┐
│  tree-sitter (official grammars)                │
│                                                 │
│  Incremental parsing │ Error recovery           │
│  Concrete syntax tree with byte-level positions │
└─────────────────────────────────────────────────┘
```

---

## 9. Key Numbers (for badges/stats on the page)

| Metric | Value |
|--------|-------|
| MCP tools | 23 |
| Supported languages | 11 |
| File extensions | 17 |
| Test count | 999 |
| Startup time | ~1 second |
| Install | `uvx --from mcp-server-codetree codetree` |
| Python support | 3.10, 3.11, 3.12, 3.13 |
| License | MIT |
| Dependencies | tree-sitter + fastmcp (no ML, no DB) |

---

## 10. Why Not Just Use [X]?

| Alternative | Limitation | codetree advantage |
|-------------|-----------|-------------------|
| **Reading files directly** | Burns tokens, no structure, no relationships | 25x token reduction, structured output |
| **grep / ripgrep** | Text only, no AST awareness, no call graphs | Understands code structure, not just text |
| **LSP servers** | Heavyweight, stateful, language-specific setup | One command, 10 languages, stateless MCP |
| **SCIP/LSIF indexers** | Slow index builds, complex setup, huge indexes | ~1s startup, JSON cache, zero config |
| **AST-only tools** | Raw trees are verbose and hard for agents to use | Pre-structured output designed for agent consumption |

---

## 11. How It's Built (technical credibility section)

- **tree-sitter** for parsing — the same parser used by Neovim, GitHub, and Zed. Handles syntax errors gracefully with error recovery.
- **FastMCP** for the MCP protocol — stdio transport, zero network config.
- **Plugin architecture** — each language is a self-contained class implementing 5 core methods. Adding a language is copying a template.
- **Smart caching** — `.codetree/index.json` with mtime-based invalidation. Unchanged files skip parsing entirely.
- **Lazy call graph** — only built when tools like `find_dead_code` or `get_blast_radius` are first called. Stored in memory, O(1) lookup.
- **PageRank** — standard algorithm (25 iterations, damping 0.85) for ranking symbol importance by reference count.
- **Clone detection** — AST normalization (identifiers → `_ID_`, strings → `_STR_`, numbers → `_NUM_`) + SHA-256 hashing. Catches exact copies and renamed-variable copies.

---

## 12. Getting Started (bottom of page CTA)

```bash
# cd into any project and run one command
cd your-project
claude mcp add codetree -- uvx --from mcp-server-codetree codetree --root .

# That's it. Your agent now has structured code understanding.
```

**GitHub:** https://github.com/ThinkyMiner/codeTree

---

## 13. Social Proof / Trust Signals

- 999 tests passing across all 10 languages
- CI on Python 3.10–3.13
- MIT licensed — use it anywhere
- Built on tree-sitter (trusted by GitHub, Neovim, Zed, Helix)
- Built on MCP (open protocol by Anthropic, adopted by Claude, Cursor, VS Code, Windsurf)
- Zero external services — runs entirely local, no data leaves your machine

---

## 14. Brand / Naming Notes

- **Product name:** codetree (lowercase, one word)
- **Package name:** `mcp-server-codetree` (PyPI) — https://pypi.org/project/mcp-server-codetree/
- **CLI command:** `codetree`
- **Install command:** `uvx --from mcp-server-codetree codetree --root .`
- **GitHub:** https://github.com/ThinkyMiner/codeTree
- **Tagline options:**
  - "Structured code understanding for AI agents"
  - "Stop feeding entire files to your AI"
  - "The MCP server that teaches agents to read code"
  - "tree-sitter powered code intelligence over MCP"
