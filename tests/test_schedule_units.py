"""Tests für app.schedule_units (Zeitplan pro Modul -> systemd-Timer)."""

import importlib

import pytest
import yaml
from fastapi.testclient import TestClient

from app import schedule_units as su


def _raw(**overrides):
    base = {
        "schedule": {"enabled": True, "time": "06:00", "frequency": "daily", "weekday": "mon"},
        "modules": {
            "competitor_analysis": {"enabled": True},
            "news_digest": {"enabled": True},
        },
        "custom_modules": [],
    }
    base.update(overrides)
    return base


# ---------- OnCalendar-Abbildung ----------


def test_oncalendar_daily():
    sched = {"auto": True, "time": "07:30", "frequency": "daily", "weekday": "mon"}
    assert su.oncalendar(sched) == "*-*-* 07:30:00"


def test_oncalendar_weekly():
    sched = {"auto": True, "time": "08:15", "frequency": "weekly", "weekday": "fri"}
    assert su.oncalendar(sched) == "Fri *-*-* 08:15:00"


def test_oncalendar_manual_is_none():
    assert su.oncalendar({"auto": False, "time": "06:00", "frequency": "daily", "weekday": "mon"}) is None


# ---------- Effektiver Zeitplan ----------


def test_effective_uses_global_default():
    eff = su.effective_schedule(_raw(), {"enabled": True})
    assert eff == {"auto": True, "time": "06:00", "frequency": "daily", "weekday": "mon",
                   "custom": False, "human": "Standard: täglich 06:00 Uhr"}


def test_effective_custom_overrides():
    mod = {"enabled": True, "schedule": {"use_default": False, "enabled": True,
                                         "time": "07:30", "frequency": "weekly", "weekday": "fri"}}
    eff = su.effective_schedule(_raw(), mod)
    assert eff["custom"] is True
    assert eff["human"] == "wöchentlich (Fr 07:30 Uhr)"
    assert su.oncalendar(eff) == "Fri *-*-* 07:30:00"


def test_effective_manual():
    mod = {"enabled": True, "schedule": {"use_default": False, "enabled": False,
                                         "time": "07:30", "frequency": "daily", "weekday": "mon"}}
    eff = su.effective_schedule(_raw(), mod)
    assert eff["auto"] is False
    assert eff["human"] == "nur manuell"


def test_effective_invalid_values_fall_back():
    mod = {"enabled": True, "schedule": {"use_default": False, "enabled": True,
                                         "time": "99:99", "frequency": "monthly", "weekday": "funday"}}
    eff = su.effective_schedule(_raw(), mod)
    assert eff["time"] == "06:00"
    assert eff["frequency"] == "daily"
    assert eff["weekday"] == "mon"


# ---------- Plan ----------


def test_compute_plan_skips_disabled_and_manual():
    raw = _raw()
    raw["modules"]["news_digest"] = {"enabled": False}
    raw["custom_modules"] = [
        {"name": "eigenes", "enabled": True,
         "schedule": {"use_default": False, "enabled": False, "time": "09:00",
                      "frequency": "daily", "weekday": "mon"}},
        {"name": "wochenblick", "enabled": True,
         "schedule": {"use_default": False, "enabled": True, "time": "08:00",
                      "frequency": "weekly", "weekday": "mon"}},
    ]
    plan = su.compute_plan(raw)
    assert set(plan) == {"research-lxc-mod-competitor_analysis.timer",
                         "research-lxc-mod-wochenblick.timer"}
    assert "OnCalendar=*-*-* 06:00:00" in plan["research-lxc-mod-competitor_analysis.timer"]
    assert "OnCalendar=Mon *-*-* 08:00:00" in plan["research-lxc-mod-wochenblick.timer"]
    assert "Unit=research-lxc@wochenblick.service" in plan["research-lxc-mod-wochenblick.timer"]


# ---------- Datei-Sync ----------


def test_sync_files_writes_updates_removes_stale(tmp_path):
    plan = {"research-lxc-mod-a.timer": "[Timer]\nOnCalendar=*-*-* 06:00:00\n"}
    stale = tmp_path / "research-lxc-mod-alt.timer"
    stale.write_text("alt", encoding="utf-8")
    keep = tmp_path / "research-lxc-web.service"
    keep.write_text("fremd", encoding="utf-8")

    res = su.sync_files(tmp_path, plan)
    assert res["written"] == ["research-lxc-mod-a.timer"]
    assert res["removed"] == ["research-lxc-mod-alt.timer"]
    assert res["changed"] is True
    assert keep.read_text(encoding="utf-8") == "fremd"  # Fremddatei bleibt

    res2 = su.sync_files(tmp_path, plan)
    assert res2["changed"] is False  # idempotent


# ---------- systemd-Anwendung (gemockt) ----------


def test_apply_systemd_with_plan_disables_all_timer(monkeypatch):
    calls = []
    monkeypatch.setattr(su.subprocess, "run", lambda *a, **k: calls.append(a[0]))
    actions = su.apply_systemd(["research-lxc-mod-a.timer"], ["research-lxc-mod-alt.timer"])
    flat = [" ".join(c) for c in calls]
    assert any("daemon-reload" in c for c in flat)
    assert any("enable --now research-lxc-mod-a.timer" in c for c in flat)
    assert any("disable --now research-lxc-mod-alt.timer" in c for c in flat)
    assert any("disable --now research-lxc-all.timer" in c for c in flat)
    assert actions["enabled"] == ["research-lxc-mod-a.timer"]


