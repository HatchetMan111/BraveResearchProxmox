"""Tests für PDF-Export und Druckansicht der Reports."""

import importlib

import pytest
from fastapi.testclient import TestClient

from app.output import render_report_pdf


def test_render_report_pdf_german_umlauts_and_links():
    md = "# Müllabfuhr Musterstadt\n\nGrüße, Äpfel, Öl -- siehe [Quelle](https://example.de/a).\n"
    pdf = render_report_pdf(md, title="2026-01-01_test")
    assert pdf[:4] == b"%PDF"
    assert len(pdf) > 1000


@pytest.fixture()
def client(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    monkeypatch.setenv("RESEARCH_LXC_CONFIG", str(config_path))
    import app.web.server as server_module

    importlib.reload(server_module)
    return TestClient(server_module.app), server_module, config_path


def _make_report(config_path, name="demo.md"):
    reports_dir = config_path.parent / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / name).write_text("# Titel\n\nInhalt mit [Link](https://example.de/).", encoding="utf-8")


def test_pdf_download_returns_pdf(client):
    test_client, _, config_path = client
    _make_report(config_path)
    resp = test_client.get("/reports/demo.md/pdf")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content[:4] == b"%PDF"
    assert 'filename="demo.pdf"' in resp.headers["content-disposition"]


def test_pdf_rejects_non_markdown(client):
    test_client, _, _ = client
    assert test_client.get("/reports/notes.txt/pdf").status_code == 400


def test_pdf_404_when_missing(client):
    test_client, _, _ = client
    assert test_client.get("/reports/fehlt.md/pdf").status_code == 404


def test_pdf_rejects_path_traversal(client):
    test_client, _, config_path = client
    _make_report(config_path)
    assert test_client.get("/reports/../config.yaml/pdf").status_code in (400, 404)


def test_report_page_has_print_and_pdf_buttons(client):
    test_client, _, config_path = client
    _make_report(config_path)
    resp = test_client.get("/reports/demo.md")
    assert resp.status_code == 200
    assert "/reports/demo.md/pdf" in resp.text
    assert "window.print()" in resp.text


def test_reports_list_links_pdf(client):
    test_client, _, config_path = client
    _make_report(config_path)
    resp = test_client.get("/reports")
    assert "/reports/demo.md/pdf" in resp.text
