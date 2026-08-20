"""
Tests de gestion des erreurs 429 et de la rotation des clés Twelve Data.
"""

import time
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