def test_apply_systemd_empty_plan_keeps_all_timer(monkeypatch):
    calls = []
    monkeypatch.setattr(su.subprocess, "run", lambda *a, **k: calls.append(a[0]))
    actions = su.apply_systemd([], [])
    flat = [" ".join(c) for c in calls]
    assert any("enable --now research-lxc-all.timer" in c for c in flat)
    assert actions["enabled"] == ["research-lxc-all.timer"]


# ---------- CLI ----------


def test_main_dry_run_lists_plan(tmp_path, capsys):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.safe_dump(_raw()), encoding="utf-8")
    assert su.main(["--config", str(cfg), "--units-dir", str(tmp_path / "units")]) == 0
    out = capsys.readouterr().out
    assert "research-lxc-mod-competitor_analysis.timer" in out
    assert not (tmp_path / "units").exists()  # dry-run schreibt nichts


def test_main_apply_writes_and_configures_systemd(tmp_path, monkeypatch):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.safe_dump(_raw()), encoding="utf-8")
    units = tmp_path / "units"
    calls = []
    monkeypatch.setattr(su.subprocess, "run", lambda *a, **k: calls.append(a[0]))
    assert su.main(["--config", str(cfg), "--units-dir", str(units), "--apply"]) == 0
    assert (units / "research-lxc-mod-news_digest.timer").exists()
    assert any("daemon-reload" in " ".join(c) for c in calls)


def test_main_missing_config_returns_2(tmp_path):
    assert su.main(["--config", str(tmp_path / "gibts-nicht.yaml")]) == 2


# ---------- Web-Integration ----------


@pytest.fixture()
def client(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    monkeypatch.setenv("RESEARCH_LXC_CONFIG", str(config_path))
    import app.web.server as server_module

    importlib.reload(server_module)
    return TestClient(server_module.app), server_module, config_path


def _base_settings_form(**extra):
    form = {
        "brave_api_key": "dummy-key",
        "brave_max_requests_per_month": "800",
        "ollama_base_url": "http://192.168.178.95:11434",
        "ollama_model": "llama3.1",
        "competitor_enabled": "on",
        "competitor_branche": "Metzgerei",
        "competitor_region": "Musterregion",
        "news_enabled": "on",
        "news_region": "Musterregion",
        "news_themen": "",
        "news_stil": "sachlich",
        "email_to": "",
        "email_from": "",
        "smtp_host": "",
        "smtp_port": "587",
        "smtp_user": "",
        "smtp_password": "",
    }
    form.update(extra)
    return form


def test_settings_saves_per_module_schedule(client):
    test_client, _, config_path = client
    resp = test_client.post("/settings", data=_base_settings_form(
        competitor_schedule_custom="on",
        competitor_schedule_enabled="on",
        competitor_schedule_time="07:30",
        competitor_schedule_frequency="weekly",
        competitor_schedule_weekday="fri",
    ))
    assert resp.status_code == 200

    from app.web import config_io

    saved = config_io.load_raw_config(config_path)
    comp_sched = saved["modules"]["competitor_analysis"]["schedule"]
    assert comp_sched == {"use_default": False, "enabled": True, "time": "07:30",
                          "frequency": "weekly", "weekday": "fri"}
    # News-Modul ohne Zeitplan-Felder -> Standard bleibt
    assert saved["modules"]["news_digest"]["schedule"]["use_default"] is True


def test_settings_without_schedule_fields_keeps_existing(client):
    test_client, _, config_path = client
    test_client.post("/settings", data=_base_settings_form())  # ohne Zeitplan-Felder
    from app.web import config_io

    saved = config_io.load_raw_config(config_path)
    assert saved["modules"]["competitor_analysis"]["schedule"]["use_default"] is True


def test_create_module_with_own_schedule(client):
    test_client, _, config_path = client
    resp = test_client.post("/modules/new", data={
        "name": "wochenblick", "enabled": "on", "search_type": "news",
        "queries": "Thema Region",
        "schedule_custom": "on", "schedule_enabled": "on",
        "schedule_time": "08:00", "schedule_frequency": "weekly", "schedule_weekday": "mon",
    }, follow_redirects=False)
    assert resp.status_code == 303

    from app.web import config_io

    cm = config_io.find_custom_module(config_io.load_raw_config(config_path), "wochenblick")
    assert cm["schedule"]["time"] == "08:00"
    assert cm["schedule"]["frequency"] == "weekly"


def test_dashboard_and_modules_show_schedule(client):
    test_client, _, _ = client
    test_client.post("/modules/new", data={"name": "sichtbar", "queries": "q"})
    resp = test_client.get("/")
    assert "Zeitplan:" in resp.text
    assert "Standard: täglich 06:00 Uhr" in resp.text
    resp = test_client.get("/modules")
    assert "Zeitplan:" in resp.text
