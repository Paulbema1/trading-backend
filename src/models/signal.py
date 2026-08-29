"""
Modèle SQLAlchemy pour les signaux de trading.
"""

from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Text
from src.core.database import Base


class Signal(Base):
    __tablename__ = "signals"

    id = Column(Integer, primary_key=True, index=True)
    signal_id = Column(String(36), nullable=True, index=True, unique=False)
    symbol = Column(String(20), nullable=False, index=True)
    action = Column(String(10), nullable=False)
    score = Column(Integer, nullable=False)
    confidence = Column(Integer, nullable=False)
    entry_price = Column(Float, nullable=True)
    stop_loss = Column(Float, nullable=True)
    take_profit_1 = Column(Float, nullable=True)
    take_profit_2 = Column(Float, nullable=True)
    take_profit_3 = Column(Float, nullable=True)
    risk_reward = Column(Float, nullable=True)
    main_timeframe = Column(String(10), nullable=False)
    confirmation_timeframe = Column(String(10), nullable=True)
    score_breakdown = Column(Text, nullable=True)
    news_used = Column(Boolean, default=False)
    news_status = Column(String(30), nullable=True)
    news_summary = Column(Text, nullable=True)
    data_quality = Column(String(10), default="GOOD")
    ai_confirmed = Column(Boolean, nullable=True)
    ai_reason = Column(Text, nullable=True)
    reasons = Column(Text, nullable=True)
    created_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
