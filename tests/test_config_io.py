from app.web import config_io


def test_load_raw_config_returns_defaults_when_missing(tmp_path):
    cfg = config_io.load_raw_config(tmp_path / "does-not-exist.yaml")
    assert cfg["brave"]["max_requests_per_month"] == 950
    assert cfg["modules"]["competitor_analysis"]["enabled"] is True


def test_load_raw_config_merges_partial_file(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        "brave:\n  api_key: abc123\nmodules:\n  competitor_analysis:\n    branche: Metzgerei\n",
        encoding="utf-8",
    )
    cfg = config_io.load_raw_config(path)
    assert cfg["brave"]["api_key"] == "abc123"
    assert cfg["brave"]["max_requests_per_month"] == 950  # Default bleibt erhalten
    assert cfg["modules"]["competitor_analysis"]["branche"] == "Metzgerei"
    assert cfg["modules"]["news_digest"]["enabled"] is True  # unberührtes Modul bleibt Default


def test_save_and_reload_roundtrip(tmp_path):
    path = tmp_path / "config.yaml"
    cfg = config_io.load_raw_config(path)
    cfg["ollama"]["base_url"] = "http://192.168.178.95:11434"
    cfg["modules"]["news_digest"]["themen"] = ["Energie", "SmartHome"]

    config_io.save_raw_config(path, cfg)
    reloaded = config_io.load_raw_config(path)

    assert reloaded["ollama"]["base_url"] == "http://192.168.178.95:11434"
    assert reloaded["modules"]["news_digest"]["themen"] == ["Energie", "SmartHome"]


def test_mutating_loaded_config_never_pollutes_defaults(tmp_path):
    """Regressionstest: load_raw_config() gab früher bei fehlender Datei das
    globale DEFAULTS-Dict per Referenz zurück (und _deep_merge kopierte nur
    die oberste Ebene). Jeder Aufrufer, der das Ergebnis mutiert -- was
    settings_save() und module_new_save() im Web-Dashboard tun --, hat damit
    die Werksdefaults für den Rest des Prozesses dauerhaft verändert."""
    missing_path = tmp_path / "does-not-exist.yaml"

    cfg_a = config_io.load_raw_config(missing_path)
    cfg_a["ollama"]["base_url"] = "http://192.168.178.95:11434"
    cfg_a["modules"]["competitor_analysis"]["branche"] = "Sollte nicht durchsickern"
    cfg_a["custom_modules"].append({"name": "sollte-nicht-da-sein"})

    # Ein völlig unabhängiger zweiter Ladevorgang (z.B. eine andere Instanz,
    # ein anderer Request) darf davon nichts mitbekommen.
    cfg_b = config_io.load_raw_config(tmp_path / "andere-datei-die-nicht-existiert.yaml")
    assert cfg_b["ollama"]["base_url"] == ""
    assert cfg_b["modules"]["competitor_analysis"]["branche"] == ""
    assert cfg_b["custom_modules"] == []

    # Auch das globale DEFAULTS-Objekt selbst darf nie verändert worden sein.
    assert config_io.DEFAULTS["ollama"]["base_url"] == ""
    assert config_io.DEFAULTS["modules"]["competitor_analysis"]["branche"] == ""
    assert config_io.DEFAULTS["custom_modules"] == []
