"""
Tests des moteurs Technique et Smart Money Concepts.
"""

from src.engine.technical_analysis import technical_engine
from src.engine.smc import smc_engine


def test_technical_analysis_bullish(sample_bullish_df):
    res = technical_engine.analyze(sample_bullish_df)
    assert res["score"] >= 12
    assert res["bias"] == "BUY"
    assert "rsi" in res["indicators"]
    assert "ema20" in res["indicators"]


def test_technical_analysis_bearish(sample_bearish_df):
    res = technical_engine.analyze(sample_bearish_df)
    assert res["score"] >= 12
    assert res["bias"] == "SELL"


def test_smc_structure_detection(sample_bullish_df):
    res = smc_engine.analyze(sample_bullish_df)
    assert res["score"] > 0
    assert res["structure"] in ("BULLISH_STRUCTURE", "BOS_BULLISH", "RANGING")