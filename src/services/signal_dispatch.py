from datetime import datetime, timezone, timedelta
import json
from sqlalchemy.orm import Session
from src.models.signal import Signal
from src.schemas.signal import SignalResponse
from src.services.notifications import notification_service

def fingerprint(signal: SignalResponse):
    return "|".join([signal.symbol, signal.action.value, str(signal.score), str(signal.entry_price), str(signal.stop_loss), str(signal.take_profit_2), signal.main_timeframe, signal.confirmation_timeframe or ""])

def row_fingerprint(row: Signal):
    return "|".join([row.symbol,row.action,str(row.score),str(row.entry_price),str(row.stop_loss),str(row.take_profit_2),row.main_timeframe,row.confirmation_timeframe or ""])

async def persist_and_dispatch(signal: SignalResponse, db: Session):
    if signal.action.value == "WAIT": return False
    cutoff=datetime.now(timezone.utc)-timedelta(minutes=15)
    recent=db.query(Signal).filter(Signal.symbol==signal.symbol,Signal.action==signal.action.value,Signal.created_at>=cutoff).all()
    if any(row_fingerprint(x)==fingerprint(signal) for x in recent): return False
    row=Signal(symbol=signal.symbol,action=signal.action.value,score=signal.score,confidence=signal.confidence,entry_price=signal.entry_price,stop_loss=signal.stop_loss,take_profit_1=signal.take_profit_1,take_profit_2=signal.take_profit_2,take_profit_3=signal.take_profit_3,risk_reward=signal.risk_reward,main_timeframe=signal.main_timeframe,confirmation_timeframe=signal.confirmation_timeframe,score_breakdown=json.dumps(signal.score_breakdown) if signal.score_breakdown else None,news_used=signal.news_used,news_status=signal.news_status.value if signal.news_status else None,news_summary=signal.news_summary,data_quality=signal.data_quality.value,ai_confirmed=signal.ai_confirmed,reasons=signal.reasons)
    db.add(row); db.commit()
    await notification_service.broadcast_signal(signal,db)
    return True
