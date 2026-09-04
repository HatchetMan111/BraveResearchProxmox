"""Schreibt den Recherche-Report als Markdown-Datei und verschickt ihn
optional per E-Mail, falls SMTP-Zugangsdaten konfiguriert sind."""

from __future__ import annotations

import io
import logging
import smtplib
from email.message import EmailMessage
from html import escape
from pathlib import Path

import markdown as md_lib
from xhtml2pdf import pisa

from .config import OutputConfig
from .pipeline import RunResult

logger = logging.getLogger(__name__)


def render_report_pdf(markdown_text: str, title: str = "Report") -> bytes:
    """Wandelt Report-Markdown in PDF-Bytes um (für Download/Weitergeben).
    Nutzt bewusst xhtml2pdf: reines Python, keine Systempakete nötig."""
    body_html = md_lib.markdown(markdown_text)
    # Einfaches, drucktaugliches Styling (xhtml2pdf versteht nur Basis-CSS).
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
body {{ font-family: Helvetica, Arial, sans-serif; font-size: 11pt; line-height: 1.5; color: #111; }}
h1 {{ font-size: 18pt; margin-bottom: 6pt; }}
h2 {{ font-size: 14pt; margin-top: 14pt; }}
h3 {{ font-size: 12pt; margin-top: 10pt; }}
a {{ color: #1d4ed8; }}
blockquote {{ border-left: 3pt solid #ccc; margin-left: 0; padding-left: 8pt; color: #444; }}
code {{ font-size: 9pt; }}
li {{ margin-bottom: 3pt; }}
</style></head><body><h1>{escape(title)}</h1>{body_html}</body></html>"""
    dest = io.BytesIO()
    result = pisa.CreatePDF(io.BytesIO(html.encode("utf-8")), dest=dest, encoding="utf-8")
    if result.err:
        raise RuntimeError(f"PDF-Erzeugung fehlgeschlagen ({result.err} Fehler).")
    return dest.getvalue()


def _sources_section(result: RunResult) -> str:
    """Baut den Quellen-Anhang: gruppiert nach Suchanfrage plus deduplizierte
    Link-Liste. Macht Reports deutlich größer und jede Aussage nachprüfbar."""
    sources = getattr(result, "sources", []) or []
    if not sources:
        return ""
    lines = ["", "---", "", "## Durchsuchte Quellen (Brave Search)", ""]
    lines.append(
        f"Aus {len(result.queries_run)} Suchanfrage(n) wurden "
        f"{len(sources)} unterschiedliche Quellen in den Report einbezogen:"
    )
    lines.append("")
    by_query: dict[str, list[dict]] = {}
    for s in sources:
        by_query.setdefault(s.get("query", "?"), []).append(s)
    for query, items in by_query.items():
        lines.append(f"### Suche: „{query}“")
        lines.append("")
        for s in items:
            title = s.get("title") or s.get("url", "")
            url = s.get("url", "")
            snippet = (s.get("snippet") or "").strip()
            age = s.get("age")
            age_str = f" — {age}" if age else ""
            if url:
                lines.append(f"- [{title}]({url}){age_str}")
            else:
                lines.append(f"- {title}{age_str}")
            if snippet:
                short = snippet if len(snippet) <= 300 else snippet[:300] + "…"
                lines.append(f"  - {short}")
        lines.append("")
    lines += ["## Alle Links im Überblick", ""]
    for s in sources:
        title = s.get("title") or s.get("url", "")
        url = s.get("url", "")
        if url:
            lines.append(f"- [{title}]({url})")
        else:
            lines.append(f"- {title}")
    lines.append("")
    return "\n".join(lines)


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
Ausgeführte Suchanfragen: {len(result.queries_run)}/{len(result.queries_planned)}
Gespeichert lokal unter: `{path.name}` (Ordner `{reports_dir.name}/`)
---
{result.content}
{_sources_section(result)}
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
