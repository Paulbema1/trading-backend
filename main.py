"""
═══════════════════════════════════════════════════════
    TRADEVISION AI - Version 9.0.0
    Signal Engine avec Score déterministe 0-100
    Multi-Timeframe 3 niveaux + Market Regime
    Data Quality + Fallback intelligent
═══════════════════════════════════════════════════════
"""

from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Float, Boolean, Text, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from passlib.context import CryptContext
from jose import JWTError, jwt
import requests
import os
import pandas as pd
import numpy as np
import xml.etree.ElementTree as ET
from html import unescape
import re
import json
import time
import threading
import uuid
from datetime import datetime, timedelta
from typing import Optional, List, Dict

import firebase_admin
from firebase_admin import credentials, messaging

# ═══════════════════════════════════════════════
#              CONFIGURATION
# ═══════════════════════════════════════════════

STRATEGY_VERSION = "v9.0.0"

app = FastAPI(
    title="TradeVision AI",
    version="9.0.0",
    description="Signal Engine avec Score déterministe et Data Quality"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Variables d'environnement
API_KEY = os.getenv("TWELVE_DATA_API_KEY", "")
API_KEY_2 = os.getenv("TWELVE_DATA_API_KEY_2", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./tradevision.db")
FIREBASE_PROJECT_ID = os.getenv("FIREBASE_PROJECT_ID", "")
FIREBASE_CLIENT_EMAIL = os.getenv("FIREBASE_CLIENT_EMAIL", "")
FIREBASE_PRIVATE_KEY = os.getenv("FIREBASE_PRIVATE_KEY", "").replace("\\n", "\n")
JWT_SECRET = os.getenv("JWT_SECRET", "tradevision-super-secret-key-change-me")

BASE_URL = "https://api.twelvedata.com"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)


# ═══════════════════════════════════════════════
#              BASE DE DONNEES
# ═══════════════════════════════════════════════

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    password_hash = Column(String(200), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)
    is_admin = Column(Boolean, default=False)
    
    main_timeframe = Column(String(10), default="1h")
    confirmation_timeframe = Column(String(10), default="4h")
    auto_confirmation = Column(Boolean, default=True)
    min_confidence = Column(Integer, default=70)
    notifications_enabled = Column(Boolean, default=True)
    refresh_interval = Column(Integer, default=5)
    
    fcm_token = Column(String(500), default="")


class SignalNotification(Base):
    __tablename__ = "signal_notifications"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True, nullable=False)
    asset = Column(String(20))
    signal_type = Column(String(10))
    confidence = Column(Integer)
    signal_key = Column(String(100))
    sent_at = Column(DateTime, default=datetime.utcnow)


class SignalV9(Base):
    """Nouvelle table pour les signaux v9.0"""
    __tablename__ = "signals_v9"
    
    id = Column(Integer, primary_key=True, index=True)
    signal_id = Column(String(100), unique=True, index=True)  # UUID
    strategy_version = Column(String(20))
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    
    asset = Column(String(20), index=True)
    symbol = Column(String(20))
    main_timeframe = Column(String(10))
    confirmation_timeframe = Column(String(10))
    higher_timeframe = Column(String(10))
    
    signal = Column(String(10), index=True)  # BUY/SELL/WAIT
    score = Column(Integer)  # 0-100
    classification = Column(String(20))  # WEAK/MODERATE/STRONG/etc
    
    scores_breakdown = Column(Text)  # JSON
    
    entry = Column(Float)
    stop_loss = Column(Float)
    take_profit_1 = Column(Float)
    take_profit_2 = Column(Float)
    take_profit_3 = Column(Float)
    risk_reward = Column(Float)
    
    market_regime = Column(String(20))  # TREND/RANGE/HIGH_VOL/LOW_VOL
    volatility = Column(String(20))
    
    data_quality_status = Column(String(20))  # GOOD/PARTIAL/POOR
    data_quality_details = Column(Text)  # JSON
    
    analysis_details = Column(Text)  # JSON complet
    reasons = Column(Text)  # JSON list
    warnings = Column(Text)  # JSON list
    
    ai_available = Column(Boolean, default=False)
    ai_summary = Column(Text)
    ai_model = Column(String(100))
    
    current_price = Column(Float)
    expiration = Column(DateTime)
    status = Column(String(20), default="ACTIVE", index=True)


class SignalResultV9(Base):
    """Résultats des signaux v9.0"""
    __tablename__ = "signal_results_v9"
    
    id = Column(Integer, primary_key=True, index=True)
    signal_id = Column(String(100), index=True)
    
    result = Column(String(20), default="PENDING")  # WIN/LOSS/EXPIRED/PENDING
    
    tp1_hit = Column(Boolean, default=False)
    tp2_hit = Column(Boolean, default=False)
    tp3_hit = Column(Boolean, default=False)
    sl_hit = Column(Boolean, default=False)
    
    tp1_hit_at = Column(DateTime)
    tp2_hit_at = Column(DateTime)
    tp3_hit_at = Column(DateTime)
    sl_hit_at = Column(DateTime)
    
    final_price = Column(Float)
    final_pnl_r = Column(Float)  # PnL en R (risk multiples)
    
    max_favorable_excursion = Column(Float)
    max_adverse_excursion = Column(Float)
    
    checked_at = Column(DateTime, default=datetime.utcnow)


try:
    Base.metadata.create_all(bind=engine)
    print("Base de donnees initialisee (v9.0)")
except Exception as e:
    print(f"Erreur base de donnees: {e}")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ═══════════════════════════════════════════════
#              AUTHENTIFICATION
# ═══════════════════════════════════════════════

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/v1/auth/login")

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = 30


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET, algorithm=ALGORITHM)
    return encoded_jwt


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token invalide ou expire",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    
    user = db.query(User).filter(User.username == username).first()
    if user is None:
        raise credentials_exception
    return user


# ═══════════════════════════════════════════════
#              FIREBASE
# ═══════════════════════════════════════════════

FIREBASE_APP = None

try:
    if FIREBASE_PROJECT_ID and FIREBASE_CLIENT_EMAIL and FIREBASE_PRIVATE_KEY:
        firebase_cred_dict = {
            "type": "service_account",
            "project_id": FIREBASE_PROJECT_ID,
            "private_key": FIREBASE_PRIVATE_KEY,
            "client_email": FIREBASE_CLIENT_EMAIL,
            "token_uri": "https://oauth2.googleapis.com/token",
        }
        cred = credentials.Certificate(firebase_cred_dict)
        FIREBASE_APP = firebase_admin.initialize_app(cred)
        print("Firebase initialise avec succes")
    else:
        print("Firebase non configure")
except Exception as e:
    print(f"Erreur Firebase: {e}")


def send_push_notification(fcm_token: str, title: str, body: str, data: dict = None):
    if not FIREBASE_APP or not fcm_token:
        return False
    
    try:
        message = messaging.Message(
            notification=messaging.Notification(title=title, body=body),
            data=data or {},
            token=fcm_token,
            android=messaging.AndroidConfig(
                priority='high',
                notification=messaging.AndroidNotification(
                    channel_id='trading_signals_channel',
                    priority='high',
                    default_sound=True,
                    default_vibrate_timings=True,
                )
            )
        )
        response = messaging.send(message)
        print(f"Notification envoyee: {response}")
        return True
    except Exception as e:
        print(f"Erreur envoi notification: {e}")
        return False


# ═══════════════════════════════════════════════
#              CONFIG TRADING
# ═══════════════════════════════════════════════

OPENROUTER_MODELS = [
    "nvidia/nemotron-nano-9b-v2:free",
    "x-ai/grok-4-fast:free",
    "deepseek/deepseek-chat-v3.1:free",
    "meta-llama/llama-4-maverick:free",
    "google/gemini-2.0-flash-exp:free",
    "qwen/qwen3-235b-a22b:free",
    "mistralai/mistral-small-3.2-24b-instruct:free"
]

ACTIVE_MODEL = None

ASSETS = {
    "EURUSD": "EUR/USD",
    "GBPUSD": "GBP/USD",
    "USDJPY": "USD/JPY",
    "XAUUSD": "XAU/USD"
}

ASSET_CURRENCIES = {
    "EURUSD": ["EUR", "USD"],
    "GBPUSD": ["GBP", "USD"],
    "USDJPY": ["USD", "JPY"],
    "XAUUSD": ["XAU", "USD"]
}

ASSET_BASE_QUOTE = {
    "EURUSD": ("EUR", "USD"),
    "GBPUSD": ("GBP", "USD"),
    "USDJPY": ("USD", "JPY"),
    "XAUUSD": ("XAU", "USD")
}

TIMEFRAMES = {
    "15m": "15min",
    "30m": "30min",
    "1h": "1h",
    "2h": "2h",
    "4h": "4h",
    "1d": "1day"
}

# Multi-Timeframe 3 niveaux (Entrée → Confirmation → Tendance générale)
MTF_3_LEVELS = {
    "15m": {"entry": "15m", "confirmation": "1h", "trend": "4h"},
    "30m": {"entry": "30m", "confirmation": "2h", "trend": "1d"},
    "1h": {"entry": "1h", "confirmation": "4h", "trend": "1d"},
    "2h": {"entry": "2h", "confirmation": "1d", "trend": "1d"},
    "4h": {"entry": "4h", "confirmation": "1d", "trend": "1d"},
    "1d": {"entry": "1d", "confirmation": "1d", "trend": "1d"}
}

CONFIRMATION_MAP = {
    "15m": "1h",
    "30m": "2h",
    "1h": "4h",
    "2h": "1d",
    "4h": "1d",
    "1d": "1d"
}

RSS_FEEDS = [
    "https://www.investing.com/rss/news_1.rss",
    "https://www.investing.com/rss/news_301.rss",
    "https://www.investing.com/rss/news_285.rss"
]

ECONOMIC_CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
TRACKED_CURRENCIES = ["USD", "EUR", "GBP", "JPY", "XAU"]

# Caches
NEWS_CACHE = {"data": None, "timestamp": 0}
CALENDAR_CACHE = {"data": None, "timestamp": 0}
AI_CACHE = {}
NEWS_CACHE_DURATION = 900
CALENDAR_CACHE_DURATION = 1800
AI_CACHE_DURATION = 900

# Classification score
SCORE_CLASSIFICATION = {
    (0, 49): "WAIT",
    (50, 59): "WEAK",
    (60, 69): "MODERATE",
    (70, 79): "STRONG",
    (80, 89): "VERY_STRONG",
    (90, 100): "EXTREME"
}


def classify_score(score: int) -> str:
    """Classifie un score de 0-100 en label"""
    for (low, high), label in SCORE_CLASSIFICATION.items():
        if low <= score <= high:
            return label
    return "WAIT"

# ═══════════════════════════════════════════════
#              KEEP ALIVE
# ═══════════════════════════════════════════════

def keep_alive():
    while True:
        time.sleep(300)
        try:
            requests.get("https://trading-backend-23od.onrender.com/health", timeout=10)
            print("Auto-ping OK")
        except Exception as e:
            print(f"Auto-ping error: {e}")


keep_alive_thread = threading.Thread(target=keep_alive, daemon=True)
keep_alive_thread.start()
print("Auto-ping thread demarre")


# ═══════════════════════════════════════════════
#              API TWELVE DATA
# ═══════════════════════════════════════════════

API_KEY_COUNTER = 0


def get_next_api_key():
    """Alterne entre les 2 cles Twelve Data"""
    global API_KEY_COUNTER
    
    if not API_KEY_2:
        return API_KEY
    
    API_KEY_COUNTER += 1
    if API_KEY_COUNTER % 2 == 0:
        return API_KEY_2
    return API_KEY


def td_request(endpoint, params):
    """Requete Twelve Data avec fallback sur 2eme cle si erreur 429"""
    current_key = get_next_api_key()
    params["apikey"] = current_key
    
    try:
        response = requests.get(BASE_URL + "/" + endpoint, params=params, timeout=10)
        result = response.json()
        
        # Si erreur de quota, essayer avec l'autre cle
        if isinstance(result, dict) and result.get("code") == 429:
            print(f"Quota depasse, bascule sur autre cle")
            other_key = API_KEY_2 if current_key == API_KEY else API_KEY
            if other_key:
                params["apikey"] = other_key
                response = requests.get(BASE_URL + "/" + endpoint, params=params, timeout=10)
                return response.json()
        
        return result
    except Exception as e:
        print(f"Erreur TD: {e}")
        return None


def get_candles_df(symbol, interval, limit=100):
    """Recupere les bougies au format DataFrame"""
    data = td_request("time_series", {
        "symbol": symbol,
        "interval": interval,
        "outputsize": limit
    })
    
    if not data or "values" not in data:
        return None
    
    values = list(reversed(data["values"]))
    df = pd.DataFrame(values)
    df["datetime"] = pd.to_datetime(df["datetime"])
    df["open"] = df["open"].astype(float)
    df["high"] = df["high"].astype(float)
    df["low"] = df["low"].astype(float)
    df["close"] = df["close"].astype(float)
    df.set_index("datetime", inplace=True)
    return df


# ═══════════════════════════════════════════════
#          DATA QUALITY CHECK (NEW v9.0)
# ═══════════════════════════════════════════════

def check_data_quality(df, min_candles=30):
    """
    Verifie la qualite des donnees avant analyse
    Retourne dict avec status et details
    """
    quality = {
        "status": "GOOD",
        "candles_count": 0,
        "missing_data": 0,
        "warnings": [],
        "usable": True
    }
    
    if df is None:
        quality["status"] = "POOR"
        quality["warnings"].append("Aucune donnee disponible")
        quality["usable"] = False
        return quality
    
    # Nombre de bougies
    candle_count = len(df)
    quality["candles_count"] = candle_count
    
    if candle_count < min_candles:
        quality["status"] = "POOR"
        quality["warnings"].append(f"Bougies insuffisantes: {candle_count}/{min_candles}")
        quality["usable"] = False
        return quality
    
    # Verifier les valeurs manquantes
    missing = df[["open", "high", "low", "close"]].isnull().sum().sum()
    quality["missing_data"] = int(missing)
    
    if missing > 0:
        quality["warnings"].append(f"{missing} valeurs manquantes")
        if missing > candle_count * 0.05:  # Plus de 5%
            quality["status"] = "POOR"
            quality["usable"] = False
            return quality
    
    # Verifier les prix aberrants (0 ou negatifs)
    if (df["close"] <= 0).any() or (df["high"] <= 0).any() or (df["low"] <= 0).any():
        quality["status"] = "POOR"
        quality["warnings"].append("Prix invalides detectes")
        quality["usable"] = False
        return quality
    
    # Verifier coherence OHLC (High >= Low, etc.)
    invalid_ohlc = ((df["high"] < df["low"]) | 
                    (df["high"] < df["close"]) | 
                    (df["high"] < df["open"]) |
                    (df["low"] > df["close"]) |
                    (df["low"] > df["open"])).sum()
    
    if invalid_ohlc > 0:
        quality["warnings"].append(f"{invalid_ohlc} bougies OHLC incoherentes")
        quality["status"] = "PARTIAL"
    
    # Verifier trous temporels
    if candle_count > 1:
        time_diffs = df.index.to_series().diff().dropna()
        if len(time_diffs) > 0:
            median_diff = time_diffs.median()
            large_gaps = (time_diffs > median_diff * 3).sum()
            
            if large_gaps > candle_count * 0.1:
                quality["warnings"].append(f"{large_gaps} trous temporels importants")
                if quality["status"] == "GOOD":
                    quality["status"] = "PARTIAL"
    
    # Verifier variations aberrantes
    price_changes = df["close"].pct_change().abs()
    extreme_moves = (price_changes > 0.10).sum()  # +10% en 1 bougie
    
    if extreme_moves > 0:
        quality["warnings"].append(f"{extreme_moves} mouvements extremes (>10%)")
        if quality["status"] == "GOOD":
            quality["status"] = "PARTIAL"
    
    return quality


# ═══════════════════════════════════════════════
#              CACHE NEWS & CALENDRIER
# ═══════════════════════════════════════════════

