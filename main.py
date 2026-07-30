from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import requests
import os
import pandas as pd
import numpy as np
import xml.etree.ElementTree as ET
from html import unescape
import re
from datetime import datetime, timedelta
import google.generativeai as genai

app = FastAPI(
    title="TradeVision AI API",
    version="5.0.0"
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
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
BASE_URL = "https://api.twelvedata.com"

# Configuration Gemini
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    GEMINI_MODEL = genai.GenerativeModel('gemini-1.5-flash')
else:
    GEMINI_MODEL = None

ASSETS = {
    "EURUSD": "EUR/USD",
    "GBPUSD": "GBP/USD",
    "USDJPY": "USD/JPY",
    "XAUUSD": "XAU/USD"
}

# Mapping actif → devises impliquées
ASSET_CURRENCIES = {
    "EURUSD": ["EUR", "USD"],
    "GBPUSD": ["GBP", "USD"],
    "USDJPY": ["USD", "JPY"],
    "XAUUSD": ["XAU", "USD"]
}

# Direction d'impact : si base fort → BUY, si quote fort → SELL
ASSET_BASE_QUOTE = {
    "EURUSD": ("EUR", "USD"),
    "GBPUSD": ("GBP", "USD"),
    "USDJPY": ("USD", "JPY"),
    "XAUUSD": ("XAU", "USD")
}

TIMEFRAMES = {
    "1h": "1h",
    "4h": "4h",
    "1d": "1day"
}

RSS_FEEDS = [
    "https://www.investing.com/rss/news_1.rss",
    "https://www.investing.com/rss/news_301.rss",
    "https://www.investing.com/rss/news_285.rss",
    "https://feeds.marketwatch.com/marketwatch/topstories/",
    "https://www.forexlive.com/feed",
]

ECONOMIC_CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

TRACKED_CURRENCIES = ["USD", "EUR", "GBP", "JPY", "XAU"]

# Cache simple pour éviter trop d'appels Gemini
GEMINI_CACHE = {}
CACHE_DURATION = 900  # 15 minutes


# ─── Fonction Twelve Data ───────────────────────────────────
def td_request(endpoint: str, params: dict):
    params["apikey"] = API_KEY
    try:
        response = requests.get(f"{BASE_URL}/{endpoint}", params=params, timeout=10)
        return response.json()
    except Exception as e:
        print(f"❌ Erreur Twelve Data: {e}")
        return None


def get_candles_df(symbol: str, interval: str, limit: int = 100):
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
    return series.ewm(span=period, adjust=False).mean()


def rsi(series, period=14):
    delta = series.diff()
    gain = delta.where(delta > 0, 0).rolling(window=period).mean()
    loss = -delta.where(delta < 0, 0).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


def macd(series, fast=12, slow=26, signal=9):
    ema_fast = ema(series, fast)
    ema_slow = ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = ema(macd_line, signal)
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


def analyze_asset(symbol: str, interval: str = "1h"):
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
    macd_signal = signal_line.iloc[-1]
    macd_hist = hist.iloc[-1]
    
    atr_val = atr(df, 14).iloc[-1]
    bb_upper, bb_mid, bb_lower = bollinger_bands(close)
    
    supports, resistances = find_support_resistance(df)
    
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
        reasons.append("Tendance haussière (EMA)")
    elif trend == "bearish":
        score -= 25
        reasons.append("Tendance baissière (EMA)")
    
    if rsi_val < 30:
        score += 20
        reasons.append(f"RSI en survente ({rsi_val:.1f})")
    elif rsi_val > 70:
        score -= 20
        reasons.append(f"RSI en surachat ({rsi_val:.1f})")
    elif 40 <= rsi_val <= 60:
        reasons.append(f"RSI neutre ({rsi_val:.1f})")
    
    if macd_val > macd_signal and macd_hist > 0:
        score += 20
        reasons.append("MACD haussier (croisement)")
    elif macd_val < macd_signal and macd_hist < 0:
        score -= 20
        reasons.append("MACD baissier (croisement)")
    
    if current_price < bb_lower.iloc[-1]:
        score += 15
        reasons.append("Prix sous la Bollinger inférieure")
    elif current_price > bb_upper.iloc[-1]:
        score -= 15
        reasons.append("Prix au-dessus de la Bollinger supérieure")
    
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
            "ema_100": round(float(ema_100), 5) if ema_100 else None,
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


# ─── Actualités (RSS) ───────────────────────────────────────
def clean_html(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r'<[^>]+>', '', text)
    text = unescape(text)
    return text.strip()


def detect_currency(text: str) -> list:
    currencies = []
    text_upper = text.upper()
    
    if "EUR" in text_upper or "EURO" in text_upper or "ECB" in text_upper or "BCE" in text_upper:
        currencies.append("EUR")
    if "USD" in text_upper or "DOLLAR" in text_upper or "FED" in text_upper or "FOMC" in text_upper:
        currencies.append("USD")
    if "GBP" in text_upper or "POUND" in text_upper or "STERLING" in text_upper or "BOE" in text_upper:
        currencies.append("GBP")
    if "JPY" in text_upper or "YEN" in text_upper or "BOJ" in text_upper:
        currencies.append("JPY")
    if "GOLD" in text_upper or "XAU" in text_upper:
        currencies.append("XAU")
    
    return currencies if currencies else ["GENERAL"]


def detect_sentiment(text: str) -> str:
    text_lower = text.lower()
    
    bullish_words = ["rise", "surge", "gain", "rally", "up", "high", "boost", "strong", "growth", "positive", "beat", "hawkish", "raise"]
    bearish_words = ["fall", "drop", "decline", "down", "low", "weak", "loss", "crash", "negative", "concern", "miss", "dovish", "cut"]
    
    bull_score = sum(1 for w in bullish_words if w in text_lower)
    bear_score = sum(1 for w in bearish_words if w in text_lower)
    
    if bull_score > bear_score:
        return "bullish"
    elif bear_score > bull_score:
        return "bearish"
    return "neutral"


def detect_impact(text: str) -> str:
    text_lower = text.lower()
    
    high_impact = ["fed", "ecb", "boj", "boe", "rate", "inflation", "gdp", "nfp", "cpi", "fomc", "recession", "war"]
    medium_impact = ["employment", "retail", "manufacturing", "trade", "consumer", "housing"]
    
    for w in high_impact:
        if w in text_lower:
            return "HIGH"
    for w in medium_impact:
        if w in text_lower:
            return "MEDIUM"
    return "LOW"


def fetch_news_from_rss(url: str, limit: int = 10) -> list:
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
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
        
        items = root.findall('.//item')
        if not items:
            items = root.findall('.//{http://www.w3.org/2005/Atom}entry')
        
        items = items[:limit]
        
        news = []
        for item in items:
            title_elem = item.find('title')
            desc_elem = item.find('description')
            link_elem = item.find('link')
            date_elem = item.find('pubDate')
            
            if title_elem is None:
                title_elem = item.find('{http://www.w3.org/2005/Atom}title')
            if desc_elem is None:
                desc_elem = item.find('{http://www.w3.org/2005/Atom}summary')
            if link_elem is None:
                link_elem = item.find('{http://www.w3.org/2005/Atom}link')
            if date_elem is None:
                date_elem = item.find('{http://www.w3.org/2005/Atom}published')
            
            title_text = title_elem.text if title_elem is not None and title_elem.text else ""
            desc_text = clean_html(desc_elem.text) if desc_elem is not None and desc_elem.text else ""
            link_text = link_elem.text if link_elem is not None and link_elem.text else ""
            pub_date = date_elem.text if date_elem is not None and date_elem.text else ""
            
            if not title_text:
                continue
            
            full_text = f"{title_text} {desc_text}"
            
            news.append({
                "title": title_text,
                "description": desc_text[:200] + "..." if len(desc_text) > 200 else desc_text,
                "link": link_text,
                "published": pub_date,
                "currencies": detect_currency(full_text),
                "sentiment": detect_sentiment(full_text),
                "impact": detect_impact(full_text)
            })
        
        return news
    except Exception as e:
        print(f"❌ Erreur RSS {url}: {e}")
        return []


# ─── Calendrier Économique ──────────────────────────────────
def fetch_economic_calendar():
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = requests.get(ECONOMIC_CALENDAR_URL, headers=headers, timeout=15)
        response.raise_for_status()
        data = response.json()
        
        events = []
        for event in data:
            currency = event.get("country", "").upper()
            
            if currency not in TRACKED_CURRENCIES:
                continue
            
            impact = event.get("impact", "Low").upper()
            
            events.append({
                "title": event.get("title", ""),
                "currency": currency,
                "date": event.get("date", ""),
                "impact": impact,
                "forecast": event.get("forecast", "") or "---",
                "previous": event.get("previous", "") or "---",
                "actual": event.get("actual", "") or "---"
            })
        
        return events
    except Exception as e:
        print(f"❌ Erreur calendrier: {e}")
        return []


def get_upcoming_events(hours_ahead: int = 24, currencies: list = None):
    """Récupère les événements à venir dans X heures"""
    events = fetch_economic_calendar()
    now = datetime.utcnow()
    upcoming = []
    
    for event in events:
        try:
            event_date_str = event["date"].split("-04:00")[0]
            event_time = datetime.fromisoformat(event_date_str)
            
            diff = (event_time - now).total_seconds() / 3600
            
            if 0 < diff <= hours_ahead:
                if currencies and event["currency"] not in currencies:
                    continue
                
                event["hours_until"] = round(diff, 1)
                upcoming.append(event)
        except Exception:
            continue
    
    return sorted(upcoming, key=lambda x: x.get("hours_until", 999))


def interpret_calendar_result(event: dict) -> dict:
    """Interprète le résultat d'un événement économique"""
    forecast = event.get("forecast", "---")
    actual = event.get("actual", "---")
    previous = event.get("previous", "---")
    
    if actual == "---" or actual == "":
        return {
            "interpretation": "PENDING",
            "impact_direction": "NEUTRAL",
            "description": "Résultat pas encore publié"
        }
    
    try:
        actual_num = float(re.sub(r'[^\d.-]', '', str(actual)))
        forecast_num = float(re.sub(r'[^\d.-]', '', str(forecast))) if forecast != "---" else None
        
        if forecast_num is None:
            return {
                "interpretation": "PUBLISHED",
                "impact_direction": "NEUTRAL",
                "description": f"Résultat: {actual}"
            }
        
        # Détermine si "meilleur" = "plus haut" ou "plus bas" selon le type d'événement
        title_lower = event["title"].lower()
        higher_is_better = not any(w in title_lower for w in ["unemployment", "chômage", "jobless", "claims"])
        
        diff_pct = ((actual_num - forecast_num) / abs(forecast_num) * 100) if forecast_num != 0 else 0
        
        if abs(diff_pct) < 2:
            return {
                "interpretation": "AS_EXPECTED",
                "impact_direction": "NEUTRAL",
                "description": f"Conforme aux attentes ({actual} vs {forecast})"
            }
        elif (diff_pct > 0 and higher_is_better) or (diff_pct < 0 and not higher_is_better):
            return {
                "interpretation": "BETTER_THAN_EXPECTED",
                "impact_direction": "BULLISH_" + event["currency"],
                "description": f"Meilleur que prévu ({actual} vs {forecast}) → {event['currency']} renforcé"
            }
        else:
            return {
                "interpretation": "WORSE_THAN_EXPECTED",
                "impact_direction": "BEARISH_" + event["currency"],
                "description": f"Pire que prévu ({actual} vs {forecast}) → {event['currency']} affaibli"
            }
    except Exception:
        return {
            "interpretation": "PUBLISHED",
            "impact_direction": "NEUTRAL",
            "description": f"Résultat: {actual}"
        }


# ─── Analyseur d'impact News ────────────────────────────────
def analyze_news_impact(asset: str, news_list: list) -> dict:
    """Analyse l'impact combiné des news sur un actif"""
    currencies = ASSET_CURRENCIES.get(asset, [])
    base, quote = ASSET_BASE_QUOTE.get(asset, (None, None))
    
    if not currencies:
        return {"score": 0, "direction": "NEUTRAL", "count": 0}
    
    relevant_news = [
        n for n in news_list 
        if any(c in n.get("currencies", []) for c in currencies)
    ]
    
    if not relevant_news:
        return {
            "score": 0,
            "direction": "NEUTRAL",
            "count": 0,
            "bullish_count": 0,
            "bearish_count": 0,
            "high_impact_count": 0
        }
    
    base_score = 0
    quote_score = 0
    high_impact = 0
    bullish = 0
    bearish = 0
    
    for news in relevant_news:
        sentiment = news.get("sentiment", "neutral")
        impact = news.get("impact", "LOW")
        news_currencies = news.get("currencies", [])
        
        weight = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}.get(impact, 1)
        
        if impact == "HIGH":
            high_impact += 1
        
        for currency in news_currencies:
            if currency == base:
                if sentiment == "bullish":
                    base_score += weight
                    bullish += 1
                elif sentiment == "bearish":
                    base_score -= weight
                    bearish += 1
            elif currency == quote:
                if sentiment == "bullish":
                    quote_score += weight
                    bullish += 1
                elif sentiment == "bearish":
                    quote_score -= weight
                    bearish += 1
    
    # Impact sur la paire = force base - force quote
    net_score = base_score - quote_score
    
    if net_score > 3:
        direction = "BULLISH"
    elif net_score < -3:
        direction = "BEARISH"
    else:
        direction = "NEUTRAL"
    
    return {
        "score": net_score,
        "direction": direction,
        "count": len(relevant_news),
        "bullish_count": bullish,
        "bearish_count": bearish,
        "high_impact_count": high
