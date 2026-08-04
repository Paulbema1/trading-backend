from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Float, Boolean, Text
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
from datetime import datetime, timedelta

# Firebase
import firebase_admin
from firebase_admin import credentials, messaging

# ═══════════════════════════════════════════════
#              CONFIGURATION
# ═══════════════════════════════════════════════

app = FastAPI(title="TradeVision AI", version="8.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Variables d'environnement
API_KEY = os.getenv("TWELVE_DATA_API_KEY", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./tradevision.db")
FIREBASE_PROJECT_ID = os.getenv("FIREBASE_PROJECT_ID", "")
FIREBASE_CLIENT_EMAIL = os.getenv("FIREBASE_CLIENT_EMAIL", "")
FIREBASE_PRIVATE_KEY = os.getenv("FIREBASE_PRIVATE_KEY", "").replace("\\n", "\n")
JWT_SECRET = os.getenv("JWT_SECRET", "tradevision-super-secret-key-change-me-in-prod")

BASE_URL = "https://api.twelvedata.com"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Fix pour Render PostgreSQL URL
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
    
    # Paramètres utilisateur
    main_timeframe = Column(String(10), default="1h")
    confirmation_timeframe = Column(String(10), default="4h")
    auto_confirmation = Column(Boolean, default=True)
    min_confidence = Column(Integer, default=70)
    notifications_enabled = Column(Boolean, default=True)
    refresh_interval = Column(Integer, default=5)
    
    # FCM Token pour notifications
    fcm_token = Column(String(500), default="")


class SignalNotification(Base):
    __tablename__ = "signal_notifications"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True, nullable=False)
    asset = Column(String(20))
    signal_type = Column(String(10))
    confidence = Column(Integer)
    signal_key = Column(String(50))  # Pour éviter doublons
    sent_at = Column(DateTime, default=datetime.utcnow)


# Créer les tables au démarrage
try:
    Base.metadata.create_all(bind=engine)
    print("Base de donnees initialisee")
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
        print("Firebase non configure (variables manquantes)")
except Exception as e:
    print(f"Erreur Firebase: {e}")


def send_push_notification(fcm_token: str, title: str, body: str, data: dict = None):
    """Envoie une notification push via Firebase"""
    if not FIREBASE_APP or not fcm_token:
        return False
    
    try:
        message = messaging.Message(
            notification=messaging.Notification(
                title=title,
                body=body,
            ),
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

NEWS_CACHE = {"data": None, "timestamp": 0}
CALENDAR_CACHE = {"data": None, "timestamp": 0}
AI_CACHE = {}
NEWS_CACHE_DURATION = 900
CALENDAR_CACHE_DURATION = 1800
AI_CACHE_DURATION = 900


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
print("Auto-ping thread demarre (5 min interval)")


# ═══════════════════════════════════════════════
#              FONCTIONS UTILITAIRES
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
                            print("Active model: " + model)
                        return content
                else:
                    break
                    
            except Exception as e:
                print("OpenRouter exception: " + str(e)[:100])
                break
    
    return None


def td_request(endpoint, params):
    params["apikey"] = API_KEY
    try:
        response = requests.get(BASE_URL + "/" + endpoint, params=params, timeout=10)
        return response.json()
    except Exception as e:
        print("Erreur TD:", e)
        return None


def get_candles_df(symbol, interval, limit=100):
    data = td_request("time_series", {"symbol": symbol, "interval": interval, "outputsize": limit})
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


def ema(series, period):
    return series.ewm(span=period, adjust=False).mean()


def rsi(series, period=14):
    delta = series.diff()
    gain = delta.where(delta > 0, 0).rolling(window=period).mean()
    loss = -delta.where(delta < 0, 0).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


def macd(series):
    ema_fast = ema(series, 12)
    ema_slow = ema(series, 26)
    macd_line = ema_fast - ema_slow
    signal_line = ema(macd_line, 9)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def atr(df, period=14):
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift()).abs()
    low_close = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()


def bollinger_bands(series, period=20, std=2):
    sma = series.rolling(window=period).mean()
    std_dev = series.rolling(window=period).std()
    upper = sma + (std_dev * std)
    lower = sma - (std_dev * std)
    return upper, sma, lower


def find_support_resistance(df, window=10):
    highs = df["high"].rolling(window=window, center=True).max()
    lows = df["low"].rolling(window=window, center=True).min()
    resistances = df["high"][df["high"] == highs].dropna().tail(3).tolist()
    supports = df["low"][df["low"] == lows].dropna().tail(3).tolist()
    return supports, resistances

# ═══════════════════════════════════════════════
#         SMART MONEY CONCEPTS (SMC)
# ═══════════════════════════════════════════════

def find_swing_points(df, lookback=5):
    swing_highs = []
    swing_lows = []
    
    for i in range(lookback, len(df) - lookback):
        high = df["high"].iloc[i]
        low = df["low"].iloc[i]
        
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
    swing_highs, swing_lows = find_swing_points(df, lookback=5)
    
    structure = {
        "trend": "neutral",
        "recent_highs": [],
        "recent_lows": [],
        "structure_type": "unknown"
    }
    
    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return structure
    
    last_highs = swing_highs[-3:] if len(swing_highs) >= 3 else swing_highs
    last_lows = swing_lows[-3:] if len(swing_lows) >= 3 else swing_lows
    
    structure["recent_highs"] = [{"price": h["price"], "index": h["index"]} for h in last_highs]
    structure["recent_lows"] = [{"price": l["price"], "index": l["index"]} for l in last_lows]
    
    higher_highs = 0
    lower_highs = 0
    higher_lows = 0
    lower_lows = 0
    
    for i in range(1, len(last_highs)):
        if last_highs[i]["price"] > last_highs[i-1]["price"]:
            higher_highs += 1
        else:
            lower_highs += 1
    
    for i in range(1, len(last_lows)):
        if last_lows[i]["price"] > last_lows[i-1]["price"]:
            higher_lows += 1
        else:
            lower_lows += 1
    
    if higher_highs >= 1 and higher_lows >= 1:
        structure["trend"] = "bullish"
        structure["structure_type"] = "HH_HL"
    elif lower_highs >= 1 and lower_lows >= 1:
        structure["trend"] = "bearish"
        structure["structure_type"] = "LH_LL"
    else:
        structure["trend"] = "ranging"
        structure["structure_type"] = "consolidation"
    
    return structure


def detect_bos(df, structure):
    swing_highs, swing_lows = find_swing_points(df, lookback=5)
    
    bos = {
        "detected": False,
        "type": None,
        "level": None,
        "index": None
    }
    
    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return bos
    
    current_price = float(df["close"].iloc[-1])
    
    if len(swing_highs) >= 2:
        last_swing_high = swing_highs[-2]["price"]
        recent_high_after = max([df["high"].iloc[i] for i in range(swing_highs[-2]["index"] + 1, len(df))])
        
        if recent_high_after > last_swing_high and current_price > last_swing_high:
            bos = {
                "detected": True,
                "type": "bullish",
                "level": round(last_swing_high, 5),
                "index": swing_highs[-2]["index"]
            }
    
    if len(swing_lows) >= 2:
        last_swing_low = swing_lows[-2]["price"]
        recent_low_after = min([df["low"].iloc[i] for i in range(swing_lows[-2]["index"] + 1, len(df))])
        
        if recent_low_after < last_swing_low and current_price < last_swing_low:
            if not bos["detected"] or bos["type"] == "bearish":
                bos = {
                    "detected": True,
                    "type": "bearish",
                    "level": round(last_swing_low, 5),
                    "index": swing_lows[-2]["index"]
                }
    
    return bos


def detect_choch(df, structure):
    swing_highs, swing_lows = find_swing_points(df, lookback=5)
    
    choch = {
        "detected": False,
        "type": None,
        "level": None,
        "reason": ""
    }
    
    if len(swing_highs) < 3 or len(swing_lows) < 3:
        return choch
    
    current_price = float(df["close"].iloc[-1])
    
    if structure["trend"] == "bearish":
        recent_high = swing_highs[-1]["price"]
        if current_price > recent_high:
            choch = {
                "detected": True,
                "type": "bullish",
                "level": round(recent_high, 5),
                "reason": "Cassure haussiere apres tendance baissiere"
            }
    
    elif structure["trend"] == "bullish":
        recent_low = swing_lows[-1]["price"]
        if current_price < recent_low:
            choch = {
                "detected": True,
                "type": "bearish",
                "level": round(recent_low, 5),
                "reason": "Cassure baissiere apres tendance haussiere"
            }
    
    return choch


def detect_order_blocks(df, lookback=20):
    order_blocks = {
        "bullish": [],
        "bearish": []
    }
    
    if len(df) < lookback + 5:
        return order_blocks
    
    for i in range(len(df) - lookback, len(df) - 2):
        candle = df.iloc[i]
        next_candles = df.iloc[i+1:i+5]
        
        candle_body = abs(candle["close"] - candle["open"])
        candle_range = candle["high"] - candle["low"]
        
        if candle_range == 0:
            continue
        
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
    
    order_blocks["bullish"] = sorted(order_blocks["bullish"], key=lambda x: x["strength"], reverse=True)[:3]
    order_blocks["bearish"] = sorted(order_blocks["bearish"], key=lambda x: x["strength"], reverse=True)[:3]
    
    return order_blocks


def detect_fvg(df, lookback=30):
    fvg_list = {
        "bullish": [],
        "bearish": []
    }
    
    if len(df) < 3:
        return fvg_list
    
    start = max(0, len(df) - lookback)
    
    for i in range(start + 1, len(df) - 1):
        prev_candle = df.iloc[i - 1]
        curr_candle = df.iloc[i]
        next_candle = df.iloc[i + 1]
        
        if next_candle["low"] > prev_candle["high"]:
            gap_size = next_candle["low"] - prev_candle["high"]
            fvg_list["bullish"].append({
                "type": "bullish",
                "top": round(float(next_candle["low"]), 5),
                "bottom": round(float(prev_candle["high"]), 5),
                "index": i,
                "size": round(float(gap_size), 5)
            })
        
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
    
    highs = []
    lows = []
    
    for i in range(start, len(df)):
        highs.append((i, float(df["high"].iloc[i])))
        lows.append((i, float(df["low"].iloc[i])))
    
    for i in range(len(highs)):
        for j in range(i + 1, len(highs)):
            if abs(highs[i][1] - highs[j][1]) <= tolerance:
                liquidity["equal_highs"].append({
                    "price": round(highs[i][1], 5),
                    "indices": [highs[i][0], highs[j][0]]
                })
    
    for i in range(len(lows)):
        for j in range(i + 1, len(lows)):
            if abs(lows[i][1] - lows[j][1]) <= tolerance:
                liquidity["equal_lows"].append({
                    "price": round(lows[i][1], 5),
                    "indices": [lows[i][0], lows[j][0]]
                })
    
    if liquidity["equal_highs"]:
        recent_eh = sorted(liquidity["equal_highs"], key=lambda x: x["price"], reverse=True)[:3]
        liquidity["buy_side_liquidity"] = [x["price"] for x in recent_eh]
    
    if liquidity["equal_lows"]:
        recent_el = sorted(liquidity["equal_lows"], key=lambda x: x["price"])[:3]
        liquidity["sell_side_liquidity"] = [x["price"] for x in recent_el]
    
    liquidity["equal_highs"] = liquidity["equal_highs"][:5]
    liquidity["equal_lows"] = liquidity["equal_lows"][:5]
    
    return liquidity


def detect_liquidity_sweep(df, liquidity):
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
    
    for bsl_price in liquidity.get("buy_side_liquidity", []):
        if recent_candles["high"].max() > bsl_price and current_close < bsl_price:
            sweep = {
                "detected": True,
                "type": "bearish",
                "level": bsl_price,
                "reason": "Balayage de liquidite haussiere puis retour"
            }
            break
    
    for ssl_price in liquidity.get("sell_side_liquidity", []):
        if recent_candles["low"].min() < ssl_price and current_close > ssl_price:
            sweep = {
                "detected": True,
                "type": "bullish",
                "level": ssl_price,
                "reason": "Balayage de liquidite baissiere puis retour"
            }
            break
    
    return sweep


def detect_premium_discount(df, lookback=50):
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
    breakers = {
        "bullish": [],
        "bearish": []
    }
    
    if len(df) < 10:
        return breakers
    
    current_price = float(df["close"].iloc[-1])
    
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


def analyze_smc(df):
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
    
    smc_score = 0
    smc_signals = []
    smc_direction = "neutral"
    
    if structure["trend"] == "bullish":
        smc_score += 20
        smc_signals.append("Structure haussiere (HH/HL)")
    elif structure["trend"] == "bearish":
        smc_score -= 20
        smc_signals.append("Structure baissiere (LH/LL)")
    
    if bos["detected"]:
        if bos["type"] == "bullish":
            smc_score += 25
            smc_signals.append("BOS haussier a " + str(bos["level"]))
        else:
            smc_score -= 25
            smc_signals.append("BOS baissier a " + str(bos["level"]))
    
    if choch["detected"]:
        if choch["type"] == "bullish":
            smc_score += 30
            smc_signals.append("CHOCH haussier a " + str(choch["level"]))
        else:
            smc_score -= 30
            smc_signals.append("CHOCH baissier a " + str(choch["level"]))
    
    if order_blocks["bullish"]:
        smc_score += 15
        smc_signals.append(str(len(order_blocks["bullish"])) + " Order Block(s) haussier(s)")
    if order_blocks["bearish"]:
        smc_score -= 15
        smc_signals.append(str(len(order_blocks["bearish"])) + " Order Block(s) baissier(s)")
    
    if breaker_blocks["bullish"]:
        smc_score += 10
        smc_signals.append("Breaker Block haussier")
    if breaker_blocks["bearish"]:
        smc_score -= 10
        smc_signals.append("Breaker Block baissier")
    
    if fvg["bullish"]:
        smc_score += 10
        smc_signals.append(str(len(fvg["bullish"])) + " FVG haussier(s)")
    if fvg["bearish"]:
        smc_score -= 10
        smc_signals.append(str(len(fvg["bearish"])) + " FVG baissier(s)")
    
    if sweep["detected"]:
        if sweep["type"] == "bullish":
            smc_score += 20
            smc_signals.append("Liquidity Sweep haussier")
        else:
            smc_score -= 20
            smc_signals.append("Liquidity Sweep baissier")
    
    if premium_discount["zone"] == "discount":
        smc_score += 10
        smc_signals.append("Prix en zone Discount (achat favorable)")
    elif premium_discount["zone"] == "premium":
        smc_score -= 10
        smc_signals.append("Prix en zone Premium (vente favorable)")
    
    if smc_score >= 30:
        smc_direction = "bullish"
    elif smc_score <= -30:
        smc_direction = "bearish"
    
    return {
        "smc_score": smc_score,
        "smc_direction": smc_direction,
        "smc_signals": smc_signals,
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
#           ANALYSE TECHNIQUE
# ═══════════════════════════════════════════════

def analyze_asset(symbol, interval="1h"):
    df = get_candles_df(symbol, interval, limit=100)
    if df is None or len(df) < 30:
        return None
    
    close = df["close"]
    current_price = float(close.iloc[-1])
    ema_20 = ema(close, 20).iloc[-1]
    ema_50 = ema(close, 50).iloc[-1]
    ema_100 = ema(close, 100).iloc[-1] if len(close) >= 100 else None
    rsi_val = rsi(close, 14).iloc[-1]
    macd_line, signal_line, hist = macd(close)
    macd_val = macd_line.iloc[-1]
    macd_sig = signal_line.iloc[-1]
    macd_hist = hist.iloc[-1]
    atr_val = atr(df, 14).iloc[-1]
    bb_upper, bb_mid, bb_lower = bollinger_bands(close)
    supports, resistances = find_support_resistance(df)
    
    smc = analyze_smc(df)
    
    trend = "neutral"
    if ema_100 and current_price > ema_50 > ema_100:
        trend = "bullish"
    elif ema_100 and current_price < ema_50 < ema_100:
        trend = "bearish"
    elif current_price > ema_20 > ema_50:
        trend = "bullish"
    elif current_price < ema_20 < ema_50:
        trend = "bearish"
    
    score = 0
    reasons = []
    
    if trend == "bullish":
        score += 25
        reasons.append("Tendance haussiere")
    elif trend == "bearish":
        score -= 25
        reasons.append("Tendance baissiere")
    
    if rsi_val < 30:
        score += 20
        reasons.append("RSI survente")
    elif rsi_val > 70:
        score -= 20
        reasons.append("RSI surachat")
    
    if macd_val > macd_sig and macd_hist > 0:
        score += 20
        reasons.append("MACD haussier")
    elif macd_val < macd_sig and macd_hist < 0:
        score -= 20
        reasons.append("MACD baissier")
    
    if current_price < bb_lower.iloc[-1]:
        score += 15
        reasons.append("Sous Bollinger inf")
    elif current_price > bb_upper.iloc[-1]:
        score -= 15
        reasons.append("Au-dessus Bollinger sup")
    
    if score >= 40:
        signal = "BUY"
        confidence = min(50 + score, 95)
    elif score <= -40:
        signal = "SELL"
        confidence = min(50 + abs(score), 95)
    else:
        signal = "WAIT"
        confidence = 50 + abs(score) // 2
    
    entry = current_price
    if signal == "BUY":
        sl = round(entry - (atr_val * 1.5), 5)
        tp1 = round(entry + (atr_val * 2), 5)
        tp2 = round(entry + (atr_val * 3), 5)
        tp3 = round(entry + (atr_val * 4), 5)
    elif signal == "SELL":
        sl = round(entry + (atr_val * 1.5), 5)
        tp1 = round(entry - (atr_val * 2), 5)
        tp2 = round(entry - (atr_val * 3), 5)
        tp3 = round(entry - (atr_val * 4), 5)
    else:
        sl = None
        tp1 = None
        tp2 = None
        tp3 = None
    
    return {
        "signal": signal,
        "confidence": int(confidence),
        "trend": trend,
        "current_price": round(current_price, 5),
        "entry": round(entry, 5) if signal != "WAIT" else None,
        "stop_loss": sl,
        "take_profit_1": tp1,
        "take_profit_2": tp2,
        "take_profit_3": tp3,
        "risk_reward": 2.0 if signal != "WAIT" else None,
        "indicators": {
            "ema_20": round(float(ema_20), 5),
            "ema_50": round(float(ema_50), 5),
            "ema_100": round(float(ema_100), 5) if ema_100 else None,
            "rsi": round(float(rsi_val), 2),
            "macd": round(float(macd_val), 5),
            "macd_signal": round(float(macd_sig), 5),
            "atr": round(float(atr_val), 5),
            "bb_upper": round(float(bb_upper.iloc[-1]), 5),
            "bb_lower": round(float(bb_lower.iloc[-1]), 5)
        },
        "support_resistance": {
            "supports": [round(s, 5) for s in supports],
            "resistances": [round(r, 5) for r in resistances]
        },
        "reasons": reasons,
        "score": score,
        "smc": smc
    }


# ═══════════════════════════════════════════════
#              NEWS ANALYSIS
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
    bs = 0
    br = 0
    for w in bull_words:
        if w in t:
            bs += 1
    for w in bear_words:
        if w in t:
            br += 1
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
            
            title_text = ""
            if title_elem is not None and title_elem.text:
                title_text = title_elem.text
            
            desc_text = ""
            if desc_elem is not None and desc_elem.text:
                desc_text = clean_html_text(desc_elem.text)
            
            link_text = ""
            if link_elem is not None and link_elem.text:
                link_text = link_elem.text
            
            pub_date = ""
            if date_elem is not None and date_elem.text:
                pub_date = date_elem.text
            
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
        print("RSS error:", e)
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
        print("Cal error:", e)
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


def analyze_news_impact(asset, news_list):
    currencies = ASSET_CURRENCIES.get(asset, [])
    base, quote = ASSET_BASE_QUOTE.get(asset, (None, None))
    
    empty = {
        "score": 0,
        "direction": "NEUTRAL",
        "count": 0,
        "bullish_count": 0,
        "bearish_count": 0,
        "high_impact_count": 0
    }
    
    if not currencies:
        return empty
    
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
    
    if net > 3:
        direction = "BULLISH"
    elif net < -3:
        direction = "BEARISH"
    else:
        direction = "NEUTRAL"
    
    return {
        "score": net,
        "direction": direction,
        "count": len(relevant),
        "bullish_count": bullish,
        "bearish_count": bearish,
        "high_impact_count": high_impact
    }


def analyze_calendar_impact(asset, upcoming_events):
    currencies = ASSET_CURRENCIES.get(asset, [])
    relevant = []
    for e in upcoming_events:
        if e.get("currency") in currencies:
            relevant.append(e)
    
    imminent = []
    upcoming_h = []
    for e in relevant:
        hours = e.get("hours_until", 999)
        imp = e.get("impact", "").upper()
        is_high = "HIGH" in imp or "ELEV" in imp
        if hours <= 2 and is_high:
            imminent.append(e)
        elif 2 < hours <= 12 and is_high:
            upcoming_h.append(e)
    
    if imminent:
        risk = "HIGH"
    elif upcoming_h:
        risk = "MEDIUM"
    else:
        risk = "LOW"
    
    return {
        "total_events": len(relevant),
        "imminent_high_impact": len(imminent),
        "upcoming_high_impact": len(upcoming_h),
        "risk_level": risk,
        "next_events": relevant[:3]
    }


def get_ai_analysis(asset, technical, news_impact, calendar_impact, news_titles, smc_data):
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
    
    ts_bucket = int(datetime.utcnow().timestamp() // AI_CACHE_DURATION)
    cache_key = asset + "_" + str(technical.get('signal')) + "_" + str(ts_bucket)
    
    if cache_key in AI_CACHE:
        return AI_CACHE[cache_key]
    
    display_name = ASSETS.get(asset, asset)
    
    smc_dir = smc_data.get('smc_direction', 'N/A') if smc_data else 'N/A'
    smc_scr = smc_data.get('smc_score', 0) if smc_data else 0
    
    prompt = "Tu es analyste Forex. Reponds UNIQUEMENT en JSON valide, rien d'autre.\n\n"
    prompt += "Actif: " + display_name + "\n"
    prompt += "Signal technique: " + str(technical.get('signal', 'N/A')) + " (confiance " + str(technical.get('confidence', 0)) + "%)\n"
    prompt += "Tendance: " + str(technical.get('trend', 'N/A')) + "\n"
    prompt += "RSI: " + str(technical.get('indicators', {}).get('rsi', 'N/A')) + "\n"
    prompt += "SMC direction: " + str(smc_dir) + " (score " + str(smc_scr) + ")\n"
    prompt += "News direction: " + str(news_impact.get('direction', 'N/A')) + " (" + str(news_impact.get('bullish_count', 0)) + " bull, " + str(news_impact.get('bearish_count', 0)) + " bear)\n"
    prompt += "Evenements imminents: " + str(calendar_impact.get('imminent_high_impact', 0)) + "\n"
    prompt += "Risque calendrier: " + str(calendar_impact.get('risk_level', 'LOW')) + "\n\n"
    prompt += "Reponds SEULEMENT ce JSON (en francais, sans markdown, sans texte avant/apres):\n"
    prompt += '{"summary":"analyse en 2 phrases","sentiment":"bullish ou bearish ou neutral","confidence_adjustment":5,"key_risks":["risque1","risque2"],"recommendation":"reco courte","invalidation_scenario":"scenario invalidation"}'
    
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
            default["summary"] = "Reponse IA sans JSON"
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
        default["summary"] = "Reponse IA non parseable"
        return default

# ═══════════════════════════════════════════════
#         MOTEUR DE FUSION SMART SIGNAL
# ═══════════════════════════════════════════════

def generate_smart_signal(asset, main_tf="1h", confirmation_tf=None):
    symbol = ASSETS.get(asset)
    if not symbol:
        return {"error": "Actif inconnu"}
    
    if confirmation_tf is None:
        confirmation_tf = CONFIRMATION_MAP.get(main_tf, "4h")
    
    if main_tf not in TIMEFRAMES:
        return {"error": "Timeframe principal invalide"}
    if confirmation_tf not in TIMEFRAMES:
        return {"error": "Timeframe de confirmation invalide"}
    
    tech_main = analyze_asset(symbol, TIMEFRAMES[main_tf])
    tech_conf = analyze_asset(symbol, TIMEFRAMES[confirmation_tf])
    
    if not tech_main:
        return {"error": "Analyse impossible"}
    
    confirmation_ok = False
    if tech_conf and tech_main["signal"] == tech_conf["signal"] and tech_main["signal"] != "WAIT":
        confirmation_ok = True
    
    smc_main = tech_main.get("smc")
    smc_conf = tech_conf.get("smc") if tech_conf else None
    
    smc_confirmed = False
    if smc_main and smc_conf:
        if smc_main["smc_direction"] == smc_conf["smc_direction"] and smc_main["smc_direction"] != "neutral":
            smc_confirmed = True
    
    all_news = get_cached_news()
    news_impact = analyze_news_impact(asset, all_news)
    
    currencies = ASSET_CURRENCIES.get(asset, [])
    upcoming = get_upcoming_events(24, currencies)
    calendar_impact = analyze_calendar_impact(asset, upcoming)
    
    news_titles = []
    for n in all_news:
        news_curr = n.get("currencies", [])
        for c in currencies:
            if c in news_curr:
                news_titles.append(n["title"])
                break
        if len(news_titles) >= 5:
            break
    
    ai_analysis = get_ai_analysis(asset, tech_main, news_impact, calendar_impact, news_titles, smc_main)
    
    smc_score_raw = smc_main.get("smc_score", 0) if smc_main else 0
    smc_score_normalized = 50 + (smc_score_raw / 2)
    smc_score_normalized = max(0, min(100, smc_score_normalized))
    if smc_confirmed:
        smc_score_normalized = min(smc_score_normalized + 15, 95)
    
    tech_score = tech_main["confidence"]
    if confirmation_ok:
        tech_score = min(tech_score + 10, 95)
    
    smc_direction = smc_main.get("smc_direction", "neutral") if smc_main else "neutral"
    news_dir = news_impact["direction"]
    
    if (smc_direction == "bullish" and news_dir == "BULLISH") or (smc_direction == "bearish" and news_dir == "BEARISH"):
        news_match = 100
    elif news_dir == "NEUTRAL":
        news_match = 50
    else:
        news_match = 20
    
    if calendar_impact["risk_level"] == "HIGH":
        cal_score = 20
    elif calendar_impact["risk_level"] == "MEDIUM":
        cal_score = 60
    else:
        cal_score = 90
    
    sent_score = 50
    if news_impact["bullish_count"] > news_impact["bearish_count"]:
        sent_score = 75 if smc_direction == "bullish" else 25
    elif news_impact["bearish_count"] > news_impact["bullish_count"]:
        sent_score = 75 if smc_direction == "bearish" else 25
    
    ai_score = 50 + ai_analysis.get("confidence_adjustment", 0) * 3
    ai_score = max(0, min(100, ai_score))
    
    final_conf = int(round(
        smc_score_normalized * 0.35 +
        tech_score * 0.20 +
        news_match * 0.20 +
        cal_score * 0.10 +
        sent_score * 0.08 +
        ai_score * 0.07
    ))
    
    final_signal = "WAIT"
    warnings = []
    
    if smc_direction == "bullish" and tech_main["signal"] in ["BUY", "WAIT"]:
        final_signal = "BUY"
    elif smc_direction == "bearish" and tech_main["signal"] in ["SELL", "WAIT"]:
        final_signal = "SELL"
    elif tech_main["signal"] == "BUY" and smc_direction != "bearish":
        final_signal = "BUY"
    elif tech_main["signal"] == "SELL" and smc_direction != "bullish":
        final_signal = "SELL"
    else:
        final_signal = "WAIT"
        warnings.append("Conflit entre SMC et Technique")
    
    if calendar_impact["imminent_high_impact"] > 0:
        final_signal = "WAIT"
        warnings.append(str(calendar_impact['imminent_high_impact']) + " evenement(s) imminent(s)")
    
    if news_match == 20 and news_impact["high_impact_count"] >= 2:
        final_conf = max(final_conf - 25, 40)
        warnings.append("News contradictoires avec SMC")
    
    if final_conf < 60:
        final_signal = "WAIT"
    
    risk_level = "LOW"
    if calendar_impact["risk_level"] == "HIGH":
        risk_level = "HIGH"
    elif calendar_impact["risk_level"] == "MEDIUM" or news_impact["high_impact_count"] >= 2:
        risk_level = "MEDIUM"
    elif not smc_confirmed and not confirmation_ok:
        risk_level = "MEDIUM"
    
    result = {
        "asset": asset,
        "symbol": symbol,
        "timestamp": datetime.utcnow().isoformat(),
        "main_timeframe": main_tf,
        "confirmation_timeframe": confirmation_tf,
        "final_signal": final_signal,
        "final_confidence": final_conf,
        "risk_level": risk_level,
        "h4_confirmed": confirmation_ok,
        "smc_confirmed": smc_confirmed,
        "warnings": warnings,
        "current_price": tech_main["current_price"],
        "entry": tech_main["entry"] if final_signal != "WAIT" else None,
        "stop_loss": tech_main["stop_loss"] if final_signal != "WAIT" else None,
        "take_profit_1": tech_main["take_profit_1"] if final_signal != "WAIT" else None,
        "take_profit_2": tech_main["take_profit_2"] if final_signal != "WAIT" else None,
        "take_profit_3": tech_main["take_profit_3"] if final_signal != "WAIT" else None,
        "risk_reward": tech_main["risk_reward"] if final_signal != "WAIT" else None,
        "scores": {
            "smc": int(smc_score_normalized),
            "technical": int(tech_score),
            "news": int(news_match),
            "calendar": int(cal_score),
            "sentiment": int(sent_score),
            "ai": int(ai_score),
            "final": final_conf
        },
        "technical_analysis": {
            "trend": tech_main["trend"],
            "reasons": tech_main["reasons"],
            "indicators": tech_main["indicators"],
            "support_resistance": tech_main["support_resistance"],
            "main_signal": tech_main["signal"],
            "confirmation_signal": tech_conf["signal"] if tech_conf else "N/A"
        },
        "smc_analysis": {
            "direction": smc_direction,
            "score": smc_score_raw,
            "signals": smc_main.get("smc_signals", []) if smc_main else [],
            "market_structure": smc_main.get("market_structure") if smc_main else None,
            "bos": smc_main.get("bos") if smc_main else None,
            "choch": smc_main.get("choch") if smc_main else None,
            "order_blocks": smc_main.get("order_blocks") if smc_main else None,
            "breaker_blocks": smc_main.get("breaker_blocks") if smc_main else None,
            "fvg": smc_main.get("fvg") if smc_main else None,
            "liquidity_zones": smc_main.get("liquidity_zones") if smc_main else None,
            "liquidity_sweep": smc_main.get("liquidity_sweep") if smc_main else None,
            "premium_discount": smc_main.get("premium_discount") if smc_main else None
        },
        "news_analysis": {
            "direction": news_impact["direction"],
            "count": news_impact["count"],
            "bullish_count": news_impact["bullish_count"],
            "bearish_count": news_impact["bearish_count"],
            "high_impact_count": news_impact["high_impact_count"],
            "top_titles": news_titles
        },
        "calendar_analysis": {
            "risk_level": calendar_impact["risk_level"],
            "imminent_high_impact": calendar_impact["imminent_high_impact"],
            "upcoming_high_impact": calendar_impact["upcoming_high_impact"],
            "next_events": calendar_impact["next_events"]
        },
        "ai_analysis": ai_analysis
    }
    
    return result


# ═══════════════════════════════════════════════
#      SCHEDULER NOTIFICATIONS AUTOMATIQUES
# ═══════════════════════════════════════════════

def send_signal_to_users(asset, signal_data):
    """Envoie une notification à tous les users qui ont activé les notifs"""
    db = SessionLocal()
    try:
        users = db.query(User).filter(
            User.notifications_enabled == True,
            User.fcm_token != ""
        ).all()
        
        signal_type = signal_data.get("final_signal", "WAIT")
        confidence = signal_data.get("final_confidence", 0)
        signal_key = f"{asset}_{signal_type}_{confidence}_{int(time.time() // 3600)}"
        
        display_name = ASSETS.get(asset, asset)
        
        for user in users:
            # Vérifier si confiance suffisante pour cet user
            if confidence < user.min_confidence:
                continue
            
            # Vérifier si déjà notifié dans la dernière heure
            existing = db.query(SignalNotification).filter(
                SignalNotification.user_id == user.id,
                SignalNotification.signal_key == signal_key
            ).first()
            
            if existing:
                continue
            
            # Envoyer la notification
            signal_emoji = "🟢" if signal_type == "BUY" else "🔴"
            signal_text = "ACHAT" if signal_type == "BUY" else "VENTE"
            
            title = f"{signal_emoji} {signal_text} {display_name} - {confidence}%"
            body = f"Entrée: {signal_data.get('entry')} | SL: {signal_data.get('stop_loss')} | TP: {signal_data.get('take_profit_1')}"
            
            data = {
                "asset": asset,
                "signal": signal_type,
                "confidence": str(confidence),
                "entry": str(signal_data.get("entry", "")),
                "stop_loss": str(signal_data.get("stop_loss", "")),
                "take_profit": str(signal_data.get("take_profit_1", ""))
            }
            
            success = send_push_notification(user.fcm_token, title, body, data)
            
            if success:
                # Enregistrer la notification pour éviter doublons
                notif = SignalNotification(
                    user_id=user.id,
                    asset=asset,
                    signal_type=signal_type,
                    confidence=confidence,
                    signal_key=signal_key
                )
                db.add(notif)
        
        db.commit()
    except Exception as e:
        print(f"Erreur send_signal_to_users: {e}")
        db.rollback()
    finally:
        db.close()


def scheduler_analyze_and_notify():
    """Analyse continue toutes les 5 minutes et envoie notifications"""
    while True:
        try:
            time.sleep(300)  # 5 minutes
            
            print(f"[{datetime.utcnow()}] Scheduler: analyse automatique...")
            
            for asset in ASSETS.keys():
                try:
                    result = generate_smart_signal(asset, "1h", "4h")
                    
                    if isinstance(result, dict) and result.get("final_signal") in ["BUY", "SELL"]:
                        conf = result.get("final_confidence", 0)
                        if conf >= 70:
                            print(f"Signal detecte {asset}: {result['final_signal']} ({conf}%)")
                            send_signal_to_users(asset, result)
                except Exception as e:
                    print(f"Erreur scheduler pour {asset}: {e}")
            
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
                print(f"Erreur nettoyage: {e}")
                
        except Exception as e:
            print(f"Erreur scheduler global: {e}")


# Démarrer le scheduler en arrière-plan
scheduler_thread = threading.Thread(target=scheduler_analyze_and_notify, daemon=True)
scheduler_thread.start()
print("Scheduler notifications demarre (5 min interval)")


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
#              ENDPOINTS PUBLICS
# ═══════════════════════════════════════════════

@app.get("/")
async def root():
    return {
        "status": "online",
        "message": "TradeVision AI - Multi-Users",
        "version": "8.0.0",
        "ai_provider": "OpenRouter",
        "ai_configured": bool(OPENROUTER_API_KEY),
        "active_model": ACTIVE_MODEL or "not_tested_yet",
        "firebase_configured": bool(FIREBASE_APP),
        "database_connected": True,
        "features": [
            "User Authentication (JWT)",
            "PostgreSQL Database",
            "Firebase Push Notifications",
            "Auto Scheduler (5 min)",
            "Technical Analysis",
            "Smart Money Concepts",
            "Multi-Timeframes",
            "AI Analysis"
        ]
    }


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "twelve_data_configured": bool(API_KEY),
        "openrouter_configured": bool(OPENROUTER_API_KEY),
        "firebase_configured": bool(FIREBASE_APP),
        "active_model": ACTIVE_MODEL or "not_tested_yet",
        "news_cached": bool(NEWS_CACHE["data"]),
        "calendar_cached": bool(CALENDAR_CACHE["data"])
    }


# ═══════════════════════════════════════════════
#              AUTHENTIFICATION
# ═══════════════════════════════════════════════

@app.post("/api/v1/auth/register", response_model=TokenResponse)
async def register(user_data: UserRegister, db: Session = Depends(get_db)):
    """Créer un nouveau compte"""
    
    # Validation
    if len(user_data.username) < 3:
        raise HTTPException(status_code=400, detail="Nom d'utilisateur trop court (min 3 caracteres)")
    
    if len(user_data.password) < 4:
        raise HTTPException(status_code=400, detail="Mot de passe trop court (min 4 caracteres)")
    
    # Vérifier si username existe déjà
    existing = db.query(User).filter(User.username == user_data.username).first()
    if existing:
        raise HTTPException(status_code=400, detail="Ce nom d'utilisateur existe deja")
    
    # Créer l'utilisateur
    hashed_pwd = hash_password(user_data.password)
    new_user = User(
        username=user_data.username,
        password_hash=hashed_pwd
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    # Créer le token JWT
    access_token = create_access_token(data={"sub": new_user.username})
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "username": new_user.username
    }


@app.post("/api/v1/auth/login", response_model=TokenResponse)
async def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    """Se connecter"""
    user = db.query(User).filter(User.username == form_data.username).first()
    
    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Nom d'utilisateur ou mot de passe incorrect"
        )
    
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Compte desactive")
    
    access_token = create_access_token(data={"sub": user.username})
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "username": user.username
    }


