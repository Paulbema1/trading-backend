from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import requests
import os
import pandas as pd
import numpy as np
import xml.etree.ElementTree as ET
from html import unescape
import re
import json
from datetime import datetime

try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

app = FastAPI(title="TradeVision AI", version="5.0.2")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

API_KEY = os.getenv("TWELVE_DATA_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
BASE_URL = "https://api.twelvedata.com"

GEMINI_MODEL = None
if GEMINI_AVAILABLE and GEMINI_API_KEY:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        GEMINI_MODEL = genai.GenerativeModel('gemini-1.5-flash')
    except Exception as e:
        print(f"Gemini init error: {e}")

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

TIMEFRAMES = {"1h": "1h", "4h": "4h", "1d": "1day"}

RSS_FEEDS = [
    "https://www.investing.com/rss/news_1.rss",
    "https://www.investing.com/rss/news_301.rss",
    "https://www.investing.com/rss/news_285.rss"
]

ECONOMIC_CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
TRACKED_CURRENCIES = ["USD", "EUR", "GBP", "JPY", "XAU"]

GEMINI_CACHE = {}


def td_request(endpoint, params):
    params["apikey"] = API_KEY
    try:
        response = requests.get(BASE_URL + "/" + endpoint, params=params, timeout=10)
        return response.json()
    except Exception as e:
        print("Erreur TD: " + str(e))
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
        reasons.append("RSI survente " + str(round(rsi_val, 1)))
    elif rsi_val > 70:
        score -= 20
        reasons.append("RSI surachat " + str(round(rsi_val, 1)))
    
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
        sl = tp1 = tp2 = tp3 = None
    
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
        "score": score
    }


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
    return currencies if currencies else ["GENERAL"]


def detect_sentiment(text):
    t = text.lower()
    bull = ["rise", "surge", "gain", "rally", "up", "high", "strong", "positive", "beat", "hawkish"]
    bear = ["fall", "drop", "decline", "down", "low", "weak", "loss", "negative", "miss", "dovish"]
    bs = sum(1 for w in bull if w in t)
    br = sum(1 for w in bear if w in t)
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
        print("RSS error: " + str(e))
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
        print("Cal error: " + str(e))
        return []


def get_upcoming_events(hours_ahead=24, currencies=None):
    events = fetch_economic_calendar()
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
    
    empty = {"score": 0, "direction": "NEUTRAL", "count": 0, "bullish_count": 0, "bearish_count": 0, "high_impact_count": 0}
    
    if not currencies:
        return empty
    
    relevant = [n for n in news_list if any(c in n.get("currencies", []) for c in currencies)]
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
        weight = 3 if imp == "HIGH" else (2 if imp == "MEDIUM" else 1)
        
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
    direction = "BULLISH" if net > 3 else ("BEARISH" if net < -3 else "NEUTRAL")
    
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
    relevant = [e for e in upcoming_events if e.get("currency") in currencies]
    
    imminent = [e for e in relevant if e.get("hours_until", 999) <= 2 and ("HIGH" in e.get("impact", "").upper() or "ELEV" in e.get("impact", "").upper())]
    upcoming_h = [e for e in relevant if 2 < e.get("hours_until", 999) <= 12 and ("HIGH" in e.get("impact", "").upper() or "ELEV" in e.get("impact", "").upper())]
    
    risk = "HIGH" if imminent else ("MEDIUM" if upcoming_h else "LOW")
    
    return {
        "total_events": len(relevant),
        "imminent_high_impact": len(imminent),
        "upcoming_high_impact": len(upcoming_h),
        "risk_level": risk,
        "next_events": relevant[:3]
    }


