"""
TradeVision AI - Routes des Signaux (v2).
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.core.database import get_db
from src.core.auth import get_current_user
from src.models.user import User
from src.models.signal import Signal
from src.engine.signal_engine import signal_engine
from src.schemas.signal import SignalResponse, SignalHistoryItem, ActionEnum
from src.services.system_config import system_config_service
from src.core.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/signals", tags=["Signaux de Trading"])


@router.get("/analyze/{symbol:path}", response_model=SignalResponse)
async def analyze_asset(
    symbol: str,

    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    cfg = system_config_service.get(db)
    signal: SignalResponse = await signal_engine.generate_signal(symbol=symbol, main_tf=cfg.main_timeframe, confirm_tf=cfg.confirmation_timeframe)



    return signal


@router.get("/history", response_model=List[SignalHistoryItem])
def get_signal_history(
    symbol: Optional[str] = None,
    limit: int = Query(default=30, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(Signal).order_by(Signal.created_at.desc())

    if symbol:
        clean_sym = symbol.replace("-", "/").upper()
        query = query.filter(Signal.symbol == clean_sym)

    signals = query.limit(limit).all()

    result = []
    for s in signals:
        result.append(SignalHistoryItem(
            id=s.id,
            symbol=s.symbol,
            action=s.action,
            score=s.score,
            confidence=s.confidence,
            main_timeframe=s.main_timeframe,
            confirmation_timeframe=s.confirmation_timeframe,
            news_used=s.news_used,
            news_status=s.news_status,
            data_quality=s.data_quality,
            created_at=s.created_at.strftime("%d/%m/%Y à %H:%M") if s.created_at else "",
        ))

    return result
