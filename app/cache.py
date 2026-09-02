"""TTL-Cache für Brave-Suchergebnisse.

Wichtigster Hebel, um mit 1000 Requests/Monat auszukommen: Wiederkehrende
Recherche-Läufe (z.B. wöchentlich dieselbe Branche+Region) treffen oft
dieselben Queries. Ein Treffer im Cache kostet 0 Requests.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


@dataclass
class CacheEntry:
    query_key: str
    response: Any
    created_at: datetime


class ResponseCache:
    def __init__(self, db_path: str | Path, ttl_hours: int, clock=None):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.ttl_hours = ttl_hours
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._init_db()

    def _init_db(self) -> None:
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cache (
                    query_key TEXT PRIMARY KEY,
                    query_text TEXT NOT NULL,
                    response_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    @staticmethod
    def make_key(endpoint: str, query: str, **params: Any) -> str:
        payload = json.dumps(
            {"endpoint": endpoint, "query": query, "params": params},
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def get(self, key: str) -> Any | None:
        with closing(sqlite3.connect(self.db_path)) as conn:
            row = conn.execute(
                "SELECT response_json, created_at FROM cache WHERE query_key = ?",
                (key,),
            ).fetchone()
        if not row:
            return None
        response_json, created_at_raw = row
        created_at = datetime.fromisoformat(created_at_raw)
        if self._clock() - created_at > timedelta(hours=self.ttl_hours):
            return None
        return json.loads(response_json)

    def set(self, key: str, query_text: str, response: Any) -> None:
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute(
                """
                INSERT INTO cache (query_key, query_text, response_json, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(query_key) DO UPDATE SET
                    response_json = excluded.response_json,
                    created_at = excluded.created_at
                """,
                (key, query_text, json.dumps(response), self._clock().isoformat()),
            )
            conn.commit()
