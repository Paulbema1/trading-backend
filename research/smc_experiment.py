"""
Expérience SMC v2 - RECHERCHE UNIQUEMENT (aucun fichier de src/ n'est modifié).

Variantes :
  - "ob"    : Order Blocks améliorés (le plus récent, avec impulsion forte,
              non mitigé, proximité mesurée en ATR au lieu de 0.5 % du prix).
  - "ob_sr" : idem + zones de support / résistance (swings regroupés en zones,
              au moins 2 touches), +5 points si le prix est proche d'une zone
              dans le sens du signal.
Le score SMC reste plafonné à 30, comme en prod.
"""
import numpy as np
import pandas as pd

from src.engine.smc import SMCEngine

OB_LOOKBACK = 50
OB_IMPULSE_ATR = 1.0      # corps de la bougie d'impulsion >= 1 ATR
OB_NEAR_ATR = 1.0         # distance max au bord de la zone, en ATR
SR_LOOKBACK = 300
SR_SWING_WINDOW = 5
SR_MIN_TOUCHES = 2
SR_CLUSTER_ATR = 0.5
SR_NEAR_ATR = 1.0
SR_POINTS = 5


def _atr(df, period=14):
    h = df["high"].values[-(period + 1):]
    l = df["low"].values[-(period + 1):]
    c = df["close"].values[-(period + 1):]
    tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
    return float(tr.mean())


def _sr_zones(df, atr):
    """Retourne la liste des zones (bas, haut, touches) issues des swings."""
    d = df.iloc[-SR_LOOKBACK:]
    w = SR_SWING_WINDOW
    levels = []
    for col, fn in (("high", "max"), ("low", "min")):
        s = d[col].reset_index(drop=True)
        ext = getattr(s.rolling(2 * w + 1, center=True), fn)()
        levels.extend(s[(s == ext) & ext.notna()].tolist())
    if not levels:
        return []
    levels.sort()
    zones, cur = [], [levels[0]]
    for lv in levels[1:]:
        if lv - cur[-1] <= SR_CLUSTER_ATR * atr:
            cur.append(lv)
        else:
            zones.append(cur)
            cur = [lv]
    zones.append(cur)
    return [(min(z), max(z), len(z)) for z in zones if len(z) >= SR_MIN_TOUCHES]


class ExperimentalSMC(SMCEngine):
    def __init__(self, variant="ob"):
        self.variant = variant

    def analyze(self, df):
        if df is None or len(df) < 40:
            return {"score": 0, "bias": "NEUTRAL", "structure": "UNKNOWN",
                    "order_blocks": [], "fvg": [],
                    "reasons": ["Données insuffisantes pour l'analyse SMC."]}

        df = df.copy()
        swing_highs, swing_lows = self._find_swing_points(df, window=3)
        fvgs = self._detect_fvg(df)
        buy_points = 0
        sell_points = 0
        reasons = []
        structure = "RANGING"
        current_price = float(df["close"].iloc[-1])
        atr = _atr(df)
        if not np.isfinite(atr) or atr <= 0:
            atr = current_price * 0.001

        # A. Structure (identique à la prod)
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
            if current_price > df["close"].iloc[-30]:
                structure = "BULLISH_STRUCTURE"
                buy_points += 8
            elif current_price < df["close"].iloc[-30]:
                structure = "BEARISH_STRUCTURE"
                sell_points += 8

        # B. Order Blocks améliorés
        o = df["open"].values
        h = df["high"].values
        l = df["low"].values
        c = df["close"].values
        n = len(df)
        order_blocks = []
        lo_idx = max(1, n - OB_LOOKBACK)

        for i in range(n - 3, lo_idx - 1, -1):  # OB haussier : le plus récent
            if c[i] < o[i] and c[i + 1] > h[i] and (c[i + 1] - o[i + 1]) >= OB_IMPULSE_ATR * atr:
                if np.all(c[i + 2:] >= l[i]):  # non mitigé
                    bottom, top = float(l[i]), float(h[i])
                    order_blocks.append({"type": "BULLISH_OB", "price": bottom})
                    if current_price >= bottom and (current_price - top) <= OB_NEAR_ATR * atr:
                        buy_points += 10
                        reasons.append("Zone d'Order Block haussier active.")
                    break
        for i in range(n - 3, lo_idx - 1, -1):  # OB baissier : le plus récent
            if c[i] > o[i] and c[i + 1] < l[i] and (o[i + 1] - c[i + 1]) >= OB_IMPULSE_ATR * atr:
                if np.all(c[i + 2:] <= h[i]):
                    bottom, top = float(l[i]), float(h[i])
                    order_blocks.append({"type": "BEARISH_OB", "price": top})
                    if current_price <= top and (bottom - current_price) <= OB_NEAR_ATR * atr:
                        sell_points += 10
                        reasons.append("Zone d'Order Block baissier active.")
                    break

        # B2. Zones de support / résistance (variante ob_sr)
        if self.variant == "ob_sr":
            sup_hit = res_hit = False
            for bottom, top, touches in _sr_zones(df, atr):
                center = (bottom + top) / 2
                dist = 0.0 if bottom <= current_price <= top else min(abs(current_price - bottom), abs(current_price - top))
                if dist > SR_NEAR_ATR * atr:
                    continue
                if center <= current_price:
                    sup_hit = True
                else:
                    res_hit = True
            if sup_hit and not res_hit:
                buy_points += SR_POINTS
                reasons.append("Prix proche d'une zone de support.")
            elif res_hit and not sup_hit:
                sell_points += SR_POINTS
                reasons.append("Prix proche d'une zone de résistance.")

        # C. FVG (identique à la prod)
        for fvg in fvgs:
            if fvg["type"] == "BULLISH_FVG" and fvg["bottom"] <= current_price <= fvg["top"]:
                buy_points += 5
                reasons.append("Rejet / Remplissage d'un Fair Value Gap haussier.")
                break
            elif fvg["type"] == "BEARISH_FVG" and fvg["bottom"] <= current_price <= fvg["top"]:
                sell_points += 5
                reasons.append("Rejet / Remplissage d'un Fair Value Gap baissier.")
                break

        # D. Balayage de liquidité (identique à la prod)
        last_candle = df.iloc[-1]
        if swing_lows and last_candle["low"] < swing_lows[-1][2] and last_candle["close"] > swing_lows[-1][2]:
            buy_points += 3
            reasons.append("Balayage de liquidité acheteuse.")
        elif swing_highs and last_candle["high"] > swing_highs[-1][2] and last_candle["close"] < swing_highs[-1][2]:
            sell_points += 3
            reasons.append("Balayage de liquidité vendeuse.")

        if buy_points > sell_points:
            bias, score = "BUY", min(30, max(5, buy_points))
        elif sell_points > buy_points:
            bias, score = "SELL", min(30, max(5, sell_points))
        else:
            bias, score = "NEUTRAL", 0

        return {"score": score, "bias": bias, "structure": structure,
                "order_blocks": order_blocks, "fvg": fvgs, "reasons": reasons}
