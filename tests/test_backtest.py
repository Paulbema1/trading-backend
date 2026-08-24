"""
Tests unitaires pour le Moteur de Backtest et le Simulateur.
"""

import pytest
import pandas as pd
from datetime import datetime, timedelta

from src.backtest.simulator import trade_simulator
from src.backtest.results import BacktestResults
from src.schemas.signal import ActionEnum


def test_simulator_tp_hit():
    """Vérifie le déclenchement d'un Take Profit (WIN)."""
    dates = [datetime(2025, 1, 1) + timedelta(hours=i) for i in range(5)]
    future_candles = pd.DataFrame({
        "datetime": dates,
        "open": [1.1000, 1.1010, 1.1030, 1.1060, 1.1080],
        "high": [1.1020, 1.1040, 1.1070, 1.1110, 1.1100],
        "low": [1.0990, 1.1000, 1.1020, 1.1050, 1.1070],
        "close": [1.1010, 1.1030, 1.1060, 1.1080, 1.1090],
    })

    res = trade_simulator.simulate_trade(
        symbol="EUR/USD",
        action=ActionEnum.BUY,
        entry_price=1.1000,
        stop_loss=1.0950,
        take_profit_1=1.1050,
        take_profit_2=1.1100,
        take_profit_3=1.1150,
        future_candles=future_candles,
        start_index=0,
    )

    assert res["result"] == "WIN"
    assert res["hit_tp"] >= 1
    assert res["pips"] > 0


def test_simulator_sl_conservative_priority():
    """Vérifie la règle conservatrice : SL prioritaire si TP et SL dans la même bougie."""
    dates = [datetime(2025, 1, 1)]
    volatile_candle = pd.DataFrame({
        "datetime": dates,
        "open": [1.1000],
        "high": [1.1150],  # Au-dessus du TP1 (1.1050)
        "low": [1.0900],   # En-dessous du SL (1.0950)
        "close": [1.1000],
    })

    res = trade_simulator.simulate_trade(
        symbol="EUR/USD",
        action=ActionEnum.BUY,
        entry_price=1.1000,
        stop_loss=1.0950,
        take_profit_1=1.1050,
        take_profit_2=1.1100,
        take_profit_3=1.1150,
        future_candles=volatile_candle,
        start_index=0,
    )

    assert res["result"] == "LOSS"
    assert res["reason"] == "SL_HIT_CONSERVATIVE"
    assert res["pips"] < 0


def test_simulator_forced_close_at_end():
    """Vérifie qu'un trade encore ouvert à la fin du dataset est FORCED_CLOSE."""
    dates = [datetime(2025, 1, 1) + timedelta(hours=i) for i in range(3)]
    flat_candles = pd.DataFrame({
        "datetime": dates,
        "open": [1.1000, 1.1002, 1.1004],
        "high": [1.1010, 1.1012, 1.1014],
        "low": [1.0990, 1.0992, 1.0994],
        "close": [1.1002, 1.1004, 1.1005],
    })

    res = trade_simulator.simulate_trade(
        symbol="EUR/USD",
        action=ActionEnum.BUY,
        entry_price=1.1000,
        stop_loss=1.0950,
        take_profit_1=1.1050,
        take_profit_2=1.1100,
        take_profit_3=1.1150,
        future_candles=flat_candles,
        start_index=0,
    )

    assert res["result"] == "FORCED_CLOSE"
    assert res["reason"] == "END_OF_DATASET"


def test_compounding_on_vs_off():
    """Vérifie la différence de calcul avec et sans Compounding."""
    trades = [
        {"result": "WIN", "pips": 50.0, "r_multiple": 2.0},
        {"result": "WIN", "pips": 50.0, "r_multiple": 2.0},
    ]

    metrics_no_compound = BacktestResults.calculate_metrics(trades, initial_balance=10000.0, compounding=False)
    metrics_compound = BacktestResults.calculate_metrics(trades, initial_balance=10000.0, compounding=True)

    assert metrics_no_compound["net_profit_dollars"] == 400.0
    assert metrics_compound["net_profit_dollars"] == 404.0
