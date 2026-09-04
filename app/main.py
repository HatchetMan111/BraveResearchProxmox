"""CLI: python -m app.main --module competitor_analysis --config config.yaml
       python -m app.main --module all --config config.yaml

Wird vom systemd-Timer periodisch aufgerufen (siehe deploy/research-lxc-all.timer),
kann aber auch manuell zum Testen ausgeführt werden. '--module all' führt alle
aktivierten Module nacheinander aus (eingebaute + über das Dashboard angelegte
eigene Module) -- neue Module brauchen dadurch keinen eigenen systemd-Timer.
"""

from __future__ import annotations

import argparse
import logging
import sys

from . import output, pipeline
from .budget_tracker import BudgetExceededError
from .config import AppConfig, load_config
from .ollama_client import OllamaError


def _run_one(module_name: str, config: AppConfig, log: logging.Logger, send_email: bool) -> int:
    try:
        result = pipeline.run_module(module_name, config)
    except ValueError as exc:
        log.error("%s", exc)
        return 2
    except BudgetExceededError as exc:
        log.error("Kein Budget mehr verfügbar, Lauf '%s' abgebrochen: %s", module_name, exc)
        return 3
    except OllamaError as exc:
        log.error("Ollama-Fehler bei Modul '%s': %s", module_name, exc)
        return 4

    report_path = output.write_report(result, config.output)
    log.info("Modul '%s' -- Report: %s", module_name, report_path)

    if result.budget_exhausted:
        log.warning(
            "Modul '%s' war unvollständig: %d/%d Queries übersprungen (Budget erschöpft).",
            module_name,
            len(result.queries_skipped),
            len(result.queries_planned),
        )

    if send_email:
        output.send_report_email(result, report_path, config.output)

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Recherche-LXC: Brave Search + externes Ollama")
    parser.add_argument(
        "--module",
        required=True,
        help="Auszuführendes Modul (Name aus config.yaml) oder 'all' für alle aktivierten Module",
    )
    parser.add_argument("--config", default="config.yaml", help="Pfad zur config.yaml")
    parser.add_argument(
        "--no-email", action="store_true", help="E-Mail-Versand für diesen Lauf unterdrücken"
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug-Logging aktivieren")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    log = logging.getLogger("main")

    try:
        config = load_config(args.config)
    except (ValueError, FileNotFoundError) as exc:
        log.error("Konfigurationsfehler: %s", exc)
        return 2

    if args.module == "all":
        module_names = pipeline.list_available_modules(config)
        if not module_names:
            log.warning("Keine aktivierten Module gefunden -- nichts zu tun.")
            return 0
        exit_codes = [
            _run_one(name, config, log, send_email=not args.no_email) for name in module_names
        ]
        return max(exit_codes)

    return _run_one(args.module, config, log, send_email=not args.no_email)


if __name__ == "__main__":
    sys.exit(main())
