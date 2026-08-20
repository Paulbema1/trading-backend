"""
TradeVision AI - Service de Données de Marché.

Responsabilités :
- Fournir des DataFrames OHLCV propres et typés
- Gérer la priorité CACHE -> API -> FALLBACK STALE
- Évaluer la qualité des données (GOOD, PARTIAL, POOR)
"""

import pandas as pd
from typing import Tuple, Optional
from datetime import datetime

from src.utils.cache import market_cache
from src.utils.helpers import normalize_symbol
from src.services.request_manager import request_manager
from src.schemas.signal import DataQualityEnum
from src.core.logging import get_logger

logger = get_logger(__name__)


class MarketDataService:
    """Service d'accès aux bougies et cours de marché."""

    async def get_candles_df(
        self,
        symbol: str,
        interval: str = "1h",
        outputsize: int = 200,
    ) -> Tuple[Optional[pd.DataFrame], DataQualityEnum]:
        """
        Récupère un DataFrame de bougies OHLCV.

        Retourne :
            (df, data_quality)
        """
        clean_symbol = normalize_symbol(symbol)

        # 1. Vérification dans le CACHE (Donnée fraîche)
        cached_df, is_stale = market_cache.get_ohlcv(
            clean_symbol,
            interval,
            outputsize,
            allow_stale=False,
        )
        if cached_df is not None and not cached_df.empty:
            return cached_df, DataQualityEnum.GOOD

        # 2. CACHE MISS -> Appel API Twelve Data via Request Manager
        params = {
            "symbol": clean_symbol,
            "interval": interval,
            "outputsize": outputsize,
            "format": "JSON",
        }

        data, err = await request_manager.execute_request("time_series", params)

        if data and "values" in data:
            values = data.get("values", [])
            if values:
                try:
                    df = pd.DataFrame(values)
                    # Standardisation des colonnes et types
                    df["datetime"] = pd.to_datetime(df["datetime"])
                    for col in ["open", "high", "low", "close"]:
                        df[col] = df[col].astype(float)

                    if "volume" in df.columns:
                        df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0.0)
                    else:
                        df["volume"] = 0.0

                    # Tri chronologique (le plus ancien en premier, le plus récent à la fin)
                    df = df.sort_values("datetime").reset_index(drop=True)

                    # Enregistrement dans le cache
                    market_cache.set_ohlcv(clean_symbol, interval, df, outputsize)

                    # Vérification du nombre de bougies reçues
                    if len(df) >= int(outputsize * 0.8):
                        return df, DataQualityEnum.GOOD
                    return df, DataQualityEnum.PARTIAL

                except Exception as e:
                    logger.error(f"Erreur de conversion pandas pour {clean_symbol} : {e}")

        # 3. Échec API -> Tentative de FALLBACK sur le CACHE PÉRIMÉ (STALE)
        stale_df, is_stale = market_cache.get_ohlcv(
            clean_symbol,
            interval,
            outputsize,
            allow_stale=True,
        )
        if stale_df is not None and not stale_df.empty:
            logger.warning(f"Utilisation du cache stale pour {clean_symbol} ({interval}). Qualité = PARTIAL.")
            return stale_df, DataQualityEnum.PARTIAL

        # 4. Données introuvables
        logger.error(f"Impossible de récupérer les données pour {clean_symbol} ({interval}) : {err}")
        return None, DataQualityEnum.POOR

    async def get_current_price(self, symbol: str) -> Tuple[Optional[float], DataQualityEnum]:
        """Récupère le prix actuel en temps réel."""
        clean_symbol = normalize_symbol(symbol)

        # 1. Vérification Cache
        cached_price, is_stale = market_cache.get_price(clean_symbol, allow_stale=False)
        if cached_price is not None:
            return cached_price, DataQualityEnum.GOOD

        # 2. Appel API
        data, err = await request_manager.execute_request("price", {"symbol": clean_symbol})
        if data and "price" in data:
            try:
                price = float(data["price"])
                market_cache.set_price(clean_symbol, price)
                return price, DataQualityEnum.GOOD
            except ValueError:
                pass

        # 3. Fallback sur le dernier cours OHLCV disponible
        df, quality = await self.get_candles_df(clean_symbol, interval="15m", outputsize=10)
        if df is not None and not df.empty:
            latest_close = float(df["close"].iloc[-1])
            return latest_close, DataQualityEnum.PARTIAL

        return None, DataQualityEnum.POOR


# Instance globale partagée
market_data_service = MarketDataService()