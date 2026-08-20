"""
Tests de l'arbitrage Prix vs Actualités.
"""

from src.engine.context import market_context_engine
from src.schemas.signal import NewsStatusEnum


def test_news_confirmed_by_market(sample_bullish_df):
    # Actualité BUY + Marché Haussier -> Validation Forte
    res = market_context_engine.evaluate_news_vs_price(sample_bullish_df, news_bias="BUY")
    assert res["status"] == NewsStatusEnum.CONFIRMED
    assert res["news_score"] == 10
    assert res["news_used"] is True


def test_news_divergence_contradiction(sample_bearish_df):
    # Actualité BUY + Marché qui s'effondre -> DANGER (Contradiction)
    res = market_context_engine.evaluate_news_vs_price(sample_bearish_df, news_bias="BUY")
    assert res["status"] == NewsStatusEnum.DIVERGENCE
    assert res["news_score"] == -15  # Forte pénalité
    assert res["news_used"] is False