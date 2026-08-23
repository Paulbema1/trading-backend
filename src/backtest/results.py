"""
TradeVision AI - Métriques et Statistiques de Backtest.
"""

from typing import List, Dict, Any
import pandas as pd


class BacktestResults:

    @staticmethod
    def calculate_metrics(trades: List[Dict[str, Any]], initial_balance: float = 10000.0) -> Dict[str, Any]:
        if not trades:
            return {
                "initial_balance": float(initial_balance),
                "final_balance": float(initial_balance),
                "net_profit_pct": 0.0,
                "total_trades": 0,
                "closed_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "win_rate_pct": 0.0,
                "profit_factor": 0.0,
                "expectancy_r": 0.0,
                "max_drawdown_pct": 0.0,
                "trades_with_news": 0,
            }

        df_trades = pd.DataFrame(trades)
        total_trades = int(len(df_trades))
        closed_trades = df_trades[df_trades["result"].isin(["WIN", "LOSS"])]

        if closed_trades.empty:
            return {
                "initial_balance": float(initial_balance),
                "final_balance": float(initial_balance),
                "net_profit_pct": 0.0,
                "total_trades": total_trades,
                "closed_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "win_rate_pct": 0.0,
                "profit_factor": 0.0,
                "expectancy_r": 0.0,
                "max_drawdown_pct": 0.0,
                "trades_with_news": 0,
            }

        wins = closed_trades[closed_trades["result"] == "WIN"]
        losses = closed_trades[closed_trades["result"] == "LOSS"]

        win_rate = (len(wins) / len(closed_trades)) * 100.0

        total_gain_pips = float(wins["pips"].sum()) if not wins.empty else 0.0
        total_loss_pips = float(abs(losses["pips"].sum())) if not losses.empty else 0.0

        profit_factor = (total_gain_pips / total_loss_pips) if total_loss_pips > 0 else 3.5
        expectancy_r = float(closed_trades["r_multiple"].mean()) if not closed_trades.empty else 0.0

        balance = float(initial_balance)
        peak = balance
        max_drawdown = 0.0

        for r in closed_trades["r_multiple"]:
            r_val = float(r)
            trade_pnl = balance * 0.01 * r_val
            balance += trade_pnl

            if balance > peak:
                peak = balance
            dd = (peak - balance) / peak * 100.0
            if dd > max_drawdown:
                max_drawdown = dd

        net_profit_pct = ((balance - initial_balance) / initial_balance) * 100.0

        return {
            "initial_balance": round(float(initial_balance), 2),
            "final_balance": round(float(balance), 2),
            "net_profit_pct": round(float(net_profit_pct), 2),
            "total_trades": total_trades,
            "closed_trades": int(len(closed_trades)),
            "winning_trades": int(len(wins)),
            "losing_trades": int(len(losses)),
            "win_rate_pct": round(float(win_rate), 2),
            "profit_factor": round(float(profit_factor), 2),
            "expectancy_r": round(float(expectancy_r), 2),
            "max_drawdown_pct": round(float(max_drawdown), 2),
            "trades_with_news": int(df_trades["news_used"].sum()) if "news_used" in df_trades.columns else 0,
        }
