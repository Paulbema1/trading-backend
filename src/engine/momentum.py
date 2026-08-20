"""
TradeVision AI - Analyse du Momentum.

Barème : 5 points maximum
- Vitesse du prix (ROC)
- Force des corps de bougies vs mèches
- Dynamique de l'accélération
"""

import pandas as pd
import numpy as np
from typing import Dict, Any


class MomentumEngine:
    """Évalue la vélocité et l'accélération du mouvement."""

    def analyze(self, df: pd.DataFrame) -> Dict[str, Any]:
        if df is None or len(df) < 10:
            return {"score": 2, "bias": "NEUTRAL", "reasons": []}

        # 1. Rate of change (ROC sur 5 périodes)
        roc = ((df["close"].iloc[-1] - df["close"].iloc[-5]) / df["close"].iloc[-5]) * 100

        # 2. Ratio corps/mèche sur les 3 dernières bougies
        bodies = (df["close"].iloc[-3:] - df["open"].iloc[-3:]).abs()
        ranges = (df["high"].iloc[-3:] - df["low"].iloc[-3:]) + 1e-9
        body_ratio = float((bodies / ranges).mean())

        # 3. Direction des dernières bougies
        green_candles = (df["close"].iloc[-3:] > df["open"].iloc[-3:]).sum()

        if roc > 0.15 and green_candles >= 2 and body_ratio > 0.55:
            return {
                "score": 5,
                "bias": "BUY",
                "reasons": ["Fort momentum acheteur avec bougies pleines."],
            }
        elif roc < -0.15 and green_candles <= 1 and body_ratio > 0.55:
            return {
                "score": 5,
                "bias": "SELL",
                "reasons": ["Fort momentum vendeur avec pression continue."],
            }

        return {
            "score": 3,
            "bias": "NEUTRAL",
            "reasons": ["Momentum stable sans accélération extrême."],
        }


# Instance globale
momentum_engine = MomentumEngine()