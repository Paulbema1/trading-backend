"""
TradeVision AI - Configuration des Fixtures de Test.
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.core.database import Base, get_db
from src.main import app

# Base SQLite en mémoire pour les tests
TEST_DATABASE_URL = "sqlite:///:memory:"
test_engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture(scope="function")
def db_session():
    """Crée une base de données temporaire et propre pour chaque test."""
    Base.metadata.create_all(bind=test_engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=test_engine)


@pytest.fixture
def sample_bullish_df():
    """
    Génère 150 bougies avec 3 vagues haussières institutionnelles nettes :
    Higher Highs (HH) et Higher Lows (HL), se terminant par une poussée haussière.
    """
    n = 150
    dates = [datetime(2025, 1, 1) + timedelta(hours=i) for i in range(n)]

    # 3 vagues parfaites : Vague 1 (1.100 -> 1.110 -> 1.106), Vague 2 (1.106 -> 1.120 -> 1.115), Vague 3 (1.115 -> 1.135)
    w1_up = np.linspace(1.1000, 1.1100, 30)
    w1_down = np.linspace(1.1100, 1.1060, 15)
    w2_up = np.linspace(1.1060, 1.1220, 35)
    w2_down = np.linspace(1.1220, 1.1160, 20)
    w3_up = np.linspace(1.1160, 1.1350, 50)

    close_prices = np.concatenate([w1_up, w1_down, w2_up, w2_down, w3_up])[:n]
    open_prices = np.roll(close_prices, 1)
    open_prices[0] = 1.0995

    high_prices = np.maximum(open_prices, close_prices) + 0.0004
    low_prices = np.minimum(open_prices, close_prices) - 0.0004

    return pd.DataFrame({
        "datetime": dates,
        "open": open_prices,
        "high": high_prices,
        "low": low_prices,
        "close": close_prices,
        "volume": np.full(n, 2500.0),
    })


@pytest.fixture
def sample_bearish_df():
    """
    Génère 150 bougies avec 3 vagues baissières institutionnelles nettes :
    Lower Highs (LH) et Lower Lows (LL), se terminant par une chute continue.
    """
    n = 150
    dates = [datetime(2025, 1, 1) + timedelta(hours=i) for i in range(n)]

    # 3 vagues parfaites : Vague 1 (1.150 -> 1.140 -> 1.144), Vague 2 (1.144 -> 1.128 -> 1.134), Vague 3 (1.134 -> 1.115)
    w1_down = np.linspace(1.1500, 1.1400, 30)
    w1_up = np.linspace(1.1400, 1.1440, 15)
    w2_down = np.linspace(1.1440, 1.1280, 35)
    w2_up = np.linspace(1.1280, 1.1340, 20)
    w3_down = np.linspace(1.1340, 1.1150, 50)

    close_prices = np.concatenate([w1_down, w1_up, w2_down, w2_up, w3_down])[:n]
    open_prices = np.roll(close_prices, 1)
    open_prices[0] = 1.1505

    high_prices = np.maximum(open_prices, close_prices) + 0.0004
    low_prices = np.minimum(open_prices, close_prices) - 0.0004

    return pd.DataFrame({
        "datetime": dates,
        "open": open_prices,
        "high": high_prices,
        "low": low_prices,
        "close": close_prices,
        "volume": np.full(n, 2500.0),
    })