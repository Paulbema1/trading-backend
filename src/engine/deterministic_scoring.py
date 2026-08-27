"""Scoring déterministe v9 partagé par le live et le backtest."""
from typing import Dict, Any
import pandas as pd
from src.engine.technical_analysis import technical_engine
from src.engine.smc import smc_engine
from src.engine.momentum import momentum_engine
from src.engine.context import market_context_engine
from src.engine.multi_timeframe import mtf_engine
from src.schemas.signal import ActionEnum, NewsStatusEnum

class DeterministicScoringEngine:
    def evaluate(self, main_df: pd.DataFrame, confirm_df: pd.DataFrame, news_data: Dict[str, Any], calendar_data: Dict[str, Any], confirm_tf: str = "4h", as_of=None) -> Dict[str, Any]:
        ta = technical_engine.analyze(main_df)
        smc = smc_engine.analyze(main_df)
        mom = momentum_engine.analyze(main_df)
        ctx = market_context_engine.evaluate_market_regime(main_df)
        mtf = mtf_engine.analyze_confluence(main_df, confirm_df, confirm_tf=confirm_tf, as_of=as_of)
        news = market_context_engine.evaluate_news_vs_price(main_df, news_data.get("bias", "NEUTRAL"))

        buy_weight = ta["score"] if ta["bias"] == "BUY" else 0
        sell_weight = ta["score"] if ta["bias"] == "SELL" else 0
        buy_weight += smc["score"] if smc["bias"] == "BUY" else 0
        sell_weight += smc["score"] if smc["bias"] == "SELL" else 0

        if buy_weight > sell_weight and buy_weight >= 20:
            candidate = ActionEnum.BUY
        elif sell_weight > buy_weight and sell_weight >= 20:
            candidate = ActionEnum.SELL
        else:
            candidate = ActionEnum.WAIT

        mtf_points = 20 if candidate != ActionEnum.WAIT and mtf.get("confirm_bias") == candidate.value else 0
        smc_score = smc["score"] if smc["bias"] == candidate.value else (smc["score"] // 2 if candidate != ActionEnum.WAIT else 0)
        ta_score = ta["score"] if ta["bias"] == candidate.value else (ta["score"] // 2 if candidate != ActionEnum.WAIT else 0)
        total = max(0, min(100, smc_score + ta_score + mtf_points + int(news["news_score"]) + int(calendar_data.get("calendar_score", 5)) + int(mom["score"]) + int(ctx["score"])))

        if news["status"] == NewsStatusEnum.DIVERGENCE or total < 70:
            final_candidate = ActionEnum.WAIT
        else:
            final_candidate = candidate

        reasons = ta["reasons"] + smc["reasons"] + mom["reasons"] + ctx["reasons"]
        reasons.append(news["explanation"])
        if calendar_data.get("summary"):
            reasons.append(calendar_data["summary"])
        if mtf.get("reasons"):
            reasons.extend(mtf["reasons"])

        return {
            "action": final_candidate,
            "candidate_action": candidate,
            "score": total,
            "confidence": total,
            "breakdown": {"smc": smc_score, "technical": ta_score, "mtf": mtf_points, "news": int(news["news_score"]), "calendar": int(calendar_data.get("calendar_score", 5)), "momentum": int(mom["score"]), "context": int(ctx["score"])},
            "news": news,
            "ta": ta,
            "smc": smc,
            "momentum": mom,
            "context": ctx,
            "mtf": mtf,
            "reasons": reasons,
        }

deterministic_scoring_engine = DeterministicScoringEngine()
