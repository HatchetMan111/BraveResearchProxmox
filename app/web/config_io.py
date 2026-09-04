"""Liest/schreibt config.yaml als einfaches verschachteltes Dict.

Bewusst getrennt von app.config.load_config(): Die Pipeline arbeitet mit
typisierten Dataclasses, aber die Web-UI muss beliebige, freie Modul-Optionen
(z.B. `themen`-Liste bei news_digest) roundtrip-sicher als Formular anzeigen
und zurückschreiben können -- dafür ist ein simples Dict flexibler.

Hinweis: YAML-Kommentare in config.example.yaml gehen beim Speichern über
die UI verloren (PyYAML schreibt reine Werte). Das ist ein bewusster
Trade-off für die MVP-Version.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml

DEFAULTS: dict[str, Any] = {
    "brave": {
        "api_key": "",
        "base_url": "https://api.search.brave.com/res/v1",
        "max_requests_per_month": 950,
    },
    "ollama": {
        "base_url": "",
        "model": "",
        "timeout_seconds": 180,
    },
    "cache": {"db_path": "data/cache.db", "ttl_hours": 24},
    "budget": {"db_path": "data/budget.db"},
    "output": {
        "reports_dir": "reports",
        "email_to": "",
        "email_from": "",
        "smtp": {"host": "", "port": 587, "user": "", "password": "", "use_tls": True},
    },
    "modules": {
        "competitor_analysis": {"enabled": True, "branche": "", "region": "", "queries_extra": []},
        "news_digest": {
            "enabled": True,
            "region": "",
            "themen": [],
            "stil": "sachlich, lokal, freundlich",
            "queries_extra": [],
        },
    },
    "custom_modules": [],
}


def _deep_merge(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_raw_config(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        return copy.deepcopy(DEFAULTS)
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return _deep_merge(DEFAULTS, raw)


def save_raw_config(path: str | Path, config: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def upsert_custom_module(config: dict[str, Any], module: dict[str, Any]) -> None:
    """Fügt ein eigenes Modul hinzu oder ersetzt eines mit demselben Namen."""
    modules = config.setdefault("custom_modules", [])
    name = module["name"]
    for i, m in enumerate(modules):
        if m.get("name") == name:
            modules[i] = module
            return
    modules.append(module)


def delete_custom_module(config: dict[str, Any], name: str) -> bool:
    modules = config.get("custom_modules", [])
    before = len(modules)
    config["custom_modules"] = [m for m in modules if m.get("name") != name]
    return len(config["custom_modules"]) < before


def find_custom_module(config: dict[str, Any], name: str) -> dict[str, Any] | None:
    for m in config.get("custom_modules", []):
        if m.get("name") == name:
            return m
    return None