def clean_html_text(text):
    if not text:
        return ""
    text = re.sub(r'<[^>]+>', '', text)
    text = unescape(text)
    return text.strip()


def detect_currency(text):
    currencies = []
    t = text.upper()
    if "EUR" in t or "ECB" in t:
        currencies.append("EUR")
    if "USD" in t or "DOLLAR" in t or "FED" in t:
        currencies.append("USD")
    if "GBP" in t or "POUND" in t or "BOE" in t:
        currencies.append("GBP")
    if "JPY" in t or "YEN" in t or "BOJ" in t:
        currencies.append("JPY")
    if "GOLD" in t or "XAU" in t:
        currencies.append("XAU")
    if not currencies:
        currencies = ["GENERAL"]
    return currencies


def detect_sentiment(text):
    t = text.lower()
    bull_words = ["rise", "surge", "gain", "rally", "up", "high", "strong", "positive", "beat", "hawkish"]
    bear_words = ["fall", "drop", "decline", "down", "low", "weak", "loss", "negative", "miss", "dovish"]
    bs = sum(1 for w in bull_words if w in t)
    br = sum(1 for w in bear_words if w in t)
    if bs > br:
        return "bullish"
    if br > bs:
        return "bearish"
    return "neutral"


def detect_impact(text):
    t = text.lower()
    high = ["fed", "ecb", "boj", "boe", "rate", "inflation", "gdp", "nfp", "cpi", "fomc"]
    med = ["employment", "retail", "manufacturing", "trade", "consumer"]
    for w in high:
        if w in t:
            return "HIGH"
    for w in med:
        if w in t:
            return "MEDIUM"
    return "LOW"


def fetch_news_from_rss(url, limit=10):
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 AppleWebKit/537.36',
            'Accept': 'application/rss+xml, application/xml, text/xml, */*'
        }
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        content = response.content
        try:
            root = ET.fromstring(content)
        except ET.ParseError:
            content_str = response.text
            content_str = re.sub(r'&(?!(?:amp|lt|gt|quot|apos);)', '&amp;', content_str)
            root = ET.fromstring(content_str.encode('utf-8'))
        
        items = root.findall('.//item')[:limit]
        news = []
        for item in items:
            title_elem = item.find('title')
            desc_elem = item.find('description')
            link_elem = item.find('link')
            date_elem = item.find('pubDate')
            
            title_text = title_elem.text if title_elem is not None and title_elem.text else ""
            desc_text = clean_html_text(desc_elem.text) if desc_elem is not None and desc_elem.text else ""
            link_text = link_elem.text if link_elem is not None and link_elem.text else ""
            pub_date = date_elem.text if date_elem is not None and date_elem.text else ""
            
            if not title_text:
                continue
            
            full = title_text + " " + desc_text
            news.append({
                "title": title_text,
                "description": desc_text[:200],
                "link": link_text,
                "published": pub_date,
                "currencies": detect_currency(full),
                "sentiment": detect_sentiment(full),
                "impact": detect_impact(full)
            })
        return news
    except Exception as e:
        print(f"RSS error: {e}")
        return []


def get_cached_news():
    now = time.time()
    
    if NEWS_CACHE["data"] and (now - NEWS_CACHE["timestamp"]) < NEWS_CACHE_DURATION:
        return NEWS_CACHE["data"]
    
    all_news = []
    for url in RSS_FEEDS:
        all_news.extend(fetch_news_from_rss(url, limit=10))
    
    if all_news:
        NEWS_CACHE["data"] = all_news
        NEWS_CACHE["timestamp"] = now
        return all_news
    
    if NEWS_CACHE["data"]:
        return NEWS_CACHE["data"]
    
    return []


def fetch_economic_calendar():
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(ECONOMIC_CALENDAR_URL, headers=headers, timeout=15)
        response.raise_for_status()
        data = response.json()
        events = []
        for e in data:
            cur = e.get("country", "").upper()
            if cur not in TRACKED_CURRENCIES:
                continue
            events.append({
                "title": e.get("title", ""),
                "currency": cur,
                "date": e.get("date", ""),
                "impact": e.get("impact", "Low").upper(),
                "forecast": e.get("forecast", "") or "---",
                "previous": e.get("previous", "") or "---",
                "actual": e.get("actual", "") or "---"
            })
        return events
    except Exception as e:
        print(f"Cal error: {e}")
        return []


def get_cached_calendar():
    now = time.time()
    
    if CALENDAR_CACHE["data"] and (now - CALENDAR_CACHE["timestamp"]) < CALENDAR_CACHE_DURATION:
        return CALENDAR_CACHE["data"]
    
    events = fetch_economic_calendar()
    
    if events:
        CALENDAR_CACHE["data"] = events
        CALENDAR_CACHE["timestamp"] = now
        return events
    
    if CALENDAR_CACHE["data"]:
        return CALENDAR_CACHE["data"]
    
    return []


def get_upcoming_events(hours_ahead=24, currencies=None):
    events = get_cached_calendar()
    now = datetime.utcnow()
    upcoming = []
    for e in events:
        try:
            ds = e["date"].split("-04:00")[0]
            et = datetime.fromisoformat(ds)
            diff = (et - now).total_seconds() / 3600
            if 0 < diff <= hours_ahead:
                if currencies and e["currency"] not in currencies:
                    continue
                e["hours_until"] = round(diff, 1)
                upcoming.append(e)
        except Exception:
            continue
    return sorted(upcoming, key=lambda x: x.get("hours_until", 999))


# ═══════════════════════════════════════════════
#              OPENROUTER (IA)
# ═══════════════════════════════════════════════

def call_openrouter(prompt, max_retries=3):
    global ACTIVE_MODEL
    
    if not OPENROUTER_API_KEY:
        return None
    
    headers = {
        "Authorization": "Bearer " + OPENROUTER_API_KEY,
        "Content-Type": "application/json",
        "HTTP-Referer": "https://tradevision-ai.app",
        "X-Title": "TradeVision AI"
    }
    
    models_to_try = [ACTIVE_MODEL] if ACTIVE_MODEL else OPENROUTER_MODELS
    
    for model in models_to_try:
        if not model:
            continue
        
        for attempt in range(max_retries):
            try:
                payload = {
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3,
                    "max_tokens": 800
                }
                
                response = requests.post(
                    OPENROUTER_URL,
                    headers=headers,
                    json=payload,
                    timeout=30
                )
                
                if response.status_code == 429:
                    wait_time = 2 ** attempt
                    time.sleep(wait_time)
                    continue
                
                if response.status_code == 200:
                    data = response.json()
                    if "choices" in data and len(data["choices"]) > 0:
                        content = data["choices"][0]["message"]["content"]
                        if ACTIVE_MODEL != model:
                            ACTIVE_MODEL = model
                            print(f"Active model: {model}")
                        return content
                else:
                    break
                    
            except Exception as e:
                print(f"OpenRouter exception: {str(e)[:100]}")
                break
    
    return None

# ═══════════════════════════════════════════════
#      TECHNICAL ANALYSIS MODULE (v9.0)
# ═══════════════════════════════════════════════

# ─── Indicateurs de base ───

def ema(series, period):
    """Exponential Moving Average"""
    return series.ewm(span=period, adjust=False).mean()


def sma(series, period):
    """Simple Moving Average"""
    return series.rolling(window=period).mean()


def rsi(series, period=14):
    """Relative Strength Index"""
    delta = series.diff()
    gain = delta.where(delta > 0, 0).rolling(window=period).mean()
    loss = -delta.where(delta < 0, 0).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


def macd(series, fast=12, slow=26, signal=9):
    """MACD - Moving Average Convergence Divergence"""
    ema_fast = ema(series, fast)
    ema_slow = ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def atr(df, period=14):
    """Average True Range"""
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift()).abs()
    low_close = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()


def bollinger_bands(series, period=20, std=2):
    """Bollinger Bands"""
    sma_val = series.rolling(window=period).mean()
    std_dev = series.rolling(window=period).std()
    upper = sma_val + (std_dev * std)
    lower = sma_val - (std_dev * std)
    return upper, sma_val, lower


def adx(df, period=14):
    """
    Average Directional Index
    Mesure la force de la tendance (0-100)
    """
    high = df["high"]
    low = df["low"]
    close = df["close"]
    
    # True Range
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs()
    ], axis=1).max(axis=1)
    
    # Directional Movement
    up_move = high - high.shift()
    down_move = low.shift() - low
    
    plus_dm = ((up_move > down_move) & (up_move > 0)) * up_move
    minus_dm = ((down_move > up_move) & (down_move > 0)) * down_move
    
    # Smoothed values
    atr_val = tr.rolling(window=period).mean()
    plus_di = 100 * (plus_dm.rolling(window=period).mean() / atr_val)
    minus_di = 100 * (minus_dm.rolling(window=period).mean() / atr_val)
    
    # ADX
    dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di))
    adx_val = dx.rolling(window=period).mean()
    
    return adx_val, plus_di, minus_di


def stochastic(df, k_period=14, d_period=3):
    """Stochastic Oscillator"""
    low_min = df["low"].rolling(window=k_period).min()
    high_max = df["high"].rolling(window=k_period).max()
    
    k = 100 * ((df["close"] - low_min) / (high_max - low_min))
    d = k.rolling(window=d_period).mean()
    
    return k, d


def find_support_resistance(df, window=10):
    """Trouve supports et resistances (pivots)"""
    highs = df["high"].rolling(window=window, center=True).max()
    lows = df["low"].rolling(window=window, center=True).min()
    resistances = df["high"][df["high"] == highs].dropna().tail(3).tolist()
    supports = df["low"][df["low"] == lows].dropna().tail(3).tolist()
    return supports, resistances


def calculate_momentum(df, period=10):
    """Momentum du prix"""
    return df["close"].diff(period)


def detect_market_regime(df):
    """
    Detecte le regime de marche
    Retourne: TREND / RANGE / HIGH_VOL / LOW_VOL
    """
    if len(df) < 30:
        return "UNKNOWN"
    
    # Calculer ADX pour la force de tendance
    adx_val, _, _ = adx(df, 14)
    current_adx = adx_val.iloc[-1] if not adx_val.empty else 0
    
    # Calculer volatilite (ATR relatif)
    atr_val = atr(df, 14)
    current_atr = atr_val.iloc[-1] if not atr_val.empty else 0
    price = df["close"].iloc[-1]
    volatility_pct = (current_atr / price) * 100 if price > 0 else 0
    
    # Volatilite moyenne sur la periode
    avg_volatility = (atr_val / df["close"] * 100).rolling(50).mean().iloc[-1] if len(df) >= 50 else volatility_pct
    
    # Classification
    if current_adx >= 25:
        # Tendance forte
        if volatility_pct > avg_volatility * 1.5:
            return "TREND_HIGH_VOL"
        return "TREND"
    else:
        # Pas de tendance forte
        if volatility_pct > avg_volatility * 1.5:
            return "HIGH_VOL"
        elif volatility_pct < avg_volatility * 0.5:
            return "LOW_VOL"
        return "RANGE"


def detect_trading_session():
    """Detecte la session de trading actuelle"""
    hour_utc = datetime.utcnow().hour
    
    if 0 <= hour_utc < 8:
        return "ASIA"
    elif 8 <= hour_utc < 13:
        return "LONDON"
    elif 13 <= hour_utc < 17:
        return "LONDON_NY_OVERLAP"
    elif 17 <= hour_utc < 22:
        return "NEW_YORK"
    else:
        return "SYDNEY"


# ─── Analyse technique complete v9.0 ───

def analyze_technical_v9(df):
    """
    Analyse technique complete pour v9.0
    Retourne un dict avec tous les indicateurs + score technique (0-25)
    """
    if df is None or len(df) < 30:
        return None
    
    close = df["close"]
    current_price = float(close.iloc[-1])
    
    # ─── Calcul des indicateurs ───
    ema_20 = ema(close, 20).iloc[-1]
    ema_50 = ema(close, 50).iloc[-1]
    ema_100 = ema(close, 100).iloc[-1] if len(close) >= 100 else None
    ema_200 = ema(close, 200).iloc[-1] if len(close) >= 200 else None
    
    rsi_val = rsi(close, 14).iloc[-1]
    
    macd_line, signal_line, hist = macd(close)
    macd_val = macd_line.iloc[-1]
    macd_sig = signal_line.iloc[-1]
    macd_hist = hist.iloc[-1]
    
    atr_val = atr(df, 14).iloc[-1]
    
    bb_upper_series, bb_mid_series, bb_lower_series = bollinger_bands(close)
    bb_upper = bb_upper_series.iloc[-1]
    bb_lower = bb_lower_series.iloc[-1]
    bb_mid = bb_mid_series.iloc[-1]
    
    adx_val, plus_di, minus_di = adx(df, 14)
    current_adx = adx_val.iloc[-1] if not adx_val.empty else 0
    current_plus_di = plus_di.iloc[-1] if not plus_di.empty else 0
    current_minus_di = minus_di.iloc[-1] if not minus_di.empty else 0
    
    stoch_k, stoch_d = stochastic(df)
    current_stoch_k = stoch_k.iloc[-1] if not stoch_k.empty else 50
    current_stoch_d = stoch_d.iloc[-1] if not stoch_d.empty else 50
    
    supports, resistances = find_support_resistance(df)
    
    # Momentum
    momentum = calculate_momentum(df, 10).iloc[-1]
    momentum_pct = (momentum / current_price * 100) if current_price > 0 else 0
    
    # Regime marche
    market_regime = detect_market_regime(df)
    session = detect_trading_session()
    
    # ─── Determiner tendance ───
    trend = "neutral"
    trend_strength = 0
    
    if ema_200 and current_price > ema_50 > ema_100 > ema_200:
        trend = "strong_bullish"
        trend_strength = 100
    elif ema_100 and current_price > ema_50 > ema_100:
        trend = "bullish"
        trend_strength = 75
    elif current_price > ema_20 > ema_50:
        trend = "weak_bullish"
        trend_strength = 50
    elif ema_200 and current_price < ema_50 < ema_100 < ema_200:
        trend = "strong_bearish"
        trend_strength = -100
    elif ema_100 and current_price < ema_50 < ema_100:
        trend = "bearish"
        trend_strength = -75
    elif current_price < ema_20 < ema_50:
        trend = "weak_bearish"
        trend_strength = -50
    
    # ─── Score technique (0-25 pts) ───
    tech_score = 0
    reasons = []
    signals_count = 0
    
    # 1. Tendance EMA (0-8 pts)
    if trend == "strong_bullish":
        tech_score += 8
        reasons.append("Tendance haussiere forte (EMA)")
        signals_count += 1
    elif trend == "bullish":
        tech_score += 6
        reasons.append("Tendance haussiere (EMA)")
        signals_count += 1
    elif trend == "weak_bullish":
        tech_score += 3
        reasons.append("Tendance haussiere faible")
    elif trend == "strong_bearish":
        tech_score -= 8
        reasons.append("Tendance baissiere forte (EMA)")
        signals_count += 1
    elif trend == "bearish":
        tech_score -= 6
        reasons.append("Tendance baissiere (EMA)")
        signals_count += 1
    elif trend == "weak_bearish":
        tech_score -= 3
        reasons.append("Tendance baissiere faible")
    
    # 2. RSI (0-4 pts)
    if 40 <= rsi_val <= 60:
        # Zone neutre
        pass
    elif rsi_val < 30:
        tech_score += 4
        reasons.append(f"RSI en survente ({rsi_val:.1f})")
        signals_count += 1
    elif rsi_val > 70:
        tech_score -= 4
        reasons.append(f"RSI en surachat ({rsi_val:.1f})")
        signals_count += 1
    elif 30 <= rsi_val <= 40:
        tech_score += 2
        reasons.append(f"RSI proche survente ({rsi_val:.1f})")
    elif 60 <= rsi_val <= 70:
        tech_score -= 2
        reasons.append(f"RSI proche surachat ({rsi_val:.1f})")
    
    # 3. MACD (0-5 pts)
    if macd_val > macd_sig and macd_hist > 0:
        tech_score += 5
        reasons.append("MACD haussier (croisement)")
        signals_count += 1
    elif macd_val < macd_sig and macd_hist < 0:
        tech_score -= 5
        reasons.append("MACD baissier (croisement)")
        signals_count += 1
    elif macd_val > macd_sig:
        tech_score += 2
        reasons.append("MACD au-dessus signal")
    elif macd_val < macd_sig:
        tech_score -= 2
        reasons.append("MACD sous signal")
    
    # 4. Bollinger Bands (0-3 pts)
    if current_price < bb_lower:
        tech_score += 3
        reasons.append("Prix sous Bollinger inferieure")
        signals_count += 1
    elif current_price > bb_upper:
        tech_score -= 3
        reasons.append("Prix au-dessus Bollinger superieure")
        signals_count += 1
    
    # 5. ADX + DI (0-3 pts) - Force de tendance
    if current_adx >= 25:
        if current_plus_di > current_minus_di:
            tech_score += 3
            reasons.append(f"ADX fort haussier ({current_adx:.1f})")
            signals_count += 1
        else:
            tech_score -= 3
            reasons.append(f"ADX fort baissier ({current_adx:.1f})")
            signals_count += 1
    
    # 6. Stochastic (0-2 pts)
    if current_stoch_k < 20 and current_stoch_k > current_stoch_d:
        tech_score += 2
        reasons.append(f"Stochastic survente + croisement haussier")
        signals_count += 1
    elif current_stoch_k > 80 and current_stoch_k < current_stoch_d:
        tech_score -= 2
        reasons.append(f"Stochastic surachat + croisement baissier")
        signals_count += 1
    
    # Score final entre -25 et +25, normalise en 0-25
    # Score negatif = baissier, positif = haussier
    tech_score_absolute = abs(tech_score)
    tech_score_final = min(tech_score_absolute, 25)
    
    # Direction technique
    if tech_score > 5:
        tech_direction = "bullish"
    elif tech_score < -5:
        tech_direction = "bearish"
    else:
        tech_direction = "neutral"
    
    return {
        "score": int(tech_score_final),
        "score_raw": int(tech_score),
        "direction": tech_direction,
        "trend": trend,
        "trend_strength": trend_strength,
        "signals_count": signals_count,
        "current_price": round(current_price, 5),
        "market_regime": market_regime,
        "trading_session": session,
        "indicators": {
            "ema_20": round(float(ema_20), 5),
            "ema_50": round(float(ema_50), 5),
            "ema_100": round(float(ema_100), 5) if ema_100 else None,
            "ema_200": round(float(ema_200), 5) if ema_200 else None,
            "rsi": round(float(rsi_val), 2),
            "macd": round(float(macd_val), 5),
            "macd_signal": round(float(macd_sig), 5),
            "macd_hist": round(float(macd_hist), 5),
            "atr": round(float(atr_val), 5),
            "atr_pct": round(float(atr_val / current_price * 100), 3) if current_price > 0 else 0,
            "bb_upper": round(float(bb_upper), 5),
            "bb_middle": round(float(bb_mid), 5),
            "bb_lower": round(float(bb_lower), 5),
            "adx": round(float(current_adx), 2),
            "plus_di": round(float(current_plus_di), 2),
            "minus_di": round(float(current_minus_di), 2),
            "stoch_k": round(float(current_stoch_k), 2),
            "stoch_d": round(float(current_stoch_d), 2),
            "momentum_pct": round(float(momentum_pct), 3)
        },
        "support_resistance": {
            "supports": [round(s, 5) for s in supports],
            "resistances": [round(r, 5) for r in resistances]
        },
        "reasons": reasons
    }

