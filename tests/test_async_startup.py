"""Tests for background indexing: the server answers before the index is built."""

import subprocess
import threading
import time

import pytest

from codetree import index_state
from codetree.indexer import Indexer
from codetree.server import create_server


def _tool(mcp, name):
    return mcp.local_provider._components[f"tool:{name}@"].fn


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    (root / ".gitignore").write_text("ignored/\n.codetree/\n")
    (root / "calc.py").write_text(
        'class Calculator:\n    def add(self, a, b):\n        return a + b\n\n'
        'def helper():\n    return Calculator().add(1, 2)\n'
    )
    (root / "main.py").write_text("from calc import helper\n\ndef main():\n    helper()\n")
    (root / "ignored").mkdir()
    (root / "ignored" / "secret.py").write_text("def hidden():\n    pass\n")
    return root


@pytest.fixture(autouse=True)
def background_states(monkeypatch):
    """Join every background build and close its store when the test ends."""
    started = []
    original = index_state.IndexState.start_background

    def tracking_start(self):
        started.append(self)
        original(self)

    monkeypatch.setattr(index_state.IndexState, "start_background", tracking_start)
    yield started
    for state in started:
        if state._thread is not None:
            state._thread.join(15)
        state.close()


@pytest.fixture
def gate(monkeypatch, background_states):
    """Block background indexing (only the codetree-index thread) until released.

    Depends on background_states so the gate opens before threads are joined.
    """
    release = threading.Event()
    original = Indexer.index_file

    def gated_index_file(self, path, mtime=None):
        if threading.current_thread().name == "codetree-index":
            release.wait(10)
        return original(self, path, mtime)

    monkeypatch.setattr(Indexer, "index_file", gated_index_file)
    monkeypatch.setattr(index_state, "WAIT_TIMEOUT", 0.3)
    yield release
    release.set()


def _wait(event, timeout=10):
    assert event.wait(timeout), "background indexing did not finish"


# ── Startup does not wait ────────────────────────────────────────────────────

def test_background_create_server_returns_before_indexing(repo, gate):
    start = time.monotonic()
    mcp = create_server(str(repo), background=True)
    assert time.monotonic() - start < 5
    state = mcp._codetree_state
    assert not state.index_ready.is_set()
    gate.set()
    _wait(state.graph_ready)


def test_index_status_never_blocks_and_reports_progress(repo, gate):
    mcp = create_server(str(repo), background=True)
    state = mcp._codetree_state
    _wait(state.files_ready)

    start = time.monotonic()
    status = _tool(mcp, "index_status")()
    assert time.monotonic() - start < 1
    assert status["status"] in ("indexing", "discovering")
    assert status["files_discovered"] == 2
    assert status["index_ready"] is False
    assert status["graph_ready"] is False

    gate.set()
    _wait(state.graph_ready)
    status = _tool(mcp, "index_status")()
    assert status["status"] == "ready"
    assert status["index_ready"] is True and status["graph_ready"] is True
    assert status["files_indexed"] == 2
    assert "startup_seconds" in status


# ── Single-file tools answer during indexing ─────────────────────────────────

def test_single_file_tools_parse_on_demand_while_indexing(repo, gate):
    mcp = create_server(str(repo), background=True)
    _wait(mcp._codetree_state.files_ready)

    skeleton = _tool(mcp, "get_file_skeleton")(file_path="calc.py")
    assert "class Calculator" in skeleton
    assert "def add" in skeleton
    assert "def helper" in _tool(mcp, "get_symbol")(file_path="calc.py", symbol_name="helper")
    assert "from calc import helper" in _tool(mcp, "get_imports")(file_path="main.py")
    assert "Complexity of helper()" in _tool(mcp, "get_complexity")(
        file_path="calc.py", function_name="helper")
    multi = _tool(mcp, "get_skeletons")(file_paths=["calc.py", "main.py"])
    assert "class Calculator" in multi and "def main" in multi
    flow = _tool(mcp, "analyze_dataflow")(file_path="calc.py", function_name="helper")
    assert "error" not in flow
    assert not mcp._codetree_state.index_ready.is_set()


