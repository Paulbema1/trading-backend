"""
TradeVision AI - Utilitaires généraux.
"""

from typing import Optional
from datetime import datetime, timezone


def normalize_symbol(symbol: str) -> str:
    """
    Normalise le symbole pour Twelve Data et le moteur.
    Ex: "eurusd" -> "EUR/USD", "EURUSD" -> "EUR/USD"
    """
    s = symbol.upper().replace("-", "").replace("_", "")
    if "/" in s:
        return s

    if len(s) == 6:
        # Forex standard: EURUSD -> EUR/USD
        return f"{s[:3]}/{s[3:]}"

    if s.startswith("XAU") and len(s) == 6:
        return f"{s[:3]}/{s[3:]}"

    return s


def format_utc_now() -> str:
    """Retourne l'horodatage actuel en format ISO UTC."""
    return datetime.now(timezone.utc).isoformat()


def round_price(symbol: str, price: float) -> float:
    """Arrondit un prix selon l'actif (JPY: 3 décimales, XAU: 2, Forex: 5)."""
    if "JPY" in symbol:
        return round(price, 3)
    if "XAU" in symbol:
        return round(price, 2)
    return round(price, 5)