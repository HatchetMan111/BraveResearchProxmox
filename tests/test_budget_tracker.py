from datetime import datetime, timezone

import pytest

from app.budget_tracker import BudgetExceededError, BudgetTracker


def make_tracker(tmp_path, limit=5, month_str="2026-09-01T00:00:00+00:00"):
    box = {"now": datetime.fromisoformat(month_str)}
    tracker = BudgetTracker(
        tmp_path / "budget.db", max_requests_per_month=limit, clock=lambda: box["now"]
    )
    return tracker, box


def test_records_requests_and_reports_status(tmp_path):
    tracker, _ = make_tracker(tmp_path, limit=5)
    status = tracker.record_request(1)
    assert status.used == 1
    assert status.remaining == 4

    tracker.record_request(2)
    assert tracker.status().used == 3
    assert tracker.status().remaining == 2


def test_blocks_when_limit_reached(tmp_path):
    tracker, _ = make_tracker(tmp_path, limit=3)
    tracker.record_request(3)
    assert tracker.status().remaining == 0

    with pytest.raises(BudgetExceededError):
        tracker.record_request(1)

    # Nichts wurde teilweise verbucht -- Zähler bleibt bei 3
    assert tracker.status().used == 3


def test_rejects_batch_that_would_exceed_limit(tmp_path):
    tracker, _ = make_tracker(tmp_path, limit=5)
    tracker.record_request(4)
    with pytest.raises(BudgetExceededError):
        tracker.record_request(2)  # 4 + 2 = 6 > 5
    assert tracker.status().used == 4  # unverändert, kein Teilverbrauch


def test_budget_resets_for_new_month(tmp_path):
    tracker, box = make_tracker(tmp_path, limit=2, month_str="2026-09-30T23:00:00+00:00")
    tracker.record_request(2)
    assert tracker.status().remaining == 0

    box["now"] = datetime(2026, 10, 1, 0, 5, tzinfo=timezone.utc)
    assert tracker.status().remaining == 2  # neuer Monat, neues Budget
    tracker.record_request(1)  # funktioniert wieder
    assert tracker.status().used == 1
