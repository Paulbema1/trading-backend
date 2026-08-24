"""
TradeVision AI - Métriques et Statistiques de Backtest Auditées.
"""

from typing import List, Dict, Any
import pandas as pd


class BacktestResults:

    @staticmethod
    def calculate_metrics(
        trades: List[Dict[str, Any]],
        initial_balance: float = 10000.0,
        compounding: bool = False,
    ) -> Dict[str, Any]:
        if not trades:
            return {
                "initial_balance": float(initial_balance),
                "final_balance": float(initial_balance),
                "net_profit_dollars": 0.0,
                "net_profit_pct": 0.0,
                "gross_profit_dollars": 0.0,
                "gross_loss_dollars": 0.0,
                "total_trades": 0,
                "closed_trades": 0,
                "forced_close_trades": 0,
                "open_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "win_rate_pct": 0.0,
                "profit_factor": 0.0,
                "expectancy_r": 0.0,
                "avg_win_pips": 0.0,
                "avg_loss_pips": 0.0,
                "avg_win_dollars": 0.0,
                "avg_loss_dollars": 0.0,
                "max_drawdown_pct": 0.0,
                "compounding_active": compounding,
                "max_simultaneous_positions": 1,
            }

        df_trades = pd.DataFrame(trades)
        total_trades = int(len(df_trades))
        
        # Ingestion stricte des résultats
        closed_trades_df = df_trades[df_trades["result"].isin(["WIN", "LOSS", "FORCED_CLOSE"])]
        normal_closed_df = df_trades[df_trades["result"].isin(["WIN", "LOSS"])]
        forced_closed_df = df_trades[df_trades["result"] == "FORCED_CLOSE"]
        open_trades_df = df_trades[df_trades["result"] == "OPEN"]

        wins = closed_trades_df[closed_trades_df["pips"] > 0]
        losses = closed_trades_df[closed_trades_df["pips"] <= 0]

        win_rate = (len(wins) / len(closed_trades_df)) * 100.0 if not closed_trades_df.empty else 0.0

        # Calcul du capital trade par trade
        balance = float(initial_balance)
        peak = balance
        max_drawdown_pct = 0.0
        
        gross_profit_dollars = 0.0
        gross_loss_dollars = 0.0

        for idx, row in closed_trades_df.iterrows():
            r_mult = float(row["r_multiple"])
            
            # Gestion du Compounding ON vs OFF
            if compounding:
                risk_dollars = balance * 0.01  # 1% du capital flottant
            else:
                risk_dollars = initial_balance * 0.01  # 1% du capital initial fixe ($100 fixes pour $10,000)

            trade_pnl = risk_dollars * r_mult
            balance += trade_pnl

            if trade_pnl > 0:
                gross_profit_dollars += trade_pnl
            else:
                gross_loss_dollars += abs(trade_pnl)

            if balance > peak:
                peak = balance
            dd = (peak - balance) / peak * 100.0
            if dd > max_drawdown_pct:
                max_drawdown_pct = dd

        profit_factor = (gross_profit_dollars / gross_loss_dollars) if gross_loss_dollars > 0 else (999.0 if gross_profit_dollars > 0 else 0.0)
        net_profit_dollars = balance - initial_balance
        net_profit_pct = (net_profit_dollars / initial_balance) * 100.0

        avg_win_pips = float(wins["pips"].mean()) if not wins.empty else 0.0
        avg_loss_pips = float(abs(losses["pips"].mean())) if not losses.empty else 0.0
        avg_r = float(closed_trades_df["r_multiple"].mean()) if not closed_trades_df.empty else 0.0

        avg_win_dollars = gross_profit_dollars / len(wins) if not wins.empty else 0.0
        avg_loss_dollars = gross_loss_dollars / len(losses) if not losses.empty else 0.0

        return {
            "initial_balance": round(float(initial_balance), 2),
            "final_balance": round(float(balance), 2),
            "net_profit_dollars": round(float(net_profit_dollars), 2),
            "net_profit_pct": round(float(net_profit_pct), 2),
            "gross_profit_dollars": round(float(gross_profit_dollars), 2),
            "gross_loss_dollars": round(float(gross_loss_dollars), 2),
            "total_trades": total_trades,
            "closed_trades": int(len(normal_closed_df)),
            "forced_close_trades": int(len(forced_closed_df)),
            "open_trades": int(len(open_trades_df)),
            "winning_trades": int(len(wins)),
            "losing_trades": int(len(losses)),
            "win_rate_pct": round(float(win_rate), 2),
            "profit_factor": round(float(profit_factor), 2),
            "expectancy_r": round(float(avg_r), 2),
            "avg_win_pips": round(float(avg_win_pips), 1),
            "avg_loss_pips": round(float(avg_loss_pips), 1),
            "avg_win_dollars": round(float(avg_win_dollars), 2),
            "avg_loss_dollars": round(float(avg_loss_dollars), 2),
            "max_drawdown_pct": round(float(max_drawdown_pct), 2),
            "compounding_active": compounding,
            "max_simultaneous_positions": 1,
        }
