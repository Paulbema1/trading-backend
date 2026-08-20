"""
TradeVision AI - Contexte de Marché & Arbitrage News/Prix.

Barème : 5 points (Contexte de marché)
Arbitrage : Statut de validation News par le prix
"""

import pandas as pd
from typing import Dict, Any
from src.schemas.signal import NewsStatusEnum


class MarketContextEngine:
    """Évalue le régime de volatilité et confronte le sentiment des news avec l'action du prix."""

    def evaluate_market_regime(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Détermine si le marché est en Tendance, en Range ou en Compression."""
        if df is None or len(df) < 20:
            return {"score": 3, "regime": "NORMAL", "reasons": []}

        atr = (df["high"] - df["low"]).rolling(14).mean()
        last_atr = atr.iloc[-1]
        avg_atr = atr.mean()

        if last_atr > avg_atr * 1.4:
            regime = "HIGH_VOLATILITY"
            score = 4
            desc = "Marché à forte volatilité (mouvements amples)."
        elif last_atr < avg_atr * 0.7:
            regime = "COMPRESSION"
            score = 2
            desc = "Marché en compression / faible volatilité."
        else:
            regime = "TRENDING_NORMAL"
            score = 5
            desc = "Conditions de liquidité et de tendance optimales."

        return {"score": score, "regime": regime, "reasons": [desc]}

    def evaluate_news_vs_price(
        self,
        df: pd.DataFrame,
        news_bias: str,
    ) -> Dict[str, Any]:
        """
        Confronte le biais de l'actualité avec la RÉACTION RÉELLE du prix.

        Le prix est l'arbitre suprême.
        """
        if news_bias == "NEUTRAL" or not news_bias or df is None or len(df) < 5:
            return {
                "status": NewsStatusEnum.NONE,
                "news_score": 5,
                "news_used": False,
                "explanation": "Aucun catalyseur fondamental majeur récent.",
            }

        # Variation sur les 5 dernières bougies
        recent_price_change = (df["close"].iloc[-1] - df["open"].iloc[-5]) / df["open"].iloc[-5] * 100

        # Cas 1 : Actualité BUY
        if news_bias == "BUY":
            if recent_price_change > 0.01:
                return {
                    "status": NewsStatusEnum.CONFIRMED,
                    "news_score": 10,
                    "news_used": True,
                    "explanation": "Actualité haussière validée par une hausse réelle du prix (+10 pts).",
                }
            elif recent_price_change < -0.01:
                return {
                    "status": NewsStatusEnum.DIVERGENCE,
                    "news_score": -15,  # Pénalité forte
                    "news_used": False,
                    "explanation": "CONTRADICTION : Actualité haussière mais le prix chute fortement !",
                }
            else:
                return {
                    "status": NewsStatusEnum.IGNORED,
                    "news_score": 3,
                    "news_used": False,
                    "explanation": "Actualité théoriquement haussière mais ignorée par le marché (impact neutre).",
                }

        # Cas 2 : Actualité SELL
        if news_bias == "SELL":
            if recent_price_change < -0.01:
                return {
                    "status": NewsStatusEnum.CONFIRMED,
                    "news_score": 10,
                    "news_used": True,
                    "explanation": "Actualité baissière validée par une chute réelle du prix (+10 pts).",
                }
            elif recent_price_change > 0.01:
                return {
                    "status": NewsStatusEnum.DIVERGENCE,
                    "news_score": -15,
                    "news_used": False,
                    "explanation": "CONTRADICTION : Actualité baissière mais le prix monte fortement !",
                }
            else:
                return {
                    "status": NewsStatusEnum.IGNORED,
                    "news_score": 3,
                    "news_used": False,
                    "explanation": "Actualité théoriquement baissière mais ignorée par le marché (impact neutre).",
                }

        return {
            "status": NewsStatusEnum.NONE,
            "news_score": 5,
            "news_used": False,
            "explanation": "Impact fondamental non déterminant.",
        }


# Instance globale
market_context_engine = MarketContextEngine()