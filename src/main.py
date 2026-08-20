"""
TradeVision AI - Point d'entrée principal de l'application.

Version : 9.0.0
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.core.config import (
    APP_NAME,
    APP_VERSION,
    API_TITLE,
    API_DESCRIPTION,
    CORS_ORIGINS,
)
from src.core.database import init_db
from src.core.firebase import init_firebase
from src.core.logging import get_logger
from src.api.v2.auth import router as auth_router
from src.api.v2.signals import router as signals_router
from src.api.v2.admin import router as admin_router
from src.api.v1.routes import router as legacy_router

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Cycle de vie de l'application : Démarrage et Extinction."""
    logger.info(f"=== Démarrage de {APP_NAME} v{APP_VERSION} ===")

    # Initialisation de la base de données (création des tables si absentes)
    try:
        init_db()
        logger.info("Base de données initialisée avec succès.")
    except Exception as e:
        logger.error(f"Erreur initialisation base de données : {e}")

    # Initialisation Firebase Cloud Messaging
    try:
        init_firebase()
    except Exception as e:
        logger.error(f"Erreur initialisation Firebase : {e}")

    yield

    logger.info(f"=== Arrêt de {APP_NAME} ===")


# Création de l'application FastAPI
app = FastAPI(
    title=API_TITLE,
    version=APP_VERSION,
    description=API_DESCRIPTION,
    lifespan=lifespan,
)

# Configuration CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Inclusion des routeurs d'API
app.include_router(auth_router, prefix="/api/v2")
app.include_router(signals_router, prefix="/api/v2")
app.include_router(admin_router, prefix="/api/v2")
app.include_router(legacy_router, prefix="/api")


@app.get("/", tags=["Santé"])
def root():
    """Vérification rapide de l'état de l'API."""
    return {
        "app": APP_NAME,
        "version": APP_VERSION,
        "status": "ONLINE",
    }


@app.get("/health", tags=["Santé"])
def health():
    """Endpoint de monitoring pour Render / Kubernetes / Cloud."""
    return {"status": "HEALTHY"}