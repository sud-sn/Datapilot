"""
DataPilot — Query Executor (Source-Agnostic)
===============================================
Wraps any BaseConnector for query execution + caching.
"""

import time
import hashlib
import logging
from typing import Dict, Optional, Tuple

from connectors.base import BaseConnector, QueryResult

logger = logging.getLogger("datapilot.executor")


class QueryExecutor:
    """Executes validated SQL via any connector."""

    def __init__(self, connector: BaseConnector):
        self.connector = connector

    def execute(self, sql: str) -> QueryResult:
        """Execute a validated SQL query through the connector."""
        return self.connector.execute_query(sql)

    def close(self):
        self.connector.disconnect()


class QueryCache:
    """In-memory TTL cache for query results."""

    def __init__(self, settings):
        self.enabled = settings.cache_enabled
        self.ttl = settings.cache_ttl
        self.max_entries = settings.cache_max_entries
        self._cache: Dict[str, Tuple[float, QueryResult]] = {}

    def _hash(self, sql: str) -> str:
        return hashlib.sha256(sql.strip().upper().encode()).hexdigest()[:16]

    def get(self, sql: str) -> Optional[QueryResult]:
        if not self.enabled:
            return None
        key = self._hash(sql)
        if key in self._cache:
            ts, result = self._cache[key]
            if time.time() - ts < self.ttl:
                logger.info(f"Cache HIT: {key}")
                return result
            del self._cache[key]
        return None

    def put(self, sql: str, result: QueryResult):
        if not self.enabled:
            return
        if len(self._cache) >= self.max_entries:
            oldest = min(self._cache, key=lambda k: self._cache[k][0])
            del self._cache[oldest]
        self._cache[self._hash(sql)] = (time.time(), result)

    def invalidate(self):
        self._cache.clear()

    @property
    def stats(self) -> Dict:
        return {"entries": len(self._cache), "max": self.max_entries, "ttl": self.ttl}
