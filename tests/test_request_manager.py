"""
Tests de gestion des erreurs 429 et de la rotation des clés Twelve Data.
"""

import time
import pytest
from src.services.request_manager import RequestManager, KeyStatus, ApiKeySlot


def test_api_key_slot_429_cooldown():
    slot = ApiKeySlot(key="fake_key_1", name="Key_1")
    assert slot.is_ready() is True

    # Détection d'un 429 -> pause de 60s
    slot.mark_429(cooldown_seconds=60)
    assert slot.is_ready() is False
    assert slot.status == KeyStatus.DEGRADED
    assert slot.total_429 == 1


def test_key_rotation_fallback():
    manager = RequestManager()
    manager.slots = [
        ApiKeySlot(key="key_1", name="Key_1"),
        ApiKeySlot(key="key_2", name="Key_2"),
    ]

    # Clé 1 subit un 429
    manager.slots[0].mark_429(cooldown_seconds=100)

    # Le gestionnaire doit automatiquement fournir la Clé 2
    available = manager._get_available_slot()
    assert available is not None
    assert available.name == "Key_2"


def test_cooldown_enforcement_over_time():
    """Une clé en cooldown n'est pas utilisable ; elle redevient prête après expiration."""
    slot = ApiKeySlot(key="fake_key", name="Key_1")
    slot.mark_429(cooldown_seconds=1)

    assert slot.is_ready() is False

    time.sleep(1.05)
    assert slot.is_ready() is True


def test_exhaustion_after_three_consecutive_failures():
    """Après 3 échecs consécutifs, la clé passe en EXHAUSTED avec un cooldown plus long."""
    slot = ApiKeySlot(key="fake_key", name="Key_1")

    slot.mark_429(cooldown_seconds=1)
    assert slot.status == KeyStatus.DEGRADED
    slot.mark_429(cooldown_seconds=1)
    assert slot.status == KeyStatus.DEGRADED
    slot.mark_429(cooldown_seconds=1)

    assert slot.status == KeyStatus.EXHAUSTED
    assert slot.consecutive_failures == 3
    # Le cooldown d'exhaustion doit être significativement plus long que le cooldown simple.
    assert (slot.cooldown_until - time.time()) > 1


@pytest.mark.asyncio
async def test_all_keys_in_cooldown_returns_explicit_error():
    """Si toutes les clés sont en cooldown, execute_request doit renvoyer une erreur explicite (pas d'exception)."""
    manager = RequestManager()
    manager.slots = [
        ApiKeySlot(key="key_1", name="Key_1"),
        ApiKeySlot(key="key_2", name="Key_2"),
    ]
    manager.slots[0].mark_429(cooldown_seconds=300)
    manager.slots[1].mark_429(cooldown_seconds=300)

    data, error = await manager.execute_request("time_series", {"symbol": "EUR/USD"})

    assert data is None
    assert error is not None
    assert "cooldown" in error.lower()


def test_no_configured_keys_returns_warning_state():
    """Sans aucune clé configurée, le RequestManager ne doit pas planter et doit exposer une liste vide."""
    manager = RequestManager()
    manager.slots = []
    assert manager._get_available_slot() is None
    assert manager.get_status_metrics() == []