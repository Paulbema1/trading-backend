"""
Modèle SQLAlchemy pour les signaux de trading.

Chaque signal (BUY, SELL, WAIT) est enregistré
pour l'historique et la traçabilité.
"""

from datetime import datetime, timezone

from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Text

from src.core.database import Base


class Signal(Base):
    __tablename__ = "signals"

    id = Column(Integer, primary_key=True, index=True)

    # Actif et direction
    symbol = Column(String(20), nullable=False, index=True)
    action = Column(String(10), nullable=False)  # BUY, SELL, WAIT

    # Score et confiance
    score = Column(Integer, nullable=False)          # 0-100
    confidence = Column(Integer, nullable=False)     # 0-100

    # Niveaux de trading
    entry_price = Column(Float, nullable=True)
    stop_loss = Column(Float, nullable=True)
    take_profit_1 = Column(Float, nullable=True)
    take_profit_2 = Column(Float, nullable=True)
    take_profit_3 = Column(Float, nullable=True)
    risk_reward = Column(Float, nullable=True)

    # Timeframes utilisés
    main_timeframe = Column(String(10), nullable=False)       # ex: "1h"
    confirmation_timeframe = Column(String(10), nullable=True) # ex: "4h"

    # Détail du score (JSON string)
    score_breakdown = Column(Text, nullable=True)
    # Exemple : '{"smc": 24, "technical": 20, "mtf": 17, ...}'

    # News
    news_used = Column(Boolean, default=False)
    news_status = Column(String(30), nullable=True)
    # CONFIRMED_BY_MARKET, IGNORED_BY_MARKET,
    # CONTRADICTION_DETECTED, NO_MAJOR_EVENT
    news_summary = Column(Text, nullable=True)

    # Qualité des données
    data_quality = Column(String(10), default="GOOD")
    # GOOD, PARTIAL, POOR

    # Confirmation IA
    ai_confirmed = Column(Boolean, nullable=True)
    ai_reason = Column(Text, nullable=True)

    # Raisons du signal
    reasons = Column(Text, nullable=True)

    # Timestamp
    created_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )