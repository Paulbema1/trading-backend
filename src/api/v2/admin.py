"""
TradeVision AI - Espace Admin & Cockpit de Contrôle (v2).
"""

from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from src.core.database import get_db
from src.core.auth import require_admin
from src.models.user import User
from src.schemas.user import AdminUserListItem
from src.services.request_manager import request_manager
from src.utils.cache import market_cache
from src.engine.signal_engine import signal_engine
from src.services.notifications import notification_service
from src.core.config import SUPPORTED_ASSETS, MAIN_TIMEFRAME, CONFIRMATION_TIMEFRAME
from src.core.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/admin", tags=["Administration & Télécommande"])


@router.get("/users", response_model=List[AdminUserListItem])
def list_users(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    users = db.query(User).order_by(User.created_at.desc()).all()

    result = []
    for u in users:
        result.append(AdminUserListItem(
            id=u.id,
            username=u.username,
            role=u.role,
            has_fcm_token=bool(u.fcm_token and len(u.fcm_token) > 10),
            is_active=u.is_active,
            notifications_enabled=u.notifications_enabled,
            created_at=u.created_at.strftime("%Y-%m-%d %H:%M") if u.created_at else "",
        ))
    return result


@router.get("/keys-metrics", response_model=List[Dict[str, Any]])
def get_twelve_data_metrics(admin: User = Depends(require_admin)):
    return request_manager.get_status_metrics()


@router.post("/cache/clear", status_code=status.HTTP_200_OK)
def clear_cache(admin: User = Depends(require_admin)):
    market_cache.clear()
    return {"message": "Cache mémoire vidé avec succès."}


@router.post("/scan-all", status_code=status.HTTP_200_OK)
async def trigger_full_market_scan(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    scan_results = []
    for asset in SUPPORTED_ASSETS:
        try:
            signal = await signal_engine.generate_signal(
                symbol=asset,
                main_tf=MAIN_TIMEFRAME,
                confirm_tf=CONFIRMATION_TIMEFRAME,
            )
            if signal.action.value in ("BUY", "SELL"):
                await notification_service.broadcast_signal(signal, db)

            scan_results.append({
                "symbol": asset,
                "action": signal.action.value,
                "confidence": signal.confidence,
                "score": signal.score,
                "news_used": signal.news_used,
            })
        except Exception as e:
            logger.error(f"Erreur scan {asset} : {e}")
            scan_results.append({"symbol": asset, "error": str(e)})

    return {"message": "Scan terminé", "results": scan_results}


@router.post("/backtest", status_code=status.HTTP_200_OK)
def run_backtest_route(
    symbol: str = Query(default="EUR/USD"),
    main_tf: str = Query(default="1h"),
    confirm_tf: str = Query(default="4h"),
    start_date: Optional[str] = Query(default=None),
    end_date: Optional[str] = Query(default=None),
    admin: User = Depends(require_admin),
):
    """Exécute une simulation de backtest sur les données historiques."""
    from src.backtest.engine import backtest_engine
    res = backtest_engine.run_backtest(
        symbol=symbol,
        main_tf=main_tf,
        confirm_tf=confirm_tf,
        start_date=start_date,
        end_date=end_date,
    )
    return res
