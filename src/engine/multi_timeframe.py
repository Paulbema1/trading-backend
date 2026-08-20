"""
TradeVision AI - Analyse Multi-Timeframe (MTF).

Barème : 20 points maximum
- Confluence entre l'UT Principale (ex: 1H) et l'UT de Confirmation (ex: 4H).
"""

import pandas as pd
from typing import Dict, Any
from src.engine.technical_analysis import technical_engine
from src.engine.smc import smc_engine


class MultiTimeframeEngine:
    """Vérifie l'alignement de la tendance sur plusieurs unités de temps."""

    def analyze_confluence(
        self,
        main_df: pd.DataFrame,
        confirm_df: pd.DataFrame,
    ) -> Dict[str, Any]:
        """
        Compare les signaux de l'UT principale et de confirmation sans re-télécharger de données.
        """
        if main_df is None or confirm_df is None:
            return {
                "score": 10,
                "alignment": "PARTIAL",
                "reasons": ["Une des unités de temps MTF est manquante."],
            }

        # Analyse légère sur le TF de confirmation (4H)
        confirm_ta = technical_engine.analyze(confirm_df)
        confirm_smc = smc_engine.analyze(confirm_df)

        confirm_bias = "NEUTRAL"
        if confirm_ta["bias"] == "BUY" or confirm_smc["bias"] == "BUY":
            confirm_bias = "BUY"
        elif confirm_ta["bias"] == "SELL" or confirm_smc["bias"] == "SELL":
            confirm_bias = "SELL"

        return {
            "confirm_bias": confirm_bias,
            "confirm_ta_score": confirm_ta["score"],
            "confirm_smc_score": confirm_smc["score"],
            "reasons": [f"Unité de temps supérieure (Confirmation) orientée {confirm_bias}."],
        }


# Instance globale
mtf_engine = MultiTimeframeEngine()