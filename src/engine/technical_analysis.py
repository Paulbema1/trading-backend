"""
TradeVision AI - Analyse Technique Déterministe.

Barème : 25 points maximum
- EMAs (20, 50, 200) : Alignement et tendance (8 pts)
- RSI (14) : Niveaux et dynamiques (6 pts)
- MACD (12, 26, 9) : Ligne, signal et histogramme (6 pts)
- Bandes de Bollinger : Position et volatilité (5 pts)
"""

import numpy as np
import pandas as pd
from typing import Dict, Any, List


class TechnicalAnalysisEngine:
    """Moteur de calcul et de scoring des indicateurs techniques."""

    def _compute_rsi(self, series: pd.Series, period: int = 14) -> pd.Series:
        """Calcule le RSI standard."""
        delta = series.diff()
        gain = (delta.where(delta > 0, 0.0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0.0)).rolling(window=period).mean()
        rs = gain / (loss + 1e-9)
        return 100 - (100 / (1 + rs))

    def _compute_ema(self, series: pd.Series, span: int) -> pd.Series:
        """Calcule la Moyenne Mobile Exponentielle."""
        return series.ewm(span=span, adjust=False).mean()

    def _compute_atr(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Calcule l'Average True Range (ATR)."""
        high = df["high"]
        low = df["low"]
        close = df["close"].shift(1)
        tr1 = high - low
        tr2 = (high - close).abs()
        tr3 = (low - close).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return tr.rolling(window=period).mean()

    def analyze(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Analyse complète des indicateurs techniques sur le DataFrame.

        Retourne :
            score (0 à 25), bias ("BUY" | "SELL" | "NEUTRAL"), indicateurs et détails.
        """
        if df is None or len(df) < 50:
            return {
                "score": 0,
                "bias": "NEUTRAL",
                "indicators": {},
                "reasons": ["Données historiques insuffisantes pour l'analyse technique."],
            }

        df = df.copy()
        close = df["close"]

        # 1. Calcul des indicateurs
        df["ema20"] = self._compute_ema(close, 20)
        df["ema50"] = self._compute_ema(close, 50)
        df["ema200"] = self._compute_ema(close, 200)
        df["rsi"] = self._compute_rsi(close, 14)
        df["atr"] = self._compute_atr(df, 14)

        # MACD
        ema12 = self._compute_ema(close, 12)
        ema26 = self._compute_ema(close, 26)
        df["macd_line"] = ema12 - ema26
        df["macd_signal"] = self._compute_ema(df["macd_line"], 9)
        df["macd_hist"] = df["macd_line"] - df["macd_signal"]

        # Bollinger Bands (20, 2)
        sma20 = close.rolling(20).mean()
        std20 = close.rolling(20).std()
        df["bb_upper"] = sma20 + (std20 * 2)
        df["bb_lower"] = sma20 - (std20 * 2)
        df["bb_mid"] = sma20

        # Dernières valeurs
        last = df.iloc[-1]
        prev = df.iloc[-2]

        buy_points = 0
        sell_points = 0
        reasons: List[str] = []

        # ── A. Tendance EMAs (8 points max) ──────────────────────
        if last["close"] > last["ema20"] > last["ema50"] > last["ema200"]:
            buy_points += 8
            reasons.append("Alignement haussier parfait des EMAs (20 > 50 > 200).")
        elif last["close"] > last["ema50"] > last["ema200"]:
            buy_points += 5
            reasons.append("Tendance haussière confirmée au-dessus de l'EMA 50/200.")
        elif last["close"] < last["ema20"] < last["ema50"] < last["ema200"]:
            sell_points += 8
            reasons.append("Alignement baissier parfait des EMAs (20 < 50 < 200).")
        elif last["close"] < last["ema50"] < last["ema200"]:
            sell_points += 5
            reasons.append("Tendance baissière confirmée sous l'EMA 50/200.")

        # ── B. RSI (6 points max) ────────────────────────────────
        rsi_val = last["rsi"]
        if 50 < rsi_val <= 68:
            buy_points += 6
            reasons.append(f"RSI haussier équilibré ({rsi_val:.1f}).")
        elif 32 <= rsi_val < 50:
            sell_points += 6
            reasons.append(f"RSI baissier équilibré ({rsi_val:.1f}).")
        elif rsi_val <= 30:
            buy_points += 4
            reasons.append(f"RSI en survente ({rsi_val:.1f}) - Potentiel rebond.")
        elif rsi_val >= 70:
            sell_points += 4
            reasons.append(f"RSI en surachat ({rsi_val:.1f}) - Potentiel rejet.")

        # ── C. MACD (6 points max) ───────────────────────────────
        if last["macd_hist"] > 0 and last["macd_line"] > last["macd_signal"]:
            buy_points += 6
            if prev["macd_hist"] <= 0:
                reasons.append("Croisement haussier MACD récent.")
            else:
                reasons.append("Momentum haussier MACD soutenu.")
        elif last["macd_hist"] < 0 and last["macd_line"] < last["macd_signal"]:
            sell_points += 6
            if prev["macd_hist"] >= 0:
                reasons.append("Croisement baissier MACD récent.")
            else:
                reasons.append("Momentum baissier MACD soutenu.")

        # ── D. Bandes de Bollinger (5 points max) ────────────────
        if last["close"] > last["bb_mid"] and last["close"] < last["bb_upper"]:
            buy_points += 5
            reasons.append("Prix en zone haussière des bandes de Bollinger.")
        elif last["close"] < last["bb_mid"] and last["close"] > last["bb_lower"]:
            sell_points += 5
            reasons.append("Prix en zone baissière des bandes de Bollinger.")
        elif last["close"] <= last["bb_lower"]:
            buy_points += 3
            reasons.append("Rebond technique sur la bande inférieure de Bollinger.")
        elif last["close"] >= last["bb_upper"]:
            sell_points += 3
            reasons.append("Rejet technique sur la bande supérieure de Bollinger.")

        # Détermination du score et du biais final
        if buy_points > sell_points and buy_points >= 12:
            bias = "BUY"
            score = min(25, buy_points)
        elif sell_points > buy_points and sell_points >= 12:
            bias = "SELL"
            score = min(25, sell_points)
        else:
            bias = "NEUTRAL"
            score = max(buy_points, sell_points) // 2

        return {
            "score": score,
            "bias": bias,
            "indicators": {
                "rsi": round(float(last["rsi"]), 2) if not np.isnan(last["rsi"]) else 50.0,
                "atr": round(float(last["atr"]), 5) if not np.isnan(last["atr"]) else 0.001,
                "ema20": round(float(last["ema20"]), 5),
                "ema50": round(float(last["ema50"]), 5),
                "ema200": round(float(last["ema200"]), 5),
                "macd_hist": round(float(last["macd_hist"]), 6),
            },
            "reasons": reasons,
        }


# Instance globale
technical_engine = TechnicalAnalysisEngine()