"""Tests for source file discovery: .gitignore, nested worktrees/repos, walk fallback."""

import json
import os
import subprocess
from pathlib import Path

import pytest

from codetree.indexer import Indexer
from codetree.server import create_server


def _git(cwd, *args):
    subprocess.run(
        ["git", "-c", "user.email=test@test.com", "-c", "user.name=Test",
         "-c", "protocol.file.allow=always", *args],
        cwd=cwd, capture_output=True, text=True, timeout=30, check=True,
    )


def _rel_files(indexer: Indexer) -> set[str]:
    return {str(f.relative_to(indexer.root)) for f in indexer.files}


def _make_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q")
    (path / "app.py").write_text("def app():\n    pass\n")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "init")
    return path


# ── Git mode ─────────────────────────────────────────────────────────────────

def test_gitignored_files_are_not_indexed(tmp_path):
    repo = _make_repo(tmp_path / "repo")
    (repo / ".gitignore").write_text("generated/\ntmp_*.py\n")
    (repo / "generated").mkdir()
    (repo / "generated" / "gen.py").write_text("def gen():\n    pass\n")
    (repo / "tmp_scratch.py").write_text("def scratch():\n    pass\n")

    indexer = Indexer(repo)
    indexer.build()

    assert _rel_files(indexer) == {"app.py"}


def test_untracked_but_not_ignored_files_are_indexed(tmp_path):
    repo = _make_repo(tmp_path / "repo")
    (repo / "new_module.py").write_text("def fresh():\n    pass\n")

    indexer = Indexer(repo)
    indexer.build()

    assert "new_module.py" in _rel_files(indexer)


def test_nested_worktree_is_not_indexed_even_if_not_ignored(tmp_path):
    repo = _make_repo(tmp_path / "repo")
    _git(repo, "worktree", "add", "-q", ".claude/worktrees/feature", "-b", "feature")
    assert (repo / ".claude" / "worktrees" / "feature" / "app.py").exists()

    indexer = Indexer(repo)
    indexer.build()

    assert _rel_files(indexer) == {"app.py"}


def test_nested_repository_is_not_indexed(tmp_path):
    repo = _make_repo(tmp_path / "repo")
    _make_repo(repo / "vendor_repo")

    indexer = Indexer(repo)
    indexer.build()

    assert _rel_files(indexer) == {"app.py"}


def test_submodule_is_not_indexed(tmp_path):
    upstream = _make_repo(tmp_path / "upstream")
    repo = _make_repo(tmp_path / "repo")
    _git(repo, "submodule", "add", "-q", str(upstream), "libs/upstream")
    _git(repo, "commit", "-q", "-m", "add submodule")

    indexer = Indexer(repo)
    indexer.build()

    assert _rel_files(indexer) == {"app.py"}


def test_root_inside_worktree_indexes_that_worktree(tmp_path):
    repo = _make_repo(tmp_path / "repo")
    _git(repo, "worktree", "add", "-q", ".claude/worktrees/feature", "-b", "feature")
    worktree = repo / ".claude" / "worktrees" / "feature"
    (worktree / "feature_only.py").write_text("def feature():\n    pass\n")

    indexer = Indexer(worktree)
    indexer.build()

    assert _rel_files(indexer) == {"app.py", "feature_only.py"}


def test_deleted_but_still_tracked_file_is_skipped(tmp_path):
    repo = _make_repo(tmp_path / "repo")
    (repo / "app.py").unlink()  # deleted in work tree, still in git index

    indexer = Indexer(repo)
    indexer.build()

    assert _rel_files(indexer) == set()


def test_codetree_dir_never_indexed_in_git_mode(tmp_path):
    repo = _make_repo(tmp_path / "repo")
    (repo / ".codetree").mkdir()
    (repo / ".codetree" / "leftover.py").write_text("def leftover():\n    pass\n")

    indexer = Indexer(repo)
    indexer.build()

    assert _rel_files(indexer) == {"app.py"}


