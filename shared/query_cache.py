"""
query_cache.py
查询结果缓存 —— 基于 SQL 文本做 key，TTL 可配置
"""
import hashlib
import time
from typing import Any


class QueryCache:
    def __init__(self, ttl: int = 300, max_size: int = 128):
        """
        ttl:      缓存有效期（秒），0 表示不缓存
        max_size: 最大缓存条数，超出时淘汰最旧的条目
        """
        self.ttl = ttl
        self.max_size = max_size
        self._store: dict[str, dict] = {}   # key -> {value, expires_at}

    def _make_key(self, sql: str, db: str = "") -> str:
        raw = f"{db}::{sql.strip().lower()}"
        return hashlib.md5(raw.encode()).hexdigest()

    def get(self, sql: str, db: str = "") -> Any | None:
        if self.ttl == 0:
            return None
        key = self._make_key(sql, db)
        entry = self._store.get(key)
        if entry is None:
            return None
        if time.time() > entry["expires_at"]:
            del self._store[key]
            return None
        return entry["value"]

    def set(self, sql: str, value: Any, db: str = "") -> None:
        if self.ttl == 0:
            return
        # 超出 max_size 时淘汰最旧
        if len(self._store) >= self.max_size:
            oldest = min(self._store, key=lambda k: self._store[k]["expires_at"])
            del self._store[oldest]
        key = self._make_key(sql, db)
        self._store[key] = {
            "value": value,
            "expires_at": time.time() + self.ttl,
        }

    def clear(self) -> None:
        self._store.clear()

    @property
    def size(self) -> int:
        return len(self._store)
