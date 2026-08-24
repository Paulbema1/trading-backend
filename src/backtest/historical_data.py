"""
TradeVision AI - Stockage et Gestion des Données Historiques Réelles.

Prohibition absolue des données synthétiques/aléatoires.
"""

from pathlib import Path
from typing import Optional
import pandas as pd
import httpx

from src.core.config import TWELVE_DATA_BASE_URL, TWELVE_DATA_API_KEYS
from src.utils.helpers import normalize_symbol
from src.core.logging import get_logger

logger = get_logger(__name__)
DATA_DIR = Path("data")


class HistoricalDataManager:

    def __init__(self, base_dir: Path = DATA_DIR):
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _normalize_interval(self, interval: str) -> str:
        inv = interval.lower().strip()
        if inv == "15m": return "15min"
        if inv == "30m": return "30min"
        return inv

    def _get_file_path(self, symbol: str, interval: str) -> Path:
        clean_sym = symbol.replace("/", "").upper()
        symbol_dir = self.base_dir / clean_sym
        symbol_dir.mkdir(parents=True, exist_ok=True)
        return symbol_dir / f"{interval}.parquet"

    def load_data(
        self,
        symbol: str,
        interval: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Optional[pd.DataFrame]:
        """Charge uniquement des données réelles depuis le stockage Parquet local."""
        file_path = self._get_file_path(symbol, interval)
        if not file_path.exists():
            logger.warning(f"Aucune donnée locale réelle trouvée pour {symbol} ({interval}) à {file_path}")
            return None

        try:
            df = pd.read_parquet(file_path)
            df["datetime"] = pd.to_datetime(df["datetime"])
            df = df.sort_values("datetime").reset_index(drop=True)

            if start_date:
                df = df[df["datetime"] >= pd.to_datetime(start_date)]
            if end_date:
                df = df[df["datetime"] <= pd.to_datetime(end_date)]

            return df.reset_index(drop=True)
        except Exception as e:
            logger.error(f"Erreur de lecture Parquet ({file_path}) : {e}")
            return None

    def save_data(self, symbol: str, interval: str, df: pd.DataFrame) -> bool:
        if df is None or df.empty:
            return False

        file_path = self._get_file_path(symbol, interval)
        try:
            if file_path.exists():
                existing_df = pd.read_parquet(file_path)
                df = pd.concat([existing_df, df]).drop_duplicates(subset=["datetime"]).sort_values("datetime")

            df.to_parquet(file_path, index=False, engine="pyarrow")
            logger.info(f"💾 Sauvegardé {len(df)} bougies réelles pour {symbol} ({interval}) dans {file_path}")
            return True
        except Exception as e:
            logger.error(f"Erreur d'écriture Parquet : {e}")
            return False

    async def download_historical_range(
        self,
        symbol: str,
        interval: str = "1h",
        outputsize: int = 5000,
    ) -> Optional[pd.DataFrame]:
        """Télécharge de vraies données historiques depuis Twelve Data."""
        clean_symbol = normalize_symbol(symbol)
        api_interval = self._normalize_interval(interval)
        api_key = TWELVE_DATA_API_KEYS[0] if TWELVE_DATA_API_KEYS else None

        if not api_key:
            return None

        url = f"{TWELVE_DATA_BASE_URL}/time_series"
        params = {
            "symbol": clean_symbol,
            "interval": api_interval,
            "outputsize": outputsize,
            "apikey": api_key,
            "format": "JSON",
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(url, params=params)

            if resp.status_code == 200:
                data = resp.json()
                if "values" in data:
                    df = pd.DataFrame(data["values"])
                    df["datetime"] = pd.to_datetime(df["datetime"])
                    for col in ["open", "high", "low", "close"]:
                        df[col] = df[col].astype(float)
                    df["volume"] = pd.to_numeric(df.get("volume", 0.0), errors="coerce").fillna(0.0)
                    df = df.sort_values("datetime").reset_index(drop=True)

                    self.save_data(clean_symbol, interval, df)
                    return df
        except Exception as e:
            logger.error(f"Erreur téléchargement historique réel : {e}")

        return None


historical_data_manager = HistoricalDataManager()
