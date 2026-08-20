"""
TradeVision AI - Signal Engine Central.

Ce module orchestre toute la logique de génération du signal final.
"""

from typing import Optional, Dict, Any
import pandas as pd

from src.services.market_data import market_data_service
from src.services.news import news_service
from src.services.economic_calendar import economic_calendar_service
from src.engine.technical_analysis import technical_engine
from src.engine.smc import smc_engine
from src.engine.momentum import momentum_engine
from src.engine.context import market_context_engine
from src.engine.multi_timeframe import mtf_engine
from src.engine.ai_analysis import ai_engine
from src.schemas.signal import (
    SignalResponse,
    ActionEnum,
    DataQualityEnum,
    NewsStatusEnum,
)
from src.utils.helpers import round_price, normalize_symbol
from src.core.config import DEFAULT_MIN_CONFIDENCE
from src.core.logging import get_logger

logger = get_logger(__name__)


class SignalEngine:
    """Moteur central d'évaluation et de génération de signaux."""

    def _calculate_levels(
        self,
        symbol: str,
        action: ActionEnum,
        current_price: float,
        atr: float,
    ) -> Dict[str, float]:
        """Calcule les niveaux précis Entry, SL, TP1, TP2, TP3 et R:R."""
        # Multiplicateur ATR pour le SL (ex: 1.5 ATR)
        sl_distance = max(atr * 1.5, current_price * 0.0015)

        if action == ActionEnum.BUY:
            entry = current_price
            sl = entry - sl_distance
            tp1 = entry + (sl_distance * 1.5)
            tp2 = entry + (sl_distance * 2.5)
            tp3 = entry + (sl_distance * 3.5)
        elif action == ActionEnum.SELL:
            entry = current_price
            sl = entry + sl_distance
            tp1 = entry - (sl_distance * 1.5)
            tp2 = entry - (sl_distance * 2.5)
            tp3 = entry - (sl_distance * 3.5)
        else:
            return {}

        return {
            "entry_price": round_price(symbol, entry),
            "stop_loss": round_price(symbol, sl),
            "take_profit_1": round_price(symbol, tp1),
            "take_profit_2": round_price(symbol, tp2),
            "take_profit_3": round_price(symbol, tp3),
            "risk_reward": 2.5,
        }

    async def generate_signal(
        self,
        symbol: str,
        main_tf: str = "1h",
        confirm_tf: str = "4h",
    ) -> SignalResponse:
        """Génère l'analyse complète d'un actif."""
        clean_symbol = normalize_symbol(symbol)

        # ── 1. Récupération des données OHLCV (Cache ou Twelve Data) ────
        main_df, quality_main = await market_data_service.get_candles_df(clean_symbol, main_tf, 200)
        confirm_df, quality_confirm = await market_data_service.get_candles_df(clean_symbol, confirm_tf, 100)

        # Qualité globale des données
        if quality_main == DataQualityEnum.POOR or main_df is None or main_df.empty:
            return SignalResponse(
                symbol=clean_symbol,
                action=ActionEnum.WAIT,
                confidence=0,
                score=0,
                main_timeframe=main_tf,
                confirmation_timeframe=confirm_tf,
                data_quality=DataQualityEnum.POOR,
                reasons="Données de marché insuffisantes ou clés API indisponibles.",
            )

        current_price = float(main_df["close"].iloc[-1])

        # ── 2. Analyses Fondamentales & Calendrier ─────────────────────
        news_data = await news_service.analyze_sentiment(clean_symbol)
        calendar_data = await economic_calendar_service.get_upcoming_events(clean_symbol)

        # ── 3. Analyses Techniques & SMC ──────────────────────────────
        ta_res = technical_engine.analyze(main_df)
        smc_res = smc_engine.analyze(main_df)
        momentum_res = momentum_engine.analyze(main_df)
        regime_res = market_context_engine.evaluate_market_regime(main_df)
        mtf_res = mtf_engine.analyze_confluence(main_df, confirm_df)

        # ── 4. Confrontation Prix vs News ─────────────────────────────
        news_reaction = market_context_engine.evaluate_news_vs_price(
            main_df,
            news_bias=news_data.get("bias", "NEUTRAL"),
        )

        # ── 5. Calcul de l'orientation dominante (BUY ou SELL) ────────
        buy_weight = 0
        sell_weight = 0

        if ta_res["bias"] == "BUY":
            buy_weight += ta_res["score"]
        elif ta_res["bias"] == "SELL":
            sell_weight += ta_res["score"]

        if smc_res["bias"] == "BUY":
            buy_weight += smc_res["score"]
        elif smc_res["bias"] == "SELL":
            sell_weight += smc_res["score"]

        # MTF points
        mtf_points = 0
        if buy_weight > sell_weight and mtf_res.get("confirm_bias") == "BUY":
            mtf_points = 20
        elif sell_weight > buy_weight and mtf_res.get("confirm_bias") == "SELL":
            mtf_points = 20
        elif mtf_res.get("confirm_bias") == "NEUTRAL":
            mtf_points = 10

        # Orientation candidate
        candidate_action = ActionEnum.WAIT
        if buy_weight > sell_weight and buy_weight >= 20:
            candidate_action = ActionEnum.BUY
        elif sell_weight > buy_weight and sell_weight >= 20:
            candidate_action = ActionEnum.SELL

        # ── 6. Calcul du Score Global (0 à 100) ────────────────────────
        smc_score = smc_res["score"] if smc_res["bias"] == candidate_action.value else smc_res["score"] // 2
        ta_score = ta_res["score"] if ta_res["bias"] == candidate_action.value else ta_res["score"] // 2
        news_score = news_reaction["news_score"]
        cal_score = calendar_data["calendar_score"]
        mom_score = momentum_res["score"]
        ctx_score = regime_res["score"]

        total_score = smc_score + ta_score + mtf_points + news_score + cal_score + mom_score + ctx_score
        total_score = max(0, min(100, total_score))
        confidence = total_score

        breakdown = {
            "smc": smc_score,
            "technical": ta_score,
            "mtf": mtf_points,
            "news": news_score,
            "calendar": cal_score,
            "momentum": mom_score,
            "context": ctx_score,
        }

        all_reasons = ta_res["reasons"] + smc_res["reasons"] + momentum_res["reasons"]
        all_reasons.append(news_reaction["explanation"])

        # ── 7. Sécurités & Filtrages (Divergence News, Seuil < 70) ──────
        # Si contradiction News / Prix détectée -> Forcer WAIT
        if news_reaction["status"] == NewsStatusEnum.DIVERGENCE:
            candidate_action = ActionEnum.WAIT

        # Si score inférieur au seuil requis (70%) -> WAIT
        if total_score < DEFAULT_MIN_CONFIDENCE:
            candidate_action = ActionEnum.WAIT

        # ── 8. Niveaux de Trading & Confirmation IA ───────────────────
        levels = {}
        ai_confirmed = None
        atr = ta_res["indicators"].get("atr", current_price * 0.001)

        if candidate_action != ActionEnum.WAIT:
            levels = self._calculate_levels(clean_symbol, candidate_action, current_price, atr)

            # Audit IA
            ai_confirmed, ai_reason = await ai_engine.validate_signal(
                symbol=clean_symbol,
                candidate_action=candidate_action.value,
                score=total_score,
                breakdown=breakdown,
                reasons=all_reasons,
                news_summary=news_data.get("summary", ""),
            )

            if not ai_confirmed:
                candidate_action = ActionEnum.WAIT
                all_reasons.append(f"Refus de sécurité IA : {ai_reason}")

        # ── 9. Construction de la Réponse Finale ───────────────────────
        return SignalResponse(
            symbol=clean_symbol,
            action=candidate_action,
            confidence=confidence,
            score=total_score,
            entry_price=levels.get("entry_price"),
            stop_loss=levels.get("stop_loss"),
            take_profit_1=levels.get("take_profit_1"),
            take_profit_2=levels.get("take_profit_2"),
            take_profit_3=levels.get("take_profit_3"),
            risk_reward=levels.get("risk_reward"),
            main_timeframe=main_tf,
            confirmation_timeframe=confirm_tf,
            score_breakdown=breakdown,
            news_used=news_reaction["news_used"],
            news_status=news_reaction["status"],
            news_summary=news_reaction["explanation"],
            data_quality=quality_main,
            ai_confirmed=ai_confirmed,
            reasons=" | ".join(all_reasons[:4]),
        )


# Instance globale
signal_engine = SignalEngine()