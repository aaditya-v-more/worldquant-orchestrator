"""Dataset / datafield / operator discovery, with a local cache.

The catalog changes slowly and is large. Caching it locally means an alpha
mining run can consult thousands of fields without spending a single request,
which is the biggest single lever on total request volume.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Iterator, Optional

from . import config, endpoints
from .session import BrainSession

CACHE_SCHEMA = """
CREATE TABLE IF NOT EXISTS datasets (
    cache_key  TEXT NOT NULL,
    id         TEXT NOT NULL,
    json       TEXT NOT NULL,
    fetched_at REAL NOT NULL,
    PRIMARY KEY (cache_key, id)
);

CREATE TABLE IF NOT EXISTS fields (
    cache_key  TEXT NOT NULL,
    id         TEXT NOT NULL,
    json       TEXT NOT NULL,
    fetched_at REAL NOT NULL,
    PRIMARY KEY (cache_key, id)
);

CREATE TABLE IF NOT EXISTS operators (
    name       TEXT PRIMARY KEY,
    json       TEXT NOT NULL,
    fetched_at REAL NOT NULL
);
"""

DEFAULT_TTL = 7 * 24 * 3600.0
PAGE_SIZE = 50
#: The API caps ``offset + limit`` at 100 for any query carrying ``search``.
SEARCH_RESULT_CAP = 100


class Catalog:
    def __init__(
        self,
        session: BrainSession,
        *,
        path: Optional[Path] = None,
        ttl: float = DEFAULT_TTL,
    ):
        self.session = session
        self.ttl = ttl
        self.path = Path(path) if path else config.CATALOG_PATH
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(CACHE_SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Catalog":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- generic paging ----------------------------------------------------

    def _paged(self, path: str, params: dict) -> Iterator[dict]:
        """Walk a ``{count, results[]}`` collection endpoint page by page.

        The API rejects ``offset + limit > 100`` when a ``search`` term is
        present ("Invalid query: maximum offset + limit for search query is
        100"), so searches stop at that ceiling instead of 400-ing.
        """
        max_total = SEARCH_RESULT_CAP if params.get("search") else None
        offset = 0
        while True:
            limit = PAGE_SIZE
            if max_total is not None:
                limit = min(limit, max_total - offset)
                if limit <= 0:
                    return
            page_params = dict(params, limit=limit, offset=offset)
            payload = self.session.json("GET", path, params=page_params)
            results = payload.get("results") or []
            for item in results:
                yield item
            offset += limit
            count = payload.get("count")
            if count is None or offset >= count or not results:
                return

    # -- cache helpers -----------------------------------------------------

    def _read_cache(self, table: str, cache_key: str) -> Optional[list[dict]]:
        cur = self.conn.execute(
            f"SELECT json, fetched_at FROM {table} WHERE cache_key = ?", (cache_key,)
        )
        rows = cur.fetchall()
        if not rows:
            return None
        if time.time() - min(r["fetched_at"] for r in rows) > self.ttl:
            return None
        return [json.loads(r["json"]) for r in rows]

    def _write_cache(self, table: str, cache_key: str, items: list[dict]) -> None:
        now = time.time()
        self.conn.execute(f"DELETE FROM {table} WHERE cache_key = ?", (cache_key,))
        self.conn.executemany(
            f"INSERT OR REPLACE INTO {table} (cache_key, id, json, fetched_at)"
            " VALUES (?, ?, ?, ?)",
            [
                (cache_key, str(item.get("id") or item.get("name")), json.dumps(item), now)
                for item in items
            ],
        )
        self.conn.commit()

    # -- datasets ----------------------------------------------------------

    def datasets(
        self,
        *,
        region: str = "USA",
        delay: int = 1,
        universe: str = "TOP3000",
        instrument_type: str = "EQUITY",
        search: Optional[str] = None,
        refresh: bool = False,
    ) -> list[dict]:
        params: dict[str, Any] = {
            "instrumentType": instrument_type,
            "region": region,
            "delay": delay,
            "universe": universe,
        }
        if search:
            params["search"] = search
        cache_key = json.dumps(params, sort_keys=True)
        if not refresh:
            cached = self._read_cache("datasets", cache_key)
            if cached is not None:
                return cached
        items = list(self._paged(endpoints.DATA_SETS, params))
        self._write_cache("datasets", cache_key, items)
        return items

    # -- datafields --------------------------------------------------------

    def fields(
        self,
        *,
        dataset_id: Optional[str] = None,
        region: str = "USA",
        delay: int = 1,
        universe: str = "TOP3000",
        instrument_type: str = "EQUITY",
        search: Optional[str] = None,
        field_type: Optional[str] = None,
        refresh: bool = False,
    ) -> list[dict]:
        params: dict[str, Any] = {
            "instrumentType": instrument_type,
            "region": region,
            "delay": delay,
            "universe": universe,
        }
        if dataset_id:
            params["dataset.id"] = dataset_id
        if search:
            params["search"] = search
        if field_type:
            params["type"] = field_type
        cache_key = json.dumps(params, sort_keys=True)
        if not refresh:
            cached = self._read_cache("fields", cache_key)
            if cached is not None:
                return cached
        items = list(self._paged(endpoints.DATA_FIELDS, params))
        self._write_cache("fields", cache_key, items)
        return items

    # -- operators ---------------------------------------------------------

    def operators(self, *, refresh: bool = False) -> list[dict]:
        if not refresh:
            cur = self.conn.execute("SELECT json, fetched_at FROM operators")
            rows = cur.fetchall()
            if rows and time.time() - min(r["fetched_at"] for r in rows) <= self.ttl:
                return [json.loads(r["json"]) for r in rows]
        payload = self.session.json("GET", endpoints.OPERATORS)
        # /operators returns a bare list, not the {count, results} envelope.
        items = payload if isinstance(payload, list) else (payload.get("results") or [])
        now = time.time()
        self.conn.execute("DELETE FROM operators")
        self.conn.executemany(
            "INSERT OR REPLACE INTO operators (name, json, fetched_at) VALUES (?, ?, ?)",
            [(item.get("name"), json.dumps(item), now) for item in items],
        )
        self.conn.commit()
        return items
