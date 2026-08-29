"""
Tests du module SMC (Smart Money Concepts) — structure, order blocks, FVG, score.
Utilise les fixtures partagées sample_bullish_df / sample_bearish_df (conftest.py).
"""
import pandas as pd
from src.engine.smc import smc_engine


def test_smc_insufficient_data_returns_neutral():
    """Moins de 40 bougies -> analyse impossible, doit retourner NEUTRAL/score 0 sans planter."""
    tiny_df = pd.DataFrame({
        "datetime": pd.date_range("2026-01-01", periods=10, freq="h"),
        "open": [1.10] * 10,
        "high": [1.101] * 10,
        "low": [1.099] * 10,
        "close": [1.1005] * 10,
        "volume": [1000.0] * 10,
    })

    result = smc_engine.analyze(tiny_df)

    assert result["score"] == 0
    assert result["bias"] == "NEUTRAL"
    assert result["structure"] == "UNKNOWN"


def test_smc_bullish_structure_detected(sample_bullish_df):
    """Sur un dataset avec Higher Highs / Higher Lows nets, le biais SMC doit être BUY."""
    result = smc_engine.analyze(sample_bullish_df)

    assert result["bias"] == "BUY"
    assert result["score"] > 0
    assert result["score"] <= 30  # barème max du module (§10 du cahier des charges)


def test_smc_bearish_structure_detected(sample_bearish_df):
    """Sur un dataset avec Lower Highs / Lower Lows nets, le biais SMC doit être SELL."""
    result = smc_engine.analyze(sample_bearish_df)

    assert result["bias"] == "SELL"
    assert result["score"] > 0
    assert result["score"] <= 30


def test_smc_score_never_exceeds_30_points_cap():
    """Le score SMC ne doit jamais dépasser le barème documenté (30 points max)."""
    import numpy as np
    from datetime import datetime, timedelta

    n = 100
    dates = [datetime(2026, 1, 1) + timedelta(hours=i) for i in range(n)]
    close = np.linspace(1.10, 1.20, n)  # forte tendance haussière continue
    df = pd.DataFrame({
        "datetime": dates,
        "open": np.roll(close, 1),
        "high": close + 0.0006,
        "low": close - 0.0006,
        "close": close,
        "volume": np.full(n, 1500.0),
    })

    result = smc_engine.analyze(df)
    assert result["score"] <= 30
