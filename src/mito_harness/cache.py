"""Disk cache for external API responses.

Guarantees reproducible runs: the first run hits live APIs (PubMed, Europe PMC,
ClinicalTrials.gov), subsequent runs replay the cached snapshot. ``--refresh``
in main.py wipes the cache directory before the run.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _key(source: str, params: dict[str, Any]) -> str:
    canonical = json.dumps(params, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(f"{source}:{canonical}".encode()).hexdigest()


class DiskCache:
    """Content-addressed JSON cache under ``<cache_dir>/<source>/<key>.json``."""

    def __init__(self, cache_dir: Path) -> None:
        self.root = Path(cache_dir)

    def _path(self, source: str, params: dict[str, Any]) -> Path:
        return self.root / source / f"{_key(source, params)}.json"

    def get(self, source: str, params: dict[str, Any]) -> Any | None:
        path = self._path(source, params)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.warning("corrupt cache entry removed: %s", path)
            path.unlink(missing_ok=True)
            return None

    def set(self, source: str, params: dict[str, Any], payload: Any) -> None:
        path = self._path(source, params)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def clear(self) -> None:
        if self.root.exists():
            for child in self.root.iterdir():
                if child.is_dir():
                    for f in child.iterdir():
                        f.unlink(missing_ok=True)
                    child.rmdir()
                else:
                    child.unlink(missing_ok=True)
            logger.info("cache cleared: %s", self.root)
