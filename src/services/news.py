"""
TradeVision AI - Service des Actualités (News).
"""

import time
import re
from typing import List, Dict, Any, Optional
import httpx

from src.core.config import NEWS_RSS_URL
from src.services.test_lab_service import test_lab_service
from src.core.logging import get_logger

logger = get_logger(__name__)


class NewsService:

    def __init__(self):
        self._cached_news: List[Dict[str, Any]] = []
        self._last_fetch_time: float = 0.0
        self._cache_ttl_seconds: int = 900

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
        # 🧪 INTERCEPTION TEST LAB
        if test_lab_service.is_enabled():
            injected = test_lab_service.get_injected_news()
            if injected:
                logger.debug(f"🧪 [TEST LAB] Utilisation des news injectées ({len(injected)} articles)")
                return injected

        now = time.time()
        if self._cached_news and (now - self._last_fetch_time) < self._cache_ttl_seconds:
            return self._cached_news

        if not NEWS_RSS_URL:
            return []

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(NEWS_RSS_URL)

            if resp.status_code == 200:
                items = self._parse_simple_feed(resp.text)
                self._cached_news = items
                self._last_fetch_time = now
                return items
        except Exception as e:
            logger.error(f"Erreur news : {e}")

        return self._cached_news

    def _parse_simple_feed(self, raw_xml: str) -> List[Dict[str, Any]]:
        items = []
        raw_items = re.findall(r"<item>(.*?)</item>", raw_xml, re.DOTALL | re.IGNORECASE)

        for raw in raw_items:
            title_match = re.search(r"<title>(.*?)</title>", raw, re.DOTALL | re.IGNORECASE)
            title = title_match.group(1).strip() if title_match else ""
            title = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", title)

            pub_match = re.search(r"<pubDate>(.*?)</pubDate>", raw, re.DOTALL | re.IGNORECASE)
            pub_date = pub_match.group(1).strip() if pub_match else ""

            if title:
                items.append({"title": title, "published": pub_date})
        return items

    async def analyze_sentiment(self, symbol: str) -> Dict[str, Any]:
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

        for item in all_news[:20]:
            title = item.get("title", "").lower()
            is_relevant = any(c.lower() in title for c in currencies) or ("forex" in title) or ("fed" in title) or ("ecb" in title)
            if not is_relevant:
                continue

            relevant.append(item.get("title"))

            for kw in self.BULLISH_KEYWORDS:
                if kw in title:
                    bullish_count += 1
            for kw in self.BEARISH_KEYWORDS:
                if kw in title:
                    bearish_count += 1

        if bullish_count > bearish_count and bullish_count >= 1:
            bias = "BUY"
            summary = f"Actualités orientées à la hausse ({bullish_count} signaux)"
        elif bearish_count > bullish_count and bearish_count >= 1:
            bias = "SELL"
            summary = f"Actualités orientées à la baisse ({bearish_count} signaux)"
        else:
            bias = "NEUTRAL"
            summary = "Sentiment d'actualité neutre"

        return {
            "bias": bias,
            "relevant_news": relevant[:5],
            "summary": summary,
        }


news_service = NewsService()
