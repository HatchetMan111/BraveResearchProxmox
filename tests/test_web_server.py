import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """Importiert app.web.server frisch mit RESEARCH_LXC_CONFIG auf ein
    Tempverzeichnis gesetzt, damit Tests sich nicht gegenseitig über eine
    gemeinsame config.yaml beeinflussen."""
    config_path = tmp_path / "config.yaml"
    monkeypatch.setenv("RESEARCH_LXC_CONFIG", str(config_path))
    import app.web.server as server_module

    importlib.reload(server_module)  # CONFIG_PATH neu aus der Env-Var lesen
    return TestClient(server_module.app), server_module, config_path


def test_dashboard_loads_with_defaults(client):
    test_client, _, _ = client
    resp = test_client.get("/")
    assert resp.status_code == 200
    assert "Budget diesen Monat" in resp.text
    assert "Kein Brave API Key hinterlegt" in resp.text  # Warnbanner, da Config leer


def test_settings_form_loads(client):
    test_client, _, _ = client
    resp = test_client.get("/settings")
    assert resp.status_code == 200
    assert "Konkurrenzanalyse" in resp.text
    assert "News-Digest" in resp.text


def test_settings_post_writes_config(client):
    test_client, _, config_path = client
    form = {
        "brave_api_key": "dummy-key",
        "brave_max_requests_per_month": "800",
        "ollama_base_url": "http://192.168.178.95:11434",
        "ollama_model": "llama3.1",
        "competitor_enabled": "on",
        "competitor_branche": "Metzgerei",
        "competitor_region": "Main-Tauber-Kreis",
        "news_enabled": "on",
        "news_region": "Main-Tauber-Kreis",
        "news_themen": "Energie, SmartHome, Förderprogramme",
        "news_stil": "sachlich, lokal, freundlich",
        "email_to": "bildung4.0@web.de",
        "email_from": "",
        "smtp_host": "",
        "smtp_port": "587",
        "smtp_user": "",
        "smtp_password": "",
    }
    resp = test_client.post("/settings", data=form)
    assert resp.status_code == 200
    assert "Gespeichert" in resp.text

    from app.web import config_io

    saved = config_io.load_raw_config(config_path)
    assert saved["brave"]["max_requests_per_month"] == 800
    assert saved["ollama"]["base_url"] == "http://192.168.178.95:11434"
    assert saved["modules"]["competitor_analysis"]["branche"] == "Metzgerei"
    assert saved["modules"]["news_digest"]["themen"] == ["Energie", "SmartHome", "Förderprogramme"]
    assert saved["output"]["email_to"] == "bildung4.0@web.de"
    assert saved["output"]["smtp"]["use_tls"] is False  # Checkbox nicht gesendet -> False


def test_trigger_run_unknown_module_returns_404(client):
    test_client, _, _ = client
    resp = test_client.post("/run/doesnotexist")
    assert resp.status_code == 404


def test_trigger_run_starts_background_task(client, monkeypatch):
    test_client, server_module, _ = client
    calls = []
    monkeypatch.setattr(server_module, "_execute_run", lambda name: calls.append(name))

    resp = test_client.post("/run/competitor_analysis", follow_redirects=False)

    assert resp.status_code == 303
    assert resp.headers["location"] == "/"
    assert calls == ["competitor_analysis"]


def test_reports_list_empty(client):
    test_client, _, _ = client
    resp = test_client.get("/reports")
    assert resp.status_code == 200
    assert "Noch keine Reports" in resp.text


def test_report_detail_rejects_non_markdown(client):
    test_client, _, _ = client
    resp = test_client.get("/reports/notes.txt")
    assert resp.status_code == 400


def test_report_detail_404_when_missing(client):
    test_client, _, _ = client
    resp = test_client.get("/reports/2026-01-01_0600_competitor_analysis.md")
    assert resp.status_code == 404


def test_report_detail_renders_existing_report(client, monkeypatch):
    test_client, server_module, config_path = client
    reports_dir = config_path.parent / "reports"
    reports_dir.mkdir(parents=True)
    (reports_dir / "example.md").write_text("# Titel\n\nInhalt hier.", encoding="utf-8")

    resp = test_client.get("/reports/example.md")
    assert resp.status_code == 200
    assert "Titel" in resp.text
    assert "Inhalt hier." in resp.text


def test_execute_run_updates_status_on_success(client, monkeypatch):
    test_client, server_module, config_path = client
    from app.web import config_io

    cfg = config_io.load_raw_config(config_path)
    cfg["brave"]["api_key"] = "dummy"
    cfg["ollama"]["base_url"] = "http://dummy-ollama:11434"
    cfg["ollama"]["model"] = "llama3.1"
    config_io.save_raw_config(config_path, cfg)

    fake_report_path = config_path.parent / "reports" / "fake.md"
    fake_report_path.parent.mkdir(parents=True, exist_ok=True)
    fake_report_path.write_text("# fake report")

    fake_result = type(
        "FakeResult", (), {"budget_exhausted": False, "queries_run": ["q1"]}
    )()

    monkeypatch.setattr(server_module.pipeline, "run_module", lambda name, cfg: fake_result)
    monkeypatch.setattr(
        server_module.output, "write_report", lambda result, out_cfg: fake_report_path
    )
    monkeypatch.setattr(
        server_module.output, "send_report_email", lambda *a, **k: False
    )

    server_module._execute_run("competitor_analysis")

    status = server_module.RUN_STATUS["competitor_analysis"]
    assert status["status"] == "done"
    assert status["report_file"] == "fake.md"


def test_execute_run_captures_errors_without_crashing(client, monkeypatch):
    test_client, server_module, config_path = client
    from app.web import config_io

    cfg = config_io.load_raw_config(config_path)
    cfg["brave"]["api_key"] = "dummy"
    cfg["ollama"]["base_url"] = "http://dummy-ollama:11434"
    cfg["ollama"]["model"] = "llama3.1"
    config_io.save_raw_config(config_path, cfg)

    def boom(name, cfg):
        raise RuntimeError("Simulierter Absturz")

    monkeypatch.setattr(server_module.pipeline, "run_module", boom)

    server_module._execute_run("competitor_analysis")  # darf NICHT werfen

    status = server_module.RUN_STATUS["competitor_analysis"]
    assert status["status"] == "error"
    assert "Simulierter Absturz" in status["error"]
