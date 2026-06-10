"""
Tiny in-process TTL cache.

poe.ninja's build snapshots update slowly (hours), and the dictionary endpoints
are content-hashed (effectively immutable). Caching keeps the tools fast and is
basic etiquette toward an undocumented API we don't want to hammer.
"""

from __future__ import annotations

import time
from typing import Any


class TTLCache:
    def __init__(self, ttl: float = 900.0) -> None:
        self.ttl = ttl
        self._store: dict[Any, tuple[float, Any]] = {}

    def get(self, key: Any) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        ts, value = entry
        if time.monotonic() - ts >= self.ttl:
            self._store.pop(key, None)
            return None
        return value

    def set(self, key: Any, value: Any) -> None:
        now = time.monotonic()
        # Sweep expired entries on write so payloads (search bytes can be ~100 KB)
        # don't accumulate forever — get() only evicts the key it was asked for.
        self._store = {k: e for k, e in self._store.items() if now - e[0] < self.ttl}
        self._store[key] = (now, value)

    def clear(self) -> None:
        self._store.clear()
