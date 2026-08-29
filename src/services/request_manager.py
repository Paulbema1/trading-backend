"""
TradeVision AI - Twelve Data Request Manager.

Gère :
- L'utilisation des 2 clés API Twelve Data
- La rotation dynamique et les basculements automatiques
- La gestion des codes 429 (Rate Limit / Quota)
- Les cooldowns progressifs
- Les métriques de consommation
"""

import time
import httpx
from typing import Optional, Dict, Any, List, Tuple
from enum import Enum

from src.core.config import (
    TWELVE_DATA_BASE_URL,
    TWELVE_DATA_API_KEYS,
    TWELVE_DATA_COOLDOWN_SECONDS,
    TWELVE_DATA_EXHAUSTED_SECONDS,
)
from src.core.logging import get_logger

logger = get_logger(__name__)


class KeyStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    DEGRADED = "DEGRADED"
    EXHAUSTED = "EXHAUSTED"


class ApiKeySlot:
    """Représente une clé API et son état d'usage."""

    def __init__(self, key: str, name: str):
        self.key = key
        self.name = name
        self.status = KeyStatus.AVAILABLE
        self.cooldown_until = 0.0
        self.consecutive_failures = 0
        self.total_requests = 0
        self.total_success = 0
        self.total_429 = 0

    def is_ready(self) -> bool:
        """Vérifie si la clé peut être utilisée immédiatement."""
        return time.time() >= self.cooldown_until

    def mark_success(self):
        """Enregistre un appel réussi et réinitialise les compteurs d'échecs."""
        self.consecutive_failures = 0
        self.status = KeyStatus.AVAILABLE
        self.total_requests += 1
        self.total_success += 1

    def mark_429(self, cooldown_seconds: int = TWELVE_DATA_COOLDOWN_SECONDS):
        """Applique un cooldown immédiat suite à un code 429."""
        self.consecutive_failures += 1
        self.total_requests += 1
        self.total_429 += 1
        self.cooldown_until = time.time() + cooldown_seconds

        if self.consecutive_failures >= 3:
            self.status = KeyStatus.EXHAUSTED
            self.cooldown_until = time.time() + TWELVE_DATA_EXHAUSTED_SECONDS
        else:
            self.status = KeyStatus.DEGRADED

        logger.warning(
            f"[{self.name}] 429 Détecté! Cooldown de {cooldown_seconds}s appliqué. "
            f"Statut: {self.status.value}"
        )

    def mark_network_error(self, cooldown_seconds: int = 10):
        """Applique une courte pause pour erreur réseau temporaire."""
        self.consecutive_failures += 1
        self.total_requests += 1
        self.cooldown_until = time.time() + cooldown_seconds
        logger.warning(f"[{self.name}] Erreur réseau/timeout. Cooldown court de {cooldown_seconds}s.")


class RequestManager:
    """Gestionnaire central des requêtes Twelve Data."""

    def __init__(self):
        self.slots: List[ApiKeySlot] = []
        for idx, key in enumerate(TWELVE_DATA_API_KEYS):
            if key:
                self.slots.append(ApiKeySlot(key=key, name=f"Key_{idx+1}"))

        if not self.slots:
            logger.warning("Aucune clé Twelve Data configurée dans l'environnement.")

    def _get_available_slot(self) -> Optional[ApiKeySlot]:
        """Sélectionne le premier slot disponible."""
        now = time.time()
        for slot in self.slots:
            if slot.is_ready():
                return slot
        return None

    async def execute_request(
        self,
        endpoint: str,
        params: Dict[str, Any],
        timeout: float = 10.0,
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """
        Exécute une requête vers Twelve Data avec basculement automatique sur la clé suivante.

        Retourne:
            (json_data, error_message)
        """
        if not self.slots:
            return None, "Aucune clé Twelve Data configurée."

        attempts = 0
        max_attempts = len(self.slots)

        while attempts < max_attempts:
            slot = self._get_available_slot()
            if not slot:
                return None, "Toutes les clés Twelve Data sont actuellement en cooldown (429/quota)."

            req_params = params.copy()
            req_params["apikey"] = slot.key
            url = f"{TWELVE_DATA_BASE_URL}/{endpoint.lstrip('/')}"

            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    resp = await client.get(url, params=req_params)

                if resp.status_code == 429:
                    slot.mark_429(cooldown_seconds=TWELVE_DATA_COOLDOWN_SECONDS)
                    attempts += 1
                    continue

                if resp.status_code == 200:
                    data = resp.json()

                    if data.get("status") == "error":
                        error_code = data.get("code")
                        error_msg = data.get("message", "")

                        if error_code == 429 or "api key" in error_msg.lower() or "limit" in error_msg.lower():
                            slot.mark_429(cooldown_seconds=TWELVE_DATA_COOLDOWN_SECONDS)
                            attempts += 1
                            continue

                        slot.mark_success()
                        return None, f"Twelve Data Error: {error_msg}"

                    slot.mark_success()
                    return data, None

                if resp.status_code >= 500:
                    slot.mark_network_error(cooldown_seconds=15)
                    attempts += 1
                    continue

                return None, f"Erreur HTTP inattendue : {resp.status_code}"

            except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ConnectError):
                slot.mark_network_error(cooldown_seconds=10)
                attempts += 1
                continue
            except Exception as e:
                logger.error(f"Erreur inattendue dans execute_request: {e}")
                return None, str(e)

        return None, "Échec des requêtes sur l'ensemble des clés disponibles."

    def get_status_metrics(self) -> List[Dict[str, Any]]:
        """Expose les statistiques de chaque clé (utilisé par l'App Admin)."""
        now = time.time()
        metrics = []
        for slot in self.slots:
            remaining_cooldown = max(0, int(slot.cooldown_until - now))
            metrics.append({
                "name": slot.name,
                "status": slot.status.value,
                "is_ready": slot.is_ready(),
                "cooldown_remaining_sec": remaining_cooldown,
                "total_requests": slot.total_requests,
                "total_success": slot.total_success,
                "total_429": slot.total_429,
                "consecutive_failures": slot.consecutive_failures,
            })
        return metrics


# Instance globale partagée
request_manager = RequestManager()