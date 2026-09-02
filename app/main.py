"""CLI: python -m app.main --module competitor_analysis --config config.yaml

Wird vom systemd-Timer periodisch aufgerufen (siehe deploy/research-lxc.timer),
kann aber auch manuell zum Testen ausgeführt werden.
"""

from __future__ import annotations

import argparse
import logging
import sys

from . import output, pipeline
from .budget_tracker import BudgetExceededError
from .config import load_config
from .modules import MODULES
from .ollama_client import OllamaError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Recherche-LXC: Brave Search + externes Ollama")
    parser.add_argument(
        "--module", required=True, choices=sorted(MODULES.keys()), help="Auszuführendes Modul"
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

    try:
        result = pipeline.run_module(args.module, config)
    except ValueError as exc:
        log.error("%s", exc)
        return 2
    except BudgetExceededError as exc:
        log.error("Kein Budget mehr verfügbar, Lauf abgebrochen: %s", exc)
        return 3
    except OllamaError as exc:
        log.error("Ollama-Fehler: %s", exc)
        return 4

    report_path = output.write_report(result, config.output)
    log.info("Report: %s", report_path)

    if result.budget_exhausted:
        log.warning(
            "Lauf war unvollständig: %d/%d Queries übersprungen (Budget erschöpft).",
            len(result.queries_skipped),
            len(result.queries_planned),
        )

    if not args.no_email:
        output.send_report_email(result, report_path, config.output)

    return 0


if __name__ == "__main__":
    sys.exit(main())
