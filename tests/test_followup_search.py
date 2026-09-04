"""Tests für Nachfragen zum Report (budgetfrei) + Volltextsuche."""

import importlib
import json

import pytest
from fastapi.testclient import TestClient

from app.web.server import build_followup_prompt


@pytest.fixture()
def client(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    monkeypatch.setenv("RESEARCH_LXC_CONFIG", str(config_path))
    import app.web.server as server_module

    importlib.reload(server_module)
    return TestClient(server_module.app), server_module, config_path


def _make_report(config_path, name="demo.md", text="# Titel\n\nMüllgebühren steigen in Musterstadt.\n"):
    reports_dir = config_path.parent / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / name).write_text(text, encoding="utf-8")


def _set_ollama(config_path):
    from app.web import config_io

    cfg = config_io.load_raw_config(config_path)
    cfg["ollama"]["base_url"] = "http://ollama:11434"
    cfg["ollama"]["model"] = "testmodell"
    config_io.save_raw_config(config_path, cfg)


# ---------- Prompt-Builder ----------


def test_followup_prompt_uses_sources_and_question():
    sidecar = {"sources": [
        {"query": "q", "title": "Anbieter X", "url": "https://x.example/a",
         "snippet": "Top Angebot in Musterstadt", "age": None},
    ]}
    system, user = build_followup_prompt("Was kostet das?", "# Report\nText", sidecar)
    assert "Was kostet das?" in user
    assert "Anbieter X" in user and "https://x.example/a" in user
    assert "AUSSCHLIESSLICH" in system


def test_followup_prompt_without_sidecar_falls_back():
    system, user = build_followup_prompt("Frage?", "# Report\nText", None)
    assert "Frage?" in user
    assert "nur Report-Text" in user


# ---------- Sidecar ----------


def test_write_report_creates_sources_sidecar(tmp_path):
    from datetime import datetime, timezone

    from app import output
    from app.config import OutputConfig, SmtpConfig
    from app.pipeline import RunResult

    result = RunResult(module_name="m", started_at=datetime.now(timezone.utc),
                       queries_planned=["q"], queries_run=["q"], content="Inhalt",
                       sources=[{"query": "q", "title": "T", "url": "https://t.example",
                                 "snippet": "S", "age": None}])
    out_cfg = OutputConfig(reports_dir=str(tmp_path / "reports"), email_to="", email_from="",
                           smtp=SmtpConfig())
    path = output.write_report(result, out_cfg)
    sidecar_path = path.with_name(f"{path.stem}.sources.json")
    assert sidecar_path.exists()
    data = json.loads(sidecar_path.read_text(encoding="utf-8"))
    assert data["sources"][0]["url"] == "https://t.example"

    assert output.load_sources_sidecar(tmp_path / "reports", path.name) is not None
    assert output.load_sources_sidecar(tmp_path / "reports", "fehlt.md") is None


# ---------- Nachfrage-Route ----------


class FakeOllama:
    last = None
    instance = None

    def __init__(self, base_url, model, timeout=180):
        self.base_url = base_url
        self.model = model
        FakeOllama.instance = self

    def generate(self, prompt, system=None):
        FakeOllama.last = {"prompt": prompt, "system": system}
        return "Antwort mit [Quelle](https://x.example/a)."


def test_ask_answers_from_stored_data(client, monkeypatch):
    test_client, server_module, config_path = client
    _make_report(config_path)
    _set_ollama(config_path)
    monkeypatch.setattr(server_module, "OllamaClient", FakeOllama)

    resp = test_client.post("/reports/demo.md/ask", data={"question": "Was kostet das?"})
    assert resp.status_code == 200
    assert "Antwort mit" in resp.text
    assert "ohne neue Suche" in resp.text
    # Prompt enthält Frage + Report-Text
    assert "Was kostet das?" in FakeOllama.last["prompt"]
    assert "Müllgebühren" in FakeOllama.last["prompt"]
    assert FakeOllama.instance.model == "testmodell"


def test_ask_uses_sidecar_sources_when_present(client, monkeypatch, tmp_path):
    test_client, server_module, config_path = client
    _make_report(config_path)
    _set_ollama(config_path)
    sidecar = {"sources": [{"query": "q", "title": "Wertstoffhof", "url": "https://w.example",
                            "snippet": "Mo-Fr 8-16", "age": None}]}
    reports_dir = config_path.parent / "reports"
    (reports_dir / "demo.sources.json").write_text(json.dumps(sidecar), encoding="utf-8")
    monkeypatch.setattr(server_module, "OllamaClient", FakeOllama)

    test_client.post("/reports/demo.md/ask", data={"question": "Wann offen?"})
    assert "Wertstoffhof" in FakeOllama.last["prompt"]


def test_ask_empty_question_calls_no_ollama(client, monkeypatch):
    test_client, server_module, config_path = client
    _make_report(config_path)
    _set_ollama(config_path)
    called = []
    monkeypatch.setattr(server_module, "OllamaClient", lambda *a, **k: called.append(1) or FakeOllama(*a, **k))

    resp = test_client.post("/reports/demo.md/ask", data={"question": "  "})
    assert "Frage eingeben" in resp.text
    assert called == []


def test_ask_without_ollama_config_shows_guidance(client):
    test_client, _, config_path = client
    _make_report(config_path)  # kein Ollama, kein Brave Key -- geht trotzdem bis zur Prüfung
    resp = test_client.post("/reports/demo.md/ask", data={"question": "Was?"})
    assert "Ollama-Modell" in resp.text


def test_ask_missing_report_404(client):
    test_client, _, config_path = client
    _set_ollama(config_path)
    assert test_client.post("/reports/fehlt.md/ask", data={"question": "Was?"}).status_code == 404


def test_ask_propagates_ollama_errors(client, monkeypatch):
    from app.ollama_client import OllamaError

    test_client, server_module, config_path = client
    _make_report(config_path)
    _set_ollama(config_path)

    class Boom:
        def __init__(self, *a, **k): pass

        def generate(self, *a, **k):
            raise OllamaError("Modell nicht installiert")

    monkeypatch.setattr(server_module, "OllamaClient", Boom)
    resp = test_client.post("/reports/demo.md/ask", data={"question": "Was?"})
    assert "nicht installiert" in resp.text


# ---------- Volltextsuche ----------


def test_search_finds_content_case_insensitive(client):
    test_client, _, config_path = client
    _make_report(config_path, "a.md", "# A\n\nMüllgebühren steigen.\n")
    _make_report(config_path, "b.md", "# B\n\nBaugebiet Nord wächst.\n")
    resp = test_client.get("/reports", params={"q": "müllgebühren"})
    assert "a.md" in resp.text
    assert "b.md" not in resp.text
    assert "Treffer" in resp.text


def test_search_filename_match(client):
    test_client, _, config_path = client
    _make_report(config_path, "2026-01-01_abfall.md", "# X\n\nBeliebiges.\n")
    resp = test_client.get("/reports", params={"q": "abfall"})
    assert "2026-01-01_abfall.md" in resp.text


def test_search_no_match_shows_hint(client):
    test_client, _, config_path = client
    _make_report(config_path)
    resp = test_client.get("/reports", params={"q": "xyz-nicht-vorhanden"})
    assert "Nichts gefunden" in resp.text


def test_search_empty_query_shows_list(client):
    test_client, _, config_path = client
    _make_report(config_path)
    resp = test_client.get("/reports")
    assert "demo.md" in resp.text
    assert "Treffer" not in resp.text
