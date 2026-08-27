"""
Schémas Pydantic pour les utilisateurs.

Utilisés pour la validation des requêtes/réponses API.
"""

from typing import Optional
from pydantic import BaseModel, Field


# ── Requêtes ─────────────────────────────────────────────

class UserRegister(BaseModel):
    username: str = Field(
        ...,
        min_length=3,
        max_length=50,
        description="Nom d'utilisateur unique",
    )
    password: str = Field(
        ...,
        min_length=6,
        max_length=100,
        description="Mot de passe (min 6 caractères)",
    )


class UserLogin(BaseModel):
    username: str
    password: str


class FCMTokenUpdate(BaseModel):
    fcm_token: str = Field(
        ...,
        description="Token Firebase de l'appareil",
    )


class UserPreferencesUpdate(BaseModel):
    notifications_enabled: Optional[bool] = None
    preferred_assets: Optional[str] = None


# ── Réponses ─────────────────────────────────────────────

class UserResponse(BaseModel):
    id: int
    username: str
    role: str
    is_active: bool
    notifications_enabled: bool
    preferred_assets: str

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    username: str


# ── Admin ────────────────────────────────────────────────

class AdminUserListItem(BaseModel):
    """Ce que l'admin voit dans son tableau (pas de mot de passe)."""
    id: int
    username: str
    role: str
    has_fcm_token: bool
    is_active: bool
    notifications_enabled: bool
    created_at: str

    class Config:
        from_attributes = True
class SystemTimeframeResponse(BaseModel):
    main_timeframe: str
    confirmation_timeframe: str

class SystemTimeframeUpdate(BaseModel):
    main_timeframe: str
    confirmation_timeframe: str
