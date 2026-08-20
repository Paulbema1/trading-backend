"""
Schémas Pydantic pour les données de marché.
"""

from typing import Optional, List
from pydantic import BaseModel


class CandleData(BaseModel):
    """Une seule bougie OHLCV."""
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: float


class MarketDataRequest(BaseModel):
    """Requête de données marché."""
    symbol: str
    timeframe: str
    outputsize: int = 200


class MarketDataResponse(BaseModel):
    """Réponse avec les bougies."""
    symbol: str
    timeframe: str
    candles: List[CandleData]
    data_quality: str  # GOOD, PARTIAL, POOR
    from_cache: bool = False