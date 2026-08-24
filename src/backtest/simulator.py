"""
TradeVision AI - Simulateur d'Exécution Conservateur (Pessimisme de Sécurité).
"""

from typing import Dict, Any
import pandas as pd
from src.schemas.signal import ActionEnum


class TradeSimulator:

    def __init__(self, spread_pips: float = 1.0):
        self.spread_pips = spread_pips

    def simulate_trade(
        self,
        symbol: str,
        action: ActionEnum,
        entry_price: float,
        stop_loss: float,
        take_profit_1: float,
        take_profit_2: float,
        take_profit_3: float,
        future_candles: pd.DataFrame,
    ) -> Dict[str, Any]:
        pip_unit = 0.01 if "JPY" in symbol else (0.1 if "XAU" in symbol else 0.0001)
        spread_cost = self.spread_pips * pip_unit

        actual_entry = entry_price + (spread_cost if action == ActionEnum.BUY else -spread_cost)

        for idx, row in future_candles.iterrows():
            high = float(row["high"])
            low = float(row["low"])
            candle_time_str = str(row["datetime"])

            # ── BUY ────────────────────────────────────────────────
            if action == ActionEnum.BUY:
                # Si SL et TP1 touches dans la MEME bougie -> REGLE CONSERVATRICE : PERTE (SL)
                if low <= stop_loss and high >= take_profit_1:
                    loss_pips = (actual_entry - stop_loss) / pip_unit
                    return {
                        "result": "LOSS",
                        "exit_price": round(stop_loss, 5),
                        "exit_time": candle_time_str,
                        "pips": -round(loss_pips, 1),
                        "hit_tp": 0,
                        "r_multiple": -1.0,
                    }

                if low <= stop_loss:
                    loss_pips = (actual_entry - stop_loss) / pip_unit
                    return {
                        "result": "LOSS",
                        "exit_price": round(stop_loss, 5),
                        "exit_time": candle_time_str,
                        "pips": -round(loss_pips, 1),
                        "hit_tp": 0,
                        "r_multiple": -1.0,
                    }

                if high >= take_profit_3:
                    gain_pips = (take_profit_3 - actual_entry) / pip_unit
                    return {"result": "WIN", "exit_price": round(take_profit_3, 5), "exit_time": candle_time_str, "pips": round(gain_pips, 1), "hit_tp": 3, "r_multiple": 3.5}
                if high >= take_profit_2:
                    gain_pips = (take_profit_2 - actual_entry) / pip_unit
                    return {"result": "WIN", "exit_price": round(take_profit_2, 5), "exit_time": candle_time_str, "pips": round(gain_pips, 1), "hit_tp": 2, "r_multiple": 2.5}
                if high >= take_profit_1:
                    gain_pips = (take_profit_1 - actual_entry) / pip_unit
                    return {"result": "WIN", "exit_price": round(take_profit_1, 5), "exit_time": candle_time_str, "pips": round(gain_pips, 1), "hit_tp": 1, "r_multiple": 1.5}

            # ── SELL ───────────────────────────────────────────────
            elif action == ActionEnum.SELL:
                if high >= stop_loss and low <= take_profit_1:
                    loss_pips = (stop_loss - actual_entry) / pip_unit
                    return {
                        "result": "LOSS",
                        "exit_price": round(stop_loss, 5),
                        "exit_time": candle_time_str,
                        "pips": -round(loss_pips, 1),
                        "hit_tp": 0,
                        "r_multiple": -1.0,
                    }

                if high >= stop_loss:
                    loss_pips = (stop_loss - actual_entry) / pip_unit
                    return {
                        "result": "LOSS",
                        "exit_price": round(stop_loss, 5),
                        "exit_time": candle_time_str,
                        "pips": -round(loss_pips, 1),
                        "hit_tp": 0,
                        "r_multiple": -1.0,
                    }

                if low <= take_profit_3:
                    gain_pips = (actual_entry - take_profit_3) / pip_unit
                    return {"result": "WIN", "exit_price": round(take_profit_3, 5), "exit_time": candle_time_str, "pips": round(gain_pips, 1), "hit_tp": 3, "r_multiple": 3.5}
                if low <= take_profit_2:
                    gain_pips = (actual_entry - take_profit_2) / pip_unit
                    return {"result": "WIN", "exit_price": round(take_profit_2, 5), "exit_time": candle_time_str, "pips": round(gain_pips, 1), "hit_tp": 2, "r_multiple": 2.5}
                if low <= take_profit_1:
                    gain_pips = (actual_entry - take_profit_1) / pip_unit
                    return {"result": "WIN", "exit_price": round(take_profit_1, 5), "exit_time": candle_time_str, "pips": round(gain_pips, 1), "hit_tp": 1, "r_multiple": 1.5}

        last_close = float(future_candles["close"].iloc[-1]) if not future_candles.empty else actual_entry
        return {
            "result": "OPEN",
            "exit_price": round(last_close, 5),
            "exit_time": str(future_candles["datetime"].iloc[-1]) if not future_candles.empty else "",
            "pips": 0.0,
            "hit_tp": 0,
            "r_multiple": 0.0,
        }


trade_simulator = TradeSimulator()
