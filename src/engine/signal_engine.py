"""TradeVision AI - moteur live : données -> scoring déterministe -> audit IA."""
from typing import Dict
import pandas as pd
from datetime import timedelta, datetime, timezone
from src.services.market_data import market_data_service
from src.services.news import news_service
from src.services.economic_calendar import economic_calendar_service
from src.engine.deterministic_scoring import deterministic_scoring_engine
from src.engine.ai_analysis import ai_engine
from src.schemas.signal import SignalResponse, ActionEnum, DataQualityEnum
from src.utils.helpers import round_price, normalize_symbol
from src.core.config import DEFAULT_MIN_CONFIDENCE
from src.core.logging import get_logger
logger = get_logger(__name__)

class SignalEngine:
    def _duration(self, tf: str) -> timedelta:
        return {"15m": timedelta(minutes=15), "30m": timedelta(minutes=30), "1h": timedelta(hours=1), "4h": timedelta(hours=4)}.get(tf.lower(), timedelta(hours=1))

    def _closed(self, df: pd.DataFrame, tf: str, now=None) -> pd.DataFrame:
        if df is None or df.empty or "datetime" not in df.columns: return df
        out=df.copy(); out["datetime"]=pd.to_datetime(out["datetime"]); now=pd.Timestamp(now or datetime.now(timezone.utc))
        if getattr(out["datetime"].dt, "tz", None) is None and now.tzinfo is not None: now=now.tz_localize(None)
        return out[(out["datetime"] + self._duration(tf)) <= now].reset_index(drop=True)

    def _calculate_levels(self, symbol: str, action: ActionEnum, current_price: float, atr: float) -> Dict[str, float]:
        if action == ActionEnum.WAIT or atr <= 0: return {}
        d = atr * 1.5; entry=current_price
        sign=1 if action == ActionEnum.BUY else -1
        sl=entry-sign*d; tp1=entry+sign*d*1.5; tp2=entry+sign*d*2.5; tp3=entry+sign*d*3.5
        return {"entry_price": round_price(symbol, entry), "stop_loss": round_price(symbol, sl), "take_profit_1": round_price(symbol, tp1), "take_profit_2": round_price(symbol, tp2), "take_profit_3": round_price(symbol, tp3), "risk_reward": 2.5}

    async def generate_signal(self, symbol: str, main_tf: str="1h", confirm_tf: str="4h") -> SignalResponse:
        clean=normalize_symbol(symbol); now=datetime.now(timezone.utc)
        raw_main,q_main=await market_data_service.get_candles_df(clean,main_tf,200); raw_confirm,q_confirm=await market_data_service.get_candles_df(clean,confirm_tf,100)
        main=self._closed(raw_main,main_tf,now); confirm=self._closed(raw_confirm,confirm_tf,now)
        if q_main == DataQualityEnum.POOR or q_confirm == DataQualityEnum.POOR or main is None or len(main)<50 or confirm is None or len(confirm)<40:
            return SignalResponse(symbol=clean, action=ActionEnum.WAIT, confidence=0, score=0, main_timeframe=main_tf, confirmation_timeframe=confirm_tf, data_quality=DataQualityEnum.POOR, reasons="Données insuffisantes ou non clôturées.")
        price,q_price=await market_data_service.get_current_price(clean)
        if price is None or q_price == DataQualityEnum.POOR:
            return SignalResponse(symbol=clean, action=ActionEnum.WAIT, confidence=0, score=0, main_timeframe=main_tf, confirmation_timeframe=confirm_tf, data_quality=DataQualityEnum.POOR, reasons="Prix courant indisponible.")
        news=await news_service.analyze_sentiment(clean); cal=await economic_calendar_service.get_upcoming_events(clean)
        scored=deterministic_scoring_engine.evaluate(main,confirm,news,cal,confirm_tf=confirm_tf,as_of=now)
        action=scored["action"]; ai_confirmed=None; reasons=scored["reasons"]
        levels={}
        if action != ActionEnum.WAIT:
            levels=self._calculate_levels(clean,action,float(price),float(scored["ta"]["indicators"].get("atr",0)))
            ai_confirmed,ai_reason=await ai_engine.validate_signal(clean,action.value,scored["score"],scored["breakdown"],reasons,news.get("summary",""))
            if not ai_confirmed:
                action=ActionEnum.WAIT; reasons.append(f"Refus de sécurité IA : {ai_reason}")
        quality=DataQualityEnum.PARTIAL if q_main==DataQualityEnum.PARTIAL or q_confirm==DataQualityEnum.PARTIAL or q_price==DataQualityEnum.PARTIAL else DataQualityEnum.GOOD
        return SignalResponse(symbol=clean,action=action,confidence=scored["confidence"],score=scored["score"],entry_price=levels.get("entry_price"),stop_loss=levels.get("stop_loss"),take_profit_1=levels.get("take_profit_1"),take_profit_2=levels.get("take_profit_2"),take_profit_3=levels.get("take_profit_3"),risk_reward=levels.get("risk_reward"),main_timeframe=main_tf,confirmation_timeframe=confirm_tf,score_breakdown=scored["breakdown"],news_used=scored["news"]["news_used"],news_status=scored["news"]["status"],news_summary=scored["news"]["explanation"],data_quality=quality,ai_confirmed=ai_confirmed,reasons=" | ".join(reasons[:6]))

signal_engine=SignalEngine()
