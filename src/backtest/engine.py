"""
TradeVision AI - Moteur de Backtest (Replay Temporel).

Exécute la stratégie sur 1 à 2 ans d'historique avec 0 requête Twelve Data.
"""

from typing import Dict, Any, Optional
import pandas as pd

from src.backtest.historical_data import historical_data_manager
from src.backtest.historical_news import historical_news_manager
from src.backtest.simulator import trade_simulator
from src.backtest.results import BacktestResults
from src.engine.technical_analysis import technical_engine
from src.engine.smc import smc_engine
from src.engine.momentum import momentum_engine
from src.engine.context import market_context_engine
from src.engine.multi_timeframe import mtf_engine
from src.schemas.signal import ActionEnum, NewsStatusEnum
from src.core.config import DEFAULT_MIN_CONFIDENCE
from src.utils.helpers import normalize_symbol
from src.core.logging import get_logger

logger = get_logger(__name__)


class BacktestEngine:
    """Moteur d'exécution historique déterministe."""

    def run_backtest(
        self,
        symbol: str,
        main_tf: str = "1h",
        confirm_tf: str = "4h",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        min_confidence: int = DEFAULT_MIN_CONFIDENCE,
    ) -> Dict[str, Any]:
        """
        Lance le backtest complet sur les fichiers Parquet locaux.
        """
        clean_symbol = normalize_symbol(symbol)

        # 1. Chargement des données Parquet locales (0 crédit Twelve Data)
        main_df = historical_data_manager.load_data(clean_symbol, main_tf, start_date, end_date)
        confirm_df = historical_data_manager.load_data(clean_symbol, confirm_tf, start_date, end_date)

        if main_df is None or len(main_df) < 150:
            return {"error": f"Données insuffisantes dans le stockage local pour {clean_symbol}."}

        logger.info(f"🚀 Lancement du backtest sur {clean_symbol} ({len(main_df)} bougies)...")

        executed_trades = []
        warmup_period = 100  # 100 bougies nécessaires pour initialiser les EMAs et SMC
        total_candles = len(main_df)

        i = warmup_period
        while i < total_candles - 20:
            current_time = main_df["datetime"].iloc[i]

            # DÉCOUPAGE STRICT DU PASSÉ (ZÉRO LOOK-AHEAD BIAS)
            current_slice_main = main_df.iloc[: i + 1].copy()
            current_slice_confirm = (
                confirm_df[confirm_df["datetime"] <= current_time].copy()
                if confirm_df is not None else None
            )

            current_price = float(current_slice_main["close"].iloc[-1])

            # 2. Contexte Fondamental Horodaté
            news_data = historical_news_manager.get_news_context_at(clean_symbol, current_time)
            calendar_data = historical_news_manager.get_calendar_context_at(clean_symbol, current_time)

            # 3. Calculs des Moteurs
            ta_res = technical_engine.analyze(current_slice_main)
            smc_res = smc_engine.analyze(current_slice_main)
            momentum_res = momentum_engine.analyze(current_slice_main)
            regime_res = market_context_engine.evaluate_market_regime(current_slice_main)
            mtf_res = (
                mtf_engine.analyze_confluence(current_slice_main, current_slice_confirm)
                if current_slice_confirm is not None and len(current_slice_confirm) >= 30
                else {"confirm_bias": "NEUTRAL"}
            )

            # Confrontation Prix vs News
            news_reaction = market_context_engine.evaluate_news_vs_price(
                current_slice_main, news_bias=news_data.get("bias", "NEUTRAL")
            )

            # 4. Orientation & Score Global (0-100)
            buy_weight = (ta_res["score"] if ta_res["bias"] == "BUY" else 0) + (smc_res["score"] if smc_res["bias"] == "BUY" else 0)
            sell_weight = (ta_res["score"] if ta_res["bias"] == "SELL" else 0) + (smc_res["score"] if smc_res["bias"] == "SELL" else 0)

            mtf_points = 20 if (buy_weight > sell_weight and mtf_res.get("confirm_bias") == "BUY") or (sell_weight > buy_weight and mtf_res.get("confirm_bias") == "SELL") else 10

            candidate_action = ActionEnum.WAIT
            if buy_weight > sell_weight and buy_weight >= 20:
                candidate_action = ActionEnum.BUY
            elif sell_weight > buy_weight and sell_weight >= 20:
                candidate_action = ActionEnum.SELL

            total_score = (
                (smc_res["score"] if smc_res["bias"] == candidate_action.value else smc_res["score"] // 2)
                + (ta_res["score"] if ta_res["bias"] == candidate_action.value else ta_res["score"] // 2)
                + mtf_points
                + news_reaction["news_score"]
                + calendar_data["calendar_score"]
                + momentum_res["score"]
                + regime_res["score"]
            )
            total_score = max(0, min(100, total_score))

            # Filtrages
            if (
                total_score >= min_confidence
                and candidate_action != ActionEnum.WAIT
                and news_reaction["status"] != NewsStatusEnum.DIVERGENCE
            ):
                # 5. Calcul des Niveaux
                atr = ta_res["indicators"].get("atr", current_price * 0.001)
                sl_dist = max(atr * 1.5, current_price * 0.0015)

                if candidate_action == ActionEnum.BUY:
                    sl = current_price - sl_dist
                    tp1 = current_price + (sl_dist * 1.5)
                    tp2 = current_price + (sl_dist * 2.5)
                    tp3 = current_price + (sl_dist * 3.5)
                else:
                    sl = current_price + sl_dist
                    tp1 = current_price - (sl_dist * 1.5)
                    tp2 = current_price - (sl_dist * 2.5)
                    tp3 = current_price - (sl_dist * 3.5)

                # 6. Simulation du futur
                future_candles = main_df.iloc[i + 1 : i + 50].copy()
                trade_result = trade_simulator.simulate_trade(
                    symbol=clean_symbol,
                    action=candidate_action,
                    entry_price=current_price,
                    stop_loss=sl,
                    take_profit_1=tp1,
                    take_profit_2=tp2,
                    take_profit_3=tp3,
                    future_candles=future_candles,
                )

                executed_trades.append({
                    "entry_time": current_time,
                    "symbol": clean_symbol,
                    "action": candidate_action.value,
                    "score": total_score,
                    "entry_price": current_price,
                    "news_used": news_reaction["news_used"],
                    **trade_result,
                })

                # On avance de quelques bougies pour ne pas re-trader la même vague
                i += 5
            else:
                i += 1

        metrics = BacktestResults.calculate_metrics(executed_trades)
        logger.info(f"✅ Backtest terminé : {metrics.get('win_rate_pct')}% Win Rate sur {metrics.get('total_trades')} trades.")
        return {
            "symbol": clean_symbol,
            "main_tf": main_tf,
            "period": f"{main_df['datetime'].iloc[0]} -> {main_df['datetime'].iloc[-1]}",
            "metrics": metrics,
            "trades": executed_trades,
        }


backtest_engine = BacktestEngine()