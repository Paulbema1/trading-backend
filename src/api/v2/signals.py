"""
TradeVision AI - Routes des Signaux (v2).
Anti-doublons et filtrage de l'historique.
"""

import json
from datetime import datetime, timezone, timedelta
from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.core.database import get_db
from src.core.auth import get_current_user
from src.models.user import User
from src.models.signal import Signal
from src.engine.signal_engine import signal_engine
from src.services.notifications import notification_service
from src.schemas.signal import SignalResponse, SignalHistoryItem, ActionEnum
from src.core.config import MAIN_TIMEFRAME, CONFIRMATION_TIMEFRAME
from src.core.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/signals", tags=["Signaux de Trading"])


@router.get("/analyze/{symbol:path}", response_model=SignalResponse)
async def analyze_asset(
    symbol: str,
    main_tf: Optional[str] = Query(default=MAIN_TIMEFRAME),
    confirm_tf: Optional[str] = Query(default=CONFIRMATION_TIMEFRAME),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    signal: SignalResponse = await signal_engine.generate_signal(
        symbol=symbol,
        main_tf=main_tf,
        confirm_tf=confirm_tf,
    )

    # ANTI-DOUBLONS : N'enregistre en base QUE si le dernier signal identique date de plus de 15 minutes
    fifteen_mins_ago = datetime.now(timezone.utc) - timedelta(minutes=15)
    last_signal = db.query(Signal).filter(
        Signal.symbol == signal.symbol,
        Signal.action == signal.action.value,
        Signal.created_at >= fifteen_mins_ago
    ).first()

    if not last_signal and signal.action != ActionEnum.WAIT:
        db_signal = Signal(
            symbol=signal.symbol,
            action=signal.action.value,
            score=signal.score,
            confidence=signal.confidence,
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,
            take_profit_1=signal.take_profit_1,
            take_profit_2=signal.take_profit_2,
            take_profit_3=signal.take_profit_3,
            risk_reward=signal.risk_reward,
            main_timeframe=signal.main_timeframe,
            confirmation_timeframe=signal.confirmation_timeframe,
            score_breakdown=json.dumps(signal.score_breakdown) if signal.score_breakdown else None,
            news_used=signal.news_used,
            news_status=signal.news_status.value if signal.news_status else None,
            news_summary=signal.news_summary,
            data_quality=signal.data_quality.value,
            ai_confirmed=signal.ai_confirmed,
            reasons=signal.reasons,
        )
        db.add(db_signal)
        db.commit()

        if signal.action in (ActionEnum.BUY, ActionEnum.SELL):
            await notification_service.broadcast_signal(signal, db)

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
