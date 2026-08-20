"""
TradeVision AI - Espace Admin & Cockpit de Contrôle (v2).

Réservé exclusivement aux utilisateurs ayant le rôle "ADMIN".
"""

from typing import List, Dict, Any
from fastapi import APIRouter, Depends, status
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
    """
    Retourne la liste de tous les utilisateurs inscrits.
    SÉCURITÉ : Aucun mot de passe ni hash n'est exposé.
    """
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
    """Affiche l'état en direct des clés Twelve Data (429, Cooldowns, Requêtes totales)."""
    return request_manager.get_status_metrics()


@router.post("/cache/clear", status_code=status.HTTP_200_OK)
def clear_cache(admin: User = Depends(require_admin)):
    """Vide le cache mémoire des bougies et des prix."""
    market_cache.clear()
    return {"message": "Cache mémoire vidé avec succès."}


@router.post("/scan-all", status_code=status.HTTP_200_OK)
async def trigger_full_market_scan(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Mode Télécommande : Lance un scan instantané de tous les actifs supportés
    (EUR/USD, GBP/USD, USD/JPY, XAU/USD) et diffuse les signaux validés.
    """
    scan_results = []

    for asset in SUPPORTED_ASSETS:
        try:
            signal = await signal_engine.generate_signal(
                symbol=asset,
                main_tf=MAIN_TIMEFRAME,
                confirm_tf=CONFIRMATION_TIMEFRAME,
            )

            # Diffusion si signal d'action
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