def get_gemini_analysis(asset, technical, news_impact, calendar_impact, news_titles):
    default = {
        "available": False,
        "summary": "Gemini non disponible",
        "sentiment": "neutral",
        "confidence_adjustment": 0,
        "key_risks": [],
        "recommendation": "",
        "invalidation_scenario": ""
    }
    
    if not GEMINI_MODEL:
        return default
    
    cache_key = asset + "_" + str(technical.get('signal')) + "_" + str(int(datetime.utcnow().timestamp() // 900))
    if cache_key in GEMINI_CACHE:
        return GEMINI_CACHE[cache_key]
    
    display_name = ASSETS.get(asset, asset)
    titles_text = "\n".join(["- " + t[:100] for t in news_titles[:5]])
    
    prompt = "Tu es un analyste Forex professionnel.\n\n"
    prompt += "ACTIF: " + display_name + "\n\n"
    prompt += "TECHNIQUE:\n"
    prompt += "- Signal: " + str(technical.get('signal', 'N/A')) + "\n"
    prompt += "- Confiance: " + str(technical.get('confidence', 0)) + "%\n"
    prompt += "- Tendance: " + str(technical.get('trend', 'N/A')) + "\n"
    prompt += "- RSI: " + str(technical.get('indicators', {}).get('rsi', 'N/A')) + "\n\n"
    prompt += "NEWS:\n"
    prompt += "- Direction: " + str(news_impact.get('direction', 'N/A')) + "\n"
    prompt += "- Haussieres: " + str(news_impact.get('bullish_count', 0)) + "\n"
    prompt += "- Baissieres: " + str(news_impact.get('bearish_count', 0)) + "\n"
    prompt += "Titres:\n" + titles_text + "\n\n"
    prompt += "CALENDRIER:\n"
    prompt += "- Imminents haut impact: " + str(calendar_impact.get('imminent_high_impact', 0)) + "\n"
    prompt += "- Risque: " + str(calendar_impact.get('risk_level', 'LOW')) + "\n\n"
    prompt += 'Reponds en JSON strict sans markdown:\n'
    prompt += '{"summary": "resume 2-3 phrases", "sentiment": "bullish/bearish/neutral", "confidence_adjustment": nombre -15 a 15, "key_risks": ["r1", "r2"], "recommendation": "courte reco", "invalidation_scenario": "ce qui invaliderait"}'
    
    try:
        response = GEMINI_MODEL.generate_content(prompt)
        text = response.text.strip()
        text = re.sub(r'^```json\s*', '', text)
        text = re.sub(r'\s*```$', '', text)
        text = text.strip()
        
        analysis = json.loads(text)
        result = {
            "available": True,
            "summary": analysis.get("summary", ""),
            "sentiment": analysis.get("sentiment", "neutral"),
            "confidence_adjustment": int(analysis.get("confidence_adjustment", 0)),
            "key_risks": analysis.get("key_risks", []),
            "recommendation": analysis.get("recommendation", ""),
            "invalidation_scenario": analysis.get("invalidation_scenario", "")
        }
        GEMINI_CACHE[cache_key] = result
        return result
    except Exception as e:
        print("Gemini error: " + str(e))
        return default


def generate_smart_signal(asset):
    symbol = ASSETS.get(asset)
    if not symbol:
        return {"error": "Actif inconnu"}
    
    tech_h1 = analyze_asset(symbol, "1h")
    tech_h4 = analyze_asset(symbol, "4h")
    
    if not tech_h1:
        return {"error": "Analyse impossible"}
    
    h4_confirmed = bool(tech_h4 and tech_h1["signal"] == tech_h4["signal"] and tech_h1["signal"] != "WAIT")
    
    all_news = []
    for url in RSS_FEEDS:
        all_news.extend(fetch_news_from_rss(url, limit=10))
    
    news_impact = analyze_news_impact(asset, all_news)
    currencies = ASSET_CURRENCIES.get(asset, [])
    upcoming = get_upcoming_events(24, currencies)
    calendar_impact = analyze_calendar_impact(asset, upcoming)
    
    news_titles = [n["title"] for n in all_news if any(c in n.get("currencies", []) for c in currencies)][:5]
    gemini = get_gemini_analysis(asset, tech_h1, news_impact, calendar_impact, news_titles)
    
    tech_score = tech_h1["confidence"]
    if h4_confirmed:
        tech_score = min(tech_score + 10, 95)
    
    if tech_h1["signal"] == "BUY" and news_impact["direction"] == "BULLISH":
        news_match = 100
    elif tech_h1["signal"] == "SELL" and news_impact["direction"] == "BEARISH":
        news_match = 100
    elif news_impact["direction"] == "NEUTRAL":
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
        sent_score = 75 if tech_h1["signal"] == "BUY" else 25
    elif news_impact["bearish_count"] > news_impact["bullish_count"]:
        sent_score = 75 if te
