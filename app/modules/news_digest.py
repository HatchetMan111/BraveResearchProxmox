"""Modul: lokale News-Zusammenfassung im vorgegebenen Stil.

Config-Optionen (unter modules.news_digest.* in config.yaml):
    region:        z.B. "Ihre Region"
    themen:        Liste von Themen, z.B. ["Energie", "SmartHome", "Förderprogramme"]
    stil:          Freitext-Stilvorgabe für Ollama, z.B. "sachlich, lokal, freundlich"

Nutzt den News-Endpoint von Brave statt der Web-Suche.
"""

from __future__ import annotations

from typing import Any

from ..brave_client import SearchResult

NAME = "news_digest"
SEARCH_TYPE = "news"


def build_queries(options: dict[str, Any]) -> list[str]:
    region = options["region"]
    themen = options.get("themen") or [""]
    queries = []
    for thema in themen:
        query = f"{thema} {region}".strip()
        queries.append(query)
    queries.extend(options.get("queries_extra", []))
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
    region = options["region"]
    stil = options.get("stil", "sachlich, lokal, freundlich")

    system = (
        f"Du bist Redakteur für einen lokalen News-Digest zur Region {region}. "
        f"Schreibstil: {stil}. Du erhältst rohe Suchergebnisse aus einer "
        "News-Suche und fasst sie zu einem kurzen, gut lesbaren Digest auf "
        "Deutsch zusammen. Erfinde keine Fakten, die nicht in den "
        "Suchergebnissen stehen. Nenne bei jeder Meldung die Quelle."
    )

    blocks = []
    for query, results in query_results:
        lines = [f"Suchthema: \"{query}\""]
        for r in results:
            age = f" ({r.age})" if r.age else ""
            lines.append(f"- {r.title}{age} ({r.url}): {r.snippet}")
        blocks.append("\n".join(lines))
    raw_data = "\n\n".join(blocks) if blocks else "(keine Suchergebnisse)"

    user = f"""Region: {region}
Rohdaten aus der News-Suche:
{raw_data}

Erstelle daraus einen News-Digest mit folgender Struktur:
1. Kurzer Überblick (2-3 Sätze, was ist diese Woche wichtig für die Region)
2. Einzelne Meldungen als kurze Absätze, je mit Quellenangabe
3. Falls nichts Relevantes dabei ist, das ehrlich so benennen statt Meldungen zu erfinden

Ziel-Stil: {stil}. Maximal eine DIN-A4-Seite."""

    return system, user
