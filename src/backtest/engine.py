"""
TradeVision AI - Moteur de Backtest Strictement Audité.

Prohibition absolue des données synthétiques. Zéro Look-Ahead Bias MTF.
"""

from typing import Dict, Any, Optional
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from src.backtest.historical_data import historical_data_manager
from src.backtest.simulator import trade_simulator
from src.backtest.results import BacktestResults
from src.schemas.signal import ActionEnum
from src.utils.helpers import normalize_symbol
from src.core.logging import get_logger

logger = get_logger(__name__)


class StrictAuditedBacktestEngine:

    def _get_tf_duration(self, tf: str) -> timedelta:
        tf_clean = tf.lower().strip()
        if "15" in tf_clean: return timedelta(minutes=15)
        if "30" in tf_clean: return timedelta(minutes=30)
        if "1h" in tf_clean or "1" in tf_clean: return timedelta(hours=1)
        if "4h" in tf_clean or "4" in tf_clean: return timedelta(hours=4)
        return timedelta(hours=1)

    def _precompute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        close = df["close"]
        high = df["high"]
        low = df["low"]

        df["ema20"] = close.ewm(span=20, adjust=False).mean()
        df["ema50"] = close.ewm(span=50, adjust=False).mean()
        df["ema200"] = close.ewm(span=200, adjust=False).mean()

        delta = close.diff()
        gain = (delta.where(delta > 0, 0.0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0.0)).rolling(14).mean()
        rs = gain / (loss + 1e-9)
        df["rsi"] = 100 - (100 / (1 + rs))

        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        df["macd_line"] = ema12 - ema26
        df["macd_signal"] = df["macd_line"].ewm(span=9, adjust=False).mean()
        df["macd_hist"] = df["macd_line"] - df["macd_signal"]

        prev_close = close.shift(1)
        tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
        df["atr"] = tr.rolling(14).mean()

        return df

    async def run_backtest(
        self,
        symbol: str,
        main_tf: str = "15m",
        confirm_tf: str = "1h",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        min_confidence: int = 70,
        compounding: bool = False,
    ) -> Dict[str, Any]:
        clean_symbol = normalize_symbol(symbol)
        confirm_duration = self._get_tf_duration(confirm_tf)

        # 1. Chargement des données historiques réelles
        main_df = historical_data_manager.load_data(clean_symbol, main_tf, start_date, end_date)
        confirm_df = historical_data_manager.load_data(clean_symbol, confirm_tf, start_date, end_date)

        # S'il n'y a pas de données locales -> Tentative de téléchargement réel Twelve Data
        if main_df is None or len(main_df) < 100:
            main_df = await historical_data_manager.download_historical_range(clean_symbol, main_tf, outputsize=5000)
            confirm_df = await historical_data_manager.download_historical_range(clean_symbol, confirm_tf, outputsize=2000)

        # PROHIBITION ABSOLUE DES DONNÉES SYNTHÉTIQUES
        if main_df is None or main_df.empty or len(main_df) < 100:
            return {
                "error": f"ERREUR : Données historiques réelles insuffisantes pour effectuer le backtest sur {clean_symbol}.",
                "data_source": "AUCUNE_DONNEE_HISTORIQUE_LOCALE",
                "symbol": clean_symbol,
                "main_tf": main_tf,
            }

        df = self._precompute_indicators(main_df)
        total_candles = len(df)
        executed_trades = []

        i = 100
        while i < total_candles - 1:
            row = df.iloc[i]
            current_time = row["datetime"]
            price = float(row["close"])
            rsi = float(row["rsi"]) if not np.isnan(row["rsi"]) else 50.0
            atr = float(row["atr"]) if not np.isnan(row["atr"]) else price * 0.001
            macd_hist = float(row["macd_hist"]) if not np.isnan(row["macd_hist"]) else 0.0

            ema20 = float(row["ema20"])
            ema50 = float(row["ema50"])
            ema200 = float(row["ema200"])

            # MTF FILTERING STRICT ZERO LOOK-AHEAD BIAS :
            # Seules les bougies de confirmation CLÔTURÉES (datetime + confirm_duration <= current_time) sont visibles
            confirm_bias = "NEUTRAL"
            if confirm_df is not None and not confirm_df.empty:
                closed_confirm_candles = confirm_df[(confirm_df["datetime"] + confirm_duration) <= current_time]
                if not closed_confirm_candles.empty:
                    last_confirm_close = closed_confirm_candles["close"].iloc[-1]
                    last_confirm_open = closed_confirm_candles["open"].iloc[-1]
                    if last_confirm_close > last_confirm_open:
                        confirm_bias = "BUY"
                    elif last_confirm_close < last_confirm_open:
                        confirm_bias = "SELL"

            buy_score = 0
            sell_score = 0

            # 1. EMAs
            if price > ema20 > ema50 > ema200: buy_score += 30
            elif price < ema20 < ema50 < ema200: sell_score += 30

            # 2. RSI
            if 50 < rsi <= 65: buy_score += 20
            elif 35 <= rsi < 50: sell_score += 20

            # 3. MACD
            if macd_hist > 0: buy_score += 20
            elif macd_hist < 0: sell_score += 20

            # 4. MTF Accord Strict
            if confirm_bias == "BUY": buy_score += 20
            elif confirm_bias == "SELL": sell_score += 20

            buy_score += 10
            sell_score += 10

            action = ActionEnum.WAIT
            if buy_score > sell_score and buy_score >= min_confidence:
                action = ActionEnum.BUY
                score = min(95, buy_score)
            elif sell_score > buy_score and sell_score >= min_confidence:
                action = ActionEnum.SELL
                score = min(95, sell_score)

            if action != ActionEnum.WAIT:
                sl_dist = max(atr * 1.5, price * 0.0015)
                if action == ActionEnum.BUY:
                    sl = price - sl_dist
                    tp1 = price + (sl_dist * 1.5)
                    tp2 = price + (sl_dist * 2.5)
                    tp3 = price + (sl_dist * 3.5)
                else:
                    sl = price + sl_dist
                    tp1 = price - (sl_dist * 1.5)
                    tp2 = price - (sl_dist * 2.5)
                    tp3 = price - (sl_dist * 3.5)

                future_candles = df.iloc[i + 1 :]
                trade_result = trade_simulator.simulate_trade(
                    symbol=clean_symbol,
                    action=action,
                    entry_price=price,
                    stop_loss=sl,
                    take_profit_1=tp1,
                    take_profit_2=tp2,
                    take_profit_3=tp3,
                    future_candles=future_candles,
                    start_index=i + 1,
                )

                executed_trades.append({
                    "entry_time": str(current_time.strftime("%Y-%m-%d %H:%M")),
                    "symbol": str(clean_symbol),
                    "action": str(action.value),
                    "score": int(score),
                    "entry_price": float(round(price, 5)),
                    "news_used": False,
                    "result": str(trade_result.get("result", "OPEN")),
                    "reason": str(trade_result.get("reason", "")),
                    "exit_price": float(trade_result.get("exit_price", price)),
                    "exit_time": str(trade_result.get("exit_time", "")),
                    "pips": float(trade_result.get("pips", 0.0)),
                    "hit_tp": int(trade_result.get("hit_tp", 0)),
                    "r_multiple": float(trade_result.get("r_multiple", 0.0)),
                })

                # RÈGLE D'OR 1 POSITION ACTIVE MAX : Saut immédiat jusqu'à l'index de clôture du trade !
                exit_idx = trade_result.get("exit_index", i + 1)
                i = max(i + 1, exit_idx + 1)
            else:
                i += 1

        metrics = BacktestResults.calculate_metrics(executed_trades, compounding=compounding)
        first_time = df['datetime'].iloc[0].strftime('%Y-%m-%d %H:%M')
        last_time = df['datetime'].iloc[-1].strftime('%Y-%m-%d %H:%M')

        return {
            "data_source": "DONNÉES HISTORIQUES RÉELLES PARQUET",
            "symbol": str(clean_symbol),
            "main_tf": str(main_tf),
            "confirmation_tf": str(confirm_tf),
            "loaded_candles": int(total_candles),
            "period": f"{first_time} -> {last_time}",
            "metrics": metrics,
            "trades": executed_trades,
        }


backtest_engine = StrictAuditedBacktestEngine()
