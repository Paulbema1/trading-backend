"""
TradeVision AI - Point d'entrée principal de l'application.

Version : 9.0.0
"""

import asyncio
import httpx
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.core.config import (
    APP_NAME,
    APP_VERSION,
    API_TITLE,
    API_DESCRIPTION,
    CORS_ORIGINS,
    SUPPORTED_ASSETS,
    MAIN_TIMEFRAME,
    CONFIRMATION_TIMEFRAME,
    DEFAULT_REFRESH_INTERVAL,
)
from src.core.database import init_db, SessionLocal
from src.core.firebase import init_firebase
from src.core.logging import get_logger
from src.engine.signal_engine import signal_engine
from src.services.notifications import notification_service
from src.models.signal import Signal
import json

from src.api.v2.auth import router as auth_router
from src.api.v2.signals import router as signals_router
from src.api.v2.admin import router as admin_router
from src.api.v1.routes import router as legacy_router

logger = get_logger(__name__)

_keep_alive_task = None
_auto_scan_task = None


async def keep_alive_task():
    while True:
        try:
            await asyncio.sleep(600)
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.get("http://127.0.0.1:10000/health")
            logger.debug("🔄 Anti-veille : Auto-ping exécuté.")
        except asyncio.CancelledError:
            break
        except Exception:
            pass


async def auto_scan_task():
    await asyncio.sleep(30)
    scan_interval_seconds = DEFAULT_REFRESH_INTERVAL * 60

    while True:
        try:
            logger.info("🤖 Auto-Scan : Analyse automatique des marchés...")
            db = SessionLocal()
            try:
                for symbol in SUPPORTED_ASSETS:
                    signal = await signal_engine.generate_signal(
                        symbol=symbol,
                        main_tf=MAIN_TIMEFRAME,
                        confirm_tf=CONFIRMATION_TIMEFRAME,
                    )

                    db_signal = Signal(
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
                    db.add(db_signal)
                    db.commit()

                    if signal.action.value in ("BUY", "SELL"):
                        await notification_service.broadcast_signal(signal, db)

            finally:
                db.close()

            await asyncio.sleep(scan_interval_seconds)

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Erreur Auto-Scan : {e}")
            await asyncio.sleep(60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"=== Démarrage de {APP_NAME} v{APP_VERSION} ===")

    try:
        init_db()
        logger.info("Base de données initialisée avec succès.")
    except Exception as e:
        logger.error(f"Erreur DB : {e}")

    try:
        init_firebase()
    except Exception as e:
        logger.error(f"Erreur Firebase : {e}")

    global _keep_alive_task, _auto_scan_task
    _keep_alive_task = asyncio.create_task(keep_alive_task())
    _auto_scan_task = asyncio.create_task(auto_scan_task())

    yield

    if _keep_alive_task:
        _keep_alive_task.cancel()
    if _auto_scan_task:
        _auto_scan_task.cancel()
    logger.info(f"=== Arrêt de {APP_NAME} ===")


app = FastAPI(
    title=API_TITLE,
    version=APP_VERSION,
    description=API_DESCRIPTION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/api/v2")
app.include_router(signals_router, prefix="/api/v2")
app.include_router(admin_router, prefix="/api/v2")
app.include_router(legacy_router, prefix="/api")


@app.get("/", tags=["Santé"])
def root():
    return {
        "app": APP_NAME,
        "version": APP_VERSION,
        "status": "ONLINE",
    }


@app.get("/health", tags=["Santé"])
def health():
    return {"status": "HEALTHY"}
