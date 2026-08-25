"""
TradeVision AI - Service de Données de Marché.
"""

import pandas as pd
from typing import Tuple, Optional

from src.utils.cache import market_cache
from src.utils.helpers import normalize_symbol
from src.services.request_manager import request_manager
from src.schemas.signal import DataQualityEnum
from src.core.logging import get_logger

logger = get_logger(__name__)


class MarketDataService:

    def _normalize_interval_for_twelve_data(self, interval: str) -> str:
        inv = interval.lower().strip()
        if inv == "15m": return "15min"
        if inv == "30m": return "30min"
        return inv

    async def get_candles_df(
        self,
        symbol: str,
        interval: str = "1h",
        outputsize: int = 200,
    ) -> Tuple[Optional[pd.DataFrame], DataQualityEnum]:
        clean_symbol = normalize_symbol(symbol)
        api_interval = self._normalize_interval_for_twelve_data(interval)

        # 1. Cache
        cached_df, is_stale = market_cache.get_ohlcv(
            clean_symbol,
            interval,
            outputsize,
            allow_stale=False,
        )
        if cached_df is not None and not cached_df.empty:
            return cached_df, DataQualityEnum.GOOD

        # 2. Appel API Twelve Data
        params = {
            "symbol": clean_symbol,
            "interval": api_interval,
            "outputsize": outputsize,
            "format": "JSON",
        }

        data, err = await request_manager.execute_request("time_series", params)

        if data and "values" in data:
            values = data.get("values", [])
            if values:
                try:
                    df = pd.DataFrame(values)
                    df["datetime"] = pd.to_datetime(df["datetime"])
                    for col in ["open", "high", "low", "close"]:
                        df[col] = df[col].astype(float)

                    if "volume" in df.columns:
                        df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0.0)
                    else:
                        df["volume"] = 0.0

                    df = df.sort_values("datetime").reset_index(drop=True)
                    market_cache.set_ohlcv(clean_symbol, interval, df, outputsize)

                    if len(df) >= int(outputsize * 0.7):
                        return df, DataQualityEnum.GOOD
                    return df, DataQualityEnum.PARTIAL

                except Exception as e:
                    logger.error(f"Erreur de conversion pandas pour {clean_symbol} : {e}")

        # 3. Fallback Stale Cache
        stale_df, is_stale = market_cache.get_ohlcv(
            clean_symbol,
            interval,
            outputsize,
            allow_stale=True,
        )
        if stale_df is not None and not stale_df.empty:
            logger.warning(f"Utilisation du cache stale pour {clean_symbol} ({interval}).")
            return stale_df, DataQualityEnum.PARTIAL

        logger.error(f"Impossible de récupérer les données pour {clean_symbol} ({interval}) : {err}")
        return None, DataQualityEnum.POOR

    async def get_current_price(self, symbol: str) -> Tuple[Optional[float], DataQualityEnum]:
        clean_symbol = normalize_symbol(symbol)

        cached_price, is_stale = market_cache.get_price(clean_symbol, allow_stale=False)
        if cached_price is not None:
            return cached_price, DataQualityEnum.GOOD

        data, err = await request_manager.execute_request("price", {"symbol": clean_symbol})
        if data and "price" in data:
            try:
                price = float(data["price"])
                market_cache.set_price(clean_symbol, price)
                return price, DataQualityEnum.GOOD
            except ValueError:
                pass

        df, quality = await self.get_candles_df(clean_symbol, interval="15m", outputsize=10)
        if df is not None and not df.empty:
            latest_close = float(df["close"].iloc[-1])
            return latest_close, DataQualityEnum.PARTIAL

        return None, DataQualityEnum.POOR


market_data_service = MarketDataService()