# ═══════════════════════════════════════════════
#      SMART MONEY CONCEPTS MODULE (v9.0)
# ═══════════════════════════════════════════════

def find_swing_points(df, lookback=5):
    """Detecte les swing highs et swing lows"""
    swing_highs = []
    swing_lows = []
    
    for i in range(lookback, len(df) - lookback):
        high = df["high"].iloc[i]
        low = df["low"].iloc[i]
        
        # Swing High
        is_swing_high = True
        for j in range(1, lookback + 1):
            if high <= df["high"].iloc[i - j] or high <= df["high"].iloc[i + j]:
                is_swing_high = False
                break
        
        if is_swing_high:
            swing_highs.append({
                "index": i,
                "datetime": df.index[i],
                "price": float(high)
            })
        
        # Swing Low
        is_swing_low = True
        for j in range(1, lookback + 1):
            if low >= df["low"].iloc[i - j] or low >= df["low"].iloc[i + j]:
                is_swing_low = False
                break
        
        if is_swing_low:
            swing_lows.append({
                "index": i,
                "datetime": df.index[i],
                "price": float(low)
            })
    
    return swing_highs, swing_lows


def analyze_market_structure(df):
    """Analyse la structure du marche (HH/HL, LH/LL)"""
    swing_highs, swing_lows = find_swing_points(df, lookback=5)
    
    structure = {
        "trend": "neutral",
        "structure_type": "unknown",
        "recent_highs": [],
        "recent_lows": [],
        "strength": 0  # 0-100
    }
    
    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return structure
    
    last_highs = swing_highs[-3:] if len(swing_highs) >= 3 else swing_highs
    last_lows = swing_lows[-3:] if len(swing_lows) >= 3 else swing_lows
    
    structure["recent_highs"] = [{"price": h["price"], "index": h["index"]} for h in last_highs]
    structure["recent_lows"] = [{"price": l["price"], "index": l["index"]} for l in last_lows]
    
    # Compter HH/HL vs LH/LL
    higher_highs = sum(1 for i in range(1, len(last_highs)) if last_highs[i]["price"] > last_highs[i-1]["price"])
    lower_highs = len(last_highs) - 1 - higher_highs
    higher_lows = sum(1 for i in range(1, len(last_lows)) if last_lows[i]["price"] > last_lows[i-1]["price"])
    lower_lows = len(last_lows) - 1 - higher_lows
    
    total_bullish = higher_highs + higher_lows
    total_bearish = lower_highs + lower_lows
    total = total_bullish + total_bearish
    
    if total_bullish > total_bearish:
        structure["trend"] = "bullish"
        structure["structure_type"] = "HH_HL"
        structure["strength"] = int((total_bullish / total) * 100) if total > 0 else 0
    elif total_bearish > total_bullish:
        structure["trend"] = "bearish"
        structure["structure_type"] = "LH_LL"
        structure["strength"] = int((total_bearish / total) * 100) if total > 0 else 0
    else:
        structure["trend"] = "ranging"
        structure["structure_type"] = "consolidation"
        structure["strength"] = 50
    
    return structure


def detect_bos(df, structure):
    """Break of Structure - Cassure de structure"""
    swing_highs, swing_lows = find_swing_points(df, lookback=5)
    
    bos = {
        "detected": False,
        "type": None,
        "level": None,
        "index": None,
        "strength": 0
    }
    
    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return bos
    
    current_price = float(df["close"].iloc[-1])
    
    # BOS Haussier
    if len(swing_highs) >= 2:
        last_swing_high = swing_highs[-2]["price"]
        recent_high_after = max([df["high"].iloc[i] for i in range(swing_highs[-2]["index"] + 1, len(df))])
        
        if recent_high_after > last_swing_high and current_price > last_swing_high:
            break_strength = ((current_price - last_swing_high) / last_swing_high) * 10000  # en pips %
            bos = {
                "detected": True,
                "type": "bullish",
                "level": round(last_swing_high, 5),
                "index": swing_highs[-2]["index"],
                "strength": min(int(break_strength * 10), 100)
            }
    
    # BOS Baissier
    if len(swing_lows) >= 2:
        last_swing_low = swing_lows[-2]["price"]
        recent_low_after = min([df["low"].iloc[i] for i in range(swing_lows[-2]["index"] + 1, len(df))])
        
        if recent_low_after < last_swing_low and current_price < last_swing_low:
            break_strength = ((last_swing_low - current_price) / last_swing_low) * 10000
            if not bos["detected"] or break_strength > bos.get("strength", 0):
                bos = {
                    "detected": True,
                    "type": "bearish",
                    "level": round(last_swing_low, 5),
                    "index": swing_lows[-2]["index"],
                    "strength": min(int(break_strength * 10), 100)
                }
    
    return bos


def detect_choch(df, structure):
    """Change of Character - Changement de caractere du marche"""
    swing_highs, swing_lows = find_swing_points(df, lookback=5)
    
    choch = {
        "detected": False,
        "type": None,
        "level": None,
        "reason": "",
        "strength": 0
    }
    
    if len(swing_highs) < 3 or len(swing_lows) < 3:
        return choch
    
    current_price = float(df["close"].iloc[-1])
    
    # CHOCH Haussier (dans tendance baissiere)
    if structure["trend"] == "bearish":
        recent_high = swing_highs[-1]["price"]
        if current_price > recent_high:
            choch = {
                "detected": True,
                "type": "bullish",
                "level": round(recent_high, 5),
                "reason": "Cassure haussiere apres tendance baissiere",
                "strength": 80
            }
    
    # CHOCH Baissier (dans tendance haussiere)
    elif structure["trend"] == "bullish":
        recent_low = swing_lows[-1]["price"]
        if current_price < recent_low:
            choch = {
                "detected": True,
                "type": "bearish",
                "level": round(recent_low, 5),
                "reason": "Cassure baissiere apres tendance haussiere",
                "strength": 80
            }
    
    return choch


def detect_order_blocks(df, lookback=20):
    """Detecte les Order Blocks (blocs d'ordres)"""
    order_blocks = {
        "bullish": [],
        "bearish": []
    }
    
    if len(df) < lookback + 5:
        return order_blocks
    
    for i in range(len(df) - lookback, len(df) - 2):
        candle = df.iloc[i]
        next_candles = df.iloc[i+1:i+5]
        
        candle_range = candle["high"] - candle["low"]
        if candle_range == 0:
            continue
        
        # OB Bullish : bougie baissiere suivie de forte hausse
        if candle["close"] < candle["open"]:
            move_up = (next_candles["high"].max() - candle["low"]) / candle["low"] * 100
            if move_up > 0.3:
                order_blocks["bullish"].append({
                    "type": "bullish",
                    "high": round(float(candle["high"]), 5),
                    "low": round(float(candle["low"]), 5),
                    "index": i,
                    "strength": round(move_up, 2)
                })
        
        # OB Bearish : bougie haussiere suivie de forte baisse
        if candle["close"] > candle["open"]:
            move_down = (candle["high"] - next_candles["low"].min()) / candle["high"] * 100
            if move_down > 0.3:
                order_blocks["bearish"].append({
                    "type": "bearish",
                    "high": round(float(candle["high"]), 5),
                    "low": round(float(candle["low"]), 5),
                    "index": i,
                    "strength": round(move_down, 2)
                })
    
    # Garder les 3 plus forts
    order_blocks["bullish"] = sorted(order_blocks["bullish"], key=lambda x: x["strength"], reverse=True)[:3]
    order_blocks["bearish"] = sorted(order_blocks["bearish"], key=lambda x: x["strength"], reverse=True)[:3]
    
    return order_blocks


def detect_fvg(df, lookback=30):
    """Fair Value Gaps - Ecarts de valeur"""
    fvg_list = {
        "bullish": [],
        "bearish": []
    }
    
    if len(df) < 3:
        return fvg_list
    
    start = max(0, len(df) - lookback)
    
    for i in range(start + 1, len(df) - 1):
        prev_candle = df.iloc[i - 1]
        next_candle = df.iloc[i + 1]
        
        # FVG Bullish
        if next_candle["low"] > prev_candle["high"]:
            gap_size = next_candle["low"] - prev_candle["high"]
            fvg_list["bullish"].append({
                "type": "bullish",
                "top": round(float(next_candle["low"]), 5),
                "bottom": round(float(prev_candle["high"]), 5),
                "index": i,
                "size": round(float(gap_size), 5)
            })
        
        # FVG Bearish
        if next_candle["high"] < prev_candle["low"]:
            gap_size = prev_candle["low"] - next_candle["high"]
            fvg_list["bearish"].append({
                "type": "bearish",
                "top": round(float(prev_candle["low"]), 5),
                "bottom": round(float(next_candle["high"]), 5),
                "index": i,
                "size": round(float(gap_size), 5)
            })
    
    fvg_list["bullish"] = fvg_list["bullish"][-3:]
    fvg_list["bearish"] = fvg_list["bearish"][-3:]
    
    return fvg_list


def detect_liquidity_zones(df, lookback=50):
    """Zones de liquidite (Equal Highs / Equal Lows)"""
    liquidity = {
        "equal_highs": [],
        "equal_lows": [],
        "buy_side_liquidity": [],
        "sell_side_liquidity": []
    }
    
    if len(df) < 10:
        return liquidity
    
    start = max(0, len(df) - lookback)
    tolerance = df["close"].mean() * 0.0005
    
    highs = [(i, float(df["high"].iloc[i])) for i in range(start, len(df))]
    lows = [(i, float(df["low"].iloc[i])) for i in range(start, len(df))]
    
    # Equal Highs
    for i in range(len(highs)):
        for j in range(i + 1, len(highs)):
            if abs(highs[i][1] - highs[j][1]) <= tolerance:
                liquidity["equal_highs"].append({
                    "price": round(highs[i][1], 5),
                    "indices": [highs[i][0], highs[j][0]]
                })
    
    # Equal Lows
    for i in range(len(lows)):
        for j in range(i + 1, len(lows)):
            if abs(lows[i][1] - lows[j][1]) <= tolerance:
                liquidity["equal_lows"].append({
                    "price": round(lows[i][1], 5),
                    "indices": [lows[i][0], lows[j][0]]
                })
    
    # Buy Side Liquidity (au-dessus)
    if liquidity["equal_highs"]:
        recent_eh = sorted(liquidity["equal_highs"], key=lambda x: x["price"], reverse=True)[:3]
        liquidity["buy_side_liquidity"] = [x["price"] for x in recent_eh]
    
    # Sell Side Liquidity (en-dessous)
    if liquidity["equal_lows"]:
        recent_el = sorted(liquidity["equal_lows"], key=lambda x: x["price"])[:3]
        liquidity["sell_side_liquidity"] = [x["price"] for x in recent_el]
    
    liquidity["equal_highs"] = liquidity["equal_highs"][:5]
    liquidity["equal_lows"] = liquidity["equal_lows"][:5]
    
    return liquidity


def detect_liquidity_sweep(df, liquidity):
    """Detecte les balayages de liquidite"""
    sweep = {
        "detected": False,
        "type": None,
        "level": None,
        "reason": ""
    }
    
    if len(df) < 5:
        return sweep
    
    recent_candles = df.tail(5)
    current_close = float(df["close"].iloc[-1])
    
    # Sweep bearish (balayage au-dessus puis retour)
    for bsl_price in liquidity.get("buy_side_liquidity", []):
        if recent_candles["high"].max() > bsl_price and current_close < bsl_price:
            sweep = {
                "detected": True,
                "type": "bearish",
                "level": bsl_price,
                "reason": "Balayage liquidite haussiere puis retour"
            }
            break
    
    # Sweep bullish (balayage en-dessous puis retour)
    for ssl_price in liquidity.get("sell_side_liquidity", []):
        if recent_candles["low"].min() < ssl_price and current_close > ssl_price:
            sweep = {
                "detected": True,
                "type": "bullish",
                "level": ssl_price,
                "reason": "Balayage liquidite baissiere puis retour"
            }
            break
    
    return sweep


