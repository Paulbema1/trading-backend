from src.engine.signal_engine import signal_engine
from src.schemas.signal import ActionEnum
from src.services.signal_dispatch import fingerprint
from src.schemas.signal import SignalResponse

def test_v9_risk_levels_buy_and_sell():
    buy = signal_engine._calculate_levels("EUR/USD", ActionEnum.BUY, 1.10000, 0.00200)
    sell = signal_engine._calculate_levels("EUR/USD", ActionEnum.SELL, 1.10000, 0.00200)
    assert buy["stop_loss"] == 1.097
    assert buy["take_profit_2"] == 1.1075
    assert sell["stop_loss"] == 1.103
    assert sell["take_profit_2"] == 1.0925
    assert buy["risk_reward"] == 2.5

def test_signal_fingerprint_differs_by_asset_and_levels():
    a=SignalResponse(symbol="EUR/USD",action=ActionEnum.BUY,confidence=80,score=80,main_timeframe="1h",entry_price=1.1,stop_loss=1.097,take_profit_2=1.1075)
    b=SignalResponse(symbol="XAU/USD",action=ActionEnum.BUY,confidence=80,score=80,main_timeframe="1h",entry_price=2400,stop_loss=2390,take_profit_2=2425)
    assert fingerprint(a) != fingerprint(b)