def test_on_demand_parsing_respects_gitignore(repo, gate):
    mcp = create_server(str(repo), background=True)
    _wait(mcp._codetree_state.files_ready)

    result = _tool(mcp, "get_file_skeleton")(file_path="ignored/secret.py")
    assert result == "File not found or empty: ignored/secret.py"


# ── Repo-wide and graph tools wait, then explain ─────────────────────────────

def test_repo_wide_tool_reports_progress_when_index_not_ready(repo, gate):
    mcp = create_server(str(repo), background=True)
    _wait(mcp._codetree_state.files_ready)

    result = _tool(mcp, "find_references")(symbol_name="helper")
    assert "still building the repository index" in result
    assert "/2 files" in result
    assert "index_status" in result


def test_graph_tools_report_not_ready(repo, gate):
    mcp = create_server(str(repo), background=True)
    _wait(mcp._codetree_state.files_ready)

    result = _tool(mcp, "get_repository_map")()
    assert "still building the code graph" in result["error"]
    assert "still building the code graph" in _tool(mcp, "find_hot_paths")()


def test_repo_wide_tool_waits_for_index_finishing_in_time(repo, gate, monkeypatch):
    monkeypatch.setattr(index_state, "WAIT_TIMEOUT", 10)
    mcp = create_server(str(repo), background=True)
    _wait(mcp._codetree_state.files_ready)
    threading.Timer(0.2, gate.set).start()

    result = _tool(mcp, "find_references")(symbol_name="helper")
    assert "calc.py" in result and "main.py" in result


def test_tools_return_full_results_once_ready(repo, gate):
    mcp = create_server(str(repo), background=True)
    gate.set()
    _wait(mcp._codetree_state.graph_ready)

    assert "main.py" in _tool(mcp, "find_references")(symbol_name="helper")
    assert "ignored/secret.py" not in _tool(mcp, "find_references")(symbol_name="hidden")
    matches = _tool(mcp, "resolve_symbol")(query="helper")["matches"]
    assert [m["file"] for m in matches] == ["calc.py"]


# ── Failures never hang tools ────────────────────────────────────────────────

def test_indexing_failure_is_reported_not_hung(repo, monkeypatch):
    def boom(self):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(Indexer, "discover_files", boom)
    mcp = create_server(str(repo), background=True)
    _wait(mcp._codetree_state.graph_ready)

    start = time.monotonic()
    result = _tool(mcp, "find_references")(symbol_name="helper")
    assert time.monotonic() - start < 3
    assert "indexing failed" in result and "disk on fire" in result
    assert "indexing failed" in _tool(mcp, "get_file_skeleton")(file_path="calc.py")
    status = _tool(mcp, "index_status")()
    assert status["status"] == "error"
    assert "disk on fire" in status["error"]


def test_graph_failure_keeps_structural_tools_working(repo, monkeypatch):
    from codetree.graph.builder import GraphBuilder

    def boom(self, indexer=None):
        raise RuntimeError("graph exploded")

    monkeypatch.setattr(GraphBuilder, "build", boom)
    mcp = create_server(str(repo), background=True)
    _wait(mcp._codetree_state.graph_ready)

    assert "main.py" in _tool(mcp, "find_references")(symbol_name="helper")
    assert "graph build failed" in _tool(mcp, "get_repository_map")()["error"]
    assert _tool(mcp, "index_status")()["graph_ready"] is False


# ── Synchronous mode (default) ───────────────────────────────────────────────

def test_default_create_server_is_ready_on_return(repo):
    mcp = create_server(str(repo))
    status = _tool(mcp, "index_status")()
    assert status["status"] == "ready"
    assert status["index_ready"] and status["graph_ready"]


def test_warm_start_reuses_cache_in_background(repo):
    first = create_server(str(repo))
    first._codetree_state.close()

    mcp = create_server(str(repo), background=True)
    _wait(mcp._codetree_state.graph_ready)
    assert "class Calculator" in _tool(mcp, "get_file_skeleton")(file_path="calc.py")
    assert _tool(mcp, "index_status")()["files_indexed"] == 2


def test_sync_create_server_raises_on_indexing_failure(repo, monkeypatch):
    def boom(self):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(Indexer, "discover_files", boom)
    with pytest.raises(RuntimeError, match="disk on fire"):
        create_server(str(repo))


