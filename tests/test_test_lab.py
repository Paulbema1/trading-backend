"""
TradeVision AI - Tests unitaires de la passerelle API Test Lab.
"""

import pytest
from fastapi.testclient import TestClient
from src.main import app
from src.services.test_lab_service import test_lab_service

client = TestClient(app)


def test_test_lab_mode_toggle():
    # Désactiver d'abord
    response = client.post("/api/v2/test/mode", json={"enabled": False})
    assert response.status_code == 200
    assert response.json()["simulation_mode"] is False
    assert test_lab_service.is_enabled() is False

    # Activer
    response = client.post("/api/v2/test/mode", json={"enabled": True})
    assert response.status_code == 200
    assert response.json()["simulation_mode"] is True
    assert test_lab_service.is_enabled() is True

    # Désactiver
    client.post("/api/v2/test/mode", json={"enabled": False})


def test_test_lab_injections():
    # Activer le mode test
    client.post("/api/v2/test/mode", json={"enabled": True})

    # Injecter temps
    resp = client.post("/api/v2/test/inject/time", json={"simulation_time": "2026-08-25T10:00:00Z"})
    assert resp.status_code == 200
    assert test_lab_service.get_simulated_time() == "2026-08-25T10:00:00Z"

    # Injecter bougies
    candles = [
        {
            "datetime": f"2026-08-25T09:{15*i:02d}:00Z",
            "open": 1.1000 + i * 0.0001,
            "high": 1.1010 + i * 0.0001,
            "low": 1.0990,
            "close": 1.1005 + i * 0.0001,
            "volume": 1000.0,
        }
        for i in range(10)
    ]
    resp = client.post("/api/v2/test/inject/market", json={"symbol": "EUR/USD", "interval": "15m", "candles": candles})
    assert resp.status_code == 200

    # Injecter news
    news = [{"title": "ECB Hawk Statement TEST", "published": "2026-08-25T09:30:00Z", "impact": "HIGH"}]
    resp = client.post("/api/v2/test/inject/news", json={"news": news})
    assert resp.status_code == 200

    # Injecter calendrier
    cal = [{"title": "CPI Release TEST", "currency": "EUR", "impact": "HIGH", "time": "2026-08-25T10:00:00Z"}]
    resp = client.post("/api/v2/test/inject/calendar", json={"events": cal})
    assert resp.status_code == 200

    # Vérifier le statut
    status_resp = client.get("/api/v2/test/status")
    assert status_resp.status_code == 200
    st = status_resp.json()
    assert st["simulation_mode"] is True
    assert st["injected_pairs_count"] >= 1

    # Reset
    reset_resp = client.post("/api/v2/test/reset")
    assert reset_resp.status_code == 200

    # Désactiver mode test
    client.post("/api/v2/test/mode", json={"enabled": False})
