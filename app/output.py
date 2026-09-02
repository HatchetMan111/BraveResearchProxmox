"""Schreibt den Recherche-Report als Markdown-Datei und verschickt ihn
optional per E-Mail, falls SMTP-Zugangsdaten konfiguriert sind."""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from pathlib import Path

from .config import OutputConfig
from .pipeline import RunResult

logger = logging.getLogger(__name__)


def write_report(result: RunResult, output_cfg: OutputConfig) -> Path:
    reports_dir = Path(output_cfg.reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)

    timestamp = result.started_at.strftime("%Y-%m-%d_%H%M")
    filename = f"{timestamp}_{result.module_name}.md"
    path = reports_dir / filename

    status_line = ""
    if result.budget_status:
        status_line = (
            f"Brave-Budget diesen Monat: {result.budget_status.used}/"
            f"{result.budget_status.limit} Requests verbraucht "
            f"({result.budget_status.remaining} verbleibend)."
        )

    warning = ""
    if result.budget_exhausted:
        warning = (
            "\n> ⚠️ **Unvollständiger Lauf:** Das Monatsbudget wurde während "
            f"der Recherche erschöpft. {len(result.queries_skipped)} von "
            f"{len(result.queries_planned)} geplanten Suchanfragen wurden "
            "nicht ausgeführt.\n"
        )

    content = f"""# Report: {result.module_name}

Erstellt: {result.started_at.isoformat()}
{status_line}
{warning}
---

{result.content}
"""
    path.write_text(content, encoding="utf-8")
    logger.info("Report geschrieben: %s", path)
    return path


def send_report_email(result: RunResult, report_path: Path, output_cfg: OutputConfig) -> bool:
    """Verschickt den Report per E-Mail. Gibt False zurück (statt zu werfen),
    wenn kein SMTP konfiguriert ist -- E-Mail-Versand ist optional."""
    smtp = output_cfg.smtp
    if not smtp.host or not output_cfg.email_to:
        logger.info("Kein SMTP konfiguriert -- Report wird nur lokal abgelegt.")
        return False

    msg = EmailMessage()
    msg["Subject"] = f"Recherche-Report: {result.module_name} ({result.started_at.date()})"
    msg["From"] = output_cfg.email_from or smtp.user or "research-lxc@localhost"
    msg["To"] = output_cfg.email_to
    msg.set_content(report_path.read_text(encoding="utf-8"))

    with smtplib.SMTP(smtp.host, smtp.port, timeout=30) as server:
        if smtp.use_tls:
            server.starttls()
        if smtp.user:
            server.login(smtp.user, smtp.password)
        server.send_message(msg)

    logger.info("Report per E-Mail an %s versendet.", output_cfg.email_to)
    return True
