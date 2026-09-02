from datetime import datetime, timedelta, timezone

from app.cache import ResponseCache


def make_cache(tmp_path, ttl_hours=24, start="2026-09-01T00:00:00+00:00"):
    box = {"now": datetime.fromisoformat(start)}
    cache = ResponseCache(tmp_path / "cache.db", ttl_hours=ttl_hours, clock=lambda: box["now"])
    return cache, box


def test_set_and_get_roundtrip(tmp_path):
    cache, _ = make_cache(tmp_path)
    key = cache.make_key("/web/search", "Testquery", count=10)
    assert cache.get(key) is None

    cache.set(key, "Testquery", [{"title": "A", "url": "https://a", "snippet": "..."}])
    result = cache.get(key)
    assert result == [{"title": "A", "url": "https://a", "snippet": "..."}]


def test_different_params_produce_different_keys(tmp_path):
    cache, _ = make_cache(tmp_path)
    key1 = cache.make_key("/web/search", "Test", count=10)
    key2 = cache.make_key("/web/search", "Test", count=20)
    assert key1 != key2


def test_entry_expires_after_ttl(tmp_path):
    cache, box = make_cache(tmp_path, ttl_hours=24)
    key = cache.make_key("/news/search", "Testquery")
    cache.set(key, "Testquery", [{"title": "A"}])

    box["now"] += timedelta(hours=23)
    assert cache.get(key) is not None  # noch innerhalb TTL

    box["now"] += timedelta(hours=2)
    assert cache.get(key) is None  # TTL abgelaufen
