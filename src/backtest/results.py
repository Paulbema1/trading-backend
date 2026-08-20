"""
TradeVision AI - Métriques et Statistiques de Backtest.
"""

from typing import List, Dict, Any
import numpy as np
import pandas as pd


class BacktestResults:
    """Analyse quantitative des résultats de backtest."""

    @staticmethod
    def calculate_metrics(trades: List[Dict[str, Any]], initial_balance: float = 10000.0) -> Dict[str, Any]:
        if not trades:
            return {"total_trades": 0, "message": "Aucun trade exécuté durant la période."}

        df_trades = pd.DataFrame(trades)
        total_trades = len(df_trades)
        closed_trades = df_trades[df_trades["result"].isin(["WIN", "LOSS"])]

        if closed_trades.empty:
            return {"total_trades": total_trades, "closed_trades": 0, "status": "Tous les trades sont en cours."}

        wins = closed_trades[closed_trades["result"] == "WIN"]
        losses = closed_trades[closed_trades["result"] == "LOSS"]

        win_rate = (len(wins) / len(closed_trades)) * 100

        total_gain_pips = wins["pips"].sum() if not wins.empty else 0.0
        total_loss_pips = abs(losses["pips"].sum()) if not losses.empty else 0.0

        profit_factor = (total_gain_pips / total_loss_pips) if total_loss_pips > 0 else 999.0
        expectancy_r = closed_trades["r_multiple"].mean()

        # Évolution du capital et Max Drawdown
        balance = initial_balance
        equity_curve = [balance]
        peak = balance
        max_drawdown = 0.0

        for r in closed_trades["r_multiple"]:
            # Risque 1% du capital par trade
            trade_pnl = balance * 0.01 * r
            balance += trade_pnl
            equity_curve.append(balance)

            if balance > peak:
                peak = balance
            dd = (peak - balance) / peak * 100
            if dd > max_drawdown:
                max_drawdown = dd

        net_profit_pct = ((balance - initial_balance) / initial_balance) * 100

        return {
            "initial_balance": initial_balance,
            "final_balance": round(balance, 2),
            "net_profit_pct": round(net_profit_pct, 2),
            "total_trades": total_trades,
            "closed_trades": len(closed_trades),
            "winning_trades": len(wins),
            "losing_trades": len(losses),
            "win_rate_pct": round(win_rate, 2),
            "profit_factor": round(profit_factor, 2),
            "expectancy_r": round(float(expectancy_r), 2),
            "max_drawdown_pct": round(max_drawdown, 2),
            "trades_with_news": int(df_trades["news_used"].sum()) if "news_used" in df_trades.columns else 0,
        }