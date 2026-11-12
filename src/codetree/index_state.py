"""Index lifecycle: build the indexer and graph, optionally in a background thread.

The MCP handshake must not wait for indexing — on a large repository a cold
build takes longer than an MCP client's startup timeout. IndexState lets the
server start immediately while tools wait (bounded) for the data they need:

- files_ready  — file discovery finished (single-file tools can parse on demand)
- index_ready  — every file indexed (repo-wide tools)
- graph_ready  — SQLite graph built (graph tools)

Every event is set even when a phase fails, so waiters never hang; they check
``indexer`` / ``error`` afterwards.
"""

import os
import threading
import time
from pathlib import Path

from .cache import Cache
from .graph.builder import GraphBuilder
from .graph.queries import GraphQueries
from .graph.store import GraphStore
from .indexer import Indexer



def _wait_timeout_from_env(default: float = 20.0) -> float:
    try:
        return float(os.environ.get("CODETREE_WAIT_TIMEOUT", default))
    except ValueError:
        return default


# How long a tool call waits for indexing before answering "still building".
# Override with CODETREE_WAIT_TIMEOUT (seconds) for clients with short tool timeouts.
WAIT_TIMEOUT = _wait_timeout_from_env()


class IndexState:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.indexer: Indexer | None = None
        self.graph_store = GraphStore(str(self.root))
        self.graph_store.open()
        self.graph_queries = GraphQueries(self.graph_store)
        # Stats of the last committed graph. index_status reports these while a
        # build is running: live queries on the builder's connection would see
        # its uncommitted, half-rewritten tables.
        self._graph_snapshot = self._read_graph_stats()

        self.phase = "starting"
        self.files_total = 0
        self.files_done = 0
        self.error: str | None = None
        self.started_at = time.time()
        self.ready_at: float | None = None
        self._discovered: set[str] = set()

        self.files_ready = threading.Event()
        self.index_ready = threading.Event()
        self.graph_ready = threading.Event()
        self._thread: threading.Thread | None = None

    # ── Building ─────────────────────────────────────────────────────────

    def start_background(self) -> None:
        """Run build() in a daemon thread and return immediately."""
        self._thread = threading.Thread(target=self.build, name="codetree-index", daemon=True)
        self._thread.start()

    def build(self, raise_errors: bool = False) -> None:
        """Discover, index (reusing the skeleton cache), then build the graph.

        Failures are recorded in ``error`` for tools to report. With
        raise_errors (synchronous startup) the exception is re-raised too, so
        the caller fails loudly with the original traceback.
        """
        try:
            self._build_index()
        except Exception as exc:
            self._fail(f"indexing failed: {exc!r}")
            self.graph_ready.set()  # no graph without an index — release waiters
            if raise_errors:
                raise
            return
        finally:
            self.files_ready.set()
            self.index_ready.set()

        try:
            self.phase = "building_graph"
            GraphBuilder(str(self.root), self.graph_store).build(indexer=self.indexer)
        except Exception as exc:
            self._fail(f"graph build failed: {exc!r}")
            try:
                self.graph_store.rollback()  # keep the last committed graph intact
            except Exception:
                pass  # store already closed, e.g. at interpreter exit
            if raise_errors:
                raise
            return
        finally:
            # Waiters must always be released, whatever failed above.
            try:
                self._graph_snapshot = self._read_graph_stats()
            except Exception:
                pass
            self.graph_ready.set()

        self.phase = "ready"
        self.ready_at = time.time()

    def _build_index(self) -> None:
        self.phase = "discovering"
        cache = Cache(self.root)
        cache.load()

        indexer = Indexer(self.root)
        files = indexer.discover_files()
        self._discovered = {str(f.relative_to(self.root)) for f in files}
        self.files_total = len(files)
        self.files_ready.set()

        self.phase = "indexing"
        # Entries written before has_errors was cached are re-parsed once.
        cached_mtimes = {
            k: v["mtime"] for k, v in (cache._data or {}).items() if "has_errors" in v
        }
        indexer.build(cached_mtimes=cached_mtimes, files=files, progress=self._on_progress)

        # Inject cached entries for unchanged files. Only files discovered by this
        # build qualify, so stale cache entries (deleted or now-ignored files,
        # e.g. old worktrees) are never resurrected.
        for rel_path in indexer.cached_candidates:
            path = self.root / rel_path
            try:
                mtime = path.stat().st_mtime
                if cache.is_valid(rel_path, mtime):
                    indexer.inject_cached(
                        rel_path=rel_path,
                        py_file=path,
                        source=path.read_bytes(),
                        skeleton=cache.get(rel_path).get("skeleton", []),
                        mtime=mtime,
                        has_errors=cache.get(rel_path).get("has_errors", False),
                    )
                    continue
            except OSError:
                continue  # deleted since discovery
            # Changed between discovery and injection — parse it instead
            entry = indexer.index_file(path)
            if entry is not None:
                indexer._index[rel_path] = entry

        # Rebuild definition index once after all injections (DATA-01, DATA-02, DATA-03 fix)
        indexer._rebuild_definitions()

        # Save updated cache — rebuilt from the index so stale entries are dropped
        cache._data = {}
        for rel_path, file_entry in indexer._index.items():
            cache.set(rel_path, {
                "mtime": file_entry.mtime,
                "skeleton": file_entry.skeleton,
                "has_errors": file_entry.has_errors,
            })
        try:
            cache.save()
        except OSError:
            pass  # the cache only speeds up the next start — never fail the index for it

        # Publish only the complete indexer: tools never see a half-built one.
        self.indexer = indexer

    def _on_progress(self, done: int, total: int) -> None:
        self.files_done = done
        self.files_total = total

    def _fail(self, message: str) -> None:
        self.phase = "error"
        self.error = message

    # ── Access for tools ─────────────────────────────────────────────────

    def wait_for_index(self, timeout: float | None = None) -> Indexer | None:
        """Return the full indexer once built; None if still indexing or failed."""
        self.index_ready.wait(WAIT_TIMEOUT if timeout is None else timeout)
        return self.indexer

    def wait_for_graph(self, timeout: float | None = None) -> bool:
        """True once the graph is built and usable."""
        self.graph_ready.wait(WAIT_TIMEOUT if timeout is None else timeout)
        return self.graph_ready.is_set() and self.error is None

    def indexer_for_files(self, rel_paths: list[str], timeout: float | None = None) -> Indexer | None:
        """Indexer able to answer about rel_paths, without waiting for the full index.

        Before the full index is ready, returns a throwaway Indexer holding just
        those files, parsed on demand — limited to discovered files so results
        match what the full index will say. None if discovery is not done yet.
        """
        if self.index_ready.is_set():
            return self.indexer
        if not self.files_ready.wait(WAIT_TIMEOUT if timeout is None else timeout):
            return None
        if self.index_ready.is_set():
            return self.indexer
        partial = Indexer(self.root)
        for rel_path in dict.fromkeys(rel_paths):
            if rel_path not in self._discovered:
                continue
            entry = partial.index_file(self.root / rel_path)
            if entry is not None:
                partial._index[rel_path] = entry
        partial._rebuild_definitions()
        return partial

    def not_ready_message(self, need: str = "index") -> str:
        """Explain why a tool cannot answer yet (or why it never will)."""
        if self.error:
            return f"codetree {self.error}. Restart the MCP server to retry."
        elapsed = int(time.time() - self.started_at)
        if self.phase == "indexing" and self.files_total:
            where = f"indexing {self.files_done}/{self.files_total} files"
        else:
            where = self.phase.replace("_", " ")
        what = "code graph" if need == "graph" else "repository index"
        return (
            f"codetree is still building the {what} ({where}, {elapsed}s elapsed). "
            "Retry in a few seconds; index_status shows progress."
        )

    def _read_graph_stats(self) -> dict:
        return {
            **self.graph_store.stats(),
            "last_indexed_at": self.graph_store.get_meta("last_indexed_at"),
        }

    def graph_stats(self) -> dict:
        """files/symbols/edges/last_indexed_at of the last committed graph (never blocks)."""
        if self.graph_ready.is_set():
            return self._read_graph_stats()
        return dict(self._graph_snapshot)

    def status(self) -> dict:
        """Lifecycle fields for index_status (never blocks)."""
        result = {
            "status": self.phase,
            "files_discovered": self.files_total,
            "files_indexed": self.files_done if self.phase == "indexing" else (
                len(self.indexer._index) if self.indexer else 0
            ),
            "index_ready": self.index_ready.is_set() and self.indexer is not None,
            "graph_ready": self.graph_ready.is_set() and self.error is None,
        }
        if self.ready_at is not None:
            result["startup_seconds"] = round(self.ready_at - self.started_at, 2)
        if self.error:
            result["error"] = self.error
        return result

    def close(self) -> None:
        self.graph_store.close()
