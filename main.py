from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import yfinance as yf
from datetime import datetime

app = FastAPI(
    title="Trading Assistant API",
    version="1.1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Actifs suivis
ASSETS = {
    "EURUSD": "EURUSD=X",
    "GBPUSD": "GBPUSD=X",
    "USDJPY": "USDJPY=X",
    "XAUUSD": "GC=F"
}

@app.get("/")
async def root():
    return {
        "status": "online",
        "message": "Trading Assistant API is running 🚀",
        "version": "1.1.0"
    }

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.get("/api/v1/price/{asset}")
async def get_price(asset: str):
    """Récupère le prix actuel d'un actif"""
    asset = asset.upper()
    
    if asset not in ASSETS:
        raise HTTPException(
            status_code=404,
            detail=f"Asset not found. Available: {list(ASSETS.keys())}"
        )
    
    try:
        ticker = yf.Ticker(ASSETS[asset])
        data = ticker.history(period="1d", interval="1m")
        
        if data.empty:
            raise HTTPException(status_code=404, detail="No data available")
        
        last_price = float(data['Close'].iloc[-1])
        
        return {
            "asset": asset,
            "price": round(last_price, 5),
            "timestamp": datetime.utcnow().isoformat(),
            "source": "yfinance"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/prices")
async def get_all_prices():
    """Récupère les prix de tous les actifs"""
    prices = {}
    
    for name, symbol in ASSETS.items():
        try:
            ticker = yf.Ticker(symbol)
            data = ticker.history(period="1d", interval="1m")
            
            if not data.empty:
                prices[name] = {
                    "price": round(float(data['Close'].iloc[-1]), 5),
                    "status": "ok"
                }
            else:
                prices[name] = {"status": "no_data"}
        except Exception as e:
            prices[name] = {"status": "error", "message": str(e)}
    
    return {
        "timestamp": datetime.utcnow().isoformat(),
        "prices": prices
    }

@app.get("/api/v1/candles/{asset}")
async def get_candles(asset: str, timeframe: str = "1h", limit: int = 100):
    """Récupère les bougies pour l'analyse technique"""
    asset = asset.upper()
    
    if asset not in ASSETS:
        raise HTTPException(status_code=404, detail="Asset not found")
    
    # Mapping timeframes
    tf_map = {
        "1h": ("1h", "60d"),
        "4h": ("1h", "60d"),  # yfinance ne fait pas 4h natif, on utilise 1h
        "1d": ("1d", "1y")
    }
    
    if timeframe not in tf_map:
        raise HTTPException(status_code=400, detail="Invalid timeframe")
    
    interval, period = tf_map[timeframe]
    
    try:
        ticker = yf.Ticker(ASSETS[asset])
        data = ticker.history(period=period, interval=interval)
        
        if data.empty:
            raise HTTPException(status_code=404, detail="No data available")
        
        # Prendre les X dernières bougies
        data = data.tail(limit)
        
        candles = []
        for idx, row in data.iterrows():
            candles.append({
                "time": idx.isoformat(),
                "open": round(float(row['Open']), 5),
                "high": round(float(row['High']), 5),
                "low": round(float(row['Low']), 5),
                "close": round(float(row['Close']), 5),
                "volume": float(row['Volume']) if row['Volume'] else 0
            })
        
        return {
            "asset": asset,
            "timeframe": timeframe,
            "count": len(candles),
            "candles": candles
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
