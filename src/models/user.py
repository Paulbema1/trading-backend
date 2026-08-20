"""
Modèle SQLAlchemy pour les utilisateurs.

Un utilisateur = un pseudo + un mot de passe hashé.
Pas d'email, pas de téléphone.
Le FCM Token est lié à l'appareil, pas à la personne.
"""

from datetime import datetime, timezone

from sqlalchemy import Column, Integer, String, Boolean, DateTime

from src.core.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)

    # ADMIN ou USER
    role = Column(String(10), default="USER", nullable=False)

    # Firebase Cloud Messaging token de l'appareil
    fcm_token = Column(String(500), nullable=True)

    # Préférences
    is_active = Column(Boolean, default=True)
    notifications_enabled = Column(Boolean, default=True)

    # Actifs préférés (séparés par des virgules)
    # Exemple : "EUR/USD,GBP/USD,XAU/USD"
    preferred_assets = Column(
        String(200),
        default="EUR/USD,GBP/USD,USD/JPY,XAU/USD",
    )

    created_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
    )