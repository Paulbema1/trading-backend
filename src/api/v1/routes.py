"""
TradeVision AI - Routes de Compatibilité (v1).
"""

from fastapi import APIRouter
from src.engine.signal_engine import signal_engine
from src.schemas.signal import SignalResponse

router = APIRouter(prefix="/v1", tags=["API v1 (Legacy)"])


@router.get("/analyze/{symbol:path}", response_model=SignalResponse)
async def analyze_legacy(symbol: str):
    """Route de compatibilité pour l'ancien frontend."""
    return await signal_engine.generate_signal(symbol=symbol, main_tf="1h", confirm_tf="4h")