def test_cache_save_failure_does_not_fail_indexing(repo, monkeypatch):
    from codetree.cache import Cache

    def readonly(self):
        raise PermissionError("read-only file system")

    monkeypatch.setattr(Cache, "save", readonly)
    mcp = create_server(str(repo))

    assert _tool(mcp, "index_status")()["status"] == "ready"
    assert "main.py" in _tool(mcp, "find_references")(symbol_name="helper")


def test_atexit_does_not_pin_the_index(repo, monkeypatch):
    registered = []
    monkeypatch.setattr("codetree.server.atexit.register", registered.append)
    mcp = create_server(str(repo))

    # Only the SQLite store is registered — not IndexState, which owns every
    # file's source through its indexer.
    assert registered == [mcp._codetree_state.graph_store.close]


def test_index_status_reports_committed_graph_during_rebuild(repo, monkeypatch):
    from codetree.graph.builder import GraphBuilder

    first = create_server(str(repo))
    committed = _tool(first, "index_status")()
    first._codetree_state.close()
    assert committed["symbols"] > 0

    # Hold the next build mid-transaction, after it deleted rows.
    in_build = threading.Event()
    release = threading.Event()
    original = GraphBuilder.build

    def held_build(self, indexer=None):
        self._store.begin()
        self._store.delete_symbols_for_file("calc.py")
        self._store.delete_symbols_for_file("main.py")
        in_build.set()
        release.wait(10)
        return original(self, indexer=indexer)

    monkeypatch.setattr(GraphBuilder, "build", held_build)
    mcp = create_server(str(repo), background=True)
    try:
        assert in_build.wait(10)
        during = _tool(mcp, "index_status")()
        assert during["status"] == "building_graph"
        assert during["symbols"] == committed["symbols"]
        assert during["last_indexed_at"] == committed["last_indexed_at"]
    finally:
        release.set()
    _wait(mcp._codetree_state.graph_ready)
    after = _tool(mcp, "index_status")()
    assert after["status"] == "ready"
    assert after["last_indexed_at"] != committed["last_indexed_at"]


def test_syntax_error_flag_survives_warm_start(repo):
    (repo / "broken.py").write_text("def broken(:\n    pass\n")
    cold = _tool(create_server(str(repo)), "get_file_skeleton")(file_path="broken.py")
    warm = _tool(create_server(str(repo)), "get_file_skeleton")(file_path="broken.py")
    assert "WARNING: File has syntax errors" in cold
    assert warm == cold


def test_cache_entries_without_error_flag_are_reparsed(repo):
    import json

    (repo / "broken.py").write_text("def broken(:\n    pass\n")
    create_server(str(repo))
    cache_file = repo / ".codetree" / "index.json"
    data = json.loads(cache_file.read_text())
    for entry in data.values():
        del entry["has_errors"]  # as written by an older codetree
    cache_file.write_text(json.dumps(data))

    mcp = create_server(str(repo))
    assert "WARNING: File has syntax errors" in _tool(mcp, "get_file_skeleton")(file_path="broken.py")


def test_wait_timeout_from_env(monkeypatch):
    monkeypatch.setenv("CODETREE_WAIT_TIMEOUT", "3.5")
    assert index_state._wait_timeout_from_env() == 3.5
    monkeypatch.setenv("CODETREE_WAIT_TIMEOUT", "soon")
    assert index_state._wait_timeout_from_env() == 20.0


def test_graph_failure_with_failing_rollback_still_releases_waiters(repo, monkeypatch):
    from codetree.graph.builder import GraphBuilder
    from codetree.graph.store import GraphStore

    def boom(self, indexer=None):
        raise RuntimeError("graph exploded")

    def broken_rollback(self):
        raise RuntimeError("connection gone")

    monkeypatch.setattr(GraphBuilder, "build", boom)
    monkeypatch.setattr(GraphStore, "rollback", broken_rollback)
    mcp = create_server(str(repo), background=True)

    _wait(mcp._codetree_state.graph_ready)
    status = _tool(mcp, "index_status")()
    assert status["status"] == "error"
    assert "graph exploded" in status["error"]
