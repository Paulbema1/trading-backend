"""
TradeVision AI - Service d'Arrière-Plan pour le Test Lab.

Gère l'état du mode simulation, l'horloge virtuelle et le stockage temporaire
des données injectées (marché, news, calendrier).
"""

from typing import Dict, Any, List, Optional
import pandas as pd
from datetime import datetime
from src.core.logging import get_logger

logger = get_logger(__name__)


class TestLabService:

    def __init__(self):
        self._enabled: bool = False
        self._simulated_time: Optional[str] = None
        self._injected_candles: Dict[str, pd.DataFrame] = {}  # key: SYMBOL:INTERVAL
        self._injected_news: List[Dict[str, Any]] = []
        self._injected_calendar: List[Dict[str, Any]] = []

    def set_mode(self, enabled: bool) -> bool:
        """Active ou désactive le mode simulation."""
        self._enabled = enabled
        if not enabled:
            self.reset()
        logger.info(f"🧪 Mode Simulation Test Lab : {'ACTIVÉ' if enabled else 'DÉSACTIVÉ'}")
        return self._enabled

    def is_enabled(self) -> bool:
        """Indique si le serveur est actuellement en mode test."""
        return self._enabled

    def set_simulated_time(self, time_str: str):
        """Définit l'horloge virtuelle du serveur."""
        self._simulated_time = time_str
        logger.debug(f"🧪 Horloge virtuelle ajustée : {time_str}")

    def get_simulated_time(self) -> Optional[str]:
        return self._simulated_time

    def inject_candles(self, symbol: str, interval: str, df: pd.DataFrame):
        """Stocke les bougies injectées par le Test Lab."""
        key = f"{symbol.upper().replace('/', '')}:{interval.lower()}"
        self._injected_candles[key] = df
        logger.debug(f"🧪 Injecté {len(df)} bougies pour {key}")

    def get_injected_candles(self, symbol: str, interval: str) -> Optional[pd.DataFrame]:
        """Récupère les bougies injectées."""
        key = f"{symbol.upper().replace('/', '')}:{interval.lower()}"
        return self._injected_candles.get(key)

    def inject_news(self, news_list: List[Dict[str, Any]]):
        """Stocke les actualités injectées par le Test Lab."""
        self._injected_news = news_list

    def get_injected_news(self) -> List[Dict[str, Any]]:
        return self._injected_news

    def inject_calendar(self, events_list: List[Dict[str, Any]]):
        """Stocke les événements économiques injectés par le Test Lab."""
        self._injected_calendar = events_list

    def get_injected_calendar(self) -> List[Dict[str, Any]]:
        return self._injected_calendar

    def reset(self):
        """Réinitialise toutes les données injectées."""
        self._simulated_time = None
        self._injected_candles.clear()
        self._injected_news.clear()
        self._injected_calendar.clear()
        logger.info("🧪 Test Lab réinitialisé.")

    def get_status(self) -> Dict[str, Any]:
        """Affiche le bilan du mode simulation."""
        return {
            "simulation_mode": self._enabled,
            "simulated_time": self._simulated_time,
            "injected_pairs_count": len(self._injected_candles),
            "injected_news_count": len(self._injected_news),
            "injected_calendar_count": len(self._injected_calendar),
        }


# Instance globale partagée
test_lab_service = TestLabService()
