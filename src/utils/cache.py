"""
TradeVision AI - Système de Cache Mémoire.

Gère la mise en cache :
- Des séries OHLCV par (symbol, interval, outputsize)
- Du dernier cours / prix par symbol

Supporte :
- TTL (Time-To-Live) configurable
- Fallback sur données périmées (stale cache) en cas de panne réseau / API
"""

import time
from typing import Any, Dict, Optional, Tuple
import pandas as pd

from src.core.logging import get_logger

logger = get_logger(__name__)


class MemoryCache:
    """Cache en mémoire thread-safe avec gestion de TTL et fallback stale."""

    def __init__(self):
        # Format: { key: (data, expiry_timestamp, created_timestamp) }
        self._ohlcv_store: Dict[str, Tuple[pd.DataFrame, float, float]] = {}
        self._price_store: Dict[str, Tuple[float, float, float]] = {}

        # TTL par défaut en secondes
        self.DEFAULT_OHLCV_TTL = {
            "15m": 60,      # 1 minute
            "30m": 120,     # 2 minutes
            "1h": 300,      # 5 minutes
            "4h": 900,      # 15 minutes
        }
        self.DEFAULT_PRICE_TTL = 30  # 30 secondes

    def _build_ohlcv_key(self, symbol: str, interval: str, outputsize: int) -> str:
        """Génère une clé unique pour une série de bougies."""
        clean_symbol = symbol.replace("/", "").upper()
        return f"OHLCV:{clean_symbol}:{interval}:{outputsize}"

    def _build_price_key(self, symbol: str) -> str:
        """Génère une clé unique pour le cours d'un actif."""
        clean_symbol = symbol.replace("/", "").upper()
        return f"PRICE:{clean_symbol}"

    # ── OHLCV Cache ──────────────────────────────────────────

    def get_ohlcv(
        self,
        symbol: str,
        interval: str,
        outputsize: int = 200,
        allow_stale: bool = False,
    ) -> Tuple[Optional[pd.DataFrame], bool]:
        """
        Récupère un DataFrame OHLCV du cache.

        Retourne :
            (df, is_stale)
            - df: le DataFrame pandas ou None si absent
            - is_stale: True si les données sont périmées mais retournées en fallback
        """
        key = self._build_ohlcv_key(symbol, interval, outputsize)
        entry = self._ohlcv_store.get(key)

        if not entry:
            return None, False

        df, expiry, _ = entry
        now = time.time()

        if now <= expiry:
            # Donnée fraîche
            logger.debug(f"[CACHE HIT] {key} (valide)")
            return df.copy(), False

        if allow_stale:
            # Donnée périmée acceptée en secours
            logger.warning(f"[CACHE STALE HIT] {key} (donnée expirée utilisée en fallback)")
            return df.copy(), True

        # Donnée expirée et stale refusé
        return None, False

    def set_ohlcv(
        self,
        symbol: str,
        interval: str,
        df: pd.DataFrame,
        outputsize: int = 200,
        ttl_seconds: Optional[int] = None,
    ) -> None:
        """Enregistre un DataFrame OHLCV dans le cache."""
        if df is None or df.empty:
            return

        key = self._build_ohlcv_key(symbol, interval, outputsize)
        ttl = ttl_seconds or self.DEFAULT_OHLCV_TTL.get(interval, 300)
        now = time.time()
        expiry = now + ttl

        self._ohlcv_store[key] = (df.copy(), expiry, now)
        logger.debug(f"[CACHE SET] {key} (TTL: {ttl}s)")

    # ── Price Cache ──────────────────────────────────────────

    def get_price(
        self,
        symbol: str,
        allow_stale: bool = False,
    ) -> Tuple[Optional[float], bool]:
        """Récupère le dernier prix mis en cache."""
        key = self._build_price_key(symbol)
        entry = self._price_store.get(key)

        if not entry:
            return None, False

        price, expiry, _ = entry
        now = time.time()

        if now <= expiry:
            return price, False

        if allow_stale:
            return price, True

        return None, False

    def set_price(
        self,
        symbol: str,
        price: float,
        ttl_seconds: Optional[int] = None,
    ) -> None:
        """Enregistre le dernier prix dans le cache."""
        key = self._build_price_key(symbol)
        ttl = ttl_seconds or self.DEFAULT_PRICE_TTL
        now = time.time()
        expiry = now + ttl

        self._price_store[key] = (price, expiry, now)

    # ── Maintenance ──────────────────────────────────────────

    def clear(self) -> None:
        """Vide l'intégralité du cache."""
        self._ohlcv_store.clear()
        self._price_store.clear()
        logger.info("Cache mémoire vidé.")


# Instance globale partagée
market_cache = MemoryCache()