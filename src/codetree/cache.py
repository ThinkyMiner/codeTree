import json
import os
import stat
import tempfile
from pathlib import Path


class Cache:
    def __init__(self, root: str | Path):
        self._root = Path(root)
        self._cache_file = self._root / ".codetree" / "index.json"
        self._data: dict = {}

    def load(self):
        """Load cache from disk. No-op if cache file doesn't exist or is corrupt."""
        if self._cache_file.exists():
            try:
                self._data = json.loads(self._cache_file.read_text())
            except (json.JSONDecodeError, OSError):
                self._data = {}

    def save(self):
        """Write cache to disk, creating .codetree/ directory if needed."""
        self._cache_file.parent.mkdir(parents=True, exist_ok=True)
        # Write-then-rename so a server killed mid-save never leaves a torn file.
        # The temp name is unique so concurrent servers on one repo cannot collide.
        fd, tmp_name = tempfile.mkstemp(
            dir=self._cache_file.parent, prefix="index.", suffix=".json.tmp"
        )
        try:
            with os.fdopen(fd, "w") as tmp_file:
                tmp_file.write(json.dumps(self._data, indent=2))
            # mkstemp creates 0600; keep the previous mode, or a regular 0644.
            try:
                mode = stat.S_IMODE(self._cache_file.stat().st_mode)
            except OSError:
                mode = 0o644
            os.chmod(tmp_name, mode)
            os.replace(tmp_name, self._cache_file)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise

    def get(self, rel_path: str) -> dict | None:
        return self._data.get(rel_path)

    def set(self, rel_path: str, data: dict):
        self._data[rel_path] = data

    def is_valid(self, rel_path: str, current_mtime: float) -> bool:
        """Return True if cached entry exists and mtime matches current_mtime."""
        entry = self._data.get(rel_path)
        if entry is None:
            return False
        return entry.get("mtime") == current_mtime
