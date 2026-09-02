"""Hartes Monatsbudget für Brave-Search-Requests.

Brave rechnet in Kalendermonaten ab ($5 Gratis-Credit/Monat = ~1000 Requests
im aktuellen Web-Search-Plan). Der Tracker zählt pro Monat (Schlüssel
"YYYY-MM") und blockt jede weitere Anfrage, sobald das konfigurierte Limit
erreicht ist -- inklusive Sicherheitspuffer, den man in der Config setzt
(Default: 950 statt 1000).
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


class BudgetExceededError(RuntimeError):
    """Wird geworfen, wenn das Monatsbudget an Brave-Requests aufgebraucht ist."""


@dataclass
class BudgetStatus:
    month: str
    used: int
    limit: int

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)


class BudgetTracker:
    def __init__(self, db_path: str | Path, max_requests_per_month: int, clock=None):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.max_requests_per_month = max_requests_per_month
        # Austauschbar für Tests: clock() -> datetime
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._init_db()

    def _init_db(self) -> None:
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS budget (
                    month TEXT PRIMARY KEY,
                    requests_used INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            conn.commit()

    def _current_month(self) -> str:
        return self._clock().strftime("%Y-%m")

    def status(self) -> BudgetStatus:
        month = self._current_month()
        with closing(sqlite3.connect(self.db_path)) as conn:
            row = conn.execute(
                "SELECT requests_used FROM budget WHERE month = ?", (month,)
            ).fetchone()
        used = row[0] if row else 0
        return BudgetStatus(month=month, used=used, limit=self.max_requests_per_month)

    def has_budget(self, n: int = 1) -> bool:
        return self.status().remaining >= n

    def record_request(self, n: int = 1) -> BudgetStatus:
        """Verbraucht n Requests aus dem Budget. Wirft BudgetExceededError,
        falls das Limit dadurch überschritten würde -- es wird NICHTS
        teilweise verbucht (alles oder nichts pro Aufruf)."""
        month = self._current_month()
        with closing(sqlite3.connect(self.db_path)) as conn:
            row = conn.execute(
                "SELECT requests_used FROM budget WHERE month = ?", (month,)
            ).fetchone()
            used = row[0] if row else 0
            if used + n > self.max_requests_per_month:
                raise BudgetExceededError(
                    f"Monatsbudget erschöpft: {used}/{self.max_requests_per_month} "
                    f"Requests bereits verbraucht (Monat {month})."
                )
            new_used = used + n
            conn.execute(
                """
                INSERT INTO budget (month, requests_used) VALUES (?, ?)
                ON CONFLICT(month) DO UPDATE SET requests_used = excluded.requests_used
                """,
                (month, new_used),
            )
            conn.commit()
        return BudgetStatus(month=month, used=new_used, limit=self.max_requests_per_month)
