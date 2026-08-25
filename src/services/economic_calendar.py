"""
TradeVision AI - Service du Calendrier Économique.
"""

import time
from typing import List, Dict, Any
from datetime import datetime, timezone
import httpx

from src.core.config import ECONOMIC_CALENDAR_URL
from src.core.logging import get_logger

logger = get_logger(__name__)


class EconomicCalendarService:

    def __init__(self):
        self._cached_events: List[Dict[str, Any]] = []
        self._last_fetch_time: float = 0.0
        self._cache_ttl_seconds: int = 3600

    def _extract_currencies(self, symbol: str) -> List[str]:
        clean = symbol.replace("/", "").upper()
        if len(clean) == 6:
            return [clean[:3], clean[3:]]
        if "XAU" in clean or "GOLD" in clean:
            return ["USD"]
        return [clean]

    async def fetch_calendar(self) -> List[Dict[str, Any]]:
        now = time.time()
        if self._cached_events and (now - self._last_fetch_time) < self._cache_ttl_seconds:
            return self._cached_events

        if not ECONOMIC_CALENDAR_URL:
            return []

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(ECONOMIC_CALENDAR_URL)

            if resp.status_code == 200:
                events = resp.json()
                if isinstance(events, list):
                    self._cached_events = events
                    self._last_fetch_time = now
                    return events
        except Exception as e:
            logger.error(f"Erreur calendrier : {e}")

        return self._cached_events

    async def get_upcoming_events(
        self,
        symbol: str,
        window_minutes_before: int = 60,
        window_minutes_after: int = 30,
    ) -> Dict[str, Any]:
        events = await self.fetch_calendar()
        currencies = self._extract_currencies(symbol)

        if not events:
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
            ev_currency = str(ev.get("currency", ev.get("country", ""))).upper()
            if ev_currency not in currencies and ev_currency != "ALL":
                continue

            ev_impact = str(ev.get("impact", "")).lower()
            ev_date_str = ev.get("date", ev.get("time", ""))

            try:
                ev_dt = datetime.fromisoformat(str(ev_date_str).replace("Z", "+00:00"))
                if ev_dt.tzinfo is None:
                    ev_dt = ev_dt.replace(tzinfo=timezone.utc)

                time_diff_min = (ev_dt - now_dt).total_seconds() / 60.0

                if -window_minutes_after <= time_diff_min <= window_minutes_before:
                    is_high = "high" in ev_impact or "red" in ev_impact
                    if is_high:
                        has_high_impact = True

                    matching_events.append({
                        "title": ev.get("title", "Événement économique"),
                        "currency": ev_currency,
                        "impact": ev.get("impact", "Medium"),
                        "minutes_relative": round(time_diff_min, 1),
                    })
            except Exception:
                continue

        if has_high_impact:
            calendar_score = 1
            summary = f"⚠️ Annonce majeure imminente/récente ({len(matching_events)} év.)"
        elif matching_events:
            calendar_score = 3
            summary = f"Événements modérés détectés ({len(matching_events)} év.)"
        else:
            calendar_score = 5
            summary = "Aucun événement économique perturbateur proche"

        return {
            "has_high_impact": has_high_impact,
            "events": matching_events,
            "calendar_score": calendar_score,
            "summary": summary,
        }


economic_calendar_service = EconomicCalendarService()
