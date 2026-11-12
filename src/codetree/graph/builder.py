import hashlib
import time
from functools import lru_cache
from pathlib import Path
from .store import GraphStore
from .models import SymbolNode, Edge, make_qualified_name
from ..indexer import Indexer


@lru_cache(maxsize=65536)
def _stem(path: str) -> str:
    return Path(path).stem


class GraphBuilder:
    def __init__(self, root: str, store: GraphStore):
        self._root = Path(root)
        self._store = store
        self._file_imports: dict[str, set[str]] = {}  # file → set of imported module stems/symbols
        # name → symbols, loaded once after pass 1 (all files' symbols are then in
        # the store) instead of one SQL lookup per callee.
        self._symbols_by_name: dict[str, list[SymbolNode]] = {}

    @staticmethod
    def _hash_source(source: bytes) -> str:
        return hashlib.sha256(source).hexdigest()

    def _is_test_file(self, rel_path: str) -> bool:
        name = Path(rel_path).name
        parts = Path(rel_path).parts
        if any(d in ("test", "tests", "spec", "__tests__") for d in parts):
            return True
        return (name.startswith("test_") or
                "_test." in name or
                ".test." in name or
                ".spec." in name or
                (name[0].isupper() and "Test" in name))

    def build(self, indexer: Indexer | None = None) -> dict:
        """Build or incrementally update the graph.

        Args:
            indexer: optional pre-built Indexer to reuse (avoids double parsing)

        Returns stats: {files_indexed, files_skipped, symbols_created, edges_created}
        """
        if indexer is None:
            indexer = Indexer(str(self._root))
            indexer.build()

        self._store.begin()

        # Get current files on disk
        current_files = {}
        for rel_path, entry in indexer._index.items():
            abs_path = self._root / rel_path
            if abs_path.exists():
                current_files[rel_path] = {
                    # Indexer already holds the file bytes — no second read.
                    "hash": self._hash_source(entry.source),
                    "entry": entry,
                }

        # Lookup tables replacing per-import scans of every file (O(files²)).
        # first_file_by_key: stem or full path → first matching file, in order.
        # files_by_stem: stem → every file with that stem.
        first_file_by_key: dict[str, str] = {}
        files_by_stem: dict[str, list[str]] = {}
        for candidate in current_files:
            stem = _stem(candidate)
            first_file_by_key.setdefault(stem, candidate)
            first_file_by_key.setdefault(candidate, candidate)
            files_by_stem.setdefault(stem, []).append(candidate)

        # Determine which files changed
        files_indexed = 0
        files_skipped = 0
        symbols_created = 0
        edges_created = 0

        indexed_paths = set()
        changed_files = []  # Track files that need edge resolution

        # Writes are batched (see GraphStore._insert_many). Each pass is flushed
        # before the next one reads, so the store sees the same state as with
        # row-by-row writes.
        stored_files = {f["file_path"]: f for f in self._store.all_files()}
        file_rows: list[tuple[str, str, str, bool]] = []
        new_symbols: list[SymbolNode] = []
        new_edges: list[Edge] = []

        # ── Pass 1: Insert all symbols first ──────────────────────────────
        for rel_path, info in current_files.items():
            indexed_paths.add(rel_path)
            existing = stored_files.get(rel_path)
            if existing and existing["sha256"] == info["hash"]:
                files_skipped += 1
                continue

            # File is new or changed — reindex it
            files_indexed += 1
            entry = info["entry"]
            is_test = self._is_test_file(rel_path)

            # Clear old data for this file (a never-indexed file has none)
            if existing:
                self._store.delete_symbols_for_file(rel_path)
                self._store.delete_edges_for_file(rel_path)

            file_rows.append((rel_path, info["hash"], entry.language, is_test))

            # Build symbols from skeleton
            for item in entry.skeleton:
                qn = make_qualified_name(rel_path, item["name"], item.get("parent"))
                is_entry = item["name"] in ("main", "__main__") and not item.get("parent")
                sym = SymbolNode(
                    qualified_name=qn,
                    name=item["name"],
                    kind=item["type"],
                    file_path=rel_path,
                    start_line=item["line"],
                    end_line=None,
                    parent_qn=make_qualified_name(rel_path, item["parent"]) if item.get("parent") else None,
                    doc=item.get("doc", ""),
                    params=item.get("params", ""),
                    is_test=is_test or item["name"].startswith("test_") or item["name"].startswith("Test"),
                    is_entry_point=is_entry,
                )
                new_symbols.append(sym)
                symbols_created += 1

                # CONTAINS edges for methods
                if item.get("parent"):
                    parent_qn = make_qualified_name(rel_path, item["parent"])
                    new_edges.append(Edge(parent_qn, qn, "CONTAINS"))
                    edges_created += 1

            changed_files.append((rel_path, info))

        self._store.upsert_files(file_rows)
        self._store.upsert_symbols(new_symbols)
        self._store.upsert_edges(new_edges)
        new_edges = []
        self._symbols_by_name = self._store.symbols_by_name_map() if changed_files else {}

        # ── Pass 2: Build CALLS and IMPORTS edges (all symbols now in store) ──
        # First, parse imports for all changed files to enable type-aware resolution
        for rel_path, info in changed_files:
            entry = info["entry"]
            self._file_imports[rel_path] = self._parse_file_imports(entry, files_by_stem)

        for rel_path, info in changed_files:
            entry = info["entry"]

            # Build CALLS edges with type-aware resolution
            for item in entry.skeleton:
                if item["type"] not in ("function", "method"):
                    continue
                caller_qn = make_qualified_name(rel_path, item["name"], item.get("parent"))
                callees = entry.plugin.extract_calls_in_function(entry.source, item["name"])
                for callee_name in callees:
                    resolved = self._resolve_callee(rel_path, callee_name)
                    for target_qn, weight in resolved:
                        new_edges.append(Edge(caller_qn, target_qn, "CALLS", weight=weight))
                        edges_created += 1

            # Build IMPORTS edges
            imports = entry.plugin.extract_imports(entry.source)
            for imp in imports:
                text = imp["text"]
                parts = text.split()
                if len(parts) >= 2:
                    module = parts[1] if parts[0] in ("import", "from") else parts[0]
                    candidate = first_file_by_key.get(module)
                    if candidate is not None:
                        new_edges.append(
                            Edge(f"{rel_path}::__file__", f"{candidate}::__file__", "IMPORTS")
                        )
                        edges_created += 1

        # ── Pass 3: Build TESTS edges (link test functions to tested symbols) ──
        for rel_path, info in changed_files:
            entry = info["entry"]
            if not self._is_test_file(rel_path):
                continue
            for item in entry.skeleton:
                if item["type"] not in ("function", "method"):
                    continue
                name = item["name"]
                # Convention: test_foo tests foo, TestFoo tests Foo
                tested_name = None
                if name.startswith("test_"):
                    tested_name = name[5:]  # strip test_ prefix
                elif name.startswith("Test"):
                    tested_name = name[4:]  # strip Test prefix
                if not tested_name:
                    continue
                targets = self._symbols_by_name.get(tested_name, [])
                if targets:
                    test_qn = make_qualified_name(rel_path, name, item.get("parent"))
                    for t in targets:
                        if not t.is_test:
                            new_edges.append(Edge(test_qn, t.qualified_name, "TESTS"))
                            edges_created += 1

        # Flush edges before deleting removed files: their edges must go too.
        self._store.upsert_edges(new_edges)

        # Delete files that no longer exist
        for stored_file in stored_files.values():
            if stored_file["file_path"] not in indexed_paths:
                fp = stored_file["file_path"]
                self._store.delete_symbols_for_file(fp)
                self._store.delete_edges_for_file(fp)
                self._store.delete_file(fp)

        self._store.set_meta("last_indexed_at", str(time.time()))
        self._store.commit()

        return {
            "files_indexed": files_indexed,
            "files_skipped": files_skipped,
            "symbols_created": symbols_created,
            "edges_created": edges_created,
        }

    def _parse_file_imports(self, entry, files_by_stem: dict[str, list[str]]) -> set[str]:
        """Extract imported module stems and symbol names from a file's imports."""
        imported = set()
        imports = entry.plugin.extract_imports(entry.source)
        for imp in imports:
            text = imp["text"]
            parts = text.split()
            # Python: "import foo", "from foo import bar, baz"
            # JS/TS: "import { bar } from 'foo'"
            # Go: "import \"foo\""
            # C/C++: "#include <foo.h>", "#include \"foo.h\""
            # Ruby: "require 'foo'"
            for part in parts:
                # Strip punctuation: quotes, braces, angle brackets, semicolons
                cleaned = part.strip("\"'<>;{}()")
                if cleaned and not cleaned.startswith(("#", "//")) and cleaned not in (
                    "import", "from", "require", "require_relative", "include", "using",
                    "as", "*", ",",
                ):
                    # Add the stem (e.g., "foo" from "foo.py" or "foo/bar")
                    stem = Path(cleaned).stem
                    imported.add(stem)
                    imported.add(cleaned)
                    # Also add individual path components
                    for component in Path(cleaned).parts:
                        imported.add(component)
        # Also record paths of files whose stem this file imports
        for stem in list(imported):
            imported.update(files_by_stem.get(stem, ()))
        return imported

    def _resolve_callee(self, caller_file: str, callee_name: str) -> list[tuple[str, float]]:
        """Resolve a callee name to qualified names with import-aware weighting.

        Returns list of (qualified_name, weight) tuples.
        Weight 1.0 = import-confirmed, 0.5 = name-only match.
        """
        targets = self._symbols_by_name.get(callee_name, [])
        if not targets:
            return [(f"?::{callee_name}", 0.5)]

        caller_imports = self._file_imports.get(caller_file, set())
        same_file = []
        import_confirmed = []
        name_only = []

        for t in targets:
            if t.file_path == caller_file:
                # Same file — always high confidence
                same_file.append((t.qualified_name, 1.0))
            elif t.file_path in caller_imports or _stem(t.file_path) in caller_imports:
                import_confirmed.append((t.qualified_name, 1.0))
            else:
                name_only.append((t.qualified_name, 0.5))

        # If we have import-confirmed or same-file matches, prefer those
        confirmed = same_file + import_confirmed
        if confirmed:
            return confirmed
        return name_only
