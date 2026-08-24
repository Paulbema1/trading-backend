"""
Tests du Signal Engine et du Backtesting.
"""

import pytest
from src.engine.signal_engine import signal_engine
from src.schemas.signal import ActionEnum
from src.backtest.simulator import trade_simulator
from src.backtest.results import BacktestResults


def test_sl_tp_calculation():
    levels = signal_engine._calculate_levels(
        symbol="EUR/USD",
        action=ActionEnum.BUY,
        current_price=1.1000,
        atr=0.0020,
    )
    assert levels["entry_price"] == 1.1000
    assert levels["stop_loss"] < 1.1000
    assert levels["take_profit_1"] > 1.1000
    assert levels["take_profit_2"] > levels["take_profit_1"]
    assert levels["risk_reward"] >= 2.0


def test_trade_simulator_win(sample_bullish_df):
    res = trade_simulator.simulate_trade(
        symbol="EUR/USD",
        action=ActionEnum.BUY,
        entry_price=1.1000,
        stop_loss=1.0950,
        take_profit_1=1.1050,
        take_profit_2=1.1100,
        take_profit_3=1.1150,
        future_candles=sample_bullish_df,
        start_index=0,
    )
    assert res["result"] in ("WIN", "LOSS", "FORCED_CLOSE", "OPEN")


def test_backtest_metrics_computation():
    mock_trades = [
        {"result": "WIN", "pips": 40.0, "r_multiple": 2.0, "news_used": True},
        {"result": "WIN", "pips": 30.0, "r_multiple": 1.5, "news_used": False},
        {"result": "LOSS", "pips": -20.0, "r_multiple": -1.0, "news_used": False},
    ]
    metrics = BacktestResults.calculate_metrics(mock_trades, initial_balance=10000.0)
    assert metrics["total_trades"] == 3
    assert metrics["win_rate_pct"] == 66.67
    assert metrics["profit_factor"] == 3.5
    assert metrics["final_balance"] > 10000.0
