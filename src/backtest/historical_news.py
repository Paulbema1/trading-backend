"""
TradeVision AI - Contexte Fondamental Historique (Zéro Look-Ahead Bias).
"""

from typing import List, Dict, Any, Optional
import pandas as pd
from datetime import datetime


class HistoricalNewsManager:
    """Fournisseur de contexte fondamental horodaté pour le backtesting."""

    def __init__(self):
        # Format : [{"datetime": Timestamp, "symbol": "EUR/USD", "bias": "BUY", "title": "..."}]
        self.news_records: List[Dict[str, Any]] = []
        # Format : [{"datetime": Timestamp, "currency": "USD", "impact": "High", "title": "CPI"}]
        self.calendar_records: List[Dict[str, Any]] = []

    def reset(self):
        self.news_records = []
        self.calendar_records = []

    def load_news_dataset(self, df_news: pd.DataFrame):
        """Charge un fichier d'actualités historiques."""
        if df_news is not None and not df_news.empty:
            df_news["datetime"] = pd.to_datetime(df_news["datetime"], utc=True).dt.tz_convert(None)
            self.news_records = df_news.to_dict(orient="records")

    def load_calendar_dataset(self, df_cal: pd.DataFrame):
        """Charge un fichier de calendrier économique historique."""
        if df_cal is not None and not df_cal.empty:
            df_cal["datetime"] = pd.to_datetime(df_cal["datetime"], utc=True).dt.tz_convert(None)
            self.calendar_records = df_cal.to_dict(orient="records")

    def get_news_context_at(self, symbol: str, current_time: datetime) -> Dict[str, Any]:
        current_time = pd.Timestamp(current_time).tz_localize(None).to_pydatetime() if pd.Timestamp(current_time).tzinfo is not None else current_time
        """
        Retourne STRICTEMENT les actualités disponibles à current_time (Look-Ahead Bias = 0).
        """
        clean_sym = symbol.replace("/", "").upper()
        # Filtrer uniquement les actualités passées (<= current_time) et récentes (max 24h avant)
        past_news = [
            n for n in self.news_records
            if n["symbol"].replace("/", "").upper() == clean_sym
            and 0 <= (current_time - n["datetime"]).total_seconds() <= 86400
        ]

        if not past_news:
            return {"bias": "NEUTRAL", "summary": "Aucune news majeure récente."}

        # Prendre la plus récente avant current_time
        latest = sorted(past_news, key=lambda x: x["datetime"])[-1]
        return {
            "bias": latest.get("bias", "NEUTRAL"),
            "summary": latest.get("title", ""),
        }

    def get_calendar_context_at(self, symbol: str, current_time: datetime) -> Dict[str, Any]:
        current_time = pd.Timestamp(current_time).tz_localize(None).to_pydatetime() if pd.Timestamp(current_time).tzinfo is not None else current_time
        """
        Vérifie si un événement économique rouge était prévu autour de current_time.
        """
        currencies = [symbol[:3], symbol[4:]] if "/" in symbol else ["USD", "EUR"]

        # Événements prévus dans une fenêtre de -30 min à +60 min par rapport à current_time
        nearby = []
        for c in self.calendar_records:
            if c.get("currency") not in currencies or str(c.get("impact", "")).lower() not in ("high", "red"):
                continue
            event_dt = c["datetime"]
            available_at = c.get("available_at")
            if available_at is not None:
                available_at = pd.Timestamp(available_at).to_pydatetime()
                if available_at.tzinfo is None and getattr(current_time, "tzinfo", None) is not None:
                    available_at = available_at.replace(tzinfo=current_time.tzinfo)
                if available_at > current_time:
                    continue
            # Sans available_at, une annonce future est interdite : seul un événement déjà publié est lisible.
            if event_dt > current_time:
                continue
            if abs((event_dt - current_time).total_seconds()) <= 3600:
                nearby.append(c)

        if nearby:
            return {
                "has_high_impact": True,
                "calendar_score": 1,
                "summary": f"⚠️ Événement majeur proche : {nearby[0].get('title')}",
            }

        return {
            "has_high_impact": False,
            "calendar_score": 5,
            "summary": "Aucun événement critique proche.",
        }


historical_news_manager = HistoricalNewsManager()