"""
Schémas Pydantic pour les signaux de trading.
"""

from typing import Optional, Dict
from enum import Enum
from pydantic import BaseModel


class ActionEnum(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    WAIT = "WAIT"


class NewsStatusEnum(str, Enum):
    CONFIRMED = "CONFIRMED_BY_MARKET"
    IGNORED = "IGNORED_BY_MARKET"
    DIVERGENCE = "CONTRADICTION_DETECTED"
    NONE = "NO_MAJOR_EVENT"


class DataQualityEnum(str, Enum):
    GOOD = "GOOD"
    PARTIAL = "PARTIAL"
    POOR = "POOR"


class SignalResponse(BaseModel):
    """Signal complet envoyé à l'app."""
    signal_id: Optional[str] = None
    symbol: str
    action: ActionEnum
    confidence: int
    score: int

    # Niveaux
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit_1: Optional[float] = None
    take_profit_2: Optional[float] = None
    take_profit_3: Optional[float] = None
    risk_reward: Optional[float] = None

    # Timeframes (toujours visibles pour l'utilisateur)
    main_timeframe: str
    confirmation_timeframe: Optional[str] = None

    # Détail du score
    score_breakdown: Optional[Dict[str, int]] = None

    # Transparence News
    news_used: bool = False
    news_status: Optional[NewsStatusEnum] = None
    news_summary: Optional[str] = None

    # Qualité
    data_quality: DataQualityEnum = DataQualityEnum.GOOD

    # IA
    ai_confirmed: Optional[bool] = None

    # Raisons
    reasons: Optional[str] = None


class SignalHistoryItem(BaseModel):
    """Élément d'historique (version simplifiée)."""
    id: int
    signal_id: Optional[str] = None
    symbol: str
    action: str
    score: int
    confidence: int
    main_timeframe: str
    confirmation_timeframe: Optional[str] = None
    news_used: bool
    news_status: Optional[str] = None
    data_quality: str
    created_at: str

    class Config:
        from_attributes = True