def detect_premium_discount(df, lookback=50):
    """Zone Premium/Discount (Fibonacci simplifie)"""
    if len(df) < lookback:
        lookback = len(df)
    
    recent = df.tail(lookback)
    high = float(recent["high"].max())
    low = float(recent["low"].min())
    current = float(df["close"].iloc[-1])
    
    mid = (high + low) / 2
    
    zone = "equilibrium"
    if current > mid:
        percent = ((current - mid) / (high - mid)) * 100 if high != mid else 0
        if percent > 30:
            zone = "premium"
    else:
        percent = ((mid - current) / (mid - low)) * 100 if low != mid else 0
        if percent > 30:
            zone = "discount"
    
    return {
        "zone": zone,
        "range_high": round(high, 5),
        "range_low": round(low, 5),
        "range_mid": round(mid, 5),
        "current_price": round(current, 5)
    }


def detect_breaker_blocks(df, order_blocks):
    """Breaker Blocks - Order Blocks casses puis retestes"""
    breakers = {
        "bullish": [],
        "bearish": []
    }
    
    if len(df) < 10:
        return breakers
    
    current_price = float(df["close"].iloc[-1])
    
    # Breaker bullish
    for ob in order_blocks.get("bearish", []):
        after_break = df.iloc[ob["index"]+1:]
        if len(after_break) > 0 and after_break["high"].max() > ob["high"]:
            if current_price > ob["low"]:
                breakers["bullish"].append({
                    "type": "bullish_breaker",
                    "high": ob["high"],
                    "low": ob["low"],
                    "index": ob["index"]
                })
    
    # Breaker bearish
    for ob in order_blocks.get("bullish", []):
        after_break = df.iloc[ob["index"]+1:]
        if len(after_break) > 0 and after_break["low"].min() < ob["low"]:
            if current_price < ob["high"]:
                breakers["bearish"].append({
                    "type": "bearish_breaker",
                    "high": ob["high"],
                    "low": ob["low"],
                    "index": ob["index"]
                })
    
    breakers["bullish"] = breakers["bullish"][:3]
    breakers["bearish"] = breakers["bearish"][:3]
    
    return breakers


# ─── Analyse SMC complete v9.0 ───

def analyze_smc_v9(df):
    """
    Analyse SMC complete pour v9.0
    Retourne dict avec toutes les detections + score SMC (0-30)
    """
    if df is None or len(df) < 30:
        return None
    
    structure = analyze_market_structure(df)
    bos = detect_bos(df, structure)
    choch = detect_choch(df, structure)
    order_blocks = detect_order_blocks(df)
    breaker_blocks = detect_breaker_blocks(df, order_blocks)
    fvg = detect_fvg(df)
    liquidity = detect_liquidity_zones(df)
    sweep = detect_liquidity_sweep(df, liquidity)
    premium_discount = detect_premium_discount(df)
    
    # ─── Score SMC (0-30 pts) ───
    smc_score = 0  # score signe (-30 a +30)
    smc_signals = []
    signals_count = 0
    
    # 1. Market Structure (0-6 pts)
    if structure["trend"] == "bullish":
        pts = 6 if structure["strength"] >= 80 else 4
        smc_score += pts
        smc_signals.append(f"Structure haussiere (HH/HL) - force {structure['strength']}%")
        signals_count += 1
    elif structure["trend"] == "bearish":
        pts = 6 if structure["strength"] >= 80 else 4
        smc_score -= pts
        smc_signals.append(f"Structure baissiere (LH/LL) - force {structure['strength']}%")
        signals_count += 1
    
    # 2. BOS (0-6 pts)
    if bos["detected"]:
        pts = 6 if bos["strength"] >= 50 else 4
        if bos["type"] == "bullish":
            smc_score += pts
            smc_signals.append(f"BOS haussier a {bos['level']}")
            signals_count += 1
        else:
            smc_score -= pts
            smc_signals.append(f"BOS baissier a {bos['level']}")
            signals_count += 1
    
    # 3. CHOCH (0-8 pts) - Signal fort
    if choch["detected"]:
        if choch["type"] == "bullish":
            smc_score += 8
            smc_signals.append(f"CHOCH haussier a {choch['level']}")
            signals_count += 1
        else:
            smc_score -= 8
            smc_signals.append(f"CHOCH baissier a {choch['level']}")
            signals_count += 1
    
    # 4. Order Blocks (0-4 pts)
    if order_blocks["bullish"]:
        smc_score += 4
        smc_signals.append(f"{len(order_blocks['bullish'])} Order Block(s) haussier(s)")
        signals_count += 1
    if order_blocks["bearish"]:
        smc_score -= 4
        smc_signals.append(f"{len(order_blocks['bearish'])} Order Block(s) baissier(s)")
        signals_count += 1
    
    # 5. Breaker Blocks (0-2 pts)
    if breaker_blocks["bullish"]:
        smc_score += 2
        smc_signals.append("Breaker Block haussier")
    if breaker_blocks["bearish"]:
        smc_score -= 2
        smc_signals.append("Breaker Block baissier")
    
    # 6. FVG (0-2 pts)
    if fvg["bullish"]:
        smc_score += 2
        smc_signals.append(f"{len(fvg['bullish'])} FVG haussier(s)")
    if fvg["bearish"]:
        smc_score -= 2
        smc_signals.append(f"{len(fvg['bearish'])} FVG baissier(s)")
    
    # 7. Liquidity Sweep (0-5 pts) - Signal fort
    if sweep["detected"]:
        if sweep["type"] == "bullish":
            smc_score += 5
            smc_signals.append("Liquidity Sweep haussier")
            signals_count += 1
        else:
            smc_score -= 5
            smc_signals.append("Liquidity Sweep baissier")
            signals_count += 1
    
    # 8. Premium/Discount (0-3 pts)
    if premium_discount["zone"] == "discount":
        smc_score += 3
        smc_signals.append("Zone Discount (achat favorable)")
    elif premium_discount["zone"] == "premium":
        smc_score -= 3
        smc_signals.append("Zone Premium (vente favorable)")
    
    # Score absolu (0-30)
    smc_score_absolute = min(abs(smc_score), 30)
    
    # Direction
    if smc_score > 5:
        smc_direction = "bullish"
    elif smc_score < -5:
        smc_direction = "bearish"
    else:
        smc_direction = "neutral"
    
    return {
        "score": int(smc_score_absolute),
        "score_raw": int(smc_score),
        "direction": smc_direction,
        "signals": smc_signals,
        "signals_count": signals_count,
        "market_structure": structure,
        "bos": bos,
        "choch": choch,
        "order_blocks": order_blocks,
        "breaker_blocks": breaker_blocks,
        "fvg": fvg,
        "liquidity_zones": liquidity,
        "liquidity_sweep": sweep,
        "premium_discount": premium_discount
                   }

# ═══════════════════════════════════════════════
#     MULTI-TIMEFRAME 3 NIVEAUX (v9.0)
# ═══════════════════════════════════════════════

def analyze_mtf_3_levels(asset, main_tf="1h"):
    """
    Analyse Multi-Timeframe a 3 niveaux
    
    Niveau 1 : Entree (main_tf)
    Niveau 2 : Confirmation (MTF_3_LEVELS[main_tf]["confirmation"])
    Niveau 3 : Tendance generale (MTF_3_LEVELS[main_tf]["trend"])
    
    Retourne un dict avec score MTF (0-20) et alignement
    """
    symbol = ASSETS.get(asset)
    if not symbol:
        return None
    
    # Recuperer les 3 niveaux de timeframes
    levels = MTF_3_LEVELS.get(main_tf, {"entry": "1h", "confirmation": "4h", "trend": "1d"})
    
    entry_tf = levels["entry"]
    confirm_tf = levels["confirmation"]
    trend_tf = levels["trend"]
    
    # Analyser chaque niveau
    entry_tech = None
    confirm_tech = None
    trend_tech = None
    
    entry_smc = None
    confirm_smc = None
    trend_smc = None
    
    # Niveau 1 : Entree
    df_entry = get_candles_df(symbol, TIMEFRAMES.get(entry_tf, "1h"), limit=100)
    if df_entry is not None and len(df_entry) >= 30:
        entry_tech = analyze_technical_v9(df_entry)
        entry_smc = analyze_smc_v9(df_entry)
    
    # Niveau 2 : Confirmation (si different de l'entree)
    if confirm_tf != entry_tf:
        df_confirm = get_candles_df(symbol, TIMEFRAMES.get(confirm_tf, "4h"), limit=100)
        if df_confirm is not None and len(df_confirm) >= 30:
            confirm_tech = analyze_technical_v9(df_confirm)
            confirm_smc = analyze_smc_v9(df_confirm)
    else:
        confirm_tech = entry_tech
        confirm_smc = entry_smc
    
    # Niveau 3 : Tendance generale (si different)
    if trend_tf != confirm_tf and trend_tf != entry_tf:
        df_trend = get_candles_df(symbol, TIMEFRAMES.get(trend_tf, "1d"), limit=100)
        if df_trend is not None and len(df_trend) >= 30:
            trend_tech = analyze_technical_v9(df_trend)
            trend_smc = analyze_smc_v9(df_trend)
    elif trend_tf == confirm_tf:
        trend_tech = confirm_tech
        trend_smc = confirm_smc
    else:
        trend_tech = entry_tech
        trend_smc = entry_smc
    
    # Determiner les directions de chaque niveau
    entry_direction = "neutral"
    confirm_direction = "neutral"
    trend_direction = "neutral"
    
    if entry_tech:
        entry_direction = entry_tech.get("direction", "neutral")
    if confirm_tech:
        confirm_direction = confirm_tech.get("direction", "neutral")
    if trend_tech:
        trend_direction = trend_tech.get("direction", "neutral")
    
    # ─── Calculer score MTF (0-20 pts) ───
    mtf_score = 0
    mtf_signals = []
    
    # Direction combinee (technique + SMC pour chaque niveau)
    entry_combined = combine_directions(
        entry_tech.get("direction") if entry_tech else "neutral",
        entry_smc.get("direction") if entry_smc else "neutral"
    )
    
    confirm_combined = combine_directions(
        confirm_tech.get("direction") if confirm_tech else "neutral",
        confirm_smc.get("direction") if confirm_smc else "neutral"
    )
    
    trend_combined = combine_directions(
        trend_tech.get("direction") if trend_tech else "neutral",
        trend_smc.get("direction") if trend_smc else "neutral"
    )
    
    # 1. Alignement des 3 niveaux (0-10 pts)
    all_bullish = all(d == "bullish" for d in [entry_combined, confirm_combined, trend_combined])
    all_bearish = all(d == "bearish" for d in [entry_combined, confirm_combined, trend_combined])
    
    if all_bullish:
        mtf_score += 10
        mtf_signals.append("3 timeframes alignes HAUSSIER")
    elif all_bearish:
        mtf_score -= 10
        mtf_signals.append("3 timeframes alignes BAISSIER")
    else:
        # Alignement partiel
        bullish_count = sum(1 for d in [entry_combined, confirm_combined, trend_combined] if d == "bullish")
        bearish_count = sum(1 for d in [entry_combined, confirm_combined, trend_combined] if d == "bearish")
        
        if bullish_count >= 2:
            mtf_score += 5
            mtf_signals.append(f"{bullish_count}/3 timeframes haussiers")
        elif bearish_count >= 2:
            mtf_score -= 5
            mtf_signals.append(f"{bearish_count}/3 timeframes baissiers")
        else:
            mtf_signals.append("Timeframes contradictoires")
    
    # 2. Confirmation HTF (0-5 pts)
    if entry_combined == confirm_combined and entry_combined != "neutral":
        mtf_score += 5 if entry_combined == "bullish" else -5
        mtf_signals.append(f"Confirmation {confirm_tf} alignee")
    
    # 3. Tendance generale compatible (0-5 pts)
    if trend_combined == entry_combined and trend_combined != "neutral":
        mtf_score += 5 if trend_combined == "bullish" else -5
        mtf_signals.append(f"Tendance {trend_tf} compatible")
    elif trend_combined != "neutral" and trend_combined != entry_combined:
        mtf_signals.append(f"Tendance {trend_tf} contradictoire")
    
    # Score absolu (0-20)
    mtf_score_absolute = min(abs(mtf_score), 20)
    
    # Direction MTF
    if mtf_score > 3:
        mtf_direction = "bullish"
    elif mtf_score < -3:
        mtf_direction = "bearish"
    else:
        mtf_direction = "neutral"
    
    # Alignement flag
    aligned = all_bullish or all_bearish
    strongly_contradicted = (entry_combined == "bullish" and trend_combined == "bearish") or \
                           (entry_combined == "bearish" and trend_combined == "bullish")
    
    return {
        "score": int(mtf_score_absolute),
        "score_raw": int(mtf_score),
        "direction": mtf_direction,
        "aligned": aligned,
        "strongly_contradicted": strongly_contradicted,
        "signals": mtf_signals,
        "levels": {
            "entry": {
                "timeframe": entry_tf,
                "direction": entry_combined,
                "tech_direction": entry_direction,
                "smc_direction": entry_smc.get("direction") if entry_smc else "neutral"
            },
            "confirmation": {
                "timeframe": confirm_tf,
                "direction": confirm_combined,
                "tech_direction": confirm_direction,
                "smc_direction": confirm_smc.get("direction") if confirm_smc else "neutral"
            },
            "trend": {
                "timeframe": trend_tf,
                "direction": trend_combined,
                "tech_direction": trend_direction,
                "smc_direction": trend_smc.get("direction") if trend_smc else "neutral"
            }
        },
        "entry_tech": entry_tech,
        "entry_smc": entry_smc,
        "confirm_tech": confirm_tech,
        "confirm_smc": confirm_smc,
        "trend_tech": trend_tech,
        "trend_smc": trend_smc
    }


def combine_directions(tech_dir, smc_dir):
    """Combine direction technique + SMC en une direction unifiee"""
    if tech_dir == smc_dir:
        return tech_dir
    
    if tech_dir == "neutral":
        return smc_dir
    if smc_dir == "neutral":
        return tech_dir
    
    # Contradiction : technique et SMC ne sont pas d'accord
    return "neutral"


# ═══════════════════════════════════════════════
#     NEWS & CALENDAR ANALYSIS (v9.0)
# ═══════════════════════════════════════════════

def analyze_news_impact_v9(asset, news_list):
    """
    Analyse l'impact des news sur un actif
    Retourne un dict avec score news (0-10)
    """
    currencies = ASSET_CURRENCIES.get(asset, [])
    base, quote = ASSET_BASE_QUOTE.get(asset, (None, None))
    
    empty = {
        "score": 0,
        "direction": "neutral",
        "available": False,
        "count": 0,
        "bullish_count": 0,
        "bearish_count": 0,
        "high_impact_count": 0,
        "signals": []
    }
    
    if not currencies or not news_list:
        empty["available"] = len(news_list) == 0
        return empty
    
    empty["available"] = True
    
    relevant = []
    for n in news_list:
        news_curr = n.get("currencies", [])
        for c in currencies:
            if c in news_curr:
                relevant.append(n)
                break
    
    if not relevant:
        return empty
    
    base_score = 0
    quote_score = 0
    high_impact = 0
    bullish = 0
    bearish = 0
    signals = []
    
    for news in relevant:
        sent = news.get("sentiment", "neutral")
        imp = news.get("impact", "LOW")
        news_curr = news.get("currencies", [])
        
        weight = 1
        if imp == "HIGH":
            weight = 3
        elif imp == "MEDIUM":
            weight = 2
        
        if imp == "HIGH":
            high_impact += 1
        
        for c in news_curr:
            if c == base:
                if sent == "bullish":
                    base_score += weight
                    bullish += 1
                elif sent == "bearish":
                    base_score -= weight
                    bearish += 1
            elif c == quote:
                if sent == "bullish":
                    quote_score += weight
                    bullish += 1
                elif sent == "bearish":
                    quote_score -= weight
                    bearish += 1
    
    net = base_score - quote_score
    
    # Score news (0-10 pts)
    news_score = 0
    if abs(net) >= 6:
        news_score = 10 if net > 0 else -10
    elif abs(net) >= 3:
        news_score = 7 if net > 0 else -7
    elif abs(net) >= 1:
        news_score = 4 if net > 0 else -4
    
    if net > 0:
        direction = "bullish"
        signals.append(f"News favorables ({bullish} bull vs {bearish} bear)")
    elif net < 0:
        direction = "bearish"
        signals.append(f"News defavorables ({bullish} bull vs {bearish} bear)")
    else:
        direction = "neutral"
        signals.append("News equilibrees")
    
    if high_impact > 0:
        signals.append(f"{high_impact} news a fort impact")
    
    return {
        "score": abs(news_score),
        "score_raw": news_score,
        "direction": direction,
        "available": True,
        "count": len(relevant),
        "bullish_count": bullish,
        "bearish_count": bearish,
        "high_impact_count": high_impact,
        "signals": signals
    }


