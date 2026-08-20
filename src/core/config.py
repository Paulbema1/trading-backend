"""
TradeVision AI - Configuration centrale de l'application.

Ce module contient uniquement :
- variables d'environnement
- constantes globales
- URLs externes
- configuration de la stratégie
- configuration de sécurité
"""

import os
from typing import List


# ============================================================
# APPLICATION
# ============================================================

APP_NAME = "TradeVision AI"
APP_VERSION = "9.0.0"
STRATEGY_VERSION = "v9.0.0"


# ============================================================
# FASTAPI
# ============================================================

API_TITLE = APP_NAME
API_VERSION = APP_VERSION
API_DESCRIPTION = (
    "Signal Engine avec Score déterministe, "
    "Multi-Timeframe 3 niveaux, Market Regime "
    "et Data Quality"
)


# ============================================================
# TWELVE DATA
# ============================================================

TWELVE_DATA_BASE_URL = "https://api.twelvedata.com"

TWELVE_DATA_API_KEY_1 = os.getenv("TWELVE_DATA_API_KEY_1", "").strip()
TWELVE_DATA_API_KEY_2 = os.getenv("TWELVE_DATA_API_KEY_2", "").strip()

# Fallback compatibilité
if not TWELVE_DATA_API_KEY_1:
    TWELVE_DATA_API_KEY_1 = os.getenv("TWELVE_DATA_API_KEY", "").strip()

TWELVE_DATA_API_KEYS: List[str] = [
    key for key in (TWELVE_DATA_API_KEY_1, TWELVE_DATA_API_KEY_2) if key
]


# ============================================================
# OPENROUTER
# ============================================================

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_CHAT_URL = f"{OPENROUTER_BASE_URL}/chat/completions"
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()


# ============================================================
# DATABASE
# ============================================================

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./tradevision.db").strip()

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)


# ============================================================
# FIREBASE
# ============================================================

FIREBASE_PROJECT_ID = os.getenv("FIREBASE_PROJECT_ID", "").strip()
FIREBASE_CLIENT_EMAIL = os.getenv("FIREBASE_CLIENT_EMAIL", "").strip()
FIREBASE_PRIVATE_KEY = os.getenv("FIREBASE_PRIVATE_KEY", "").replace("\\n", "\n")


# ============================================================
# JWT / AUTHENTIFICATION
# ============================================================

JWT_SECRET = os.getenv("JWT_SECRET", "tradevision-super-secret-key-change-me")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))


# ============================================================
# ASSETS & TIMEFRAMES
# ============================================================

SUPPORTED_ASSETS = [
    "EUR/USD",
    "GBP/USD",
    "USD/JPY",
    "XAU/USD",
]

SUPPORTED_TIMEFRAMES = [
    "15m",
    "30m",
    "1h",
    "4h",
]

MAIN_TIMEFRAME = os.getenv("MAIN_TIMEFRAME", "1h").strip()
CONFIRMATION_TIMEFRAME = os.getenv("CONFIRMATION_TIMEFRAME", "4h").strip()


# ============================================================
# STRATEGY & RISK
# ============================================================

DEFAULT_MIN_CONFIDENCE = int(os.getenv("MIN_CONFIDENCE", "70"))
DEFAULT_REFRESH_INTERVAL = int(os.getenv("REFRESH_INTERVAL", "5"))


# ============================================================
# CORS & URLS EXTERNES
# ============================================================

CORS_ORIGINS = ["*"]
NEWS_RSS_URL = os.getenv("NEWS_RSS_URL", "").strip()
ECONOMIC_CALENDAR_URL = os.getenv(
    "ECONOMIC_CALENDAR_URL",
    "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
).strip()


# ============================================================
# FONCTIONS DE VALIDATION
# ============================================================

def get_configured_twelve_data_keys() -> List[str]:
    return [k for k in (TWELVE_DATA_API_KEY_1, TWELVE_DATA_API_KEY_2) if k]

def has_twelve_data_keys() -> bool:
    return bool(get_configured_twelve_data_keys())

def validate_timeframe(timeframe: str) -> bool:
    return timeframe in SUPPORTED_TIMEFRAMES

def validate_asset(asset: str) -> bool:
    return asset in SUPPORTED_ASSETS