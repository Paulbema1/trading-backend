"""
Test P0 obligatoire : absence de look-ahead dans StrictAuditedBacktestEngine.

Vérifie que le résultat du scoring à l'instant T est identique, que le dataset
de confirmation contienne ou non des bougies futures au-delà de T. Ne modifie
aucune logique de scoring : n'inspecte que le respect de la coupure temporelle.
"""
from datetime import datetime, timedelta
import pandas as pd

from src.backtest.engine import backtest_engine


def _make_ohlcv(start: datetime, count: int, freq_hours: int, base: float = 1.1000):
    dates = [start + timedelta(hours=freq_hours * i) for i in range(count)]
    closes = [base + 0.0001 * i for i in range(count)]
    return pd.DataFrame({
        "datetime": dates,
        "open": closes,
        "high": [c + 0.0005 for c in closes],
        "low": [c - 0.0005 for c in closes],
        "close": closes,
        "volume": [1000.0] * count,
    })


def test_closed_confirm_excludes_future_candles():
    """
    _closed_confirm ne doit jamais retourner de bougie dont la clôture
    (datetime + duration) dépasse current_time (pas de look-ahead).
    """
    start = datetime(2026, 1, 1, 0, 0)
    confirm_df = _make_ohlcv(start, count=50, freq_hours=4)

    # current_time volontairement au milieu du dataset
    current_time = start + timedelta(hours=4 * 20) + timedelta(hours=1)  # dans la bougie n°20, pas encore close

    closed = backtest_engine._closed_confirm(confirm_df, "4h", current_time)

    # Aucune bougie retournée ne doit se clôturer après current_time.
    assert all((closed["datetime"] + timedelta(hours=4)) <= current_time)

    # La bougie n°20 (encore ouverte à current_time) ne doit PAS être incluse.
    unclosed_candle_time = confirm_df["datetime"].iloc[20]
    assert unclosed_candle_time not in closed["datetime"].values


def test_closed_confirm_result_unaffected_by_appending_future_candles():
    """
    Ajouter des bougies futures (au-delà de current_time) au DataFrame de confirmation
    ne doit PAS changer l'ensemble des bougies considérées "clôturées" à current_time.
    C'est le test explicite de non-look-ahead exigé par le cahier des charges (§26/§27).
    """
    start = datetime(2026, 1, 1, 0, 0)
    confirm_df_without_future = _make_ohlcv(start, count=20, freq_hours=4)
    confirm_df_with_future = _make_ohlcv(start, count=50, freq_hours=4)  # 30 bougies futures en plus

    current_time = start + timedelta(hours=4 * 15)  # bougie n°15 tout juste clôturée

    closed_without_future = backtest_engine._closed_confirm(confirm_df_without_future, "4h", current_time)
    closed_with_future = backtest_engine._closed_confirm(confirm_df_with_future, "4h", current_time)

    # Même nombre de bougies "vues" et mêmes timestamps, malgré la présence de données futures.
    assert list(closed_without_future["datetime"]) == list(closed_with_future["datetime"])
