from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import requests
import os
import pandas as pd
import numpy as np
from datetime import datetime

app = FastAPI(
    title="Trading Assistant API",
    version="3.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Configuration ──────────────────────────────────────────
API_KEY = os.getenv("TWELVE_DATA_API_KEY", "")
BASE_URL = "https://api.twelvedata.com"

ASSETS = {
    "EURUSD": "EUR/USD",
    "GBPUSD": "GBP/USD",
    "USDJPY": "USD/JPY",
    "XAUUSD": "XAU/USD"
}

TIMEFRAMES = {
    "1h": "1h",
    "4h": "4h",
    "1d": "1day"
}


# ─── Fonction Twelve Data ───────────────────────────────────
def td_request(endpoint: str, params: dict):
    params["apikey"] = API_KEY
    try:
        response = requests.get(f"{BASE_URL}/{endpoint}", params=params, timeout=10)
        return response.json()
    except Exception as e:
        print(f"❌ Erreur Twelve Data: {e}")
        return None


def get_candles_df(symbol: str, interval: str, limit: int = 200):
    """Récupère les bougies sous forme de DataFrame pandas"""
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


# ─── Indicateurs techniques ─────────────────────────────────
def ema(series, period):
    """Exponential Moving Average"""
    return series.ewm(span=period, adjust=False).mean()


def rsi(series, period=14):
    """Relative Strength Index"""
    delta = series.diff()
    gain = delta.where(delta > 0, 0).rolling(window=period).mean()
    loss = -delta.where(delta < 0, 0).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


def macd(series, fast=12, slow=26, signal=9):
    """MACD"""
    ema_fast = ema(series, fast)
    ema_slow = ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def atr(df, period=14):
    """Average True Range (volatilité)"""
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift()).abs()
    low_close = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()


def bollinger_bands(series, period=20, std=2):
    """Bandes de Bollinger"""
    sma = series.rolling(window=period).mean()
    std_dev = series.rolling(window=period).std()
    upper = sma + (std_dev * std)
    lower = sma - (std_dev * std)
    return upper, sma, lower


def find_support_resistance(df, window=20):
    """Détecte les supports et résistances"""
    highs = df["high"].rolling(window=window, center=True).max()
    lows = df["low"].rolling(window=window, center=True).min()
    
    resistances = df["high"][df["high"] == highs].dropna().tail(3).tolist()
    supports = df["low"][df["low"] == lows].dropna().tail(3).tolist()
    
    return supports, resistances


