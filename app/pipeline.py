"""Orchestriert einen Recherche-Lauf: Queries bauen -> Brave (budgetiert/gecacht)
-> Ollama (extern, unbegrenzt) -> Report.

Wird das Brave-Budget mitten im Lauf erschöpft, bricht der Lauf NICHT komplett
ab -- er fasst zusammen, was bis dahin gesammelt wurde, und markiert den
Report deutlich als unvollständig, statt stillschweigend Lücken zu lassen.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .brave_client import BraveClient, SearchResult
from .budget_tracker import BudgetExceededError, BudgetStatus, BudgetTracker
from .cache import ResponseCache
from .config import AppConfig
from .modules import MODULES
from .ollama_client import OllamaClient

logger = logging.getLogger(__name__)


@dataclass
class RunResult:
    module_name: str
    started_at: datetime
    queries_planned: list[str]
    queries_run: list[str] = field(default_factory=list)
    queries_skipped: list[str] = field(default_factory=list)
    budget_status: BudgetStatus | None = None
    content: str = ""
    budget_exhausted: bool = False


def run_module(module_name: str, config: AppConfig) -> RunResult:
    if module_name not in MODULES:
        raise ValueError(
            f"Unbekanntes Modul '{module_name}'. Verfügbar: {', '.join(MODULES)}"
        )
    module_cfg = config.modules.get(module_name)
    if module_cfg is None or not module_cfg.enabled:
        raise ValueError(f"Modul '{module_name}' ist in der Config nicht aktiviert.")

    module = MODULES[module_name]

    budget_tracker = BudgetTracker(config.budget.db_path, config.brave.max_requests_per_month)
    cache = ResponseCache(config.cache.db_path, config.cache.ttl_hours)
    brave = BraveClient(config.brave.api_key, config.brave.base_url, budget_tracker, cache)
    ollama = OllamaClient(config.ollama.base_url, config.ollama.model, config.ollama.timeout_seconds)

    return _run(module, module_cfg.options, brave, ollama, budget_tracker)


def _run(module, options, brave: BraveClient, ollama: OllamaClient, budget_tracker: BudgetTracker) -> RunResult:
    queries = module.build_queries(options)
    result = RunResult(
        module_name=module.NAME,
        started_at=datetime.now(timezone.utc),
        queries_planned=queries,
    )

    search_fn = brave.news_search if module.SEARCH_TYPE == "news" else brave.web_search

    query_results: list[tuple[str, list[SearchResult]]] = []
    for query in queries:
        try:
            results = search_fn(query)
            query_results.append((query, results))
            result.queries_run.append(query)
        except BudgetExceededError:
            logger.warning("Budget während Lauf erschöpft, überspringe restliche Queries.")
            result.budget_exhausted = True
            result.queries_skipped.extend(queries[len(result.queries_run) :])
            break

    result.budget_status = budget_tracker.status()

    if not query_results:
        result.content = (
            "Keine Suchergebnisse verfügbar -- entweder war das Brave-Budget "
            "bereits zu Beginn des Laufs erschöpft, oder es gab keine Treffer."
        )
        return result

    system_prompt, user_prompt = module.build_prompt(query_results, options)
    if result.budget_exhausted:
        user_prompt += (
            "\n\nHinweis: Diese Recherche ist unvollständig, weil das monatliche "
            "Suchbudget während des Laufs erschöpft wurde. Weise im Bericht "
            "kurz darauf hin, dass die Datenbasis nur teilweise vorliegt."
        )

    result.content = ollama.generate(user_prompt, system=system_prompt)
    return result