def analyze_calendar_impact_v9(asset, upcoming_events):
    """
    Analyse l'impact du calendrier economique
    Retourne un dict avec score calendrier (0-5)
    et niveau de risque
    """
    currencies = ASSET_CURRENCIES.get(asset, [])
    
    result = {
        "score": 5,  # Par defaut : pas de risque = score max
        "risk_level": "NORMAL",
        "available": True,
        "total_events": 0,
        "imminent_high_impact": 0,
        "upcoming_high_impact": 0,
        "warnings": [],
        "next_events": [],
        "signals": []
    }
    
    if not upcoming_events:
        result["signals"].append("Aucun evenement imminent")
        return result
    
    relevant = [e for e in upcoming_events if e.get("currency") in currencies]
    result["total_events"] = len(relevant)
    
    # Classer les evenements
    imminent = []  # < 2h
    upcoming_h = []  # 2-12h
    
    for e in relevant:
        hours = e.get("hours_until", 999)
        imp = e.get("impact", "").upper()
        is_high = "HIGH" in imp or "ELEV" in imp
        is_medium = "MEDIUM" in imp or "MOYEN" in imp
        
        if hours <= 2:
            if is_high:
                imminent.append(e)
            elif is_medium:
                upcoming_h.append(e)
        elif 2 < hours <= 12 and is_high:
            upcoming_h.append(e)
    
    result["imminent_high_impact"] = len(imminent)
    result["upcoming_high_impact"] = len(upcoming_h)
    result["next_events"] = relevant[:3]
    
    # ─── Score calendrier (0-5 pts) ───
    # Plus le risque est faible, plus le score est eleve
    
    if imminent:
        result["score"] = 0
        result["risk_level"] = "BLOCKED"
        result["warnings"].append(f"⚠️ {len(imminent)} evenement(s) HIGH dans les 2h")
        result["signals"].append(f"ATTENTION: {len(imminent)} evenement(s) imminent(s)")
    elif upcoming_h:
        result["score"] = 2
        result["risk_level"] = "HIGH_RISK"
        result["warnings"].append(f"Evenement(s) HIGH dans les 12h")
        result["signals"].append(f"Attention: evenements importants a venir")
    elif len(relevant) > 0:
        result["score"] = 3
        result["risk_level"] = "CAUTION"
        result["signals"].append(f"{len(relevant)} evenements prevus")
    else:
        result["score"] = 5
        result["risk_level"] = "NORMAL"
        result["signals"].append("Aucun risque calendrier")
    
    return result


# ═══════════════════════════════════════════════
#     IA ANALYSIS (v9.0 - OPTIONNEL)
# ═══════════════════════════════════════════════

