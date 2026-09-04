import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    monkeypatch.setenv("RESEARCH_LXC_CONFIG", str(config_path))
    import app.web.server as server_module

    importlib.reload(server_module)
    return TestClient(server_module.app), server_module, config_path


# ---------- Ollama-Modell-Auswahl ----------


def test_ollama_models_endpoint_without_url_returns_error(client):
    test_client, _, _ = client
    resp = test_client.get("/api/ollama-models")
    assert resp.status_code == 200
    data = resp.json()
    assert data["models"] == []
    assert "Keine Ollama-URL" in data["error"]


def test_ollama_models_endpoint_uses_query_param(monkeypatch, client):
    test_client, server_module, _ = client

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"models": [{"name": "llama3.1:latest"}, {"name": "qwen2.5:14b"}]}

    monkeypatch.setattr(server_module.requests, "get", lambda url, timeout: FakeResponse())

    resp = test_client.get("/api/ollama-models?base_url=http://192.168.178.95:11434")
    assert resp.status_code == 200
    data = resp.json()
    assert data["models"] == ["llama3.1:latest", "qwen2.5:14b"]


def test_ollama_models_endpoint_handles_unreachable_host(monkeypatch, client):
    test_client, server_module, _ = client
    import requests

    def raise_conn_error(url, timeout):
        raise requests.ConnectionError("nope")

    monkeypatch.setattr(server_module.requests, "get", raise_conn_error)

    resp = test_client.get("/api/ollama-models?base_url=http://unreachable:11434")
    assert resp.status_code == 200
    data = resp.json()
    assert data["models"] == []
    assert "nicht erreichbar" in data["error"]


# ---------- Custom-Module-Verwaltung ----------


def test_modules_list_shows_empty_state(client):
    test_client, _, _ = client
    resp = test_client.get("/modules")
    assert resp.status_code == 200
    assert "Noch keine eigenen Module" in resp.text


def test_module_new_form_loads(client):
    test_client, _, _ = client
    resp = test_client.get("/modules/new")
    assert resp.status_code == 200
    assert "Neues Modul anlegen" in resp.text


def test_create_custom_module_success(client):
    test_client, server_module, config_path = client
    form = {
        "name": "Vereinsnachrichten",
        "enabled": "on",
        "search_type": "news",
        "queries": "Musterverein Neuigkeiten\nVereinsheim Region XY",
        "system_prompt": "Fasse kurz zusammen.",
    }
    resp = test_client.post("/modules/new", data=form, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/modules"

    from app.web import config_io

    cfg = config_io.load_raw_config(config_path)
    assert len(cfg["custom_modules"]) == 1
    cm = cfg["custom_modules"][0]
    assert cm["name"] == "vereinsnachrichten"  # slugifiziert (kleingeschrieben)
    assert cm["search_type"] == "news"
    assert cm["queries"] == ["Musterverein Neuigkeiten", "Vereinsheim Region XY"]
    assert cm["enabled"] is True


def test_create_custom_module_rejects_reserved_name(client):
    test_client, _, _ = client
    form = {"name": "all", "queries": "q"}
    resp = test_client.post("/modules/new", data=form)
    assert resp.status_code == 200
    assert "reserviert" in resp.text


def test_create_custom_module_rejects_empty_queries(client):
    test_client, _, _ = client
    form = {"name": "leeres modul", "queries": ""}
    resp = test_client.post("/modules/new", data=form)
    assert resp.status_code == 200
    assert "mindestens eine Suchanfrage" in resp.text


def test_create_custom_module_rejects_duplicate_name(client):
    test_client, _, _ = client
    form = {"name": "doppelt", "queries": "q1"}
    test_client.post("/modules/new", data=form)
    resp = test_client.post("/modules/new", data=form)
    assert "existiert bereits" in resp.text


def test_edit_custom_module_updates_queries(client):
    test_client, _, config_path = client
    test_client.post("/modules/new", data={"name": "test", "queries": "alt"})

    resp = test_client.post(
        "/modules/test/edit",
        data={"queries": "neu1\nneu2", "search_type": "web", "enabled": "on"},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    from app.web import config_io

    cfg = config_io.load_raw_config(config_path)
    cm = config_io.find_custom_module(cfg, "test")
    assert cm["queries"] == ["neu1", "neu2"]


def test_edit_nonexistent_module_returns_404(client):
    test_client, _, _ = client
    resp = test_client.get("/modules/does-not-exist/edit")
    assert resp.status_code == 404


def test_delete_custom_module_removes_it(client):
    test_client, _, config_path = client
    test_client.post("/modules/new", data={"name": "zu-loeschen", "queries": "q"})

    resp = test_client.post("/modules/zu_loeschen/delete", follow_redirects=False)
    assert resp.status_code == 303

    from app.web import config_io

    cfg = config_io.load_raw_config(config_path)
    assert config_io.find_custom_module(cfg, "zu_loeschen") is None


def test_trigger_run_accepts_custom_module_name(client, monkeypatch):
    test_client, server_module, _ = client
    test_client.post("/modules/new", data={"name": "eigenes", "queries": "q"})

    calls = []
    monkeypatch.setattr(server_module, "_execute_run", lambda name: calls.append(name))
    resp = test_client.post("/run/eigenes", follow_redirects=False)

    assert resp.status_code == 303
    assert calls == ["eigenes"]


def test_dashboard_shows_custom_module_card(client):
    test_client, _, _ = client
    test_client.post("/modules/new", data={"name": "sichtbares-modul", "queries": "q"})

    resp = test_client.get("/")
    assert "sichtbares_modul" in resp.text
    assert "eigenes Modul" in resp.text
