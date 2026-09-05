"""Tests für lesbare Anzeige: Titel, relative Zeiten, Budget-Ampel, Report-Meta."""

import importlib
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.web.server import human_rel, pretty_module_name, pretty_report


def test_pretty_module_name_builtin():
    assert pretty_module_name("competitor_analysis") == "Konkurrenzanalyse"
    assert pretty_module_name("news_digest") == "News-Digest"


def test_pretty_module_name_custom():
    assert pretty_module_name("sichtbares_modul") == "Sichtbares Modul"


def test_pretty_report_parses_filename():
    meta = {"name": "2026-09-04_0600_competitor_analysis.md",
            "mtime": datetime(2026, 9, 4, 6, 0)}
    pretty = pretty_report(meta)
    assert pretty["title"] == "Konkurrenzanalyse"
    assert pretty["date_str"] == "04.09.2026 06:00"
    assert pretty["name"] == "2026-09-04_0600_competitor_analysis.md"  # Dateiname bleibt


def test_pretty_report_custom_module():
    meta = {"name": "2026-09-04_0600_vereinsnachrichten.md",
            "mtime": datetime(2026, 9, 4, 6, 0)}
    assert pretty_report(meta)["title"] == "Vereinsnachrichten"


def test_pretty_report_unknown_filename():
    meta = {"name": "notizen.md", "mtime": datetime(2026, 9, 4, 6, 0)}
    pretty = pretty_report(meta)
    assert pretty["title"] == "Notizen"
    assert pretty["date_str"] == ""


def test_human_rel():
    now = datetime(2026, 9, 5, 12, 0)
    assert human_rel(now - timedelta(seconds=30), now) == "gerade eben"
    assert human_rel(now - timedelta(minutes=1), now) == "vor 1 Minute"
    assert human_rel(now - timedelta(minutes=5), now) == "vor 5 Minuten"
    assert human_rel(now - timedelta(hours=3), now) == "vor 3 Stunden"
    assert human_rel(now - timedelta(days=1, hours=2), now) == "gestern"
    assert human_rel(now - timedelta(days=3), now) == "vor 3 Tagen"
    assert human_rel(None, now) == ""


@pytest.fixture()
def client(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    monkeypatch.setenv("RESEARCH_LXC_CONFIG", str(config_path))
    import app.web.server as server_module

    importlib.reload(server_module)
    return TestClient(server_module.app), server_module, config_path


def _make_report(config_path, name="2026-09-04_0600_demo_modul.md"):
    reports_dir = config_path.parent / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / name).write_text("# Titel\n\nInhalt.\n", encoding="utf-8")


def test_dashboard_shows_titles_dots_and_budget_level(client, monkeypatch):
    from datetime import timezone

    from app.budget_tracker import BudgetStatus

    test_client, server_module, _ = client
    # Abgeschlossener Lauf -> Status-Punkt rendern
    server_module.RUN_STATUS["competitor_analysis"] = {
        "status": "done",
        "started_at": datetime(2026, 9, 5, 6, 0, tzinfo=timezone.utc),
        "finished_at": datetime(2026, 9, 5, 6, 5, tzinfo=timezone.utc),
        "report_file": "r.md",
        "budget_exhausted": False,
    }
    # Fast aufgebrauchtes Budget -> Ampel auf Rot
    class FakeTracker:
        def __init__(self, *a, **k): pass

        def status(self):
            return BudgetStatus(month="2026-09", used=900, limit=950)

    monkeypatch.setattr(server_module, "BudgetTracker", FakeTracker)
    resp = test_client.get("/")
    assert resp.status_code == 200
    assert "Konkurrenzanalyse" in resp.text
    assert "News-Digest" in resp.text
    assert "dot-done" in resp.text
    assert "level-danger" in resp.text


def test_dashboard_custom_module_pretty_title_keeps_raw_name(client):
    test_client, _, _ = client
    test_client.post("/modules/new", data={"name": "sichtbares-modul", "queries": "q"})
    resp = test_client.get("/")
    assert "Sichtbares Modul" in resp.text
    assert "sichtbares_modul" in resp.text  # Rohname im Tooltip


def test_reports_list_shows_pretty_title_and_rel(client):
    test_client, _, config_path = client
    _make_report(config_path)
    resp = test_client.get("/reports")
    assert "Demo Modul" in resp.text
    assert "2026-09-04_0600_demo_modul.md" in resp.text


def test_report_page_shows_meta_header(client):
    test_client, _, config_path = client
    _make_report(config_path)
    resp = test_client.get("/reports/2026-09-04_0600_demo_modul.md")
    assert resp.status_code == 200
    assert "Demo Modul" in resp.text
    assert "04.09.2026 06:00" in resp.text


def test_settings_has_sticky_save_and_favicon(client):
    test_client, _, _ = client
    resp = test_client.get("/settings")
    assert "sticky-save" in resp.text
    resp = test_client.get("/")
    assert 'rel="icon"' in resp.text
