"""Lädt die YAML-Konfiguration und erlaubt Overrides per Umgebungsvariable.

Umgebungsvariablen haben Vorrang vor der YAML-Datei, damit sensible Werte
(API-Keys, SMTP-Passwörter) nicht zwingend in der Config-Datei liegen müssen:

    BRAVE_API_KEY, OLLAMA_BASE_URL, OLLAMA_MODEL, SMTP_PASSWORD
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class BraveConfig:
    api_key: str
    base_url: str = "https://api.search.brave.com/res/v1"
    max_requests_per_month: int = 950  # Sicherheitspuffer unter dem 1000er-Gratislimit


@dataclass
class OllamaConfig:
    base_url: str
    model: str
    timeout_seconds: int = 180


@dataclass
class CacheConfig:
    db_path: str = "data/cache.db"
    ttl_hours: int = 24


@dataclass
class BudgetConfig:
    db_path: str = "data/budget.db"


@dataclass
class SmtpConfig:
    host: str = ""
    port: int = 587
    user: str = ""
    password: str = ""
    use_tls: bool = True


@dataclass
class OutputConfig:
    reports_dir: str = "reports"
    email_to: str = "info@lichtvalleyapps.de"
    email_from: str = ""
    smtp: SmtpConfig = field(default_factory=SmtpConfig)


@dataclass
class ModuleConfig:
    """Freie Konfiguration pro Modul (Branche, Region, Stil, Themen, ...)."""

    enabled: bool = True
    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class AppConfig:
    brave: BraveConfig
    ollama: OllamaConfig
    cache: CacheConfig
    budget: BudgetConfig
    output: OutputConfig
    modules: dict[str, ModuleConfig]
    base_dir: Path


def _apply_env_overrides(raw: dict[str, Any]) -> dict[str, Any]:
    if val := os.environ.get("BRAVE_API_KEY"):
        raw.setdefault("brave", {})["api_key"] = val
    if val := os.environ.get("OLLAMA_BASE_URL"):
        raw.setdefault("ollama", {})["base_url"] = val
    if val := os.environ.get("OLLAMA_MODEL"):
        raw.setdefault("ollama", {})["model"] = val
    if val := os.environ.get("SMTP_PASSWORD"):
        raw.setdefault("output", {}).setdefault("smtp", {})["password"] = val
    return raw


def load_config(path: str | Path) -> AppConfig:
    path = Path(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raw = _apply_env_overrides(raw)
    base_dir = path.resolve().parent

    brave_raw = raw.get("brave", {})
    if not brave_raw.get("api_key"):
        raise ValueError(
            "Kein Brave API Key gesetzt (config.yaml: brave.api_key oder "
            "Umgebungsvariable BRAVE_API_KEY)."
        )
    brave = BraveConfig(**brave_raw)

    ollama_raw = raw.get("ollama", {})
    if not ollama_raw.get("base_url") or not ollama_raw.get("model"):
        raise ValueError(
            "Ollama base_url und model müssen in config.yaml gesetzt sein."
        )
    ollama = OllamaConfig(**ollama_raw)

    cache = CacheConfig(**raw.get("cache", {}))
    budget = BudgetConfig(**raw.get("budget", {}))

    output_raw = dict(raw.get("output", {}))
    smtp_raw = output_raw.pop("smtp", {})
    output = OutputConfig(smtp=SmtpConfig(**smtp_raw), **output_raw)

    modules_raw = raw.get("modules", {}) or {}
    modules = {
        name: ModuleConfig(
            enabled=cfg.get("enabled", True),
            options={k: v for k, v in cfg.items() if k != "enabled"},
        )
        for name, cfg in modules_raw.items()
    }

    # Relative Pfade werden relativ zur Config-Datei aufgelöst, damit der
    # Installer die App unabhängig vom Arbeitsverzeichnis starten kann.
    cache.db_path = str(_resolve(base_dir, cache.db_path))
    budget.db_path = str(_resolve(base_dir, budget.db_path))
    output.reports_dir = str(_resolve(base_dir, output.reports_dir))

    return AppConfig(
        brave=brave,
        ollama=ollama,
        cache=cache,
        budget=budget,
        output=output,
        modules=modules,
        base_dir=base_dir,
    )


def _resolve(base_dir: Path, value: str) -> Path:
    p = Path(value)
    return p if p.is_absolute() else (base_dir / p)
