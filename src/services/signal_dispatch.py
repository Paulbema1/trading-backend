from datetime import datetime, timezone, timedelta
import json
from sqlalchemy.orm import Session
from src.models.signal import Signal
from src.models.position import OpenPosition
from src.schemas.signal import SignalResponse
from src.services.notifications import notification_service
from src.core.logging import get_logger

logger = get_logger(__name__)


def fingerprint(signal: SignalResponse):
    return "|".join([signal.symbol, signal.action.value, str(signal.score), str(signal.entry_price), str(signal.stop_loss), str(signal.take_profit_2), signal.main_timeframe, signal.confirmation_timeframe or ""])


def row_fingerprint(row: Signal):
    return "|".join([row.symbol, row.action, str(row.score), str(row.entry_price), str(row.stop_loss), str(row.take_profit_2), row.main_timeframe, row.confirmation_timeframe or ""])


def _check_anti_stacking(signal: SignalResponse, db: Session) -> bool:
    """
    Applique la règle anti-stacking (§24) : une seule position active par symbole.

    - Si une position identique (même direction) est déjà active sur ce symbole
      -> le nouveau signal est refusé (pas de doublon de position).
    - Si une position de direction opposée est active
      -> elle est considérée clôturée (retournement) et la nouvelle position s'ouvre.
    - Sinon -> la position s'ouvre normalement.

    Retourne True si le signal peut être dispatché, False s'il doit être bloqué.
    Cette fonction n'intervient qu'au niveau de l'orchestration : elle ne modifie
    ni le scoring déterministe, ni la hiérarchie des garde-fous du signal_engine.
    """
    existing = db.query(OpenPosition).filter(OpenPosition.symbol == signal.symbol).first()

    if existing is None:
        db.add(OpenPosition(symbol=signal.symbol, action=signal.action.value, signal_id=signal.signal_id))
        db.commit()
        return True

    if existing.action == signal.action.value:
        logger.info(f"Anti-stacking : position {signal.action.value} déjà active sur {signal.symbol}, signal ignoré.")
        return False

    # Direction opposée -> retournement : on clôture l'ancienne position et on ouvre la nouvelle.
    existing.action = signal.action.value
    existing.signal_id = signal.signal_id
    existing.opened_at = datetime.now(timezone.utc)
    db.commit()
    return True


async def persist_and_dispatch(signal: SignalResponse, db: Session):
    if signal.action.value == "WAIT":
        return False

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=15)
    recent = db.query(Signal).filter(Signal.symbol == signal.symbol, Signal.action == signal.action.value, Signal.created_at >= cutoff).all()
    if any(row_fingerprint(x) == fingerprint(signal) for x in recent):
        return False

    if not _check_anti_stacking(signal, db):
        return False

    row = Signal(
        signal_id=signal.signal_id,
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
    db.add(row)
    db.commit()
    await notification_service.broadcast_signal(signal, db)
    return True
