"""Modul: lokale Konkurrenzanalyse.

Config-Optionen (unter modules.competitor_analysis.* in config.yaml):
    branche:       z.B. "SmartHome Integration"
    region:        z.B. "Main-Tauber-Kreis"
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
        "sachlichen, kurzen Konkurrenzanalyse-Bericht auf Deutsch. "
        "Erfinde keine Fakten, die nicht in den Suchergebnissen stehen. "
        "Wenn ein Ergebnis nicht eindeutig relevant ist, ignoriere es."
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

Erstelle daraus einen Konkurrenzanalyse-Kurzbericht mit folgender Struktur:
1. Zusammenfassung (2-3 Sätze)
2. Identifizierte Anbieter/Wettbewerber (mit Quelle)
3. Auffällige Preise oder Angebote, falls in den Daten erkennbar
4. Einschätzung: gibt es neue Entwicklungen seit der letzten Recherche?

Schreibe verständlich, ohne Fachjargon, maximal eine halbe DIN-A4-Seite."""

    return system, user
