"""
TradeVision AI - Espace Admin & Cockpit de Contrôle (v2).
"""

from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, Query, status, HTTPException
from sqlalchemy.orm import Session

from src.core.database import get_db
from src.core.auth import require_admin
from src.models.user import User
from src.schemas.user import AdminUserListItem, SystemTimeframeResponse, SystemTimeframeUpdate
from src.services.system_config import system_config_service
from src.core.config import validate_timeframe
from src.services.request_manager import request_manager
from src.utils.cache import market_cache
from src.engine.signal_engine import signal_engine
from src.services.signal_dispatch import persist_and_dispatch
from src.core.config import SUPPORTED_ASSETS
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



@router.get("/timeframes", response_model=SystemTimeframeResponse)
def get_system_timeframes(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    cfg = system_config_service.get(db)
    return SystemTimeframeResponse(main_timeframe=cfg.main_timeframe, confirmation_timeframe=cfg.confirmation_timeframe)

@router.put("/timeframes", response_model=SystemTimeframeResponse)
def update_system_timeframes(payload: SystemTimeframeUpdate, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    if not validate_timeframe(payload.main_timeframe) or not validate_timeframe(payload.confirmation_timeframe):
        raise HTTPException(status_code=400, detail="Timeframe non supporté.")
    cfg = system_config_service.update(db, payload.main_timeframe, payload.confirmation_timeframe)
    return SystemTimeframeResponse(main_timeframe=cfg.main_timeframe, confirmation_timeframe=cfg.confirmation_timeframe)

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
            cfg = system_config_service.get(db)
            signal = await signal_engine.generate_signal(symbol=asset, main_tf=cfg.main_timeframe, confirm_tf=cfg.confirmation_timeframe)
            await persist_and_dispatch(signal, db)

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
async def run_backtest_route(
    symbol: str = Query(default="EUR/USD"),
    main_tf: Optional[str] = Query(default=None),
    confirm_tf: Optional[str] = Query(default=None),
    start_date: Optional[str] = Query(default=None),
    end_date: Optional[str] = Query(default=None),
    compounding: bool = Query(default=False),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        from src.backtest.engine import backtest_engine
        db_cfg = system_config_service.get(db)
        effective_main_tf = main_tf or db_cfg.main_timeframe
        effective_confirm_tf = confirm_tf or db_cfg.confirmation_timeframe
        if not validate_timeframe(effective_main_tf) or not validate_timeframe(effective_confirm_tf):
            raise HTTPException(status_code=400, detail="Timeframe non supporté.")
        res = await backtest_engine.run_backtest(
            symbol=symbol,
            main_tf=effective_main_tf,
            confirm_tf=effective_confirm_tf,
            start_date=start_date,
            end_date=end_date,
            compounding=compounding,
        )
        return res
    except Exception as e:
        logger.error(f"Erreur Backtest : {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur calcul backtest : {str(e)}"
        )
