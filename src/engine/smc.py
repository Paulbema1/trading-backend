"""
TradeVision AI - Smart Money Concepts (SMC).

Barème : 30 points maximum
- Structure du marché (BOS / CHoCH) : 12 points
- Order Blocks institutionnels : 10 points
- Fair Value Gaps (FVG) / Imbalances : 5 points
- Balayages de liquidité (Liquidity Sweeps) : 3 points
"""

import pandas as pd
import numpy as np
from typing import Dict, Any, List, Optional


class SMCEngine:
    """Moteur d'analyse de la structure institutionnelle et Smart Money."""

    def _find_swing_points(self, df: pd.DataFrame, window: int = 3):
        """Identifie les Swing Highs et Swing Lows locaux."""
        highs = df["high"].values
        lows = df["low"].values
        n = len(df)

        swing_highs = []
        swing_lows = []

        for i in range(window, n - window):
            current_high = highs[i]
            if all(current_high >= highs[i - j] for j in range(1, window + 1)) and \
               all(current_high >= highs[i + j] for j in range(1, window + 1)):
                swing_highs.append((i, df["datetime"].iloc[i], current_high))

            current_low = lows[i]
            if all(current_low <= lows[i - j] for j in range(1, window + 1)) and \
               all(current_low <= lows[i + j] for j in range(1, window + 1)):
                swing_lows.append((i, df["datetime"].iloc[i], current_low))

        return swing_highs, swing_lows

    def _detect_fvg(self, df: pd.DataFrame) -> List[Dict[str, Any]]:
        """Détecte les Fair Value Gaps (FVG) récents non comblés."""
        fvgs = []
        for i in range(2, len(df)):
            c1_high = df["high"].iloc[i - 2]
            c1_low = df["low"].iloc[i - 2]
            c3_high = df["high"].iloc[i]
            c3_low = df["low"].iloc[i]

            # Bullish FVG
            if c3_low > c1_high:
                fvgs.append({
                    "type": "BULLISH_FVG",
                    "top": c3_low,
                    "bottom": c1_high,
                    "index": i - 1,
                })
            # Bearish FVG
            elif c3_high < c1_low:
                fvgs.append({
                    "type": "BEARISH_FVG",
                    "top": c1_low,
                    "bottom": c3_high,
                    "index": i - 1,
                })

        return fvgs[-5:]

    def analyze(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Analyse SMC complète sur les bougies fournies.
        """
        if df is None or len(df) < 40:
            return {
                "score": 0,
                "bias": "NEUTRAL",
                "structure": "UNKNOWN",
                "order_blocks": [],
                "fvg": [],
                "reasons": ["Données insuffisantes pour l'analyse SMC."],
            }

        df = df.copy()
        swing_highs, swing_lows = self._find_swing_points(df, window=3)
        fvgs = self._detect_fvg(df)

        buy_points = 0
        sell_points = 0
        reasons: List[str] = []
        structure = "RANGING"

        current_price = df["close"].iloc[-1]

        # ── A. Structure & BOS / CHoCH (12 points max) ───────────
        if len(swing_highs) >= 2 and len(swing_lows) >= 2:
            last_sh = swing_highs[-1][2]
            prev_sh = swing_highs[-2][2]
            last_sl = swing_lows[-1][2]
            prev_sl = swing_lows[-2][2]

            if last_sh > prev_sh and last_sl > prev_sl:
                structure = "BULLISH_STRUCTURE"
                buy_points += 12
                reasons.append("Structure institutionnelle haussière (HH + HL).")
            elif last_sh < prev_sh and last_sl < prev_sl:
                structure = "BEARISH_STRUCTURE"
                sell_points += 12
                reasons.append("Structure institutionnelle baissière (LH + LL).")
            elif current_price > last_sh:
                structure = "BOS_BULLISH"
                buy_points += 10
                reasons.append("Cassure haussière de structure (BOS) confirmée.")
            elif current_price < last_sl:
                structure = "BOS_BEARISH"
                sell_points += 10
                reasons.append("Cassure baissière de structure (BOS) confirmée.")
        else:
            # Tendance générale des prix sur 30 bougies
            if current_price > df["close"].iloc[-30]:
                structure = "BULLISH_STRUCTURE"
                buy_points += 8
            elif current_price < df["close"].iloc[-30]:
                structure = "BEARISH_STRUCTURE"
                sell_points += 8

        # ── B. Order Blocks (10 points max) ──────────────────────
        order_blocks = []
        for i in range(len(df) - 20, len(df) - 2):
            if df["close"].iloc[i] < df["open"].iloc[i]:  # Bougie baissière
                if df["close"].iloc[i + 1] > df["high"].iloc[i]:
                    ob_level = df["low"].iloc[i]
                    order_blocks.append({"type": "BULLISH_OB", "price": ob_level})
                    if 0 <= (current_price - ob_level) <= (current_price * 0.005):
                        buy_points += 10
                        reasons.append("Zone d'Order Block haussier active.")
                    break

        for i in range(len(df) - 20, len(df) - 2):
            if df["close"].iloc[i] > df["open"].iloc[i]:  # Bougie haussière
                if df["close"].iloc[i + 1] < df["low"].iloc[i]:
                    ob_level = df["high"].iloc[i]
                    order_blocks.append({"type": "BEARISH_OB", "price": ob_level})
                    if 0 <= (ob_level - current_price) <= (current_price * 0.005):
                        sell_points += 10
                        reasons.append("Zone d'Order Block baissier active.")
                    break

        # ── C. Fair Value Gaps (5 points max) ────────────────────
        for fvg in fvgs:
            if fvg["type"] == "BULLISH_FVG" and fvg["bottom"] <= current_price <= fvg["top"]:
                buy_points += 5
                reasons.append("Rejet / Remplissage d'un Fair Value Gap haussier.")
                break
            elif fvg["type"] == "BEARISH_FVG" and fvg["bottom"] <= current_price <= fvg["top"]:
                sell_points += 5
                reasons.append("Rejet / Remplissage d'un Fair Value Gap baissier.")
                break

        # ── D. Balayage de Liquidité (3 points max) ──────────────
        last_candle = df.iloc[-1]
        if swing_lows and last_candle["low"] < swing_lows[-1][2] and last_candle["close"] > swing_lows[-1][2]:
            buy_points += 3
            reasons.append("Balayage de liquidité acheteuse.")
        elif swing_highs and last_candle["high"] > swing_highs[-1][2] and last_candle["close"] < swing_highs[-1][2]:
            sell_points += 3
            reasons.append("Balayage de liquidité vendeuse.")

        # Calcul final du score SMC
        if buy_points > sell_points:
            bias = "BUY"
            score = min(30, max(5, buy_points))
        elif sell_points > buy_points:
            bias = "SELL"
            score = min(30, max(5, sell_points))
        else:
            bias = "NEUTRAL"
            score = 0

        return {
            "score": score,
            "bias": bias,
            "structure": structure,
            "order_blocks": order_blocks,
            "fvg": fvgs,
            "reasons": reasons,
        }


# Instance globale
smc_engine = SMCEngine()