"""
Remonte l'historique réel de XAU/USD (par défaut) le plus loin possible
via pagination sur end_date (Twelve Data), en réutilisant le RequestManager
partagé (rotation des 2 clés, cooldown 429 déjà géré) — RECHERCHE UNIQUEMENT,
aucun fichier de scoring ni de prod n'est touché.
Stocke le résultat dans Neon (table historical_candles) ET en local, pour
enchaîner directement sur un backtest dans le même run.
"""
import asyncio
import os
import pandas as pd

from src.services.request_manager import request_manager
from src.utils.helpers import normalize_symbol
from src.backtest.historical_data import historical_data_manager
from research.neon_store import get_conn, ensure_table, upsert_candles

SYMBOLS = [s.strip() for s in os.getenv("SYMBOLS", "XAU/USD").split(",") if s.strip()]
TIMEFRAMES = [t.strip() for t in os.getenv("TIMEFRAMES", "1h,4h").split(",") if t.strip()]
MAX_CALLS_PER_TF = int(os.getenv("MAX_CALLS_PER_TF", "20"))  # 20 x 5000 = 100 000 bougies max
SLEEP_BETWEEN_CALLS = 8  # secondes, pour rester sous 8 requêtes/minute


async def fetch_full_history(symbol: str, interval: str) -> pd.DataFrame:
    clean_symbol = normalize_symbol(symbol)
    frames = []
    end_date = None
    for call_n in range(1, MAX_CALLS_PER_TF + 1):
        params = {"symbol": clean_symbol, "interval": interval, "outputsize": 5000, "format": "JSON"}
        if end_date:
            params["end_date"] = end_date
        data, error = await request_manager.execute_request("time_series", params, timeout=30.0)
        if error or not data or "values" not in data:
            print(f"  [{symbol} {interval}] appel {call_n}: arrêt ({error or 'pas de données'})")
            break
        df = pd.DataFrame(data["values"])
        if df.empty:
            break
        df["datetime"] = pd.to_datetime(df["datetime"])
        for col in ["open", "high", "low", "close"]:
            df[col] = df[col].astype(float)
        df["volume"] = pd.to_numeric(df.get("volume", 0.0), errors="coerce").fillna(0.0)
        df = df.sort_values("datetime").reset_index(drop=True)

        frames.append(df)
        oldest = df["datetime"].min()
        print(f"  [{symbol} {interval}] appel {call_n}: {len(df)} bougies, plus ancienne = {oldest}")

        if len(df) < 5000:
            print(f"  [{symbol} {interval}] fin de l'historique disponible atteinte.")
            break

        end_date = (oldest - pd.Timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
        await asyncio.sleep(SLEEP_BETWEEN_CALLS)

    if not frames:
        return pd.DataFrame()

    full = pd.concat(frames, ignore_index=True)
    full = full.drop_duplicates(subset="datetime").sort_values("datetime").reset_index(drop=True)
    return full


async def main():
    conn = get_conn()
    ensure_table(conn)

    for symbol in SYMBOLS:
        for tf in TIMEFRAMES:
            print(f"=== {symbol} ({tf}) ===")
            df = await fetch_full_history(symbol, tf)
            if df.empty:
                print(f"  ❌ Aucune donnée récupérée pour {symbol} ({tf})")
                continue

            n = upsert_candles(conn, symbol, tf, df)
            print(f"  💾 {n} lignes envoyées vers Neon (doublons ignorés automatiquement)")

            historical_data_manager.save_data(symbol, tf, df)
            print(f"  📁 {len(df)} bougies écrites localement ({df['datetime'].min()} → {df['datetime'].max()})")

    conn.close()


if __name__ == "__main__":
    asyncio.run(main())
