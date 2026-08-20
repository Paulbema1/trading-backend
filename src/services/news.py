"""
TradeVision AI - Service des Actualités (News).

Responsabilités :
- Récupérer les flux RSS ou actualités financières
- Mettre en cache les flux (TTL 15 minutes)
- Identifier les titres concernant les devises de la paire
- Déterminer un biais initial (BULLISH, BEARISH, NEUTRAL)
"""

import time
import re
from typing import List, Dict, Any, Optional
import httpx

from src.core.config import NEWS_RSS_URL
from src.core.logging import get_logger

logger = get_logger(__name__)


class NewsService:
    """Service d'analyse fondamentale et des flux d'actualités."""

    def __init__(self):
        self._cached_news: List[Dict[str, Any]] = []
        self._last_fetch_time: float = 0.0
        self._cache_ttl_seconds: int = 900  # 15 minutes

        # Mots-clés de sentiment de base
        self.BULLISH_KEYWORDS = [
            "rate hike", "hawkish", "growth", "strong", "higher inflation",
            "gains", "rally", "outperform", "bullish", "hausse", "croissance",
            "faucon", "renforcement", "solid"
        ]
        self.BEARISH_KEYWORDS = [
            "rate cut", "dovish", "recession", "weak", "cooling inflation",
            "slump", "drop", "underperform", "bearish", "baisse", "ralentissement",
            "colombe", "affaiblissement", "crisis"
        ]

    async def fetch_news(self) -> List[Dict[str, Any]]:
        """Récupère les actualités récentes depuis le flux configuré."""
        now = time.time()
        if self._cached_news and (now - self._last_fetch_time) < self._cache_ttl_seconds:
            return self._cached_news

        if not NEWS_RSS_URL:
            # Pas d'URL fournie : fonctionnement normal en mode technique pure
            return []

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(NEWS_RSS_URL)

            if resp.status_code == 200:
                text = resp.text
                items = self._parse_simple_feed(text)
                self._cached_news = items
                self._last_fetch_time = now
                logger.info(f"Actualités mises à jour ({len(items)} articles).")
                return items
        except Exception as e:
            logger.error(f"Erreur lors de la récupération des news : {e}")

        return self._cached_news

    def _parse_simple_feed(self, raw_xml: str) -> List[Dict[str, Any]]:
        """Parseur léger pour flux RSS XML sans dépendance lourde supplémentaire."""
        items = []
        raw_items = re.findall(r"<item>(.*?)</item>", raw_xml, re.DOTALL | re.IGNORECASE)

        for raw in raw_items:
            title_match = re.search(r"<title>(.*?)</title>", raw, re.DOTALL | re.IGNORECASE)
            title = title_match.group(1).strip() if title_match else ""
            # Nettoyer les balises CDATA éventuelles
            title = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", title)

            pub_match = re.search(r"<pubDate>(.*?)</pubDate>", raw, re.DOTALL | re.IGNORECASE)
            pub_date = pub_match.group(1).strip() if pub_match else ""

            if title:
                items.append({
                    "title": title,
                    "published": pub_date,
                })
        return items

    async def analyze_sentiment(self, symbol: str) -> Dict[str, Any]:
        """
        Analyse les actualités liées au symbole et extrait le biais fondamental.

        Retourne :
        {
            "bias": "BUY" | "SELL" | "NEUTRAL",
            "relevant_news": [...],
            "summary": str
        }
        """
        all_news = await self.fetch_news()
        if not all_news:
            return {
                "bias": "NEUTRAL",
                "relevant_news": [],
                "summary": "Aucune actualité majeure récente",
            }

        symbol_clean = symbol.replace("/", "").upper()
        currencies = [symbol_clean[:3], symbol_clean[3:]] if len(symbol_clean) == 6 else ["USD", "GOLD"]

        relevant = []
        bullish_count = 0
        bearish_count = 0

        for item in all_news[:20]:  # Scan des 20 dernières actualités
            title = item.get("title", "").lower()

            # Vérifier si l'article mentionne une des devises
            is_relevant = any(c.lower() in title for c in currencies) or ("forex" in title) or ("fed" in title) or ("ecb" in title)
            if not is_relevant:
                continue

            relevant.append(item.get("title"))

            # Évaluation du sentiment du titre
            for kw in self.BULLISH_KEYWORDS:
                if kw in title:
                    bullish_count += 1
            for kw in self.BEARISH_KEYWORDS:
                if kw in title:
                    bearish_count += 1

        if bullish_count > bearish_count and bullish_count >= 2:
            bias = "BUY"
            summary = f"Actualités orientées à la hausse ({bullish_count} signaux haussiers)"
        elif bearish_count > bullish_count and bearish_count >= 2:
            bias = "SELL"
            summary = f"Actualités orientées à la baisse ({bearish_count} signaux baissiers)"
        else:
            bias = "NEUTRAL"
            summary = "Sentiment d'actualité neutre ou équilibré"

        return {
            "bias": bias,
            "relevant_news": relevant[:5],
            "summary": summary,
        }


# Instance globale partagée
news_service = NewsService()