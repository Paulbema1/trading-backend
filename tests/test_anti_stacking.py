"""
Test P0 obligatoire : anti-stacking (§24 du cahier des charges).

Vérifie qu'une seule position active par symbole est autorisée en LIVE,
et qu'un retournement (direction opposée) est bien géré. N'affecte aucune
règle de scoring : porte uniquement sur la couche d'orchestration/dispatch.
"""
import pytest
from src.schemas.signal import SignalResponse, ActionEnum, DataQualityEnum
from src.services.signal_dispatch import persist_and_dispatch
from src.models.position import OpenPosition


def _make_signal(symbol="EUR/USD", action=ActionEnum.BUY, score=80, entry=1.10, sl=1.095):
    return SignalResponse(
        signal_id="test-uuid-0001",
        symbol=symbol,
        action=action,
        confidence=score,
        score=score,
        entry_price=entry,
        stop_loss=sl,
        take_profit_1=entry + 0.005,
        take_profit_2=entry + 0.010,
        take_profit_3=entry + 0.015,
        risk_reward=2.5,
        main_timeframe="1h",
        confirmation_timeframe="4h",
        data_quality=DataQualityEnum.GOOD,
        ai_confirmed=True,
        reasons="test",
    )


@pytest.mark.asyncio
async def test_second_identical_direction_signal_blocked(db_session, monkeypatch):
    """Un second BUY sur un symbole déjà en position BUY doit être refusé (anti-stacking)."""
    async def fake_broadcast(signal, db):
        return {"sent": True}
    monkeypatch.setattr("src.services.signal_dispatch.notification_service.broadcast_signal", fake_broadcast)

    first = _make_signal(action=ActionEnum.BUY, entry=1.1000)
    second = _make_signal(action=ActionEnum.BUY, entry=1.1050)  # signal différent (fingerprint différent), même direction

    dispatched_1 = await persist_and_dispatch(first, db_session)
    dispatched_2 = await persist_and_dispatch(second, db_session)

    assert dispatched_1 is True
    assert dispatched_2 is False  # bloqué par l'anti-stacking

    positions = db_session.query(OpenPosition).filter(OpenPosition.symbol == "EUR/USD").all()
    assert len(positions) == 1
    assert positions[0].action == "BUY"


@pytest.mark.asyncio
async def test_opposite_direction_signal_reverses_position(db_session, monkeypatch):
    """Un signal de direction opposée doit clôturer la position existante et en ouvrir une nouvelle."""
    async def fake_broadcast(signal, db):
        return {"sent": True}
    monkeypatch.setattr("src.services.signal_dispatch.notification_service.broadcast_signal", fake_broadcast)

    buy_signal = _make_signal(action=ActionEnum.BUY, entry=1.1000)
    sell_signal = _make_signal(action=ActionEnum.SELL, entry=1.1000, sl=1.105)

    dispatched_buy = await persist_and_dispatch(buy_signal, db_session)
    dispatched_sell = await persist_and_dispatch(sell_signal, db_session)

    assert dispatched_buy is True
    assert dispatched_sell is True  # retournement autorisé

    positions = db_session.query(OpenPosition).filter(OpenPosition.symbol == "EUR/USD").all()
    assert len(positions) == 1
    assert positions[0].action == "SELL"


@pytest.mark.asyncio
async def test_expired_position_allows_same_direction_signal(db_session, monkeypatch):
    """
    Une position active depuis plus de POSITION_EXPIRY_HOURS doit être considérée
    expirée : un nouveau signal de MÊME direction doit alors être autorisé,
    évitant un blocage indéfini si la tendance persiste (ou si le timeframe
    d'analyse change) sans jamais produire de signal opposé.
    """
    from datetime import datetime, timezone, timedelta
    from src.core.config import POSITION_EXPIRY_HOURS

    async def fake_broadcast(signal, db):
        return {"sent": True}
    monkeypatch.setattr("src.services.signal_dispatch.notification_service.broadcast_signal", fake_broadcast)

    first = _make_signal(action=ActionEnum.BUY, entry=1.1000)
    dispatched_1 = await persist_and_dispatch(first, db_session)
    assert dispatched_1 is True

    # On vieillit artificiellement la position pour simuler l'expiration.
    position = db_session.query(OpenPosition).filter(OpenPosition.symbol == "EUR/USD").first()
    position.opened_at = datetime.now(timezone.utc) - timedelta(hours=POSITION_EXPIRY_HOURS + 1)
    db_session.commit()

    second = _make_signal(action=ActionEnum.BUY, entry=1.1080)  # même direction, signal différent
    dispatched_2 = await persist_and_dispatch(second, db_session)

    assert dispatched_2 is True  # autorisé car l'ancienne position a expiré

    position_after = db_session.query(OpenPosition).filter(OpenPosition.symbol == "EUR/USD").first()
    assert position_after.signal_id == second.signal_id


@pytest.mark.asyncio
async def test_non_expired_position_still_blocks_same_direction_signal(db_session, monkeypatch):
    """Une position récente (moins de POSITION_EXPIRY_HOURS) doit continuer à bloquer normalement."""
    async def fake_broadcast(signal, db):
        return {"sent": True}
    monkeypatch.setattr("src.services.signal_dispatch.notification_service.broadcast_signal", fake_broadcast)

    first = _make_signal(action=ActionEnum.BUY, entry=1.1000)
    second = _make_signal(action=ActionEnum.BUY, entry=1.1080)

    dispatched_1 = await persist_and_dispatch(first, db_session)
    dispatched_2 = await persist_and_dispatch(second, db_session)

    assert dispatched_1 is True
    assert dispatched_2 is False  # position encore fraîche -> toujours bloquée