# ─── Analyse complète ───────────────────────────────────────
def analyze_asset(symbol: str, interval: str = "1h"):
    """Analyse technique complète d'un actif"""
    df = get_candles_df(symbol, interval, limit=200)
    
    if df is None or len(df) < 50:
        return None
    
    close = df["close"]
    current_price = float(close.iloc[-1])
    
    # Indicateurs
    ema_20 = ema(close, 20).iloc[-1]
    ema_50 = ema(close, 50).iloc[-1]
    ema_200 = ema(close, 200).iloc[-1] if len(close) >= 200 else None
    
    rsi_val = rsi(close, 14).iloc[-1]
    macd_line, signal_line, hist = macd(close)
    macd_val = macd_line.iloc[-1]
    macd_signal = signal_line.iloc[-1]
    macd_hist = hist.iloc[-1]
    
    atr_val = atr(df, 14).iloc[-1]
    bb_upper, bb_mid, bb_lower = bollinger_bands(close)
    
    supports, resistances = find_support_resistance(df)
    
    # ─── Détection de tendance ─────────────────
    trend = "neutral"
    if ema_200 and current_price > ema_50 > ema_200:
        trend = "bullish"
    elif ema_200 and current_price < ema_50 < ema_200:
        trend = "bearish"
    elif current_price > ema_20 > ema_50:
        trend = "bullish"
    elif current_price < ema_20 < ema_50:
        trend = "bearish"
    
    # ─── Score de signal ───────────────────────
    score = 0
    reasons = []
    
    # Tendance
    if trend == "bullish":
        score += 25
        reasons.append("Tendance haussière (EMA)")
    elif trend == "bearish":
        score -= 25
        reasons.append("Tendance baissière (EMA)")
    
    # RSI
    if rsi_val < 30:
        score += 20
        reasons.append(f"RSI en survente ({rsi_val:.1f})")
    elif rsi_val > 70:
        score -= 20
        reasons.append(f"RSI en surachat ({rsi_val:.1f})")
    elif 40 <= rsi_val <= 60:
        reasons.append(f"RSI neutre ({rsi_val:.1f})")
    
    # MACD
    if macd_val > macd_signal and macd_hist > 0:
        score += 20
        reasons.append("MACD haussier (croisement)")
    elif macd_val < macd_signal and macd_hist < 0:
        score -= 20
        reasons.append("MACD baissier (croisement)")
    
    # Bollinger
    if current_price < bb_lower.iloc[-1]:
        score += 15
        reasons.append("Prix sous la Bollinger inférieure")
    elif current_price > bb_upper.iloc[-1]:
        score -= 15
        reasons.append("Prix au-dessus de la Bollinger supérieure")
    
    # ─── Décision finale ───────────────────────
    if score >= 40:
        signal = "BUY"
        confidence = min(50 + score, 95)
    elif score <= -40:
        signal = "SELL"
        confidence = min(50 + abs(score), 95)
    else:
        signal = "WAIT"
        confidence = 50 + abs(score) // 2
    
    # ─── Calcul SL / TP (basé sur ATR) ─────────
    entry = current_price
    if signal == "BUY":
        stop_loss = round(entry - (atr_val * 1.5), 5)
        take_profit_1 = round(entry + (atr_val * 2), 5)
        take_profit_2 = round(entry + (atr_val * 3), 5)
        take_profit_3 = round(entry + (atr_val * 4), 5)
    elif signal == "SELL":
        stop_loss = round(entry + (atr_val * 1.5), 5)
        take_profit_1 = round(entry - (atr_val * 2), 5)
        take_profit_2 = round(entry - (atr_val * 3), 5)
        take_profit_3 = round(entry - (atr_val * 4), 5)
    else:
        stop_loss = take_profit_1 = take_profit_2 = take_profit_3 = None
    
    risk_reward = 2.0 if signal != "WAIT" else None
    
    return {
        "signal": signal,
        "confidence": int(confidence),
        "trend": trend,
        "current_price": round(current_price, 5),
        "entry": round(entry, 5) if signal != "WAIT" else None,
        "stop_loss": stop_loss,
        "take_profit_1": take_profit_1,
        "take_profit_2": take_profit_2,
        "take_profit_3": take_profit_3,
        "risk_reward": risk_reward,
        "indicators": {
            "ema_20": round(float(ema_20), 5),
            "ema_50": round(float(ema_50), 5),
            "ema_200": round(float(ema_200), 5) if ema_200 else None,
            "rsi": round(float(rsi_val), 2),
            "macd": round(float(macd_val), 5),
            "macd_signal": round(float(macd_signal), 5),
            "atr": round(float(atr_val), 5),
            "bb_upper": round(float(bb_upper.iloc[-1]), 5),
            "bb_lower": round(float(bb_lower.iloc[-1]), 5)
        },
        "support_resistance": {
            "supports": [round(s, 5) for s in supports],
            "resistances": [round(r, 5) for r in resistances]
        },
        "reasons": reasons,
        "score": score
    }


# ─── Endpoints ──────────────────────────────────────────────
@app.get("/")
async def root():
    return {
        "status": "online",
        "message": "Trading Assistant API is running 🚀",
        "version": "3.0.0",
        "data_provider": "Twelve Data",
        "features": ["prices", "candles", "technical_analysis", "signals"]
    }


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "api_key_configured": bool(API_KEY)
    }


