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
APP_VERSION = "9.1.0"
STRATEGY_VERSION = "v9.1.0"

# ENVIRONMENT: "development" (default) or "production".
# Utilisé uniquement pour activer des vérifications de sécurité strictes
# (fail-fast JWT_SECRET) — n'affecte aucune règle métier/scoring.
ENVIRONMENT = os.getenv("ENVIRONMENT", "development").strip().lower()


def _clamp_env_int(var_name: str, default: int, min_value: int, max_value: int) -> int:
    """Lit un entier depuis l'environnement et le borne à [min_value, max_value]."""
    raw = os.getenv(var_name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError:
        value = default
    return max(min_value, min(max_value, value))


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

TWELVE_DATA_BASE_URL = os.getenv("TWELVE_DATA_BASE_URL", "https://api.twelvedata.com").strip()

TWELVE_DATA_API_KEY_1 = os.getenv("TWELVE_DATA_API_KEY_1", "").strip()
TWELVE_DATA_API_KEY_2 = os.getenv("TWELVE_DATA_API_KEY_2", "").strip()

# Fallback compatibilité
if not TWELVE_DATA_API_KEY_1:
    TWELVE_DATA_API_KEY_1 = os.getenv("TWELVE_DATA_API_KEY", "").strip()

TWELVE_DATA_API_KEYS: List[str] = [
    key for key in (TWELVE_DATA_API_KEY_1, TWELVE_DATA_API_KEY_2) if key
]

# Durées de cooldown/exhaustion — configurables, bornées à [60, 300] secondes
# conformément au cahier des charges v9.1.0 (§3).
TWELVE_DATA_COOLDOWN_SECONDS = _clamp_env_int("TWELVE_DATA_COOLDOWN_SECONDS", 60, 60, 300)
TWELVE_DATA_EXHAUSTED_SECONDS = _clamp_env_int("TWELVE_DATA_EXHAUSTED_SECONDS", 300, 60, 300)

# Anti-stacking (§24) : une position active expire automatiquement après ce délai
# si aucun signal de direction opposée n'est survenu entretemps, pour éviter
# qu'une tendance prolongée bloque indéfiniment tout nouveau signal sur un actif.
POSITION_EXPIRY_HOURS = _clamp_env_int("POSITION_EXPIRY_HOURS", 5, 1, 168)

# Délai (secondes) entre chaque actif lors de l'Auto-Scan, pour éviter de saturer
# le quota Twelve Data en envoyant toutes les requêtes d'un coup (§3 du cahier
# des charges). N'affecte aucune règle de scoring — orchestration uniquement.
AUTO_SCAN_DELAY_BETWEEN_ASSETS_SECONDS = _clamp_env_int("AUTO_SCAN_DELAY_BETWEEN_ASSETS_SECONDS", 8, 0, 60)


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

_INSECURE_JWT_DEFAULT = "tradevision-insecure-default-DO-NOT-USE-IN-PRODUCTION"
JWT_SECRET = os.getenv("JWT_SECRET", "").strip() or _INSECURE_JWT_DEFAULT
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))


def validate_production_security() -> None:
    """
    Garde-fou de sécurité au démarrage : échoue immédiatement si l'application
    est lancée en production sans JWT_SECRET explicite.

    N'affecte aucune règle métier — vérification de configuration uniquement.
    """
    if ENVIRONMENT == "production" and JWT_SECRET == _INSECURE_JWT_DEFAULT:
        raise RuntimeError(
            "JWT_SECRET manquant ou vide en environnement de production. "
            "Définissez la variable d'environnement JWT_SECRET avant de démarrer "
            "l'application (voir .env.example)."
        )


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
DEFAULT_REFRESH_INTERVAL = int(os.getenv("REFRESH_INTERVAL", "15"))
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3-8b-instruct:free").strip()


# ============================================================
# CORS & URLS EXTERNES
# ============================================================

_cors_env = os.getenv("CORS_ORIGINS", "*").strip()
CORS_ORIGINS: List[str] = ["*"] if _cors_env == "*" else [o.strip() for o in _cors_env.split(",") if o.strip()]
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
