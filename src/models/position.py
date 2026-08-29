"""
Modèle SQLAlchemy pour le suivi des positions actives (anti-stacking, §24 du cahier des charges).

Une seule position active par symbole. Ce modèle n'intervient qu'au niveau de
l'orchestration (dispatch des signaux) — il ne modifie ni le scoring déterministe,
ni la hiérarchie des garde-fous, ni le moteur de backtest.
"""

from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime
from src.core.database import Base


class OpenPosition(Base):
    __tablename__ = "open_positions"

    symbol = Column(String(20), primary_key=True, index=True)
    action = Column(String(10), nullable=False)  # "BUY" ou "SELL"
    signal_id = Column(String(36), nullable=True)
    opened_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
    )
