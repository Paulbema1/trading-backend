from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import requests
import os
from datetime import datetime

app = FastAPI(
    title="Trading Assistant API",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Clé API Twelve Data (depuis variable d'environnement)
API_KEY = os.getenv("TWELVE_DATA_API_KEY", "")
BASE_URL = "https://api.twelvedata.com"

# Actifs suivis (symboles Twelve Data)
ASSETS = {
    "EURUSD": "EUR/USD",
    "GBPUSD": "GBP/USD",
    "USDJPY": "USD/JPY",
    "XAUUSD": "XAU/USD"
}

# Mapping timeframes → intervalles Twelve Data
TIMEFRAMES = {
    "1h": "1h",
    "4h": "4h",
    "1d": "1day"
}


def td_request(endpoint: str, params: dict):
    """Effectue une requête vers Twelve Data"""
    params["apikey"] = API_KEY
    try:
        response = requests.get(f"{BASE_URL}/{endpoint}", params=params, timeout=10)
        return response.json()
    except Exception as e:
        print(f"❌ Erreur Twelve Data: {e}")
        return None


@app.get("/")
async def root():
    return {
        "status": "online",
        "message": "Trading Assistant API is running 🚀",
        "version": "2.0.0",
        "data_provider": "Twelve Data"
    }


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "api_key_configured": bool(API_KEY)
    }


@app.get("/api/v1/price/{asset}")
async def get_price(asset: str):
    """Récupère le prix actuel d'un actif"""
    asset = asset.upper()
    
    if asset not in ASSETS:
        raise HTTPException(
            status_code=404,
            detail=f"Asset not found. Available: {list(ASSETS.keys())}"
        )
    
    if not API_KEY:
        raise HTTPException(status_code=500, detail="API key not configured")
    
    data = td_request("price", {"symbol": ASSETS[asset]})
    
    if not data or "price" not in data:
        raise HTTPException(
            status_code=503,
            detail=f"No data: {data}"
        )
    
    return {
        "asset": asset,
        "symbol": ASSETS[asset],
        "price": float(data["price"]),
        "timestamp": datetime.utcnow().isoformat(),
        "source": "Twelve Data"
    }


@app.get("/api/v1/prices")
async def get_all_prices():
    """Récupère les prix de tous les actifs"""
    prices = {}
    
    for name, symbol in ASSETS.items():
        data = td_request("price", {"symbol": symbol})
        
        if data and "price" in data:
            prices[name] = {
                "price": float(data["price"]),
                "symbol": symbol,
                "status": "ok"
            }
        else:
            prices[name] = {
                "status": "error",
                "message": data.get("message", "Unknown error") if data else "No response"
            }
    
    return {
        "timestamp": datetime.utcnow().isoformat(),
        "prices": prices
    }


@app.get("/api/v1/quote/{asset}")
async def get_quote(asset: str):
    """Récupère les infos complètes (prix, variation, high, low, etc.)"""
    asset = asset.upper()
    
    if asset not in ASSETS:
        raise HTTPException(status_code=404, detail="Asset not found")
    
    data = td_request("quote", {"symbol": ASSETS[asset]})
    
    if not data or "close" not in data:
        raise HTTPException(status_code=503, detail=f"No data: {data}")
    
    return {
        "asset": asset,
        "symbol": ASSETS[asset],
        "price": float(data["close"]),
        "open": float(data["open"]),
        "high": float(data["high"]),
        "low": float(data["low"]),
        "previous_close": float(data["previous_close"]),
        "change": float(data["change"]),
        "change_pct": float(data["percent_change"]),
        "timestamp": datetime.utcnow().isoformat()
    }


@app.get("/api/v1/candles/{asset}")
async def get_candles(asset: str, timeframe: str = "1h", limit: int = 100):
    """Récupère les bougies pour l'analyse technique"""
    asset = asset.upper()
    
    if asset not in ASSETS:
        raise HTTPException(status_code=404, detail="Asset not found")
    
    if timeframe not in TIMEFRAMES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid timeframe. Available: {list(TIMEFRAMES.keys())}"
        )
    
    data = td_request("time_series", {
        "symbol": ASSETS[asset],
        "interval": TIMEFRAMES[timeframe],
        "outputsize": limit
    })
    
    if not data or "values" not in data:
        raise HTTPException(
            status_code=503,
            detail=f"No data: {data}"
        )
    
    # Twelve Data renvoie les bougies de la plus récente à la plus ancienne
    # On inverse pour avoir un ordre chronologique
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
    
    return {
        "asset": asset,
        "symbol": ASSETS[asset],
        "timeframe": timeframe,
        "count": len(candles),
        "candles": candles
    }
