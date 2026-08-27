"""Analyse Multi-Timeframe sans lecture de bougie de confirmation non clôturée."""
from datetime import timedelta
from typing import Dict, Any
import pandas as pd
from src.engine.technical_analysis import technical_engine
from src.engine.smc import smc_engine

class MultiTimeframeEngine:
    def _duration(self, tf: str) -> timedelta:
        t = tf.lower().strip()
        if t == "15m": return timedelta(minutes=15)
        if t == "30m": return timedelta(minutes=30)
        if t == "1h": return timedelta(hours=1)
        if t == "4h": return timedelta(hours=4)
        return timedelta(hours=1)

    def analyze_confluence(self, main_df: pd.DataFrame, confirm_df: pd.DataFrame, confirm_tf: str = "4h", as_of=None) -> Dict[str, Any]:
        if main_df is None or main_df.empty or confirm_df is None or confirm_df.empty:
            return {"confirm_bias": "NEUTRAL", "score": 0, "alignment": "PARTIAL", "reasons": ["Données MTF insuffisantes."]}
        cdf = confirm_df.copy()
        if as_of is not None:
            cdf["datetime"] = pd.to_datetime(cdf["datetime"])
            cutoff = pd.Timestamp(as_of)
            if cutoff.tzinfo is not None and getattr(cdf["datetime"].dt, "tz", None) is None:
                cutoff = cutoff.tz_localize(None)
            cdf = cdf[(cdf["datetime"] + self._duration(confirm_tf)) <= cutoff]
        if cdf.empty:
            return {"confirm_bias": "NEUTRAL", "score": 0, "alignment": "WAIT", "reasons": ["Aucune bougie de confirmation clôturée disponible."]}
        confirm_ta = technical_engine.analyze(cdf)
        confirm_smc = smc_engine.analyze(cdf)
        if confirm_ta["bias"] == confirm_smc["bias"]:
            bias = confirm_ta["bias"]
        elif confirm_ta["bias"] != "NEUTRAL" and confirm_smc["bias"] == "NEUTRAL":
            bias = confirm_ta["bias"]
        elif confirm_smc["bias"] != "NEUTRAL" and confirm_ta["bias"] == "NEUTRAL":
            bias = confirm_smc["bias"]
        else:
            bias = "NEUTRAL"
        return {"confirm_bias": bias, "confirm_ta_score": confirm_ta["score"], "confirm_smc_score": confirm_smc["score"], "score": 20 if bias != "NEUTRAL" else 0, "alignment": bias, "reasons": [f"UT de confirmation clôturée orientée {bias}."]}

mtf_engine = MultiTimeframeEngine()