@app.get("/api/v1/price/{asset}")
async def get_price(asset: str):
    asset = asset.upper()
    if asset not in ASSETS:
        raise HTTPException(status_code=404, detail="Asset not found")
    
    data = td_request("price", {"symbol": ASSETS[asset]})
    if not data or "price" not in data:
        raise HTTPException(status_code=503, detail=f"No data: {data}")
    
    return {
        "asset": asset,
        "price": float(data["price"]),
        "timestamp": datetime.utcnow().isoformat()
    }


@app.get("/api/v1/prices")
async def get_all_prices():
    prices = {}
    for name, symbol in ASSETS.items():
        data = td_request("price", {"symbol": symbol})
        if data and "price" in data:
            prices[name] = {"price": float(data["price"]), "status": "ok"}
        else:
            prices[name] = {"status": "error"}
    return {"timestamp": datetime.utcnow().isoformat(), "prices": prices}


@app.get("/api/v1/analyze/{asset}")
async def analyze(asset: str, timeframe: str = "1h"):
    """Analyse technique complète d'un actif"""
    asset = asset.upper()
    
    if asset not in ASSETS:
        raise HTTPException(status_code=404, detail="Asset not found")
    
    if timeframe not in TIMEFRAMES:
        raise HTTPException(status_code=400, detail="Invalid timeframe")
    
    result = analyze_asset(ASSETS[asset], TIMEFRAMES[timeframe])
    
    if result is None:
        raise HTTPException(status_code=503, detail="Analysis failed - not enough data")
    
    return {
        "asset": asset,
        "symbol": ASSETS[asset],
        "timeframe": timeframe,
        "timestamp": datetime.utcnow().isoformat(),
        **result
    }


@app.get("/api/v1/signals")
async def get_all_signals(min_confidence: int = 70):
    """Récupère les signaux pour tous les actifs (H1 + confirmation H4)"""
    signals = {}
    
    for name, symbol in ASSETS.items():
        # Analyse H1
        h1_result = analyze_asset(symbol, "1h")
        # Analyse H4 (confirmation)
        h4_result = analyze_asset(symbol, "4h")
        
        if h1_result is None:
            signals[name] = {"status": "error", "signal": "WAIT"}
            continue
        
        # Confirmation H4
        confirmed = False
        if h4_result:
            if h1_result["signal"] == h4_result["signal"] and h1_result["signal"] != "WAIT":
                confirmed = True
                # Bonus de confiance si H4 confirme
                h1_result["confidence"] = min(h1_result["confidence"] + 10, 95)
        
        # Filtrage par confiance
        if h1_result["signal"] != "WAIT" and h1_result["confidence"] >= min_confidence:
            signals[name] = {
                "status": "ok",
                "h4_confirmed": confirmed,
                **h1_result
            }
        else:
            signals[name] = {
                "status": "wait",
                "signal": "WAIT",
                "confidence": h1_result["confidence"],
                "reason": "Confiance insuffisante ou pas d'opportunité"
            }
    
    return {
        "timestamp": datetime.utcnow().isoformat(),
        "min_confidence": min_confidence,
        "signals": signals
    }


@app.get("/api/v1/candles/{asset}")
async def get_candles(asset: str, timeframe: str = "1h", limit: int = 100):
    asset = asset.upper()
    if asset not in ASSETS:
        raise HTTPException(status_code=404, detail="Asset not found")
    if timeframe not in TIMEFRAMES:
        raise HTTPException(status_code=400, detail="Invalid timeframe")
    
    data = td_request("time_series", {
        "symbol": ASSETS[asset],
        "interval": TIMEFRAMES[timeframe],
        "outputsize": limit
    })
    
    if not data or "values" not in data:
        raise HTTPException(status_code=503, detail="No data")
    
    values = list(reversed(data["values"]))
    candles = [{
        "time": v["datetime"],
        "open": float(v["open"]),
        "high": float(v["high"]),
        "low": float(v["low"]),
        "close": float(v["close"]),
        "volume": float(v.get("volume", 0))
    } for v in values]
    
    return {
        "asset": asset,
        "timeframe": timeframe,
        "count": len(candles),
        "candles": candles
    }