def get_ai_analysis_v9(asset, tech_data, smc_data, mtf_data, news_data, calendar_data):
    """
    Analyse IA optionnelle
    Si IA indisponible, le signal continue de fonctionner
    """
    default = {
        "available": False,
        "summary": "IA non disponible",
        "sentiment": "neutral",
        "confidence_adjustment": 0,
        "key_risks": [],
        "recommendation": "",
        "invalidation_scenario": "",
        "model_used": "none"
    }
    
    if not OPENROUTER_API_KEY:
        return default
    
    # Cache basique
    ts_bucket = int(datetime.utcnow().timestamp() // AI_CACHE_DURATION)
    cache_key = f"{asset}_{tech_data.get('direction') if tech_data else 'N'}_{ts_bucket}"
    
    if cache_key in AI_CACHE:
        return AI_CACHE[cache_key]
    
    display_name = ASSETS.get(asset, asset)
    
    smc_dir = smc_data.get("direction", "N/A") if smc_data else "N/A"
    smc_scr = smc_data.get("score", 0) if smc_data else 0
    mtf_dir = mtf_data.get("direction", "N/A") if mtf_data else "N/A"
    mtf_aligned = mtf_data.get("aligned", False) if mtf_data else False
    
    prompt = "Tu es analyste Forex. Reponds UNIQUEMENT en JSON valide, rien d'autre.\n\n"
    prompt += f"Actif: {display_name}\n"
    prompt += f"Technique: {tech_data.get('direction', 'N/A')} (score {tech_data.get('score', 0)}/25)\n" if tech_data else ""
    prompt += f"SMC: {smc_dir} (score {smc_scr}/30)\n"
    prompt += f"MTF: {mtf_dir} (aligne: {mtf_aligned})\n"
    prompt += f"News: {news_data.get('direction', 'N/A')}\n" if news_data else ""
    prompt += f"Calendrier: {calendar_data.get('risk_level', 'N/A')}\n" if calendar_data else ""
    prompt += "\nReponds SEULEMENT ce JSON:\n"
    prompt += '{"summary":"analyse 2 phrases","sentiment":"bullish ou bearish ou neutral","confidence_adjustment":0,"key_risks":["r1","r2"],"recommendation":"reco","invalidation_scenario":"invalidation"}'
    
    response_text = call_openrouter(prompt)
    
    if not response_text:
        return default
    
    try:
        text = response_text.strip()
        text = re.sub(r'```json\s*', '', text)
        text = re.sub(r'```\s*', '', text)
        text = text.strip()
        
        start = text.find('{')
        end = text.rfind('}')
        
        if start == -1 or end == -1:
            return default
        
        text = text[start:end+1]
        text = re.sub(r'[\x00-\x1f\x7f]', ' ', text)
        text = re.sub(r',(\s*[}\]])', r'\1', text)
        
        analysis = json.loads(text)
        result = {
            "available": True,
            "summary": analysis.get("summary", ""),
            "sentiment": analysis.get("sentiment", "neutral"),
            "confidence_adjustment": int(analysis.get("confidence_adjustment", 0)),
            "key_risks": analysis.get("key_risks", []),
            "recommendation": analysis.get("recommendation", ""),
            "invalidation_scenario": analysis.get("invalidation_scenario", ""),
            "model_used": ACTIVE_MODEL or "unknown"
        }
        AI_CACHE[cache_key] = result
        return result
    except Exception as e:
        return default

# ═══════════════════════════════════════════════
#     SCORING ENGINE v9.0 (DÉTERMINISTE)
# ═══════════════════════════════════════════════

def calculate_momentum_score(tech_data):
    """
    Score Momentum (0-5 pts)
    Basé sur RSI, MACD histogram, Stochastic
    """
    if not tech_data:
        return 0, []
    
    score = 0
    signals = []
    indicators = tech_data.get("indicators", {})
    
    rsi_val = indicators.get("rsi", 50)
    macd_hist = indicators.get("macd_hist", 0)
    stoch_k = indicators.get("stoch_k", 50)
    momentum_pct = indicators.get("momentum_pct", 0)
    
    # RSI momentum
    if 50 < rsi_val < 70:
        score += 1
        signals.append("RSI momentum haussier")
    elif 30 < rsi_val < 50:
        score -= 1
        signals.append("RSI momentum baissier")
    
    # MACD histogram croissant
    if macd_hist > 0:
        score += 1
        signals.append("MACD histogram positif")
    elif macd_hist < 0:
        score -= 1
        signals.append("MACD histogram negatif")
    
    # Momentum prix
    if momentum_pct > 0.1:
        score += 1
        signals.append("Momentum prix positif")
    elif momentum_pct < -0.1:
        score -= 1
        signals.append("Momentum prix negatif")
    
    # Stochastic
    if 20 < stoch_k < 80:
        if stoch_k > 50:
            score += 1
        else:
            score -= 1
    
    return min(abs(score), 5), signals


def calculate_context_score(tech_data, calendar_data, news_data):
    """
    Score Contexte de marché (0-5 pts)
    Basé sur regime, session, volatilité
    """
    score = 0
    signals = []
    
    if not tech_data:
        return 0, []
    
    # Regime de marché
    regime = tech_data.get("market_regime", "UNKNOWN")
    
    if regime in ["TREND", "TREND_HIGH_VOL"]:
        score += 2
        signals.append(f"Regime de marche favorable ({regime})")
    elif regime == "RANGE":
        score += 1
        signals.append("Regime de range (prudence)")
    elif regime == "HIGH_VOL":
        score -= 1
        signals.append("Haute volatilite (risque eleve)")
    elif regime == "LOW_VOL":
        score += 1
        signals.append("Faible volatilite (stable)")
    
    # Session de trading
    session = tech_data.get("trading_session", "UNKNOWN")
    
    if session in ["LONDON", "LONDON_NY_OVERLAP"]:
        score += 2
        signals.append(f"Session active ({session})")
    elif session in ["NEW_YORK", "ASIA"]:
        score += 1
        signals.append(f"Session {session}")
    else:
        signals.append(f"Session calme ({session})")
    
    # Calendrier OK ?
    if calendar_data and calendar_data.get("risk_level") == "NORMAL":
        score += 1
        signals.append("Aucun risque calendrier")
    
    return min(abs(score), 5), signals


def calculate_final_score_v9(tech_score, smc_score, mtf_score, news_score, calendar_score, momentum_score, context_score):
    """
    Calcule le score FINAL deterministe (0-100)
    
    Repartition :
    SMC              : 30 pts max
    Technique        : 25 pts max
    Multi-Timeframe  : 20 pts max
    News             : 10 pts max
    Calendrier       :  5 pts max
    Momentum         :  5 pts max
    Contexte         :  5 pts max
    ─────────────────────────────
    TOTAL            : 100 pts max
    """
    
    # Les scores sont deja calcules entre 0 et leur max
    final = (
        min(smc_score, 30) +      # SMC : 30 pts max
        min(tech_score, 25) +     # Technique : 25 pts max
        min(mtf_score, 20) +      # MTF : 20 pts max
        min(news_score, 10) +     # News : 10 pts max
        min(calendar_score, 5) +  # Calendrier : 5 pts max
        min(momentum_score, 5) +  # Momentum : 5 pts max
        min(context_score, 5)     # Contexte : 5 pts max
    )
    
    # Clamper entre 0 et 100
    final = max(0, min(100, final))
    
    return int(final)


# ═══════════════════════════════════════════════
#     RISK MANAGEMENT v9.0
# ═══════════════════════════════════════════════

def calculate_sl_tp_v9(direction, current_price, atr_value, supports, resistances):
    """
    Calcule SL/TP intelligents bases sur :
    - ATR (volatilite)
    - Supports/Resistances
    - Direction du signal
    
    Retourne : entry, sl, tp1, tp2, tp3, risk_reward
    """
    if not direction or direction == "neutral":
        return None, None, None, None, None, None
    
    entry = current_price
    
    if direction == "bullish":
        # Stop Loss basé sur ATR
        sl_atr = entry - (atr_value * 1.5)
        
        # Verifier si un support est proche (meilleur SL)
        sl_structure = None
        for sup in sorted(supports, reverse=True):
            if sup < entry:
                sl_structure = sup - (atr_value * 0.2)  # Petit buffer sous le support
                break
        
        # Prendre le SL le plus proche (le moins risque)
        if sl_structure and sl_structure > sl_atr:
            sl = sl_structure
        else:
            sl = sl_atr
        
        # Take Profits basés sur ATR
        tp1 = entry + (atr_value * 2)
        tp2 = entry + (atr_value * 3)
        tp3 = entry + (atr_value * 4)
        
        # Verifier si une resistance est proche de TP1
        for res in sorted(resistances):
            if res > entry and res < tp1:
                tp1 = res - (atr_value * 0.1)
                break
        
    elif direction == "bearish":
        # Stop Loss basé sur ATR
        sl_atr = entry + (atr_value * 1.5)
        
        # Verifier si une resistance est proche (meilleur SL)
        sl_structure = None
        for res in sorted(resistances):
            if res > entry:
                sl_structure = res + (atr_value * 0.2)
                break
        
        if sl_structure and sl_structure < sl_atr:
            sl = sl_structure
        else:
            sl = sl_atr
        
        tp1 = entry - (atr_value * 2)
        tp2 = entry - (atr_value * 3)
        tp3 = entry - (atr_value * 4)
        
        for sup in sorted(supports, reverse=True):
            if sup < entry and sup > tp1:
                tp1 = sup + (atr_value * 0.1)
                break
    else:
        return None, None, None, None, None, None
    
    # Calculer Risk/Reward
    risk = abs(entry - sl)
    reward = abs(tp1 - entry)
    rr = round(reward / risk, 2) if risk > 0 else 0
    
    return (
        round(entry, 5),
        round(sl, 5),
        round(tp1, 5),
        round(tp2, 5),
        round(tp3, 5),
        rr
    )


def validate_risk_reward(rr, min_rr=1.5):
    """
    Valide le Risk/Reward
    
    Retourne :
    - True si RR acceptable
    - False si trop faible
    """
    if rr is None or rr <= 0:
        return False, "R/R non calculable"
    
    if rr < 1.0:
        return False, f"R/R trop faible ({rr}:1) - Minimum 1.0"
    
    if rr < min_rr:
        return False, f"R/R sous le seuil ({rr}:1 < {min_rr}:1)"
    
    return True, f"R/R acceptable ({rr}:1)"


def validate_signal_conditions(score, direction, tech_data, smc_data, mtf_data, calendar_data, rr, min_score=70, min_rr=1.5):
    """
    Validation finale du signal
    Verifie TOUTES les conditions avant d'emettre BUY/SELL
    
    Retourne : (signal_ok, final_signal, reasons)
    """
    reasons_ok = []
    reasons_ko = []
    
    # 1. Score suffisant ?
    if score >= min_score:
        reasons_ok.append(f"Score {score}/100 >= {min_score}")
    else:
        reasons_ko.append(f"Score insuffisant ({score}/100 < {min_score})")
    
    # 2. Direction claire ?
    if direction in ["bullish", "bearish"]:
        reasons_ok.append(f"Direction claire : {direction}")
    else:
        reasons_ko.append("Direction neutre ou incertaine")
    
    # 3. Calendrier non bloquant ?
    if calendar_data:
        if calendar_data.get("risk_level") == "BLOCKED":
            reasons_ko.append("Evenement HIGH imminent - signal bloque")
        elif calendar_data.get("risk_level") == "HIGH_RISK":
            reasons_ko.append("Evenement important a venir - prudence")
        else:
            reasons_ok.append("Calendrier OK")
    
    # 4. MTF pas fortement contradictoire ?
    if mtf_data:
        if mtf_data.get("strongly_contradicted"):
            reasons_ko.append("Timeframes fortement contradictoires")
        elif mtf_data.get("aligned"):
            reasons_ok.append("Timeframes alignes")
    
    # 5. Risk/Reward valide ?
    rr_ok, rr_msg = validate_risk_reward(rr, min_rr)
    if rr_ok:
        reasons_ok.append(rr_msg)
    else:
        reasons_ko.append(rr_msg)
    
    # 6. Data quality ?
    # (verifie par la fonction appelante)
    
    # ─── Decision finale ───
    # Le signal est BLOQUE si :
    # - Score insuffisant
    # - Direction neutre
    # - Calendrier BLOCKED
    # - Timeframes fortement contradictoires
    
    critical_ko = any(
        "bloque" in r.lower() or
        "insuffisant" in r.lower() or
        "neutre" in r.lower() or
        "fortement contradictoires" in r.lower()
        for r in reasons_ko
    )
    
    if critical_ko or len(reasons_ko) >= 3:
        final_signal = "WAIT"
        signal_ok = False
    else:
        final_signal = "BUY" if direction == "bullish" else "SELL"
        signal_ok = True
    
    return signal_ok, final_signal, reasons_ok, reasons_ko


def calculate_signal_expiration(main_tf):
    """Calcule l'expiration du signal selon le timeframe"""
    expiration_hours = {
        "15m": 2,
        "30m": 4,
        "1h": 8,
        "2h": 16,
        "4h": 24,
        "1d": 72
    }
    
    hours = expiration_hours.get(main_tf, 8)
    return datetime.utcnow() + timedelta(hours=hours)

# ═══════════════════════════════════════════════
#     SIGNAL GENERATOR v9.0 (CŒUR DU SYSTÈME)
# ═══════════════════════════════════════════════

def generate_signal_v9(asset, main_tf="1h", min_score=70, min_rr=1.5):
    """
    Generateur de signal v9.0
    
    Architecture :
    1. Data Quality Check
    2. Technical Analysis
    3. SMC Analysis
    4. Multi-Timeframe 3 niveaux
    5. News Analysis
    6. Calendar Analysis
    7. Momentum
    8. Context
    9. Scoring (0-100)
    10. Risk Management (SL/TP/RR)
    11. Validation finale
    12. IA (optionnel)
    13. Signal Journal (DB)
    
    IMPORTANT : Score = qualite du setup, PAS probabilite de gain
    """
    
    symbol = ASSETS.get(asset)
    if not symbol:
        return {"error": "Actif inconnu", "signal": "WAIT", "score": 0}
    
    signal_id = f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{asset}"
    
    # ═══ ÉTAPE 1 : Data Quality Check ═══
    df_main = get_candles_df(symbol, TIMEFRAMES.get(main_tf, "1h"), limit=100)
    data_quality = check_data_quality(df_main)
    
    if not data_quality["usable"]:
        return {
            "signal_id": signal_id,
            "strategy_version": STRATEGY_VERSION,
            "asset": asset,
            "symbol": symbol,
            "timestamp": datetime.utcnow().isoformat(),
            "signal": "WAIT",
            "score": 0,
            "classification": "WAIT",
            "reason": "Donnees insuffisantes ou invalides",
            "data_quality": data_quality,
            "warnings": data_quality["warnings"]
        }
    
    # ═══ ÉTAPE 2 : Technical Analysis ═══
    tech_data = analyze_technical_v9(df_main)
    
    if not tech_data:
        return {
            "signal_id": signal_id,
            "strategy_version": STRATEGY_VERSION,
            "asset": asset,
            "symbol": symbol,
            "timestamp": datetime.utcnow().isoformat(),
            "signal": "WAIT",
            "score": 0,
            "classification": "WAIT",
            "reason": "Analyse technique impossible",
            "data_quality": data_quality,
            "warnings": ["Analyse technique echouee"]
        }
    
    current_price = tech_data["current_price"]
    atr_value = tech_data["indicators"].get("atr", current_price * 0.005)
    
    # ═══ ÉTAPE 3 : SMC Analysis ═══
    smc_data = analyze_smc_v9(df_main)
    
    # ═══ ÉTAPE 4 : Multi-Timeframe 3 niveaux ═══
    mtf_data = analyze_mtf_3_levels(asset, main_tf)
    
    # ═══ ÉTAPE 5 : News Analysis ═══
    all_news = get_cached_news()
    news_data = analyze_news_impact_v9(asset, all_news)
    
    # ═══ ÉTAPE 6 : Calendar Analysis ═══
    currencies = ASSET_CURRENCIES.get(asset, [])
    upcoming = get_upcoming_events(24, currencies)
    calendar_data = analyze_calendar_impact_v9(asset, upcoming)
    
    # ═══ ÉTAPE 7 : Momentum ═══
    momentum_score, momentum_signals = calculate_momentum_score(tech_data)
    
    # ═══ ÉTAPE 8 : Context ═══
    context_score, context_signals = calculate_context_score(tech_data, calendar_data, news_data)
    
    # ═══ ÉTAPE 9 : Scoring Final (0-100) ═══
    tech_score = tech_data.get("score", 0) if tech_data else 0
    smc_score = smc_data.get("score", 0) if smc_data else 0
    mtf_score = mtf_data.get("score", 0) if mtf_data else 0
    news_score = news_data.get("score", 0) if news_data else 0
    calendar_score_val = calendar_data.get("score", 5) if calendar_data else 5
    
    final_score = calculate_final_score_v9(
        tech_score, smc_score, mtf_score,
        news_score, calendar_score_val,
        momentum_score, context_score
    )
    
    classification = classify_score(final_score)
    
    # ═══ ÉTAPE 10 : Determiner la direction ═══
    # La direction est basee sur la confluence de toutes les sources
    tech_dir = tech_data.get("direction", "neutral") if tech_data else "neutral"
    smc_dir = smc_data.get("direction", "neutral") if smc_data else "neutral"
    mtf_dir = mtf_data.get("direction", "neutral") if mtf_data else "neutral"
    
    # Compter les votes
    bullish_votes = sum(1 for d in [tech_dir, smc_dir, mtf_dir] if d == "bullish")
    bearish_votes = sum(1 for d in [tech_dir, smc_dir, mtf_dir] if d == "bearish")
    
    if bullish_votes >= 2:
        primary_direction = "bullish"
    elif bearish_votes >= 2:
        primary_direction = "bearish"
    elif tech_dir != "neutral":
        primary_direction = tech_dir
    elif smc_dir != "neutral":
        primary_direction = smc_dir
    else:
        primary_direction = "neutral"
    
    # ═══ ÉTAPE 11 : Risk Management (SL/TP/RR) ═══
    supports = tech_data.get("support_resistance", {}).get("supports", [])
    resistances = tech_data.get("support_resistance", {}).get("resistances", [])
    
    entry, sl, tp1, tp2, tp3, rr = calculate_sl_tp_v9(
        primary_direction, current_price, atr_value, supports, resistances
    )
    
    # ═══ ÉTAPE 12 : Validation finale ═══
    signal_ok, final_signal, reasons_ok, reasons_ko = validate_signal_conditions(
        score=final_score,
        direction=primary_direction,
        tech_data=tech_data,
        smc_data=smc_data,
        mtf_data=mtf_data,
        calendar_data=calendar_data,
        rr=rr,
        min_score=min_score,
        min_rr=min_rr
    )
    
    # Si signal WAIT, pas de SL/TP
    if final_signal == "WAIT":
        entry = None
        sl = None
        tp1 = None
        tp2 = None
        tp3 = None
        rr = None
    
    # ═══ ÉTAPE 13 : IA Analysis (optionnel) ═══
    ai_data = get_ai_analysis_v9(asset, tech_data, smc_data, mtf_data, news_data, calendar_data)
    
    # ═══ Collecter les top titres news ═══
    news_titles = []
    for n in all_news:
        news_curr = n.get("currencies", [])
        for c in currencies:
            if c in news_curr:
                news_titles.append(n["title"])
                break
        if len(news_titles) >= 5:
            break
    
    # ═══ Collecter toutes les raisons ═══
    all_reasons = []
    if tech_data and tech_data.get("reasons"):
        all_reasons.extend(tech_data["reasons"])
    if smc_data and smc_data.get("signals"):
        all_reasons.extend(smc_data["signals"][:3])
    if mtf_data and mtf_data.get("signals"):
        all_reasons.extend(mtf_data["signals"])
    if news_data and news_data.get("signals"):
        all_reasons.extend(news_data["signals"])
    if calendar_data and calendar_data.get("signals"):
        all_reasons.extend(calendar_data["signals"])
    if momentum_signals:
        all_reasons.extend(momentum_signals[:2])
    if context_signals:
        all_reasons.extend(context_signals[:2])
    
    # Warnings
    all_warnings = []
    if reasons_ko:
        all_warnings.extend(reasons_ko)
    if calendar_data and calendar_data.get("warnings"):
        all_warnings.extend(calendar_data["warnings"])
    if data_quality.get("warnings"):
        all_warnings.extend(data_quality["warnings"])
    
    # MTF levels info
    levels_config = MTF_3_LEVELS.get(main_tf, {"entry": main_tf, "confirmation": "4h", "trend": "1d"})
    
    # Expiration
    expiration = calculate_signal_expiration(main_tf)
    
    # ═══ Construction du resultat ═══
    result = {
        "signal_id": signal_id,
        "strategy_version": STRATEGY_VERSION,
        "timestamp": datetime.utcnow().isoformat(),
        
        "asset": asset,
        "symbol": symbol,
        "main_timeframe": main_tf,
        "confirmation_timeframe": levels_config["confirmation"],
        "higher_timeframe": levels_config["trend"],
        
        "signal": final_signal,
        "score": final_score,
        "classification": classification,
        
        "scores_breakdown": {
            "smc": smc_score,
            "smc_max": 30,
            "technical": tech_score,
            "technical_max": 25,
            "mtf": mtf_score,
            "mtf_max": 20,
            "news": news_score,
            "news_max": 10,
            "calendar": calendar_score_val,
            "calendar_max": 5,
            "momentum": momentum_score,
            "momentum_max": 5,
            "context": context_score,
            "context_max": 5,
            "total": final_score,
            "total_max": 100
        },
        
        "current_price": current_price,
        "entry": entry,
        "stop_loss": sl,
        "take_profit_1": tp1,
        "take_profit_2": tp2,
        "take_profit_3": tp3,
        "risk_reward": rr,
        
        "direction": primary_direction,
        "direction_votes": {
            "technical": tech_dir,
            "smc": smc_dir,
            "mtf": mtf_dir,
            "bullish_votes": bullish_votes,
            "bearish_votes": bearish_votes
        },
        
        "market_context": {
            "regime": tech_data.get("market_regime", "UNKNOWN"),
            "session": tech_data.get("trading_session", "UNKNOWN"),
            "volatility": tech_data["indicators"].get("atr_pct", 0),
            "trend": tech_data.get("trend", "neutral"),
            "trend_strength": tech_data.get("trend_strength", 0)
        },
        
        "data_quality": data_quality,
        
        "mtf_alignment": {
            "aligned": mtf_data.get("aligned", False) if mtf_data else False,
            "contradicted": mtf_data.get("strongly_contradicted", False) if mtf_data else False,
            "levels": mtf_data.get("levels", {}) if mtf_data else {}
        },
        
        "smc_details": {
            "direction": smc_dir,
            "score": smc_score,
            "signals": smc_data.get("signals", []) if smc_data else [],
            "market_structure": smc_data.get("market_structure") if smc_data else None,
            "bos": smc_data.get("bos") if smc_data else None,
            "choch": smc_data.get("choch") if smc_data else None,
            "order_blocks": smc_data.get("order_blocks") if smc_data else None,
            "fvg": smc_data.get("fvg") if smc_data else None,
            "liquidity_sweep": smc_data.get("liquidity_sweep") if smc_data else None,
            "premium_discount": smc_data.get("premium_discount") if smc_data else None
        },
        
        "technical_details": {
            "direction": tech_dir,
            "score": tech_score,
            "indicators": tech_data.get("indicators", {}) if tech_data else {},
            "support_resistance": tech_data.get("support_resistance", {}) if tech_data else {},
            "reasons": tech_data.get("reasons", []) if tech_data else []
        },
        
        "news_analysis": {
            "direction": news_data.get("direction", "neutral") if news_data else "neutral",
            "score": news_score,
            "available": news_data.get("available", False) if news_data else False,
            "count": news_data.get("count", 0) if news_data else 0,
            "high_impact_count": news_data.get("high_impact_count", 0) if news_data else 0,
            "top_titles": news_titles
        },
        
        "calendar_analysis": {
            "risk_level": calendar_data.get("risk_level", "NORMAL") if calendar_data else "NORMAL",
            "score": calendar_score_val,
            "imminent_high_impact": calendar_data.get("imminent_high_impact", 0) if calendar_data else 0,
            "next_events": calendar_data.get("next_events", []) if calendar_data else []
        },
        
        "ai_analysis": ai_data,
        
        "reasons": all_reasons,
        "reasons_ok": reasons_ok,
        "reasons_ko": reasons_ko,
        "warnings": all_warnings,
        
        "expiration": expiration.isoformat(),
        "status": "ACTIVE" if final_signal != "WAIT" else "WAIT",
        
        "disclaimer": "Score = qualite du setup. NE constitue PAS une probabilite de gain."
    }
    
    return result


# ═══════════════════════════════════════════════
#     SIGNAL JOURNAL (Enregistrement DB)
# ═══════════════════════════════════════════════

def save_signal_to_db(signal_data):
    """Enregistre un signal dans la base de donnees"""
    if signal_data.get("signal") == "WAIT":
        return  # On n'enregistre pas les WAIT
    
    db = SessionLocal()
    try:
        signal_record = SignalV9(
            signal_id=signal_data.get("signal_id", str(uuid.uuid4())),
            strategy_version=signal_data.get("strategy_version", STRATEGY_VERSION),
            timestamp=datetime.utcnow(),
            
            asset=signal_data.get("asset"),
            symbol=signal_data.get("symbol"),
            main_timeframe=signal_data.get("main_timeframe"),
            confirmation_timeframe=signal_data.get("confirmation_timeframe"),
            higher_timeframe=signal_data.get("higher_timeframe"),
            
            signal=signal_data.get("signal"),
            score=signal_data.get("score", 0),
            classification=signal_data.get("classification"),
            
            scores_breakdown=json.dumps(signal_data.get("scores_breakdown", {})),
            
            entry=signal_data.get("entry"),
            stop_loss=signal_data.get("stop_loss"),
            take_profit_1=signal_data.get("take_profit_1"),
            take_profit_2=signal_data.get("take_profit_2"),
            take_profit_3=signal_data.get("take_profit_3"),
            risk_reward=signal_data.get("risk_reward"),
            
            market_regime=signal_data.get("market_context", {}).get("regime"),
            volatility=str(signal_data.get("market_context", {}).get("volatility", "")),
            
            data_quality_status=signal_data.get("data_quality", {}).get("status"),
            data_quality_details=json.dumps(signal_data.get("data_quality", {})),
            
            analysis_details=json.dumps({
                "smc": signal_data.get("smc_details", {}),
                "technical": signal_data.get("technical_details", {}),
                "mtf": signal_data.get("mtf_alignment", {}),
                "direction_votes": signal_data.get("direction_votes", {})
            }),
            
            reasons=json.dumps(signal_data.get("reasons", [])),
            warnings=json.dumps(signal_data.get("warnings", [])),
            
            ai_available=signal_data.get("ai_analysis", {}).get("available", False),
            ai_summary=signal_data.get("ai_analysis", {}).get("summary", ""),
            ai_model=signal_data.get("ai_analysis", {}).get("model_used", ""),
            
            current_price=signal_data.get("current_price"),
            expiration=datetime.fromisoformat(signal_data["expiration"]) if signal_data.get("expiration") else None,
            status="ACTIVE"
        )
        
        db.add(signal_record)
        db.commit()
        print(f"Signal enregistre: {signal_data.get('signal_id')} - {signal_data.get('asset')} {signal_data.get('signal')}")
        
    except Exception as e:
        print(f"Erreur enregistrement signal: {e}")
        db.rollback()
    finally:
        db.close()


def check_and_update_signal_results():
    """
    Verifie les signaux actifs et met a jour les resultats
    Appele periodiquement par le scheduler
    """
    db = SessionLocal()
    try:
        # Recuperer les signaux actifs non expires
        active_signals = db.query(SignalV9).filter(
            SignalV9.status == "ACTIVE",
            SignalV9.signal.in_(["BUY", "SELL"])
        ).all()
        
        for sig in active_signals:
            # Verifier si expire
            if sig.expiration and datetime.utcnow() > sig.expiration:
                sig.status = "EXPIRED"
                
                # Creer le resultat
                result = SignalResultV9(
                    signal_id=sig.signal_id,
                    result="EXPIRED",
                    checked_at=datetime.utcnow()
                )
                db.add(result)
                continue
            
            # Verifier le prix actuel
            try:
                price_data = td_request("price", {"symbol": sig.symbol})
                if not price_data or "price" not in price_data:
                    continue
                
                current = float(price_data["price"])
                
                # Verifier TP/SL
                tp1_hit = False
                tp2_hit = False
                tp3_hit = False
                sl_hit = False
                
                if sig.signal == "BUY":
                    if sig.take_profit_1 and current >= sig.take_profit_1:
                        tp1_hit = True
                    if sig.take_profit_2 and current >= sig.take_profit_2:
                        tp2_hit = True
                    if sig.take_profit_3 and current >= sig.take_profit_3:
                        tp3_hit = True
                    if sig.stop_loss and current <= sig.stop_loss:
                        sl_hit = True
                elif sig.signal == "SELL":
                    if sig.take_profit_1 and current <= sig.take_profit_1:
                        tp1_hit = True
                    if sig.take_profit_2 and current <= sig.take_profit_2:
                        tp2_hit = True
                    if sig.take_profit_3 and current <= sig.take_profit_3:
                        tp3_hit = True
                    if sig.stop_loss and current >= sig.stop_loss:
                        sl_hit = True
                
                # Si TP1 ou SL touche, fermer le signal
                if tp1_hit or sl_hit:
                    result_type = "WIN" if tp1_hit else "LOSS"
                    sig.status = "CLOSED"
                    
                    # PnL en R
                    risk = abs(sig.entry - sig.stop_loss) if sig.entry and sig.stop_loss else 1
                    pnl = abs(current - sig.entry) if sig.entry else 0
                    pnl_r = round(pnl / risk, 2) if risk > 0 else 0
                    if sl_hit:
                        pnl_r = -1.0
                    
                    # Chercher si resultat existe deja
                    existing_result = db.query(SignalResultV9).filter(
                        SignalResultV9.signal_id == sig.signal_id
                    ).first()
                    
                    if not existing_result:
                        result = SignalResultV9(
                            signal_id=sig.signal_id,
                            result=result_type,
                            tp1_hit=tp1_hit,
                            tp2_hit=tp2_hit,
                            tp3_hit=tp3_hit,
                            sl_hit=sl_hit,
                            tp1_hit_at=datetime.utcnow() if tp1_hit else None,
                            sl_hit_at=datetime.utcnow() if sl_hit else None,
                            final_price=current,
                            final_pnl_r=pnl_r,
                            checked_at=datetime.utcnow()
                        )
                        db.add(result)
                    
                    print(f"Signal {sig.signal_id}: {result_type} ({pnl_r}R)")
                
            except Exception as e:
                print(f"Erreur check signal {sig.signal_id}: {e}")
        
        db.commit()
        
    except Exception as e:
        print(f"Erreur check_and_update_signal_results: {e}")
        db.rollback()
    finally:
        db.close()

# ═══════════════════════════════════════════════
#     SCHEDULER v9.0 (NOTIFICATIONS)
# ═══════════════════════════════════════════════

def send_signal_notification_v9(user, asset, signal_data, db):
    """Envoie une notification pour un signal v9.0"""
    try:
        signal_type = signal_data.get("signal", "WAIT")
        score = signal_data.get("score", 0)
        classification = signal_data.get("classification", "WAIT")
        
        # Anti-doublons 2h
        two_hours_ago = datetime.utcnow() - timedelta(hours=2)
        recent = db.query(SignalNotification).filter(
            SignalNotification.user_id == user.id,
            SignalNotification.asset == asset,
            SignalNotification.signal_type == signal_type,
            SignalNotification.sent_at >= two_hours_ago
        ).first()
        
        if recent:
            return
        
        display_name = ASSETS.get(asset, asset)
        signal_emoji = "🟢" if signal_type == "BUY" else "🔴"
        signal_text = "ACHAT" if signal_type == "BUY" else "VENTE"
        
        entry_val = signal_data.get("entry") or "N/A"
        sl_val = signal_data.get("stop_loss") or "N/A"
        tp1_val = signal_data.get("take_profit_1") or "N/A"
        tp2_val = signal_data.get("take_profit_2") or "N/A"
        current_price = signal_data.get("current_price") or "N/A"
        rr = signal_data.get("risk_reward") or "N/A"
        
        # Score breakdown
        breakdown = signal_data.get("scores_breakdown", {})
        smc_pts = breakdown.get("smc", 0)
        tech_pts = breakdown.get("technical", 0)
        mtf_pts = breakdown.get("mtf", 0)
        
        risk_level = signal_data.get("calendar_analysis", {}).get("risk_level", "NORMAL")
        risk_emoji = "🔴" if risk_level in ["BLOCKED", "HIGH_RISK"] else ("🟡" if risk_level == "CAUTION" else "🟢")
        
        title = f"{signal_emoji} {signal_text} {display_name}  •  Score {score}/100 ({classification})"
        
        body = (
            f"💰 Prix : {current_price}\n"
            f"🎯 Entrée : {entry_val}\n"
            f"🛑 SL : {sl_val}\n"
            f"✅ TP1 : {tp1_val}\n"
            f"✅ TP2 : {tp2_val}\n"
            f"📊 R/R : 1:{rr}\n"
            f"🧠 SMC:{smc_pts}/30 Tech:{tech_pts}/25 MTF:{mtf_pts}/20\n"
            f"{risk_emoji} Calendrier : {risk_level}\n"
            f"⚠️ Score ≠ probabilite de gain"
        )
        
        data = {
            "asset": asset,
            "signal": signal_type,
            "score": str(score),
            "classification": classification,
            "entry": str(entry_val),
            "stop_loss": str(sl_val),
            "take_profit": str(tp1_val),
            "strategy_version": STRATEGY_VERSION
        }
        
        success = send_push_notification(user.fcm_token, title, body, data)
        
        if success:
            notif = SignalNotification(
                user_id=user.id,
                asset=asset,
                signal_type=signal_type,
                confidence=score,
                signal_key=f"{asset}_{signal_type}_{score}_{int(time.time())}"
            )
            db.add(notif)
            db.commit()
            print(f"Notification v9 envoyee a {user.username} : {asset} {signal_type} {score}/100")
    except Exception as e:
        print(f"Erreur notification v9 {user.username}: {e}")
        db.rollback()


def scheduler_v9():
    """
    Scheduler v9.0
    - Analyse toutes les 15 min selon preferences user
    - Enregistre les signaux
    - Verifie les resultats
    - Envoie notifications
    """
    while True:
        try:
            time.sleep(900)  # 15 minutes
            
            print(f"\n[{datetime.utcnow()}] ═══ SCHEDULER v9.0 ═══")
            
            db = SessionLocal()
            try:
                # Recuperer les users actifs
                users = db.query(User).filter(
                    User.notifications_enabled == True,
                    User.fcm_token != ""
                ).all()
                
                if not users:
                    print("Aucun user actif")
                    db.close()
                    continue
                
                print(f"Users actifs : {len(users)}")
                
                # Combinaisons uniques de timeframes
                tf_combinations = set()
                user_configs = {}
                
                for user in users:
                    main_tf = user.main_timeframe
                    if user.auto_confirmation:
                        confirm_tf = CONFIRMATION_MAP.get(main_tf, "4h")
                    else:
                        confirm_tf = user.confirmation_timeframe
                    
                    tf_combinations.add(main_tf)
                    user_configs[user.id] = {
                        "main_tf": main_tf,
                        "min_score": user.min_confidence
                    }
                
                print(f"Timeframes a analyser : {tf_combinations}")
                
                # Analyser chaque combinaison UNE fois
                signals_cache = {}
                
                for main_tf in tf_combinations:
                    for asset in ASSETS.keys():
                        try:
                            result = generate_signal_v9(asset, main_tf, min_score=60, min_rr=1.5)
                            
                            if result.get("signal") in ["BUY", "SELL"]:
                                key = f"{asset}_{main_tf}"
                                signals_cache[key] = result
                                
                                # Enregistrer dans la DB
                                save_signal_to_db(result)
                                
                                print(f"  Signal : {asset} {result['signal']} Score:{result['score']}/100 ({result['classification']})")
                        except Exception as e:
                            print(f"  Erreur {asset} {main_tf}: {e}")
                
                # Dispatcher aux users
                for user in users:
                    config = user_configs.get(user.id, {})
                    main_tf = config.get("main_tf", "1h")
                    min_score = config.get("min_score", 70)
                    
                    for asset in ASSETS.keys():
                        key = f"{asset}_{main_tf}"
                        if key in signals_cache:
                            result = signals_cache[key]
                            if result.get("score", 0) >= min_score:
                                send_signal_notification_v9(user, asset, result, db)
                
            finally:
                db.close()
            
            # Verifier les resultats des anciens signaux
            try:
                print("  Verification des resultats...")
                check_and_update_signal_results()
            except Exception as e:
                print(f"  Erreur verification resultats: {e}")
            
            # Nettoyer les vieilles notifications (>7 jours)
            try:
                db = SessionLocal()
                cutoff = datetime.utcnow() - timedelta(days=7)
                db.query(SignalNotification).filter(
                    SignalNotification.sent_at < cutoff
                ).delete()
                db.commit()
                db.close()
            except Exception as e:
                print(f"  Erreur nettoyage: {e}")
            
            print(f"═══ FIN SCHEDULER ═══\n")
                
        except Exception as e:
            print(f"Erreur scheduler v9: {e}")


scheduler_thread = threading.Thread(target=scheduler_v9, daemon=True)
scheduler_thread.start()
print("Scheduler v9.0 demarre (15 min interval)")


# ═══════════════════════════════════════════════
#              MODELES PYDANTIC
# ═══════════════════════════════════════════════

class UserRegister(BaseModel):
    username: str
    password: str


class UserLogin(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    username: str


class FCMTokenUpdate(BaseModel):
    fcm_token: str


class UserSettingsUpdate(BaseModel):
    main_timeframe: str = None
    confirmation_timeframe: str = None
    auto_confirmation: bool = None
    min_confidence: int = None
    notifications_enabled: bool = None
    refresh_interval: int = None


# ═══════════════════════════════════════════════
#              ENDPOINTS API
# ═══════════════════════════════════════════════

@app.get("/")
async def root():
    return {
        "status": "online",
        "message": "TradeVision AI v9.0",
        "version": "9.0.0",
        "strategy_version": STRATEGY_VERSION,
        "ai_provider": "OpenRouter",
        "ai_configured": bool(OPENROUTER_API_KEY),
        "active_model": ACTIVE_MODEL or "not_tested_yet",
        "firebase_configured": bool(FIREBASE_APP),
        "database_connected": True,
        "scoring_system": "Deterministic 0-100",
        "features": [
            "Score 0-100 deterministe",
            "Classification WEAK/MODERATE/STRONG/VERY_STRONG/EXTREME",
            "Data Quality Check",
            "Multi-Timeframe 3 niveaux",
            "Market Regime Detection",
            "Smart Money Concepts complet",
            "ADX + Stochastic + EMA200",
            "Risk Management intelligent",
            "Signal Journal (PostgreSQL)",
            "Signal Results Tracking",
            "Anti-duplicate 2h",
            "Personalized Scheduler",
            "Firebase Push Notifications",
            "AI optionnelle (fallback)",
            "Score ≠ probabilite"
        ]
    }


@app.get("/health")
async def health():
    db = SessionLocal()
    signals_count = db.query(SignalV9).count()
    results_count = db.query(SignalResultV9).count()
    db.close()
    
    return {
        "status": "healthy",
        "version": "9.0.0",
        "twelve_data_configured": bool(API_KEY),
        "twelve_data_key_2": bool(API_KEY_2),
        "openrouter_configured": bool(OPENROUTER_API_KEY),
        "firebase_configured": bool(FIREBASE_APP),
        "active_model": ACTIVE_MODEL or "not_tested_yet",
        "news_cached": bool(NEWS_CACHE["data"]),
        "calendar_cached": bool(CALENDAR_CACHE["data"]),
        "total_signals_recorded": signals_count,
        "total_results_recorded": results_count
    }


# ─── Auth ───

@app.post("/api/v1/auth/register", response_model=TokenResponse)
async def register(user_data: UserRegister, db: Session = Depends(get_db)):
    if len(user_data.username) < 3:
        raise HTTPException(status_code=400, detail="Nom trop court (min 3)")
    if len(user_data.password) < 4:
        raise HTTPException(status_code=400, detail="Mot de passe trop court (min 4)")
    
    existing = db.query(User).filter(User.username == user_data.username).first()
    if existing:
        raise HTTPException(status_code=400, detail="Ce nom existe deja")
    
    new_user = User(username=user_data.username, password_hash=hash_password(user_data.password))
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    return {"access_token": create_access_token(data={"sub": new_user.username}), "token_type": "bearer", "username": new_user.username}


@app.post("/api/v1/auth/login", response_model=TokenResponse)
async def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Identifiants incorrects")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Compte desactive")
    return {"access_token": create_access_token(data={"sub": user.username}), "token_type": "bearer", "username": user.username}


@app.post("/api/v1/auth/login-simple", response_model=TokenResponse)
async def login_simple(user_data: UserLogin, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == user_data.username).first()
    if not user or not verify_password(user_data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Identifiants incorrects")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Compte desactive")
    return {"access_token": create_access_token(data={"sub": user.username}), "token_type": "bearer", "username": user.username}


@app.get("/api/v1/auth/me")
async def get_me(current_user: User = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "username": current_user.username,
        "created_at": current_user.created_at.isoformat() if current_user.created_at else None,
        "settings": {
            "main_timeframe": current_user.main_timeframe,
            "confirmation_timeframe": current_user.confirmation_timeframe,
            "auto_confirmation": current_user.auto_confirmation,
            "min_confidence": current_user.min_confidence,
            "notifications_enabled": current_user.notifications_enabled,
            "refresh_interval": current_user.refresh_interval
        }
    }


# ─── User Settings ───

@app.put("/api/v1/user/settings")
async def update_settings(settings: UserSettingsUpdate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if settings.main_timeframe and settings.main_timeframe in TIMEFRAMES:
        current_user.main_timeframe = settings.main_timeframe
    if settings.confirmation_timeframe and settings.confirmation_timeframe in TIMEFRAMES:
        current_user.confirmation_timeframe = settings.confirmation_timeframe
    if settings.auto_confirmation is not None:
        current_user.auto_confirmation = settings.auto_confirmation
    if settings.min_confidence is not None and 60 <= settings.min_confidence <= 95:
        current_user.min_confidence = settings.min_confidence
    if settings.notifications_enabled is not None:
        current_user.notifications_enabled = settings.notifications_enabled
    if settings.refresh_interval is not None and settings.refresh_interval in [5, 10, 15, 30]:
        current_user.refresh_interval = settings.refresh_interval
    
    db.commit()
    db.refresh(current_user)
    
    return {"message": "Parametres mis a jour", "settings": {
        "main_timeframe": current_user.main_timeframe,
        "confirmation_timeframe": current_user.confirmation_timeframe,
        "auto_confirmation": current_user.auto_confirmation,
        "min_confidence": current_user.min_confidence,
        "notifications_enabled": current_user.notifications_enabled,
        "refresh_interval": current_user.refresh_interval
    }}


@app.post("/api/v1/user/fcm-token")
async def update_fcm_token(token_data: FCMTokenUpdate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    current_user.fcm_token = token_data.fcm_token
    db.commit()
    return {"message": "FCM token enregistre"}


# ─── Signals v2 (v9.0) ───

@app.get("/api/v2/signal/{asset}")
async def get_signal_v9(asset: str, main_tf: str = "1h", min_score: int = 70, min_rr: float = 1.5):
    """Signal v9.0 avec score deterministe"""
    asset = asset.upper()
    if asset not in ASSETS:
        raise HTTPException(status_code=404, detail="Asset not found")
    return generate_signal_v9(asset, main_tf, min_score, min_rr)


@app.get("/api/v2/signals")
async def get_all_signals_v9(main_tf: str = "1h", min_score: int = 70):
    """Tous les signaux v9.0"""
    signals = {}
    for asset in ASSETS.keys():
        try:
            result = generate_signal_v9(asset, main_tf, min_score)
            signals[asset] = {
                "signal": result.get("signal"),
                "score": result.get("score"),
                "classification": result.get("classification"),
                "current_price": result.get("current_price"),
                "entry": result.get("entry"),
                "stop_loss": result.get("stop_loss"),
                "take_profit_1": result.get("take_profit_1"),
                "risk_reward": result.get("risk_reward"),
                "direction": result.get("direction"),
                "market_regime": result.get("market_context", {}).get("regime"),
                "warnings": result.get("warnings", []),
                "scores_breakdown": result.get("scores_breakdown", {}),
                "disclaimer": result.get("disclaimer")
            }
        except Exception as e:
            signals[asset] = {"signal": "WAIT", "score": 0, "error": str(e)}
    
    return {
        "timestamp": datetime.utcnow().isoformat(),
        "strategy_version": STRATEGY_VERSION,
        "scoring_system": "Deterministic 0-100",
        "main_timeframe": main_tf,
        "min_score": min_score,
        "signals": signals,
        "disclaimer": "Score = qualite du setup. NE constitue PAS une probabilite de gain."
    }


@app.get("/api/v2/user/signals")
async def get_user_signals_v9(current_user: User = Depends(get_current_user)):
    """Signaux personnalises v9.0 selon parametres user"""
    main_tf = current_user.main_timeframe
    min_score = current_user.min_confidence
    
    signals = {}
    for asset in ASSETS.keys():
        try:
            result = generate_signal_v9(asset, main_tf, min_score)
            signals[asset] = {
                "signal": result.get("signal"),
                "score": result.get("score"),
                "classification": result.get("classification"),
                "current_price": result.get("current_price"),
                "entry": result.get("entry"),
                "stop_loss": result.get("stop_loss"),
                "take_profit_1": result.get("take_profit_1"),
                "take_profit_2": result.get("take_profit_2"),
                "risk_reward": result.get("risk_reward"),
                "direction": result.get("direction"),
                "scores_breakdown": result.get("scores_breakdown", {}),
                "smc_signals": result.get("smc_details", {}).get("signals", []),
                "reasons": result.get("reasons", []),
                "warnings": result.get("warnings", []),
                "ai_summary": result.get("ai_analysis", {}).get("summary", ""),
                "disclaimer": result.get("disclaimer")
            }
        except Exception as e:
            signals[asset] = {"signal": "WAIT", "score": 0, "error": str(e)}
    
    return {
        "timestamp": datetime.utcnow().isoformat(),
        "username": current_user.username,
        "strategy_version": STRATEGY_VERSION,
        "main_timeframe": main_tf,
        "min_score": min_score,
        "signals": signals
    }


# ─── Compatibilite v1 (pour l'app Android existante) ───

@app.get("/api/v1/signals")
async def get_signals_v1_compat(min_confidence: int = 70, main_tf: str = "1h", confirmation_tf: str = None):
    """Endpoint v1 compatible avec l'app Android existante"""
    signals = {}
    for asset in ASSETS.keys():
        try:
            result = generate_signal_v9(asset, main_tf, min_confidence)
            
            if result.get("signal") in ["BUY", "SELL"] and result.get("score", 0) >= min_confidence:
                signals[asset] = {
                    "status": "ok",
                    "signal": result["signal"],
                    "confidence": result.get("score", 0),
                    "trend": result.get("market_context", {}).get("trend", "neutral"),
                    "current_price": result.get("current_price"),
                    "entry": result.get("entry"),
                    "stop_loss": result.get("stop_loss"),
                    "take_profit_1": result.get("take_profit_1"),
                    "take_profit_2": result.get("take_profit_2"),
                    "take_profit_3": result.get("take_profit_3"),
                    "risk_reward": result.get("risk_reward"),                    "risk_reward": result.get("risk_reward"),
                    "risk_level": result.get("calendar_analysis", {}).get("risk_level", "NORMAL"),
                    "reasons": result.get("reasons", []),
                    "warnings": result.get("warnings", []),
                    "scores": result.get("scores_breakdown", {}),
                    "ai_summary": result.get("ai_analysis", {}).get("summary", ""),
                    "smc_signals": result.get("smc_details", {}).get("signals", [])
                }
            else:
                signals[asset] = {
                    "status": "wait",
                    "signal": "WAIT",
                    "confidence": result.get("score", 0),
                    "reason": "Score insuffisant ou conditions non validees",
                    "warnings": result.get("warnings", [])
                }
        except Exception as e:
            signals[asset] = {"status": "error", "signal": "WAIT", "error": str(e)}
    
    return {
        "timestamp": datetime.utcnow().isoformat(),
        "min_confidence": min_confidence,
        "main_timeframe": main_tf,
        "signals": signals
    }


@app.get("/api/v1/user/signals")
async def get_user_signals_v1_compat(current_user: User = Depends(get_current_user)):
    """Endpoint v1 user compatible"""
    main_tf = current_user.main_timeframe
    min_conf = current_user.min_confidence
    
    signals = {}
    for asset in ASSETS.keys():
        try:
            result = generate_signal_v9(asset, main_tf, min_conf)
            
            if result.get("signal") in ["BUY", "SELL"] and result.get("score", 0) >= min_conf:
                signals[asset] = {
                    "status": "ok",
                    "signal": result["signal"],
                    "confidence": result.get("score", 0),
                    "trend": result.get("market_context", {}).get("trend", "neutral"),
                    "current_price": result.get("current_price"),
                    "entry": result.get("entry"),
                    "stop_loss": result.get("stop_loss"),
                    "take_profit_1": result.get("take_profit_1"),
                    "take_profit_2": result.get("take_profit_2"),
                    "take_profit_3": result.get("take_profit_3"),
                    "risk_reward": result.get("risk_reward"),
                    "risk_level": result.get("calendar_analysis", {}).get("risk_level", "NORMAL"),
                    "reasons": result.get("reasons", []),
                    "warnings": result.get("warnings", []),
                    "scores": result.get("scores_breakdown", {}),
                    "ai_summary": result.get("ai_analysis", {}).get("summary", ""),
                    "smc_signals": result.get("smc_details", {}).get("signals", [])
                }
            else:
                signals[asset] = {
                    "status": "wait",
                    "signal": "WAIT",
                    "confidence": result.get("score", 0),
                    "reason": "Score insuffisant",
                    "warnings": result.get("warnings", [])
                }
        except Exception as e:
            signals[asset] = {"status": "error", "signal": "WAIT", "error": str(e)}
    
    return {
        "timestamp": datetime.utcnow().isoformat(),
        "username": current_user.username,
        "min_confidence": min_conf,
        "main_timeframe": main_tf,
        "signals": signals
    }


@app.get("/api/v1/prices")
async def get_prices():
    prices = {}
    for name, symbol in ASSETS.items():
        data = td_request("price", {"symbol": symbol})
        if data and "price" in data:
            prices[name] = {"price": float(data["price"]), "status": "ok"}
        else:
            prices[name] = {"status": "error"}
    return {"timestamp": datetime.utcnow().isoformat(), "prices": prices}


@app.get("/api/v1/timeframes")
async def get_timeframes():
    return {
        "timeframes": list(TIMEFRAMES.keys()),
        "confirmation_map": CONFIRMATION_MAP,
        "mtf_3_levels": MTF_3_LEVELS,
        "descriptions": {
            "15m": "15 minutes (scalping)",
            "30m": "30 minutes (scalping)",
            "1h": "1 heure (intraday)",
            "2h": "2 heures (intraday long)",
            "4h": "4 heures (swing)",
            "1d": "1 jour (position)"
        }
    }


@app.get("/api/v1/news")
async def get_news(limit: int = 20, currency: str = None):
    all_news = get_cached_news()
    if currency:
        currency = currency.upper()
        all_news = [n for n in all_news if currency in n["currencies"]]
    return {"timestamp": datetime.utcnow().isoformat(), "count": len(all_news[:limit]), "news": all_news[:limit]}


@app.get("/api/v1/calendar")
async def get_calendar(currency: str = None, impact: str = None):
    events = get_cached_calendar()
    if currency:
        currency = currency.upper()
        events = [e for e in events if e["currency"] == currency]
    if impact:
        impact = impact.upper()
        events = [e for e in events if impact in e["impact"].upper()]
    return {"timestamp": datetime.utcnow().isoformat(), "count": len(events), "events": events}


@app.get("/api/v1/admin/users-count")
async def admin_users_count(db: Session = Depends(get_db)):
    total = db.query(User).count()
    with_fcm = db.query(User).filter(User.fcm_token != "").count()
    notifs_enabled = db.query(User).filter(User.notifications_enabled == True).count()
    return {"total_users": total, "users_with_fcm": with_fcm, "notifications_enabled": notifs_enabled}


@app.get("/api/v1/admin/api-keys-status")
async def admin_api_keys_status():
    return {
        "twelve_data_key_1": "configured" if API_KEY else "missing",
        "twelve_data_key_2": "configured" if API_KEY_2 else "missing",
        "total_requests": API_KEY_COUNTER,
        "current_active": "key_2" if API_KEY_COUNTER % 2 == 0 and API_KEY_2 else "key_1"
    }


@app.get("/api/v2/signal/{asset}")
async def get_signal_v9(asset: str, main_tf: str = "1h", min_score: int = 70, min_rr: float = 1.5):
    asset = asset.upper()
    if asset not in ASSETS:
        raise HTTPException(status_code=404, detail="Asset not found")
    return generate_signal_v9(asset, main_tf, min_score, min_rr)


@app.get("/api/v2/signals")
async def get_all_signals_v9(main_tf: str = "1h", min_score: int = 70):
    signals = {}
    for asset in ASSETS.keys():
        try:
            result = generate_signal_v9(asset, main_tf, min_score)
            signals[asset] = {
                "signal": result.get("signal"),
                "score": result.get("score"),
                "classification": result.get("classification"),
                "current_price": result.get("current_price"),
                "entry": result.get("entry"),
                "stop_loss": result.get("stop_loss"),
                "take_profit_1": result.get("take_profit_1"),
                "risk_reward": result.get("risk_reward"),
                "direction": result.get("direction"),
                "scores_breakdown": result.get("scores_breakdown", {}),
                "warnings": result.get("warnings", []),
                "disclaimer": result.get("disclaimer")
            }
        except Exception as e:
            signals[asset] = {"signal": "WAIT", "score": 0, "error": str(e)}
    
    return {
        "timestamp": datetime.utcnow().isoformat(),
        "strategy_version": STRATEGY_VERSION,
        "scoring_system": "Deterministic 0-100",
        "main_timeframe": main_tf,
        "min_score": min_score,
        "signals": signals,
        "disclaimer": "Score = qualite du setup. NE constitue PAS une probabilite de gain."
    }


@app.get("/api/v2/user/signals")
async def get_user_signals_v9(current_user: User = Depends(get_current_user)):
    main_tf = current_user.main_timeframe
    min_score = current_user.min_confidence
    
    signals = {}
    for asset in ASSETS.keys():
        try:
            result = generate_signal_v9(asset, main_tf, min_score)
            signals[asset] = {
                "signal": result.get("signal"),
                "score": result.get("score"),
                "classification": result.get("classification"),
                "current_price": result.get("current_price"),
                "entry": result.get("entry"),
                "stop_loss": result.get("stop_loss"),
                "take_profit_1": result.get("take_profit_1"),
                "take_profit_2": result.get("take_profit_2"),
                "risk_reward": result.get("risk_reward"),
                "direction": result.get("direction"),
                "scores_breakdown": result.get("scores_breakdown", {}),
                "smc_signals": result.get("smc_details", {}).get("signals", []),
                "reasons": result.get("reasons", []),
                "warnings": result.get("warnings", []),
                "ai_summary": result.get("ai_analysis", {}).get("summary", ""),
                "disclaimer": result.get("disclaimer")
            }
        except Exception as e:
            signals[asset] = {"signal": "WAIT", "score": 0, "error": str(e)}
    
    return {
        "timestamp": datetime.utcnow().isoformat(),
        "username": current_user.username,
        "strategy_version": STRATEGY_VERSION,
        "main_timeframe": main_tf,
        "min_score": min_score,
        "signals": signals
    }


@app.get("/api/v2/signals/history")
async def get_signals_history(limit: int = 50, asset: str = None, db: Session = Depends(get_db)):
    query = db.query(SignalV9).order_by(SignalV9.timestamp.desc())
    if asset:
        query = query.filter(SignalV9.asset == asset.upper())
    signals = query.limit(limit).all()
    
    results = []
    for sig in signals:
        result = db.query(SignalResultV9).filter(SignalResultV9.signal_id == sig.signal_id).first()
        results.append({
            "signal_id": sig.signal_id,
            "timestamp": sig.timestamp.isoformat() if sig.timestamp else None,
            "asset": sig.asset,
            "signal": sig.signal,
            "score": sig.score,
            "classification": sig.classification,
            "entry": sig.entry,
            "stop_loss": sig.stop_loss,
            "take_profit_1": sig.take_profit_1,
            "risk_reward": sig.risk_reward,
            "strategy_version": sig.strategy_version,
            "status": sig.status,
            "result": result.result if result else "PENDING",
            "pnl_r": result.final_pnl_r if result else None
        })
    
    return {"timestamp": datetime.utcnow().isoformat(), "count": len(results), "signals": results}


@app.get("/api/v2/performance")
async def get_performance(db: Session = Depends(get_db)):
    total = db.query(SignalV9).filter(SignalV9.signal.in_(["BUY", "SELL"])).count()
    results = db.query(SignalResultV9).all()
    
    wins = sum(1 for r in results if r.result == "WIN")
    losses = sum(1 for r in results if r.result == "LOSS")
    pending = sum(1 for r in results if r.result == "PENDING")
    expired = sum(1 for r in results if r.result == "EXPIRED")
    total_closed = wins + losses
    win_rate = round((wins / total_closed * 100), 2) if total_closed > 0 else 0
    
    pnl_values = [r.final_pnl_r for r in results if r.final_pnl_r is not None]
    avg_pnl = round(sum(pnl_values) / len(pnl_values), 3) if pnl_values else 0
    
    gross_profit = sum(r.final_pnl_r for r in results if r.final_pnl_r and r.final_pnl_r > 0)
    gross_loss = abs(sum(r.final_pnl_r for r in results if r.final_pnl_r and r.final_pnl_r < 0))
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else 0
    
    return {
        "timestamp": datetime.utcnow().isoformat(),
        "strategy_version": STRATEGY_VERSION,
        "total_signals": total,
        "results": {
            "wins": wins,
            "losses": losses,
            "pending": pending,
            "expired": expired,
            "total_closed": total_closed,
            "win_rate": win_rate,
            "average_pnl_r": avg_pnl,
            "profit_factor": profit_factor
        },
        "disclaimer": "Performances historiques. Ne garantissent pas les resultats futurs."
    }


@app.post("/api/v1/admin/test-notification")
async def admin_test_notification(current_user: User = Depends(get_current_user)):
    if not current_user.fcm_token:
        raise HTTPException(status_code=400, detail="Aucun FCM token")
    
    test_body = (
        f"🐉 Bonjour {current_user.username} !\n\n"
        f"💰 Prix : 1.15353\n"
        f"🎯 Entrée : 1.15353\n"
        f"🛑 SL : 1.15235\n"
        f"✅ TP1 : 1.15510\n"
        f"📊 R/R : 1:2.0\n"
        f"🧠 SMC:25/30 Tech:20/25 MTF:18/20\n"
        f"🟢 Calendrier : NORMAL\n\n"
        f"⚠️ Score ≠ probabilite de gain\n"
        f"✨ v9.0 fonctionne !"
    )
    
    success = send_push_notification(
        current_user.fcm_token,
        "🧪 🟢 ACHAT EUR/USD • Score 83/100 (VERY_STRONG)",
        test_body,
        {"type": "test", "strategy_version": STRATEGY_VERSION}
    )
    
    if success:
        return {"message": "Notification v9.0 envoyee"}
    raise HTTPException(status_code=500, detail="Echec envoi")
    
