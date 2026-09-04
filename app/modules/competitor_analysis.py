"""Modul: lokale Konkurrenzanalyse.

Config-Optionen (unter modules.competitor_analysis.* in config.yaml):
    branche:       z.B. "Ihre Branche"
    region:        z.B. "Ihre Region"
    queries_extra: optionale Liste zusätzlicher, frei formulierter Queries

Bewusst wenige, breite Brave-Queries -- die Detailarbeit (neue Anbieter,
Preisänderungen, auffällige Angebote herausfiltern) übernimmt Ollama anhand
der gesammelten Rohdaten, nicht zusätzliche Brave-Anfragen.
"""

from __future__ import annotations

from typing import Any

from ..brave_client import SearchResult

NAME = "competitor_analysis"
SEARCH_TYPE = "web"


def build_queries(options: dict[str, Any]) -> list[str]:
    branche = options["branche"]
    region = options["region"]
    queries = [
        f"{branche} {region}",
        f"{branche} Anbieter {region}",
        f"{branche} Preise {region}",
    ]
    queries.extend(options.get("queries_extra", []))
    # Dedupe unter Beibehaltung der Reihenfolge
    seen: set[str] = set()
    unique = []
    for q in queries:
        if q not in seen:
            seen.add(q)
            unique.append(q)
    return unique


def build_prompt(
    query_results: list[tuple[str, list[SearchResult]]], options: dict[str, Any]
) -> tuple[str, str]:
    branche = options["branche"]
    region = options["region"]

    system = (
        "Du bist Marktanalyst für ein regionales Dienstleistungsunternehmen. "
        "Du erhältst rohe Web-Suchergebnisse und erstellst daraus einen "
        "sachlichen, ausführlichen Konkurrenzanalyse-Bericht auf Deutsch. "
        "Erfinde keine Fakten, die nicht in den Suchergebnissen stehen. "
        "Wenn ein Ergebnis nicht eindeutig relevant ist, ignoriere es. "
        "Verlinke jeden genannten Anbieter/jede Quelle als Markdown-Link "
        "[Name](URL) mit der exakten URL aus den Rohdaten."
    )

    blocks = []
    for query, results in query_results:
        lines = [f"Suchanfrage: \"{query}\""]
        for r in results:
            lines.append(f"- {r.title} ({r.url}): {r.snippet}")
        blocks.append("\n".join(lines))
    raw_data = "\n\n".join(blocks) if blocks else "(keine Suchergebnisse)"

    user = f"""Branche: {branche}
Region: {region}

Rohdaten aus der Websuche:
{raw_data}

Erstelle daraus einen ausführlichen Konkurrenzanalyse-Bericht mit folgender Struktur:
1. Zusammenfassung (3-5 Sätze, wichtigste Erkenntnisse vorweg)
2. Identifizierte Anbieter/Wettbewerber als Liste: JEDEN Anbieter mit
   Markdown-Link [Anbietername](URL) plus 1-2 Sätzen Beschreibung
   (Leistung, Besonderheit, Region). Nutze dafür alle relevanten Quellen
   aus den Rohdaten -- lasse keinen relevanten Treffer weg.
3. Auffällige Preise oder Angebote, falls in den Daten erkennbar
   (ebenfalls mit Quellen-Link pro Aussage)
4. Neue Entwicklungen / Veränderungen (was ist neu, was hat sich geändert?)
5. Fazit mit kurzer Einschätzung für das eigene Unternehmen

Schreibe verständlich, ohne Fachjargon, ausführlich (ca. 1-2 DIN-A4-Seiten).
Jede Tatsachenbehauptung braucht einen Quellen-Link aus den Rohdaten."""

    return system, user
