"""Über das Dashboard frei angelegte Module ("custom_modules" in config.yaml).

Implementiert dieselbe Schnittstelle wie die eingebauten Module
(NAME, SEARCH_TYPE, build_queries(), build_prompt()), aber ohne dass dafür
eine eigene .py-Datei geschrieben werden muss -- Name, Suchanfragen und
Ollama-System-Prompt kommen komplett aus der Config.
"""

from __future__ import annotations

from typing import Any

from ..brave_client import SearchResult
from ..config import CustomModuleConfig

DEFAULT_SYSTEM_PROMPT = (
    "Du erhältst rohe Suchergebnisse zu einem Recherche-Thema und fasst sie "
    "zu einem ausführlichen, sachlichen Bericht auf Deutsch zusammen. Erfinde keine "
    "Fakten, die nicht in den Suchergebnissen stehen. Verlinke jede Quelle "
    "als Markdown-Link [Titel](URL) mit der exakten URL aus den Rohdaten."
)


class DynamicModule:
    def __init__(self, spec: CustomModuleConfig):
        self.NAME = spec.name
        self.SEARCH_TYPE = "news" if spec.search_type == "news" else "web"
        self._queries = list(spec.queries)
        self._system_prompt = spec.system_prompt.strip() or DEFAULT_SYSTEM_PROMPT

    def build_queries(self, options: dict[str, Any]) -> list[str]:
        return list(self._queries)

    def build_prompt(
        self, query_results: list[tuple[str, list[SearchResult]]], options: dict[str, Any]
    ) -> tuple[str, str]:
        blocks = []
        for query, results in query_results:
            lines = [f'Suchanfrage: "{query}"']
            for r in results:
                age = f" ({r.age})" if r.age else ""
                lines.append(f"- {r.title}{age} ({r.url}): {r.snippet}")
            blocks.append("\n".join(lines))
        raw_data = "\n\n".join(blocks) if blocks else "(keine Suchergebnisse)"

        user_prompt = f"""Rohdaten aus der Suche:
{raw_data}

Erstelle daraus einen ausführlichen, gut lesbaren Bericht auf Deutsch
(ca. 1-2 DIN-A4-Seiten) mit Zusammenfassung vorweg, dann Details pro
Thema/Quelle. Verlinke jede verwendete Quelle als Markdown-Link
[Titel](URL) mit der exakten URL aus den Rohdaten. Falls nichts Relevantes
dabei ist, das ehrlich so benennen statt Inhalte zu erfinden."""

        return self._system_prompt, user_prompt
