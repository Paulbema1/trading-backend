"""
Tests du cache mémoire OHLCV/prix (TTL par timeframe + fallback stale, §D du cahier des charges).
"""
import time
import pandas as pd
from src.utils.cache import MemoryCache


def _make_df():
    return pd.DataFrame({
        "datetime": pd.date_range("2026-01-01", periods=5, freq="h"),
        "open": [1.10] * 5,
        "high": [1.101] * 5,
        "low": [1.099] * 5,
        "close": [1.1005] * 5,
        "volume": [1000.0] * 5,
    })


def test_ohlcv_cache_hit_before_ttl():
    cache = MemoryCache()
    df = _make_df()
    cache.set_ohlcv("EUR/USD", "1h", df, outputsize=200, ttl_seconds=5)

    result, is_stale = cache.get_ohlcv("EUR/USD", "1h", outputsize=200)

    assert result is not None
    assert is_stale is False
    assert len(result) == 5


def test_ohlcv_cache_miss_after_ttl_without_stale_fallback():
    cache = MemoryCache()
    df = _make_df()
    cache.set_ohlcv("EUR/USD", "1h", df, outputsize=200, ttl_seconds=0.2)

    time.sleep(0.3)

    result, is_stale = cache.get_ohlcv("EUR/USD", "1h", outputsize=200, allow_stale=False)

    assert result is None
    assert is_stale is False


def test_ohlcv_cache_stale_fallback_after_ttl():
    """Après expiration du TTL, allow_stale=True doit retourner la dernière donnée connue."""
    cache = MemoryCache()
    df = _make_df()
    cache.set_ohlcv("EUR/USD", "1h", df, outputsize=200, ttl_seconds=0.2)

    time.sleep(0.3)

    result, is_stale = cache.get_ohlcv("EUR/USD", "1h", outputsize=200, allow_stale=True)

    assert result is not None
    assert is_stale is True
    assert len(result) == 5


def test_default_ttl_per_timeframe():
    """Les TTL par défaut doivent respecter le mapping du cahier des charges (§D)."""
    cache = MemoryCache()
    assert cache.DEFAULT_OHLCV_TTL["15m"] == 60
    assert cache.DEFAULT_OHLCV_TTL["30m"] == 120
    assert cache.DEFAULT_OHLCV_TTL["1h"] == 300
    assert cache.DEFAULT_OHLCV_TTL["4h"] == 900


def test_price_cache_hit_and_stale_fallback():
    cache = MemoryCache()
    cache.set_price("EUR/USD", 1.1050, ttl_seconds=0.2)

    price, is_stale = cache.get_price("EUR/USD")
    assert price == 1.1050
    assert is_stale is False

    time.sleep(0.3)

    price_expired, _ = cache.get_price("EUR/USD", allow_stale=False)
    assert price_expired is None

    price_stale, is_stale2 = cache.get_price("EUR/USD", allow_stale=True)
    assert price_stale == 1.1050
    assert is_stale2 is True


def test_clear_empties_both_stores():
    cache = MemoryCache()
    cache.set_ohlcv("EUR/USD", "1h", _make_df())
    cache.set_price("EUR/USD", 1.1)

    cache.clear()

    result, _ = cache.get_ohlcv("EUR/USD", "1h")
    price, _ = cache.get_price("EUR/USD")
    assert result is None
    assert price is None
