"""
TradeVision AI - Stockage et Gestion des Données Historiques Réelles.

Prohibition absolue des données synthétiques/aléatoires.
"""

from pathlib import Path
from typing import Optional
import pandas as pd

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
        """
        Télécharge de vraies données historiques depuis Twelve Data.

        Utilise le RequestManager partagé (rotation automatique des 2 clés,
        cooldown/429 gérés de façon centralisée) plutôt qu'une clé unique en
        dur, pour rester cohérent avec le reste du système et supporter le
        téléchargement de plusieurs actifs/timeframes à la suite sans
        épuiser une seule clé.

        outputsize=5000 est le maximum autorisé par requête Twelve Data :
        à 1h cela couvre environ 208 jours (~7 mois), à 4h environ 833 jours
        (~2.3 ans) — largement suffisant pour un backtest sur longue période.
        """
        # Import différé pour éviter toute dépendance circulaire avec request_manager.
        from src.services.request_manager import request_manager

        clean_symbol = normalize_symbol(symbol)
        api_interval = self._normalize_interval(interval)

        params = {
            "symbol": clean_symbol,
            "interval": api_interval,
            "outputsize": outputsize,
            "format": "JSON",
        }

        data, error = await request_manager.execute_request("time_series", params, timeout=30.0)

        if error or not data:
            logger.error(f"Erreur téléchargement historique réel pour {clean_symbol} ({interval}) : {error}")
            return None

        if "values" not in data:
            logger.error(f"Réponse Twelve Data sans 'values' pour {clean_symbol} ({interval}) : {data}")
            return None

        try:
            df = pd.DataFrame(data["values"])
            df["datetime"] = pd.to_datetime(df["datetime"])
            for col in ["open", "high", "low", "close"]:
                df[col] = df[col].astype(float)
            # Le forex/or n'a pas de colonne "volume" dans la réponse Twelve Data
            # (contrairement aux actions). df.get("volume", 0.0) sur un DataFrame
            # sans cette colonne retourne le scalaire 0.0 (pas une Series), donc
            # .fillna() plantait ("'float' object has no attribute 'fillna'").
            if "volume" in df.columns:
                df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0.0)
            else:
                df["volume"] = 0.0
            df = df.sort_values("datetime").reset_index(drop=True)

            self.save_data(clean_symbol, interval, df)
            return df
        except Exception as e:
            logger.error(f"Erreur traitement historique réel pour {clean_symbol} ({interval}) : {e}")
            return None


historical_data_manager = HistoricalDataManager()