# ── Walk fallback ────────────────────────────────────────────────────────────

def test_walk_fallback_without_git_skips_skip_dirs(tmp_path):
    root = tmp_path / "plain"
    root.mkdir()
    (root / "main.py").write_text("def main():\n    pass\n")
    for skipped in ("node_modules", ".venv", "pkg.egg-info"):
        (root / skipped).mkdir()
        (root / skipped / "dep.py").write_text("def dep():\n    pass\n")

    indexer = Indexer(root)
    assert indexer._git_files() is None
    indexer.build()

    assert _rel_files(indexer) == {"main.py"}


def test_root_ignored_by_parent_repo_falls_back_to_walk(tmp_path):
    parent = _make_repo(tmp_path / "parent")
    (parent / ".gitignore").write_text("ignored_area/\n")
    root = parent / "ignored_area"
    root.mkdir()
    (root / "lib.py").write_text("def lib():\n    pass\n")

    indexer = Indexer(root)
    indexer.build()

    assert _rel_files(indexer) == {"lib.py"}


def test_walk_fallback_when_git_is_unavailable(tmp_path, monkeypatch):
    repo = _make_repo(tmp_path / "repo")
    (repo / "node_modules").mkdir()
    (repo / "node_modules" / "dep.js").write_text("function dep() {}\n")

    def _no_git(*args, **kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr("codetree.indexer.subprocess.run", _no_git)
    indexer = Indexer(repo)
    indexer.build()

    assert _rel_files(indexer) == {"app.py"}


def test_discovered_files_are_sorted(tmp_path):
    root = tmp_path / "plain"
    root.mkdir()
    for name in ("zeta.py", "alpha.py", "mid.py"):
        (root / name).write_text("x = 1\n")

    files = Indexer(root).discover_files()

    assert files == sorted(files)


# ── Cache interaction ────────────────────────────────────────────────────────

def test_stale_cache_entries_for_ignored_files_are_not_resurrected(tmp_path):
    repo = _make_repo(tmp_path / "repo")
    ignored = repo / "old_worktree" / "ghost.py"
    ignored.parent.mkdir()
    ignored.write_text("def ghost():\n    pass\n")

    # First startup indexes ghost.py and caches it
    create_server(str(repo))
    cache_file = repo / ".codetree" / "index.json"
    assert "old_worktree/ghost.py" in json.loads(cache_file.read_text())

    # Now the directory is ignored; the valid cache entry must not come back
    (repo / ".gitignore").write_text("old_worktree/\n.codetree/\n")
    mcp = create_server(str(repo))
    find_refs = mcp.local_provider._components["tool:find_references@"].fn

    assert "ghost.py" not in find_refs(symbol_name="ghost")
    assert "old_worktree/ghost.py" not in json.loads(cache_file.read_text())


def test_git_mode_indexes_tracked_files_in_skip_dirs(tmp_path):
    repo = _make_repo(tmp_path / "repo")
    for tracked in ("build", "dist", "env"):
        (repo / tracked).mkdir()
        (repo / tracked / "mod.py").write_text("def mod():\n    pass\n")
    _git(repo, "add", "build", "dist", "env")
    _git(repo, "commit", "-q", "-m", "tracked build output")

    indexer = Indexer(repo)
    indexer.build()

    assert _rel_files(indexer) == {"app.py", "build/mod.py", "dist/mod.py", "env/mod.py"}


def test_git_mode_skips_untracked_unignored_venv_and_node_modules(tmp_path):
    repo = _make_repo(tmp_path / "repo")  # no .gitignore at all
    (repo / ".venv" / "lib" / "site-packages" / "pkg").mkdir(parents=True)
    (repo / ".venv" / "lib" / "site-packages" / "pkg" / "m.py").write_text("def m():\n    pass\n")
    (repo / "venv" / "lib").mkdir(parents=True)
    (repo / "venv" / "lib" / "dep.py").write_text("def dep():\n    pass\n")
    (repo / "node_modules" / "x").mkdir(parents=True)
    (repo / "node_modules" / "x" / "i.js").write_text("function i() {}\n")
    (repo / "fresh.py").write_text("def fresh():\n    pass\n")

    indexer = Indexer(repo)
    indexer.build()

    assert _rel_files(indexer) == {"app.py", "fresh.py"}


def test_walk_fallback_skips_worktrees_but_keeps_nested_repositories(tmp_path):
    root = tmp_path / "plain"  # not a repo itself, e.g. a folder grouping several repos
    root.mkdir()
    (root / "main.py").write_text("def main():\n    pass\n")
    nested_repo = root / "vendor_repo"
    (nested_repo / ".git").mkdir(parents=True)
    (nested_repo / ".git" / "hooks.py").write_text("x = 1\n")
    (nested_repo / "lib.py").write_text("def lib():\n    pass\n")
    worktree = root / ".claude" / "worktrees" / "feature"
    worktree.mkdir(parents=True)
    (worktree / ".git").write_text("gitdir: /elsewhere/.git/worktrees/feature\n")
    (worktree / "main.py").write_text("def main():\n    pass\n")

    indexer = Indexer(root)
    assert indexer._git_files() is None
    indexer.build()

    assert _rel_files(indexer) == {"main.py", "vendor_repo/lib.py"}


def test_non_utf8_file_names_are_indexed_in_git_mode(tmp_path):
    repo = _make_repo(tmp_path / "repo")
    name = os.fsdecode(b"caf\xe9.py")
    (repo / name).write_text("def cafe():\n    pass\n")

    indexer = Indexer(repo)
    indexer.build()

    assert name in _rel_files(indexer)


def test_conflicted_file_is_discovered_once(tmp_path):
    repo = _make_repo(tmp_path / "repo")
    _git(repo, "checkout", "-q", "-b", "other")
    (repo / "app.py").write_text("def app():\n    return 1\n")
    _git(repo, "commit", "-q", "-am", "other")
    _git(repo, "checkout", "-q", "-")
    (repo / "app.py").write_text("def app():\n    return 2\n")
    _git(repo, "commit", "-q", "-am", "main")
    subprocess.run(["git", "merge", "-q", "other"], cwd=repo, capture_output=True)  # conflicts

    files = Indexer(repo).discover_files()

    assert [str(f.relative_to(repo)) for f in files] == ["app.py"]


def test_index_order_does_not_depend_on_cache(tmp_path):
    root = tmp_path / "plain"
    root.mkdir()
    for name in ("a.py", "b.py", "c.py", "d.py"):
        (root / name).write_text("def target():\n    pass\n")
    first = Indexer(root)
    first.build()
    cached = {rel: e.mtime for rel, e in first._index.items() if rel != "c.py"}

    # c.py is re-parsed, the others come from the "cache": order must not change
    second = Indexer(root)
    second.build(cached_mtimes=cached)
    for rel in second.cached_candidates:
        entry = first._index[rel]
        second.inject_cached(rel, entry.path, entry.source, entry.skeleton, entry.mtime)
    second._rebuild_definitions()

    assert list(second._index) == ["a.py", "b.py", "c.py", "d.py"]
    assert [r["file"] for r in second.find_references("target")] == ["a.py", "b.py", "c.py", "d.py"]


def test_concurrent_cache_saves_never_fail_or_tear(tmp_path):
    import threading
    from codetree.cache import Cache

    errors = []

    def writer(tag):
        cache = Cache(tmp_path)
        cache.set("x.py", {"mtime": 1.0, "skeleton": [{"name": tag * 200}]})
        try:
            for _ in range(50):
                cache.save()
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(tag,)) for tag in "abcd"]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    data = json.loads((tmp_path / ".codetree" / "index.json").read_text())
    assert data["x.py"]["mtime"] == 1.0
    assert list((tmp_path / ".codetree").glob("*.tmp")) == []
