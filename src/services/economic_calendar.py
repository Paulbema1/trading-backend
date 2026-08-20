"""
TradeVision AI - Service du Calendrier Économique.

Responsabilités :
- Récupérer les événements économiques de la semaine
- Filtrer par devises de l'actif (ex: EUR et USD pour EUR/USD)
- Identifier les annonces majeures (High / Medium impact)
- Calculer le temps restant ou écoulé par rapport à l'annonce
- Assurer la mise en cache pour ne pas surcharger les appels
"""

import time
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
import httpx

from src.core.config import ECONOMIC_CALENDAR_URL
from src.core.logging import get_logger

logger = get_logger(__name__)


class EconomicCalendarService:
    """Service de suivi et d'analyse du calendrier économique."""

    def __init__(self):
        self._cached_events: List[Dict[str, Any]] = []
        self._last_fetch_time: float = 0.0
        self._cache_ttl_seconds: int = 3600  # Mise en cache 1 heure

    def _extract_currencies(self, symbol: str) -> List[str]:
        """Extrait les deux devises composant une paire (ex: EUR/USD -> ['EUR', 'USD'])."""
        clean = symbol.replace("/", "").upper()
        if len(clean) == 6:
            return [clean[:3], clean[3:]]
        if "XAU" in clean or "GOLD" in clean:
            return ["USD"]
        return [clean]

    async def fetch_calendar(self) -> List[Dict[str, Any]]:
        """Télécharge le calendrier économique avec gestion du cache."""
        now = time.time()
        if self._cached_events and (now - self._last_fetch_time) < self._cache_ttl_seconds:
            return self._cached_events

        if not ECONOMIC_CALENDAR_URL:
            logger.warning("ECONOMIC_CALENDAR_URL non configuré.")
            return []

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(ECONOMIC_CALENDAR_URL)

            if resp.status_code == 200:
                events = resp.json()
                if isinstance(events, list):
                    self._cached_events = events
                    self._last_fetch_time = now
                    logger.info(f"Calendrier économique actualisé ({len(events)} événements reçus).")
                    return events
            else:
                logger.warning(f"Erreur HTTP {resp.status_code} lors du téléchargement du calendrier.")
        except Exception as e:
            logger.error(f"Erreur lors de la récupération du calendrier économique : {e}")

        return self._cached_events

    async def get_upcoming_events(
        self,
        symbol: str,
        window_minutes_before: int = 60,
        window_minutes_after: int = 30,
    ) -> Dict[str, Any]:
        """
        Vérifie s'il y a des événements majeurs proches dans le temps pour un symbole.

        Retourne un résumé structuré :
        {
            "has_high_impact": bool,
            "events": [...],
            "calendar_score": int (0 à 5 points),
            "summary": str
        }
        """
        events = await self.fetch_calendar()
        currencies = self._extract_currencies(symbol)

        if not events:
            # Si pas de données calendrier, score neutre
            return {
                "has_high_impact": False,
                "events": [],
                "calendar_score": 5,
                "summary": "Aucune donnée calendrier (neutre)",
            }

        now_dt = datetime.now(timezone.utc)
        matching_events = []
        has_high_impact = False

        for ev in events:
            ev_currency = ev.get("country", "").upper()
            if ev_currency not in currencies:
                continue

            ev_impact = str(ev.get("impact", "")).lower()
            ev_date_str = ev.get("date", "")

            try:
                # Format standard FairEconomy : "2025-01-15T14:30:00-05:00" ou ISO
                ev_dt = datetime.fromisoformat(ev_date_str)
                if ev_dt.tzinfo is None:
                    ev_dt = ev_dt.replace(tzinfo=timezone.utc)
                else:
                    ev_dt = ev_dt.astimezone(timezone.utc)

                time_diff_min = (ev_dt - now_dt).total_seconds() / 60.0

                # L'événement est-il dans la fenêtre critique ?
                if -window_minutes_after <= time_diff_min <= window_minutes_before:
                    is_high = "high" in ev_impact or "red" in ev_impact
                    if is_high:
                        has_high_impact = True

                    matching_events.append({
                        "title": ev.get("title", "Événement économique"),
                        "currency": ev_currency,
                        "impact": ev.get("impact", "Medium"),
                        "minutes_relative": round(time_diff_min, 1),
                        "forecast": ev.get("forecast", ""),
                        "previous": ev.get("previous", ""),
                    })

            except Exception:
                continue

        # Calcul du score calendrier (5 points max)
        if has_high_impact:
            calendar_score = 1  # Risque élevé d'extrême volatilité / spread
            summary = f"⚠️ Annonce majeure imminente/récente ({len(matching_events)} événement(s))"
        elif matching_events:
            calendar_score = 3
            summary = f"Événements modérés détectés ({len(matching_events)} événement(s))"
        else:
            calendar_score = 5
            summary = "Aucun événement économique perturbateur proche"

        return {
            "has_high_impact": has_high_impact,
            "events": matching_events,
            "calendar_score": calendar_score,
            "summary": summary,
        }


# Instance globale partagée
economic_calendar_service = EconomicCalendarService()