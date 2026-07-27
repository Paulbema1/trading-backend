from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import yfinance as yf
import requests
from datetime import datetime

app = FastAPI(
    title="Trading Assistant API",
    version="1.3.0"
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

# Session avec User-Agent (contourne le blocage Yahoo)
def get_session():
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                      'AppleWebKit/537.36 (KHTML, like Gecko) '
                      'Chrome/120.0.0.0 Safari/537.36'
    })
    return session


def fetch_data(symbol: str, period: str = "5d", interval: str = "1h"):
    """Récupère les données yfinance avec session personnalisée"""
    try:
        session = get_session()
        ticker = yf.Ticker(symbol, session=session)
        data = ticker.history(period=period, interval=interval)
        
        if data.empty:
            # Fallback avec download direct
            data = yf.download(
                symbol,
                period=period,
                interval=interval,
                progress=False,
                session=session
            )
        
        return data
    except Exception as e:
        print(f"❌ Erreur yfinance pour {symbol}: {e}")
        return None


@app.get("/")
async def root():
    return {
        "status": "online",
        "message": "Trading Assistant API is running 🚀",
        "version": "1.3.0"
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
    
    data = fetch_data(ASSETS[asset], period="5d", interval="1h")
    
    if data is None or data.empty:
        raise HTTPException(status_code=503, detail="No data from yfinance")
    
    last_price = float(data['Close'].iloc[-1])
    prev_price = float(data['Close'].iloc[-2]) if len(data) > 1 else last_price
    change = last_price - prev_price
    change_pct = (change / prev_price * 100) if prev_price else 0
    
    return {
        "asset": asset,
        "price": round(last_price, 5),
        "previous": round(prev_price, 5),
        "change": round(change, 5),
        "change_pct": round(change_pct, 3),
        "timestamp": datetime.utcnow().isoformat(),
        "source": "yfinance"
    }


@app.get("/api/v1/prices")
async def get_all_prices():
    """Récupère les prix de tous les actifs"""
    prices = {}
    
    for name, symbol in ASSETS.items():
        data = fetch_data(symbol, period="5d", interval="1h")
        
        if data is not None and not data.empty:
            last_price = float(data['Close'].iloc[-1])
            prev_price = float(data['Close'].iloc[-2]) if len(data) > 1 else last_price
            change_pct = ((last_price - prev_price) / prev_price * 100) if prev_price else 0
            
            prices[name] = {
                "price": round(last_price, 5),
                "change_pct": round(change_pct, 3),
                "status": "ok"
            }
        else:
            prices[name] = {"status": "no_data"}
    
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
    
    tf_map = {
        "1h": ("1h", "1mo"),
        "4h": ("1h", "3mo"),
        "1d": ("1d", "1y")
    }
    
    if timeframe not in tf_map:
        raise HTTPException(status_code=400, detail="Invalid timeframe")
    
    interval, period = tf_map[timeframe]
    data = fetch_data(ASSETS[asset], period=period, interval=interval)
    
    if data is None or data.empty:
        raise HTTPException(status_code=503, detail="No data from yfinance")
    
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