@app.post("/api/v1/auth/login-simple", response_model=TokenResponse)
async def login_simple(user_data: UserLogin, db: Session = Depends(get_db)):
    """Login simple avec JSON (pour l'app Android)"""
    user = db.query(User).filter(User.username == user_data.username).first()
    
    if not user or not verify_password(user_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Nom d'utilisateur ou mot de passe incorrect"
        )
    
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Compte desactive")
    
    access_token = create_access_token(data={"sub": user.username})
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "username": user.username
    }


@app.get("/api/v1/auth/me")
async def get_me(current_user: User = Depends(get_current_user)):
    """Récupère les infos du user connecté"""
    return {
        "id": current_user.id,
        "username": current_user.username,
        "created_at": current_user.created_at.isoformat() if current_user.created_at else None,
        "is_admin": current_user.is_admin,
        "settings": {
            "main_timeframe": current_user.main_timeframe,
            "confirmation_timeframe": current_user.confirmation_timeframe,
            "auto_confirmation": current_user.auto_confirmation,
            "min_confidence": current_user.min_confidence,
            "notifications_enabled": current_user.notifications_enabled,
            "refresh_interval": current_user.refresh_interval
        }
    }


# ═══════════════════════════════════════════════
#              PARAMETRES UTILISATEUR
# ═══════════════════════════════════════════════

