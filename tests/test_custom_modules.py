import textwrap

import pytest

from app.brave_client import SearchResult
from app.config import load_config
from app.modules.dynamic import DynamicModule
from app.pipeline import _resolve_module, list_available_modules


def write_config(tmp_path, extra_yaml: str = "") -> str:
    path = tmp_path / "config.yaml"
    base = (
        "brave:\n"
        "  api_key: dummy\n"
        "ollama:\n"
        "  base_url: http://dummy:11434\n"
        "  model: llama3.1\n"
        "modules:\n"
        "  competitor_analysis:\n"
        "    enabled: false\n"
        "    branche: X\n"
        "    region: Y\n"
        "  news_digest:\n"
        "    enabled: false\n"
        "    region: Y\n"
    )
    path.write_text(base + extra_yaml, encoding="utf-8")
    return str(path)


def test_custom_module_parsed_from_config(tmp_path):
    extra = textwrap.dedent(
        """\
        custom_modules:
          - name: vereinsnachrichten
            enabled: true
            search_type: news
            queries:
              - "Musterverein Neuigkeiten"
            system_prompt: "Fasse kurz zusammen."
        """
    )
    config = load_config(write_config(tmp_path, extra))
    assert len(config.custom_modules) == 1
    cm = config.custom_modules[0]
    assert cm.name == "vereinsnachrichten"
    assert cm.search_type == "news"
    assert cm.queries == ["Musterverein Neuigkeiten"]


def test_custom_modules_without_name_are_skipped(tmp_path):
    extra = "custom_modules:\n  - enabled: true\n    queries: ['x']\n"
    config = load_config(write_config(tmp_path, extra))
    assert config.custom_modules == []


def test_dynamic_module_builds_queries_and_prompt():
    from app.config import CustomModuleConfig

    spec = CustomModuleConfig(
        name="vereinsnachrichten",
        search_type="news",
        queries=["Musterverein Neuigkeiten"],
        system_prompt="Fasse kurz zusammen.",
    )
    module = DynamicModule(spec)
    assert module.NAME == "vereinsnachrichten"
    assert module.SEARCH_TYPE == "news"
    assert module.build_queries({}) == ["Musterverein Neuigkeiten"]

    results = [("Musterverein Neuigkeiten", [SearchResult(title="T", url="https://x", snippet="S")])]
    system, user = module.build_prompt(results, {})
    assert system == "Fasse kurz zusammen."
    assert "Musterverein Neuigkeiten" in user
    assert "T" in user and "https://x" in user


def test_dynamic_module_falls_back_to_default_prompt_when_empty():
    from app.config import CustomModuleConfig

    spec = CustomModuleConfig(name="x", queries=["q"], system_prompt="   ")
    module = DynamicModule(spec)
    system, _ = module.build_prompt([], {})
    assert "Du erhältst rohe Suchergebnisse" in system


def test_resolve_module_finds_custom_module(tmp_path):
    extra = textwrap.dedent(
        """\
        custom_modules:
          - name: vereinsnachrichten
            enabled: true
            queries: ["q"]
        """
    )
    config = load_config(write_config(tmp_path, extra))
    module, options = _resolve_module("vereinsnachrichten", config)
    assert isinstance(module, DynamicModule)
    assert options == {}


def test_resolve_module_raises_for_disabled_custom_module(tmp_path):
    extra = textwrap.dedent(
        """\
        custom_modules:
          - name: vereinsnachrichten
            enabled: false
            queries: ["q"]
        """
    )
    config = load_config(write_config(tmp_path, extra))
    with pytest.raises(ValueError, match="nicht aktiviert"):
        _resolve_module("vereinsnachrichten", config)


def test_resolve_module_raises_for_unknown_module(tmp_path):
    config = load_config(write_config(tmp_path))
    with pytest.raises(ValueError, match="Unbekanntes Modul"):
        _resolve_module("does-not-exist", config)


def test_list_available_modules_includes_enabled_custom_and_excludes_disabled_builtin(tmp_path):
    extra = textwrap.dedent(
        """\
        custom_modules:
          - name: aktiv
            enabled: true
            queries: ["q"]
          - name: inaktiv
            enabled: false
            queries: ["q"]
        """
    )
    config = load_config(write_config(tmp_path, extra))
    names = list_available_modules(config)
    # competitor_analysis/news_digest sind in write_config() auf enabled: false gesetzt
    assert "competitor_analysis" not in names
    assert "news_digest" not in names
    assert "aktiv" in names
    assert "inaktiv" not in names
