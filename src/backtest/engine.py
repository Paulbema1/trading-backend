"""Backtest v9 : même scoring déterministe que le live, sans OpenRouter ni données futures."""
from typing import Dict, Any, Optional
from datetime import timedelta
import pandas as pd
import numpy as np
from src.backtest.historical_data import historical_data_manager
from src.backtest.historical_news import historical_news_manager
from src.backtest.simulator import trade_simulator
from src.backtest.results import BacktestResults
from src.engine.deterministic_scoring import deterministic_scoring_engine
from src.schemas.signal import ActionEnum
from src.utils.helpers import normalize_symbol, round_price
from src.core.logging import get_logger
logger=get_logger(__name__)

class StrictAuditedBacktestEngine:
    def _duration(self, tf):
        return {"15m":timedelta(minutes=15),"30m":timedelta(minutes=30),"1h":timedelta(hours=1),"4h":timedelta(hours=4)}.get(tf.lower(),timedelta(hours=1))
    def _closed_confirm(self, df, tf, current_time):
        if df is None or df.empty:return df
        x=df.copy(); x["datetime"]=pd.to_datetime(x["datetime"]); cutoff=pd.Timestamp(current_time)
        if getattr(x["datetime"].dt,"tz",None) is None and cutoff.tzinfo is not None: cutoff=cutoff.tz_localize(None)
        return x[(x["datetime"]+self._duration(tf))<=cutoff].reset_index(drop=True)
    def _load_fundamentals(self):
        historical_news_manager.reset()
        data_dir=historical_data_manager.base_dir
        news_path=data_dir/"news.parquet"; cal_path=data_dir/"calendar.parquet"
        try:
            if news_path.exists(): historical_news_manager.load_news_dataset(pd.read_parquet(news_path))
            if cal_path.exists(): historical_news_manager.load_calendar_dataset(pd.read_parquet(cal_path))
        except Exception as e: logger.warning("Impossible de charger le contexte fondamental historique: %s",e)
    async def run_backtest(self,symbol:str,main_tf:str="15m",confirm_tf:str="1h",start_date:Optional[str]=None,end_date:Optional[str]=None,min_confidence:int=70,compounding:bool=False)->Dict[str,Any]:
        clean=normalize_symbol(symbol); self._load_fundamentals()
        main=historical_data_manager.load_data(clean,main_tf,start_date,end_date)
        confirm=historical_data_manager.load_data(clean,confirm_tf,start_date,end_date)
        if main is None or len(main)<100 or confirm is None or len(confirm)<40:
            return {"error":f"Données historiques Parquet insuffisantes pour {clean} ({main_tf}/{confirm_tf}). Aucun téléchargement live n'est autorisé pendant un backtest.","data_source":"PARQUET_LOCAL_UNIQUEMENT","symbol":clean,"main_tf":main_tf}
        main["datetime"]=pd.to_datetime(main["datetime"]); confirm["datetime"]=pd.to_datetime(confirm["datetime"]) if confirm is not None else None
        trades=[]; i=100
        while i < len(main)-1:
            current=main.iloc[:i+1].copy(); now=current["datetime"].iloc[-1]
            c=self._closed_confirm(confirm,confirm_tf,now)
            if c is None or len(c)<40: i+=1; continue
            news=historical_news_manager.get_news_context_at(clean, now.to_pydatetime())
            cal=historical_news_manager.get_calendar_context_at(clean, now.to_pydatetime())
            scored=deterministic_scoring_engine.evaluate(current,c,news,cal,confirm_tf=confirm_tf,as_of=now)
            action=scored["action"]
            if scored["score"] < min_confidence: action=ActionEnum.WAIT
            if action==ActionEnum.WAIT: i+=1; continue
            price=float(current["close"].iloc[-1]); atr=float(scored["ta"]["indicators"].get("atr",np.nan))
            if not np.isfinite(atr) or atr<=0: i+=1; continue
            d=atr*1.5; sign=1 if action==ActionEnum.BUY else -1
            sl=price-sign*d; tp1=price+sign*d*1.5; tp2=price+sign*d*2.5; tp3=price+sign*d*3.5
            future=main.iloc[i+1:]
            result=trade_simulator.simulate_trade(clean,action,price,sl,tp1,tp2,tp3,future,start_index=i+1)
            trades.append({"entry_time":str(now),"symbol":clean,"action":action.value,"score":int(scored["score"]),"entry_price":float(round_price(clean,price)),"news_used":bool(scored["news"]["news_used"]),"result":str(result.get("result","OPEN")),"reason":str(result.get("reason","")),"exit_price":float(result.get("exit_price",price)),"exit_time":str(result.get("exit_time","")),"pips":float(result.get("pips",0)),"hit_tp":int(result.get("hit_tp",0)),"r_multiple":float(result.get("r_multiple",0))})
            i=max(i+1,int(result.get("exit_index",i+1))+1)
        metrics=BacktestResults.calculate_metrics(trades,compounding=compounding)
        return {"data_source":"DONNÉES HISTORIQUES RÉELLES PARQUET","symbol":clean,"main_tf":main_tf,"confirmation_tf":confirm_tf,"loaded_candles":len(main),"period":f"{main['datetime'].iloc[0]} -> {main['datetime'].iloc[-1]}","metrics":metrics,"trades":trades,"fundamental_data_available":bool(historical_news_manager.news_records or historical_news_manager.calendar_records)}
backtest_engine=StrictAuditedBacktestEngine()
