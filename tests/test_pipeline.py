from datetime import datetime, timezone

from app.brave_client import SearchResult
from app.budget_tracker import BudgetExceededError, BudgetStatus
from app.modules import competitor_analysis
from app.pipeline import _run


class FakeBrave:
    """Simuliert BraveClient: web_search/news_search je nach Testfall."""

    def __init__(self, results_by_query=None, fail_after=None):
        self.results_by_query = results_by_query or {}
        self.fail_after = fail_after  # Anzahl erfolgreicher Calls, danach BudgetExceededError
        self.calls = []

    def web_search(self, query, count=10):
        self.calls.append(query)
        if self.fail_after is not None and len(self.calls) > self.fail_after:
            raise BudgetExceededError("Budget erschöpft (Test)")
        return self.results_by_query.get(query, [])

    news_search = web_search


class FakeOllama:
    def __init__(self, response="ZUSAMMENFASSUNG"):
        self.response = response
        self.last_prompt = None
        self.last_system = None
        self.call_count = 0

    def generate(self, prompt, system=None):
        self.call_count += 1
        self.last_prompt = prompt
        self.last_system = system
        return self.response


class FakeBudgetTracker:
    def __init__(self, used=1, limit=950):
        self._status = BudgetStatus(month="2026-09", used=used, limit=limit)

    def status(self):
        return self._status


OPTIONS = {"branche": "SmartHome Integration", "region": "Main-Tauber-Kreis"}


def test_full_run_produces_report_content():
    queries = competitor_analysis.build_queries(OPTIONS)
    results_by_query = {
        q: [SearchResult(title="Anbieter X", url="https://x.example", snippet="...")]
        for q in queries
    }
    brave = FakeBrave(results_by_query=results_by_query)
    ollama = FakeOllama(response="Kurzbericht Text")

    result = _run(competitor_analysis, OPTIONS, brave, ollama, FakeBudgetTracker())

    assert result.content == "Kurzbericht Text"
    assert result.queries_run == queries
    assert result.queries_skipped == []
    assert result.budget_exhausted is False
    assert ollama.call_count == 1
    assert "Anbieter X" in ollama.last_prompt


def test_budget_exhausted_mid_run_marks_incomplete():
    queries = competitor_analysis.build_queries(OPTIONS)
    assert len(queries) >= 2, "Testannahme: Modul plant mind. 2 Queries"

    brave = FakeBrave(results_by_query={}, fail_after=1)  # erste Query klappt, Rest schlägt fehl
    ollama = FakeOllama()

    result = _run(competitor_analysis, OPTIONS, brave, ollama, FakeBudgetTracker())

    assert result.budget_exhausted is True
    assert len(result.queries_run) == 1
    assert len(result.queries_skipped) == len(queries) - 1
    # Ollama wird trotzdem mit den Teildaten aufgerufen und über die Lücke informiert
    assert ollama.call_count == 1
    assert "unvollständig" in ollama.last_prompt


def test_no_results_skips_ollama_call():
    brave = FakeBrave(results_by_query={}, fail_after=0)  # jede Query schlägt sofort fehl
    ollama = FakeOllama()

    result = _run(competitor_analysis, OPTIONS, brave, ollama, FakeBudgetTracker())

    assert ollama.call_count == 0
    assert "Budget" in result.content or "keine Treffer" in result.content
    assert result.budget_exhausted is True
