"""
TradeVision AI - Endpoints API pour le Test Lab (Simulation & Injection).
"""

from typing import List, Dict, Any, Optional
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
import pandas as pd

from src.services.test_lab_service import test_lab_service
from src.services.market_data import market_data_service
from src.engine.signal_engine import signal_engine
from src.schemas.signal import SignalResponse
from src.core.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/test", tags=["Test Lab & Simulation"])


# ── SCHÉMAS PYDANTIC ─────────────────────────────────────

class ModeRequest(BaseModel):
    enabled: bool = Field(..., description="True pour activer le mode test, False pour désactiver")


class TimeInjectRequest(BaseModel):
    simulation_time: str = Field(..., description="Format ISO (ex: 2026-08-25T10:00:00Z)")


class CandleItem(BaseModel):
    datetime: str
    open: float
    high: float
    low: float
    close: float
    volume: Optional[float] = 0.0


class MarketInjectRequest(BaseModel):
    symbol: str
    interval: str
    candles: List[CandleItem]


class NewsItem(BaseModel):
    title: str
    published: str
    currency: Optional[str] = None
    impact: Optional[str] = "MEDIUM"


class NewsInjectRequest(BaseModel):
    news: List[NewsItem]


class CalendarItem(BaseModel):
    title: str
    currency: str
    impact: str
    time: str


class CalendarInjectRequest(BaseModel):
    events: List[CalendarItem]


class AnalyzeTestRequest(BaseModel):
    symbol: str = "EUR/USD"
    main_tf: str = "15m"
    confirm_tf: str = "1h"


# ── ENDPOINTS API TEST LAB ───────────────────────────────

@router.post("/mode", status_code=status.HTTP_200_OK)
def set_simulation_mode(payload: ModeRequest):
    """Active ou désactive le mode simulation du Test Lab."""
    is_active = test_lab_service.set_mode(payload.enabled)
    return {
        "message": f"Mode simulation {'ACTIVÉ' if is_active else 'DÉSACTIVÉ'}",
        "simulation_mode": is_active,
    }


@router.get("/status", status_code=status.HTTP_200_OK)
def get_simulation_status():
    """Affiche le statut actuel du Test Lab sur le serveur."""
    return test_lab_service.get_status()


@router.post("/inject/time", status_code=status.HTTP_200_OK)
def inject_simulated_time(payload: TimeInjectRequest):
    """Ajuste l'horloge virtuelle du serveur."""
    test_lab_service.set_simulated_time(payload.simulation_time)
    return {"message": f"Horloge virtuelle réglée sur {payload.simulation_time}"}


@router.post("/inject/market", status_code=status.HTTP_200_OK)
def inject_market_data(payload: MarketInjectRequest):
    """Injecte un lot de bougies simulées dans le service de marché."""
    if not payload.candles:
        raise HTTPException(status_code=400, detail="La liste des bougies ne peut pas être vide.")

    records = [c.dict() for c in payload.candles]
    df = pd.DataFrame(records)
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.sort_values("datetime").reset_index(drop=True)

    test_lab_service.inject_candles(payload.symbol, payload.interval, df)
    return {
        "message": f"Injecté {len(df)} bougies pour {payload.symbol} ({payload.interval})",
        "symbol": payload.symbol,
        "interval": payload.interval,
    }


@router.post("/inject/news", status_code=status.HTTP_200_OK)
def inject_news_data(payload: NewsInjectRequest):
    """Injecte les actualités simulées."""
    records = [n.dict() for n in payload.news]
    test_lab_service.inject_news(records)
    return {"message": f"Injecté {len(records)} actualités simulées."}


@router.post("/inject/calendar", status_code=status.HTTP_200_OK)
def inject_calendar_data(payload: CalendarInjectRequest):
    """Injecte les événements du calendrier économique simulé."""
    records = [c.dict() for c in payload.events]
    test_lab_service.inject_calendar(records)
    return {"message": f"Injecté {len(records)} événements de calendrier simulés."}


@router.post("/reset", status_code=status.HTTP_200_OK)
def reset_test_lab():
    """Efface toutes les données simulées et réinitialise le lab."""
    test_lab_service.reset()
    return {"message": "Test Lab réinitialisé."}


@router.post("/analyze", response_model=SignalResponse)
async def analyze_test_signal(payload: AnalyzeTestRequest):
    """
    Exécute l'analyse RÉELLE du Signal Engine sur les données simulées injectées.
    """
    if not test_lab_service.is_enabled():
        raise HTTPException(
            status_code=400,
            detail="Le mode simulation doit être ACTIVÉ via /api/v2/test/mode avant de lancer l'analyse de test."
        )

    signal = await signal_engine.generate_signal(
        symbol=payload.symbol,
        main_tf=payload.main_tf,
        confirm_tf=payload.confirm_tf,
    )
    return signal
