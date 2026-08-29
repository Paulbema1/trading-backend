"""
Tests P0 obligatoires (cahier des charges v9.1.0) :
- POOR -> WAIT (data quality)
- Seuil de score 69/70
- MTF : bougie de confirmation clôturée vs ouverte

Ces tests valident le COMPORTEMENT existant du moteur, sans modifier
sa logique de scoring ni sa hiérarchie de garde-fous.
"""
import pytest
import pandas as pd
from datetime import datetime, timedelta, timezone

from src.schemas.signal import ActionEnum, DataQualityEnum
from src.engine.signal_engine import signal_engine
from src.engine.multi_timeframe import mtf_engine
from src.engine.deterministic_scoring import deterministic_scoring_engine


# ── POOR -> WAIT ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_poor_main_quality_forces_wait(monkeypatch, sample_bullish_df):
    """Si la qualité des données du timeframe principal est POOR, l'action finale doit être WAIT."""

    async def fake_get_candles_df(symbol, interval, outputsize):
        # Simule une qualité POOR sur les données (main et confirmation).
        return None, DataQualityEnum.POOR

    monkeypatch.setattr(
        "src.engine.signal_engine.market_data_service.get_candles_df",
        fake_get_candles_df,
    )

    result = await signal_engine.generate_signal("EUR/USD", main_tf="1h", confirm_tf="4h")

    assert result.action == ActionEnum.WAIT
    assert result.data_quality == DataQualityEnum.POOR
    assert result.entry_price is None
    assert result.stop_loss is None


@pytest.mark.asyncio
async def test_poor_price_quality_forces_wait(monkeypatch, sample_bullish_df):
    """Si le prix courant est de qualité POOR, l'action finale doit être WAIT même si les candles sont GOOD."""

    async def fake_get_candles_df(symbol, interval, outputsize):
        return sample_bullish_df, DataQualityEnum.GOOD

    async def fake_get_current_price(symbol):
        return None, DataQualityEnum.POOR

    monkeypatch.setattr(
        "src.engine.signal_engine.market_data_service.get_candles_df",
        fake_get_candles_df,
    )
    monkeypatch.setattr(
        "src.engine.signal_engine.market_data_service.get_current_price",
        fake_get_current_price,
    )

    result = await signal_engine.generate_signal("EUR/USD", main_tf="1h", confirm_tf="4h")

    assert result.action == ActionEnum.WAIT
    assert result.data_quality == DataQualityEnum.POOR


# ── Seuil de score 69/70 ─────────────────────────────────────

def test_score_below_70_forces_wait(monkeypatch):
    """score < 70 -> action = WAIT, quel que soit le candidat déterminé en amont."""

    class FakeMTF:
        def analyze_confluence(self, *a, **k):
            return {"confirm_bias": "NEUTRAL", "score": 0, "alignment": "NEUTRAL", "reasons": []}

    monkeypatch.setattr(
        "src.engine.deterministic_scoring.mtf_engine",
        FakeMTF(),
    )

    class FakeTA:
        def analyze(self, df):
            return {"score": 10, "bias": "BUY", "reasons": ["ta"], "indicators": {"atr": 0.001}}

    class FakeSMC:
        def analyze(self, df):
            return {"score": 5, "bias": "BUY", "reasons": ["smc"]}

    class FakeMom:
        def analyze(self, df):
            return {"score": 5, "reasons": ["mom"]}

    class FakeCtx:
        def evaluate_market_regime(self, df):
            return {"score": 5, "reasons": ["ctx"]}

        def evaluate_news_vs_price(self, df, bias):
            from src.schemas.signal import NewsStatusEnum
            return {"news_score": 0, "status": NewsStatusEnum.NONE, "explanation": "no news", "news_used": False}

    monkeypatch.setattr("src.engine.deterministic_scoring.technical_engine", FakeTA())
    monkeypatch.setattr("src.engine.deterministic_scoring.smc_engine", FakeSMC())
    monkeypatch.setattr("src.engine.deterministic_scoring.momentum_engine", FakeMom())
    monkeypatch.setattr("src.engine.deterministic_scoring.market_context_engine", FakeCtx())

    result = deterministic_scoring_engine.evaluate(
        main_df=pd.DataFrame({"close": [1.0]}),
        confirm_df=pd.DataFrame({"close": [1.0]}),
        news_data={"bias": "NEUTRAL"},
        calendar_data={"calendar_score": 0},
    )

    assert result["score"] < 70
    assert result["action"] == ActionEnum.WAIT


# ── MTF : bougie clôturée vs ouverte ─────────────────────────

def _make_confirm_df(start: datetime, count: int, tf_hours: int = 4):
    dates = [start + timedelta(hours=tf_hours * i) for i in range(count)]
    return pd.DataFrame({
        "datetime": dates,
        "open": [1.10 + i * 0.001 for i in range(count)],
        "high": [1.101 + i * 0.001 for i in range(count)],
        "low": [1.099 + i * 0.001 for i in range(count)],
        "close": [1.1005 + i * 0.001 for i in range(count)],
        "volume": [1000.0] * count,
    })


def test_mtf_rejects_unclosed_confirmation_candle():
    """
    Si AUCUNE bougie de confirmation n'est encore clôturée à as_of, le MTF doit
    retourner WAIT/score 0 plutôt que d'utiliser une bougie encore ouverte.
    """
    start = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)  # bougie 4h : 08h -> 12h
    confirm_df = _make_confirm_df(start, count=5)
    main_df = _make_confirm_df(start, count=30, tf_hours=1)

    # Analyse 1h après l'ouverture de l'UNIQUE bougie disponible : elle n'est pas
    # encore clôturée (il faudrait attendre 4h). Aucune bougie clôturée disponible.
    as_of = start + timedelta(hours=1)

    result = mtf_engine.analyze_confluence(main_df, confirm_df.iloc[[0]], confirm_tf="4h", as_of=as_of)

    assert result["alignment"] == "WAIT"
    assert result["score"] == 0


def test_mtf_accepts_closed_confirmation_candle():
    """Une bougie 4h clôturée (datetime + 4h <= as_of) doit pouvoir servir de confirmation."""
    start = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)
    confirm_df = _make_confirm_df(start, count=30)
    main_df = _make_confirm_df(start, count=30, tf_hours=1)

    last_candle_start = confirm_df["datetime"].iloc[-1]
    as_of = last_candle_start + timedelta(hours=5)  # +5h >= +4h -> clôturée

    result = mtf_engine.analyze_confluence(main_df, confirm_df, confirm_tf="4h", as_of=as_of)

    # La bougie clôturée doit être utilisée : alignment != "WAIT" (NEUTRAL ou biais directionnel)
    assert result["alignment"] != "WAIT"
