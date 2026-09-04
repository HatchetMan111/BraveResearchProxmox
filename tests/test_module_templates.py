"""Tests für den Vorlagen-Katalog (app.modules.templates) + Routen."""

import importlib

import pytest
from fastapi.testclient import TestClient

from app.modules.templates import TEMPLATES, get_template, render_queries


# ---------- Katalog-Konsistenz ----------


def test_template_keys_unique():
    keys = [t["key"] for t in TEMPLATES]
    assert len(keys) == len(set(keys)) >= 8


def test_templates_have_required_topics():
    keys = {t["key"] for t in TEMPLATES}
    assert {"job_markt", "immobilien", "veranstaltungen", "kommunalpolitik",
            "verkehr", "energie", "gesundheit", "bildung"} <= keys


def test_all_placeholders_defined():
    import re
    for t in TEMPLATES:
        fields = {f["name"] for f in t["fields"]}
        assert t["search_type"] in ("web", "news"), t["key"]
        assert len(t["queries"]) >= 2, t["key"]
        assert t["system_prompt"].strip(), t["key"]
        for q in t["queries"]:
            for ph in re.findall(r"\{([a-z_]+)\}", q):
                assert ph in fields, f"{t['key']}: {{{ph}}} nicht in fields"


def test_every_template_renders_with_sample_values():
    sample = {"region": "Musterregion", "stadt": "Musterstadt", "branche": "Handwerk"}
    for t in TEMPLATES:
        queries = render_queries(t, sample)
        assert len(queries) >= 2, t["key"]
        assert not any("{" in q or "}" in q for q in queries), t["key"]


def test_get_template_unknown_returns_none():
    assert get_template("gibts-nicht") is None


# ---------- Rendering ----------


def test_render_skips_queries_with_empty_optional_field():
    t = get_template("job_markt")
    queries = render_queries(t, {"region": "Musterregion", "stadt": "", "branche": ""})
    assert queries  # Pflichtfeld region reicht
    assert all("{" not in q for q in queries)
    assert not any("  " in q for q in queries)


def test_render_missing_required_raises():
    t = get_template("job_markt")
    with pytest.raises(ValueError, match="Region"):
        render_queries(t, {"region": "", "stadt": "X", "branche": ""})


# ---------- Web-Routen ----------


@pytest.fixture()
def client(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    monkeypatch.setenv("RESEARCH_LXC_CONFIG", str(config_path))
    import app.web.server as server_module

    importlib.reload(server_module)
    return TestClient(server_module.app), server_module, config_path


def test_modules_page_lists_templates(client):
    test_client, _, _ = client
    resp = test_client.get("/modules")
    assert resp.status_code == 200
    assert "Aus Vorlage anlegen" in resp.text
    assert "Arbeitsmarkt" in resp.text


def test_template_form_unknown_key_404(client):
    test_client, _, _ = client
    assert test_client.get("/modules/from-template/nope").status_code == 404
    assert test_client.post("/modules/from-template/nope", data={}).status_code == 404


def test_template_form_renders_fields(client):
    test_client, _, _ = client
    resp = test_client.get("/modules/from-template/job_markt")
    assert resp.status_code == 200
    assert "Region / Landkreis" in resp.text
    assert "Stellenangebote" in resp.text or "query-preview" in resp.text


def test_create_module_from_template(client):
    test_client, _, config_path = client
    resp = test_client.post("/modules/from-template/job_markt", data={
        "name": "Stellenmarkt",
        "enabled": "on",
        "field_region": "Musterregion",
        "field_stadt": "Musterstadt",
        "field_branche": "",
    }, follow_redirects=False)
    assert resp.status_code == 303

    from app.web import config_io

    cm = config_io.find_custom_module(config_io.load_raw_config(config_path), "stellenmarkt")
    assert cm is not None
    assert cm["search_type"] == "web"
    assert any("Musterregion" in q for q in cm["queries"])
    assert not any("{" in q for q in cm["queries"])
    assert "Stellenmarkt" in cm["system_prompt"] or "Arbeitsmarkt" in cm["system_prompt"]


def test_create_from_template_missing_required_shows_error(client):
    test_client, _, _ = client
    resp = test_client.post("/modules/from-template/job_markt", data={
        "name": "Stellenmarkt", "field_region": "", "field_stadt": "X",
    })
    assert resp.status_code == 200
    assert "Region" in resp.text  # Fehlermeldung nennt das Pflichtfeld


def test_create_from_template_duplicate_name_shows_error(client):
    test_client, _, _ = client
    data = {"name": "doppelt", "field_region": "R", "field_stadt": "S"}
    test_client.post("/modules/from-template/job_markt", data=data)
    resp = test_client.post("/modules/from-template/immobilien", data={
        "name": "doppelt", "field_region": "R", "field_stadt": "S"})
    assert "existiert bereits" in resp.text


def test_created_template_module_runs_through_pipeline(client, monkeypatch):
    """Aus Vorlage erstelltes Modul ist sofort lauffähig (Trigger akzeptiert es)."""
    test_client, server_module, _ = client
    test_client.post("/modules/from-template/verkehr", data={
        "name": "stau", "field_region": "Musterregion",
    })
    calls = []
    monkeypatch.setattr(server_module, "_execute_run", lambda name: calls.append(name))
    resp = test_client.post("/run/stau", follow_redirects=False)
    assert resp.status_code == 303
    assert calls == ["stau"]
