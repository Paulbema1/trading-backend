"""
Tests unitaires pour l'authentification et les comptes.
"""

from src.core.auth import hash_password, verify_password, create_access_token, decode_access_token
from src.models.user import User


def test_password_hashing():
    password = "SuperSecretPassword123"
    hashed = hash_password(password)
    assert hashed != password
    assert verify_password(password, hashed) is True
    assert verify_password("WrongPassword", hashed) is False


def test_jwt_token_generation():
    payload = {"sub": "paul_trader", "role": "ADMIN"}
    token = create_access_token(payload)
    assert isinstance(token, str)

    decoded = decode_access_token(token)
    assert decoded is not None
    assert decoded.get("sub") == "paul_trader"
    assert decoded.get("role") == "ADMIN"


def test_user_creation_and_fcm(db_session):
    user = User(
        username="trader_bob",
        hashed_password=hash_password("mypassword"),
        role="USER",
        fcm_token="fcm_token_device_abc123",
    )
    db_session.add(user)
    db_session.commit()

    saved = db_session.query(User).filter(User.username == "trader_bob").first()
    assert saved is not None
    assert saved.role == "USER"
    assert saved.fcm_token == "fcm_token_device_abc123"