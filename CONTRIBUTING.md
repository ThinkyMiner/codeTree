# Contributing to codetree

Thanks for your interest in contributing!

## Quick setup

```bash
git clone https://github.com/ThinkyMiner/codeTree.git
cd codeTree
python -m venv .venv
source .venv/bin/activate
pip install -e .
pip install pytest
pytest  # ~1200 tests, ~20s
```

## What to work on

- **New language support** — the most impactful contribution. See below.
- **Bug fixes** — check [open issues](https://github.com/ThinkyMiner/codeTree/issues) labeled `bug`
- **Tool improvements** — better output formats, edge cases, performance
- **Documentation** — README, docstrings, examples

## Adding a new language

1. `pip install tree-sitter-LANG` and add to `pyproject.toml`
2. Copy `src/codetree/languages/_template.py` to `languages/yourlang.py`
3. Implement the 5 abstract methods + `check_syntax`
4. Register extensions in `src/codetree/registry.py`
5. Add tests in `tests/languages/test_yourlang.py` (use `test_python.py` as reference)
6. Run `pytest` to verify everything passes

## Running tests

```bash
# All tests
pytest

# Single file
pytest tests/languages/test_python.py -v

# Single test
pytest tests/languages/test_python.py::test_skeleton_finds_class -v
```

## Code style

No linter or formatter is configured. Follow existing patterns:

- Plugin classes: `{Lang}Plugin` (e.g., `PythonPlugin`, `GoPlugin`)
- Module-level parser/language globals: `_PARSER`, `_LANGUAGE`
- Skeleton results deduplicated by `(name, line)`, sorted by line number

## Pull request process

1. Open an issue first for larger changes
2. Create a branch from `main`
3. Write tests for any new behavior
4. Ensure all tests pass (`pytest`)
5. Submit a PR using the template
