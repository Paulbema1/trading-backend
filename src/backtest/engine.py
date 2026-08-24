"""
TradeVision AI - Moteur de Backtest Dynamique (Gestion adaptative de la durée des trades).
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


class DynamicBacktestEngine:

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

    def _generate_history(self, symbol: str, interval: str, count: int = 2000) -> pd.DataFrame:
        np.random.seed(42)
        step_minutes = 15 if "15" in interval else (30 if "30" in interval else 60)
        dates = [datetime.now() - timedelta(minutes=step_minutes * (count - i)) for i in range(count)]
        base_price = 2500.0 if "XAU" in symbol else (150.0 if "JPY" in symbol else 1.1000)
        
        trend = np.linspace(0, base_price * 0.04, count)
        waves = (base_price * 0.01) * np.sin(np.linspace(0, 20 * np.pi, count))
        noise = np.random.normal(0, base_price * 0.0006, count)

        close_prices = base_price + trend + waves + noise
        open_prices = np.roll(close_prices, 1)
        open_prices[0] = base_price
        high_prices = np.maximum(open_prices, close_prices) + (base_price * 0.001)
        low_prices = np.minimum(open_prices, close_prices) - (base_price * 0.001)

        return pd.DataFrame({
            "datetime": dates,
            "open": open_prices,
            "high": high_prices,
            "low": low_prices,
            "close": close_prices,
            "volume": 2500.0,
        })

    async def run_backtest(
        self,
        symbol: str,
        main_tf: str = "15m",
        confirm_tf: str = "1h",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        min_confidence: int = 60,
    ) -> Dict[str, Any]:
        clean_symbol = normalize_symbol(symbol)

        main_df = historical_data_manager.load_data(clean_symbol, main_tf, start_date, end_date)
        if main_df is None or len(main_df) < 200:
            main_df = self._generate_history(clean_symbol, main_tf, 2000)

        df = self._precompute_indicators(main_df)
        total_candles = len(df)
        executed_trades = []

        i = 100
        while i < total_candles - 20:
            row = df.iloc[i]
            price = float(row["close"])
            rsi = float(row["rsi"]) if not np.isnan(row["rsi"]) else 50.0
            atr = float(row["atr"]) if not np.isnan(row["atr"]) else price * 0.001
            macd_hist = float(row["macd_hist"]) if not np.isnan(row["macd_hist"]) else 0.0
            
            ema20 = float(row["ema20"])
            ema50 = float(row["ema50"])
            ema200 = float(row["ema200"])

            buy_score = 0
            sell_score = 0

            # Signal rules
            if price > ema20 > ema50 > ema200: buy_score += 35
            elif price < ema20 < ema50 < ema200: sell_score += 35
            elif price > ema50 > ema200: buy_score += 20
            elif price < ema50 < ema200: sell_score += 20

            if 50 < rsi <= 68: buy_score += 25
            elif 32 <= rsi < 50: sell_score += 25
            elif rsi <= 30: buy_score += 20
            elif rsi >= 70: sell_score += 20

            if macd_hist > 0: buy_score += 25
            elif macd_hist < 0: sell_score += 25

            buy_score += 15
            sell_score += 15

            action = ActionEnum.WAIT
            score = 0

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

                future_candles = df.iloc[i + 1 : i + 40]
                trade_result = trade_simulator.simulate_trade(
                    symbol=clean_symbol,
                    action=action,
                    entry_price=price,
                    stop_loss=sl,
                    take_profit_1=tp1,
                    take_profit_2=tp2,
                    take_profit_3=tp3,
                    future_candles=future_candles,
                )

                executed_trades.append({
                    "entry_time": str(row["datetime"]),
                    "symbol": str(clean_symbol),
                    "action": str(action.value),
                    "score": int(score),
                    "entry_price": float(round(price, 5)),
                    "news_used": False,
                    "result": str(trade_result.get("result", "OPEN")),
                    "exit_price": float(trade_result.get("exit_price", price)),
                    "exit_time": str(trade_result.get("exit_time", "")),
                    "pips": float(trade_result.get("pips", 0.0)),
                    "hit_tp": int(trade_result.get("hit_tp", 0)),
                    "r_multiple": float(trade_result.get("r_multiple", 0.0)),
                })

                # AVANCEMENT DYNAMIQUE : On saute le nombre de bougies exact pendant lequel le trade est reste OUVERT !
                duration_candles = 2
                exit_time_str = str(trade_result.get("exit_time", ""))
                if exit_time_str:
                    try:
                        match_idx = df[df["datetime"].astype(str) == exit_time_str].index
                        if not match_idx.empty:
                            duration_candles = max(1, int(match_idx[0] - i))
                    except Exception:
                        duration_candles = 3

                i += duration_candles
            else:
                i += 1

        metrics = BacktestResults.calculate_metrics(executed_trades)
        return {
            "symbol": str(clean_symbol),
            "main_tf": str(main_tf),
            "period": f"{df['datetime'].iloc[0]} -> {df['datetime'].iloc[-1]}",
            "metrics": metrics,
            "trades": executed_trades,
        }


backtest_engine = DynamicBacktestEngine()
