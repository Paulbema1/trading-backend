"""
TradeVision AI - Simulateur d'Exécution Conservateur et Complet.
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
        start_index: int = 0,
    ) -> Dict[str, Any]:
        pip_unit = 0.01 if "JPY" in symbol else (0.1 if "XAU" in symbol else 0.0001)
        # v9 : niveaux calculés autour de l'Entry sans spread implicite non spécifié.
        actual_entry = entry_price

        for rel_idx, (abs_idx, row) in enumerate(future_candles.iterrows()):
            high = float(row["high"])
            low = float(row["low"])
            candle_time_str = str(row["datetime"])

            # ── BUY ────────────────────────────────────────────────
            if action == ActionEnum.BUY:
                sl_hit = low <= stop_loss
                tp1_hit = high >= take_profit_1

                # RÈGLE CONSERVATRICE INTRA-BOUGIE : Double franchissement = LOSS
                if sl_hit and tp1_hit:
                    loss_pips = (actual_entry - stop_loss) / pip_unit
                    return {
                        "result": "LOSS",
                        "reason": "SL_HIT_CONSERVATIVE",
                        "exit_price": round(stop_loss, 5),
                        "exit_time": candle_time_str,
                        "pips": -round(loss_pips, 1),
                        "hit_tp": 0,
                        "r_multiple": -1.0,
                        "exit_index": abs_idx,
                    }

                if sl_hit:
                    loss_pips = (actual_entry - stop_loss) / pip_unit
                    return {
                        "result": "LOSS",
                        "reason": "SL_HIT",
                        "exit_price": round(stop_loss, 5),
                        "exit_time": candle_time_str,
                        "pips": -round(loss_pips, 1),
                        "hit_tp": 0,
                        "r_multiple": -1.0,
                        "exit_index": abs_idx,
                    }

                if high >= take_profit_3:
                    gain_pips = (take_profit_3 - actual_entry) / pip_unit
                    return {"result": "WIN", "reason": "TP3_HIT", "exit_price": round(take_profit_3, 5), "exit_time": candle_time_str, "pips": round(gain_pips, 1), "hit_tp": 3, "r_multiple": 3.5, "exit_index": abs_idx}
                if high >= take_profit_2:
                    gain_pips = (take_profit_2 - actual_entry) / pip_unit
                    return {"result": "WIN", "reason": "TP2_HIT", "exit_price": round(take_profit_2, 5), "exit_time": candle_time_str, "pips": round(gain_pips, 1), "hit_tp": 2, "r_multiple": 2.5, "exit_index": abs_idx}
                if high >= take_profit_1:
                    gain_pips = (take_profit_1 - actual_entry) / pip_unit
                    return {"result": "WIN", "reason": "TP1_HIT", "exit_price": round(take_profit_1, 5), "exit_time": candle_time_str, "pips": round(gain_pips, 1), "hit_tp": 1, "r_multiple": 1.5, "exit_index": abs_idx}

            # ── SELL ───────────────────────────────────────────────
            elif action == ActionEnum.SELL:
                sl_hit = high >= stop_loss
                tp1_hit = low <= take_profit_1

                if sl_hit and tp1_hit:
                    loss_pips = (stop_loss - actual_entry) / pip_unit
                    return {
                        "result": "LOSS",
                        "reason": "SL_HIT_CONSERVATIVE",
                        "exit_price": round(stop_loss, 5),
                        "exit_time": candle_time_str,
                        "pips": -round(loss_pips, 1),
                        "hit_tp": 0,
                        "r_multiple": -1.0,
                        "exit_index": abs_idx,
                    }

                if sl_hit:
                    loss_pips = (stop_loss - actual_entry) / pip_unit
                    return {
                        "result": "LOSS",
                        "reason": "SL_HIT",
                        "exit_price": round(stop_loss, 5),
                        "exit_time": candle_time_str,
                        "pips": -round(loss_pips, 1),
                        "hit_tp": 0,
                        "r_multiple": -1.0,
                        "exit_index": abs_idx,
                    }

                if low <= take_profit_3:
                    gain_pips = (actual_entry - take_profit_3) / pip_unit
                    return {"result": "WIN", "reason": "TP3_HIT", "exit_price": round(take_profit_3, 5), "exit_time": candle_time_str, "pips": round(gain_pips, 1), "hit_tp": 3, "r_multiple": 3.5, "exit_index": abs_idx}
                if low <= take_profit_2:
                    gain_pips = (actual_entry - take_profit_2) / pip_unit
                    return {"result": "WIN", "reason": "TP2_HIT", "exit_price": round(take_profit_2, 5), "exit_time": candle_time_str, "pips": round(gain_pips, 1), "hit_tp": 2, "r_multiple": 2.5, "exit_index": abs_idx}
                if low <= take_profit_1:
                    gain_pips = (actual_entry - take_profit_1) / pip_unit
                    return {"result": "WIN", "reason": "TP1_HIT", "exit_price": round(take_profit_1, 5), "exit_time": candle_time_str, "pips": round(gain_pips, 1), "hit_tp": 1, "r_multiple": 1.5, "exit_index": abs_idx}

        # ── FIN DU DATASET : FORCED CLOSE ───────────────────────
        last_row = future_candles.iloc[-1]
        last_close = float(last_row["close"])
        if action == ActionEnum.BUY:
            pips = (last_close - actual_entry) / pip_unit
            r_mult = (last_close - actual_entry) / (actual_entry - stop_loss)
        else:
            pips = (actual_entry - last_close) / pip_unit
            r_mult = (actual_entry - last_close) / (stop_loss - actual_entry)

        return {
            "result": "FORCED_CLOSE",
            "reason": "END_OF_DATASET",
            "exit_price": round(last_close, 5),
            "exit_time": str(last_row["datetime"]),
            "pips": round(pips, 1),
            "hit_tp": 0,
            "r_multiple": round(r_mult, 2),
            "exit_index": len(future_candles) + start_index - 1,
        }


trade_simulator = TradeSimulator()