@app.put("/api/v1/user/settings")
async def update_settings(
    settings: UserSettingsUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Met à jour les paramètres de l'utilisateur"""
    if settings.main_timeframe is not None:
        if settings.main_timeframe in TIMEFRAMES:
            current_user.main_timeframe = settings.main_timeframe
    
    if settings.confirmation_timeframe is not None:
        if settings.confirmation_timeframe in TIMEFRAMES:
            current_user.confirmation_timeframe = settings.confirmation_timeframe
    
    if settings.auto_confirmation is not None:
        current_user.auto_confirmation = settings.auto_confirmation
    
    if settings.min_confidence is not None:
        if 60 <= settings.min_confidence <= 95:
            current_user.min_confidence = settings.min_confidence
    
    if settings.notifications_enabled is not None:
        current_user.notifications_enabled = settings.notifications_enabled
    
    if settings.refresh_interval is not None:
        if settings.refresh_interval in [5, 10, 15, 30]:
            current_user.refresh_interval = settings.refresh_interval
    
    db.commit()
    db.refresh(current_user)
    
    return {
        "message": "Parametres mis a jour",
        "settings": {
            "main_timeframe": current_user.main_timeframe,
            "confirmation_timeframe": current_user.confirmation_timeframe,
            "auto_confirmation": current_user.auto_confirmation,
            "min_confidence": current_user.min_confidence,
            "notifications_enabled": current_user.notifications_enabled,
            "refresh_interval": current_user.refresh_interval
        }
    }


@app.post("/api/v1/user/fcm-token")
async def update_fcm_token(
    token_data: FCMTokenUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Enregistre le FCM token pour recevoir les notifications"""
    current_user.fcm_token = token_data.fcm_token
    db.commit()
    return {"message": "FCM token enregistre avec succes"}


@app.get("/api/v1/user/stats")
async def get_user_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Statistiques des notifications reçues par le user"""
    total = db.query(SignalNotification).filter(
        SignalNotification.user_id == current_user.id
    ).count()
    
    week_ago = datetime.utcnow() - timedelta(days=7)
    last_week = db.query(SignalNotification).filter(
        SignalNotification.user_id == current_user.id,
        SignalNotification.sent_at >= week_ago
    ).count()
    
    return {
        "total_notifications": total,
        "last_7_days": last_week
    }


# ═══════════════════════════════════════════════
#              ENDPOINTS TRADING
# ═══════════════════════════════════════════════

@app.get("/api/v1/timeframes")
async def get_timeframes():
    return {
        "timeframes": list(TIMEFRAMES.keys()),
        "confirmation_map": CONFIRMATION_MAP,
        "descriptions": {
            "15m": "15 minutes (scalping court)",
            "30m": "30 minutes (scalping)",
            "1h": "1 heure (intraday)",
            "2h": "2 heures (intraday long)",
            "4h": "4 heures (swing)",
            "1d": "1 jour (position)"
        }
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


@app.get("/api/v1/signals")
async def get_signals(
    min_confidence: int = 70,
    main_tf: str = "1h",
    confirmation_tf: str = None
):
    """Signaux publics (pour compatibilité)"""
    signals = {}
    
    for asset in ASSETS.keys():
        try:
            result = generate_smart_signal(asset, main_tf, confirmation_tf)
            
            if result.get("final_signal") != "WAIT" and result.get("final_confidence", 0) >= min_confidence:
                signals[asset] = {
                    "status": "ok",
                    "signal": result["final_signal"],
                    "confidence": result["final_confidence"],
                    "trend": result["technical_analysis"]["trend"],
                    "current_price": result["current_price"],
                    "entry": result["entry"],
                    "stop_loss": result["stop_loss"],
                    "take_profit_1": result["take_profit_1"],
                    "take_profit_2": result["take_profit_2"],
                    "take_profit_3": result["take_profit_3"],
                    "risk_reward": result["risk_reward"],
                    "h4_confirmed": result["h4_confirmed"],
                    "smc_confirmed": result["smc_confirmed"],
                    "risk_level": result["risk_level"],
                    "reasons": result["technical_analysis"]["reasons"],
                    "warnings": result["warnings"],
                    "scores": result["scores"],
                    "ai_summary": result["ai_analysis"].get("summary", ""),
                    "smc_signals": result["smc_analysis"]["signals"],
                    "main_timeframe": result["main_timeframe"],
                    "confirmation_timeframe": result["confirmation_timeframe"]
                }
            else:
                signals[asset] = {
                    "status": "wait",
                    "signal": "WAIT",
                    "confidence": result.get("final_confidence", 0),
                    "reason": "Confiance insuffisante",
                    "warnings": result.get("warnings", [])
                }
        except Exception as e:
            signals[asset] = {"status": "error", "signal": "WAIT", "error": str(e)}
    
    return {
        "timestamp": datetime.utcnow().isoformat(),
        "min_confidence": min_confidence,
        "main_timeframe": main_tf,
        "confirmation_timeframe": confirmation_tf or CONFIRMATION_MAP.get(main_tf, "4h"),
        "signals": signals
    }


@app.get("/api/v1/user/signals")
async def get_user_signals(current_user: User = Depends(get_current_user)):
    """Signaux personnalisés selon les paramètres de l'utilisateur"""
    main_tf = current_user.main_timeframe
    confirm_tf = current_user.confirmation_timeframe if not current_user.auto_confirmation else CONFIRMATION_MAP.get(main_tf, "4h")
    min_conf = current_user.min_confidence
    
    signals = {}
    
    for asset in ASSETS.keys():
        try:
            result = generate_smart_signal(asset, main_tf, confirm_tf)
            
            if result.get("final_signal") != "WAIT" and result.get("final_confidence", 0) >= min_conf:
                signals[asset] = {
                    "status": "ok",
                    "signal": result["final_signal"],
                    "confidence": result["final_confidence"],
                    "trend": result["technical_analysis"]["trend"],
                    "current_price": result["current_price"],
                    "entry": result["entry"],
                    "stop_loss": result["stop_loss"],
                    "take_profit_1": result["take_profit_1"],
                    "take_profit_2": result["take_profit_2"],
                    "take_profit_3": result["take_profit_3"],
                    "risk_reward": result["risk_reward"],
                    "h4_confirmed": result["h4_confirmed"],
                    "smc_confirmed": result["smc_confirmed"],
                    "risk_level": result["risk_level"],
                    "reasons": result["technical_analysis"]["reasons"],
                    "warnings": result["warnings"],
                    "scores": result["scores"],
                    "ai_summary": result["ai_analysis"].get("summary", ""),
                    "smc_signals": result["smc_analysis"]["signals"],
                    "main_timeframe": result["main_timeframe"],
                    "confirmation_timeframe": result["confirmation_timeframe"]
                }
            else:
                signals[asset] = {
                    "status": "wait",
                    "signal": "WAIT",
                    "confidence": result.get("final_confidence", 0),
                    "reason": "Confiance insuffisante",
                    "warnings": result.get("warnings", [])
                }
        except Exception as e:
            signals[asset] = {"status": "error", "signal": "WAIT", "error": str(e)}
    
    return {
        "timestamp": datetime.utcnow().isoformat(),
        "username": current_user.username,
        "min_confidence": min_conf,
        "main_timeframe": main_tf,
        "confirmation_timeframe": confirm_tf,
        "signals": signals
    }


@app.get("/api/v1/smart-analysis/{asset}")
async def smart_analysis(asset: str, main_tf: str = "1h", confirmation_tf: str = None):
    asset = asset.upper()
    if asset not in ASSETS:
        raise HTTPException(status_code=404, detail="Asset not found")
    return generate_smart_signal(asset, main_tf, confirmation_tf)


@app.get("/api/v1/analyze/{asset}")
async def analyze_endpoint(asset: str, timeframe: str = "1h"):
    asset = asset.upper()
    if asset not in ASSETS:
        raise HTTPException(status_code=404, detail="Asset not found")
    if timeframe not in TIMEFRAMES:
        raise HTTPException(status_code=400, detail="Invalid timeframe")
    result = analyze_asset(ASSETS[asset], TIMEFRAMES[timeframe])
    if result is None:
        raise HTTPException(status_code=503, detail="Analysis failed")
    return {"asset": asset, "symbol": ASSETS[asset], "timeframe": timeframe, "timestamp": datetime.utcnow().isoformat(), **result}


@app.get("/api/v1/smc/{asset}")
async def get_smc_only(asset: str, timeframe: str = "1h"):
    asset = asset.upper()
    if asset not in ASSETS:
        raise HTTPException(status_code=404, detail="Asset not found")
    if timeframe not in TIMEFRAMES:
        raise HTTPException(status_code=400, detail="Invalid timeframe")
    
    df = get_candles_df(ASSETS[asset], TIMEFRAMES[timeframe], limit=100)
    if df is None:
        raise HTTPException(status_code=503, detail="No data")
    
    smc = analyze_smc(df)
    if smc is None:
        raise HTTPException(status_code=503, detail="SMC analysis failed")
    
    return {
        "asset": asset,
        "symbol": ASSETS[asset],
        "timeframe": timeframe,
        "timestamp": datetime.utcnow().isoformat(),
        **smc
    }


@app.get("/api/v1/candles/{asset}")
async def get_candles(asset: str, timeframe: str = "1h", limit: int = 100):
    asset = asset.upper()
    if asset not in ASSETS:
        raise HTTPException(status_code=404, detail="Asset not found")
    if timeframe not in TIMEFRAMES:
        raise HTTPException(status_code=400, detail="Invalid timeframe")
    data = td_request("time_series", {"symbol": ASSETS[asset], "interval": TIMEFRAMES[timeframe], "outputsize": limit})
    if not data or "values" not in data:
        raise HTTPException(status_code=503, detail="No data")
    values = list(reversed(data["values"]))
    candles = []
    for v in values:
        candles.append({
            "time": v["datetime"],
            "open": float(v["open"]),
            "high": float(v["high"]),
            "low": float(v["low"]),
            "close": float(v["close"]),
            "volume": float(v.get("volume", 0))
        })
    return {"asset": asset, "timeframe": timeframe, "count": len(candles), "candles": candles}


@app.get("/api/v1/news")
async def get_news(limit: int = 20, currency: str = None):
    all_news = get_cached_news()
    if currency:
        currency = currency.upper()
        filtered = []
        for n in all_news:
            if currency in n["currencies"]:
                filtered.append(n)
        all_news = filtered
    all_news = all_news[:limit]
    return {"timestamp": datetime.utcnow().isoformat(), "count": len(all_news), "news": all_news, "cached": True}


@app.get("/api/v1/calendar")
async def get_calendar(currency: str = None, impact: str = None):
    events = get_cached_calendar()
    if currency:
        currency = currency.upper()
        filtered = []
        for e in events:
            if e["currency"] == currency:
                filtered.append(e)
        events = filtered
    if impact:
        impact = impact.upper()
        filtered = []
        for e in events:
            if impact in e["impact"].upper():
                filtered.append(e)
        events = filtered
    return {"timestamp": datetime.utcnow().isoformat(), "count": len(events), "events": events, "cached": True}


# ═══════════════════════════════════════════════
#              ADMIN (Debug)
# ═══════════════════════════════════════════════

@app.get("/api/v1/admin/users-count")
async def admin_users_count(db: Session = Depends(get_db)):
    """Nombre d'utilisateurs (public pour debug)"""
    total = db.query(User).count()
    with_fcm = db.query(User).filter(User.fcm_token != "").count()
    notifs_enabled = db.query(User).filter(User.notifications_enabled == True).count()
    return {
        "total_users": total,
        "users_with_fcm": with_fcm,
        "notifications_enabled": notifs_enabled
    }


@app.post("/api/v1/admin/test-notification")
async def admin_test_notification(current_user: User = Depends(get_current_user)):
    """Envoie une notification de test au user connecté"""
    if not current_user.fcm_token:
        raise HTTPException(status_code=400, detail="Aucun FCM token enregistre")
    
    success = send_push_notification(
        current_user.fcm_token,
        "🧪 Test TradeVision AI",
        "Ceci est une notification de test. Si tu vois ça, tout fonctionne !",
        {"type": "test"}
    )
    
    if success:
        return {"message": "Notification envoyee avec succes"}
    else:
        raise HTTPException(status_code=500, detail="Echec envoi notification")
