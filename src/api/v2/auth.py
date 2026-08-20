"""
TradeVision AI - Routes d'Authentification (v2).

- Inscription : Pseudo + Mot de passe (pas de numéro de téléphone obligatoire)
- Connexion : Génère un JWT avec rôle (USER ou ADMIN)
- Enregistrement du Token FCM pour les alertes push
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from src.core.database import get_db
from src.core.auth import (
    hash_password,
    verify_password,
    create_access_token,
    get_current_user,
)
from src.models.user import User
from src.schemas.user import (
    UserRegister,
    UserLogin,
    TokenResponse,
    UserResponse,
    FCMTokenUpdate,
    UserPreferencesUpdate,
)
from src.core.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/auth", tags=["Authentification"])


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(user_in: UserRegister, db: Session = Depends(get_db)):
    """Crée un nouveau compte utilisateur et renvoie son token d'accès."""
    clean_username = user_in.username.strip()

    # Vérifier l'unicité du pseudo
    existing_user = db.query(User).filter(User.username == clean_username).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ce nom d'utilisateur est déjà utilisé.",
        )

    # Premier utilisateur enregistré = ADMIN, sinon USER
    user_count = db.query(User).count()
    role = "ADMIN" if user_count == 0 else "USER"

    new_user = User(
        username=clean_username,
        hashed_password=hash_password(user_in.password),
        role=role,
        is_active=True,
        notifications_enabled=True,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    logger.info(f"Nouveau compte créé : {new_user.username} (Rôle: {role})")

    token = create_access_token(data={"sub": new_user.username, "role": new_user.role})
    return TokenResponse(
        access_token=token,
        role=new_user.role,
        username=new_user.username,
    )


@router.post("/login", response_model=TokenResponse)
def login(user_in: UserLogin, db: Session = Depends(get_db)):
    """Connecte un utilisateur et renvoie son token d'accès JWT."""
    user = db.query(User).filter(User.username == user_in.username.strip()).first()

    if not user or not verify_password(user_in.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Nom d'utilisateur ou mot de passe incorrect.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Ce compte est désactivé.",
        )

    token = create_access_token(data={"sub": user.username, "role": user.role})
    return TokenResponse(
        access_token=token,
        role=user.role,
        username=user.username,
    )


@router.post("/fcm-token", status_code=status.HTTP_200_OK)
def update_fcm_token(
    payload: FCMTokenUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Associe le token de notification Firebase du téléphone au compte utilisateur."""
    current_user.fcm_token = payload.fcm_token.strip()
    db.commit()
    logger.debug(f"Token FCM mis à jour pour {current_user.username}")
    return {"message": "Token de notification enregistré avec succès."}


@router.get("/me", response_model=UserResponse)
def get_profile(current_user: User = Depends(get_current_user)):
    """Retourne les informations du profil utilisateur connecté."""
    return current_user


@router.put("/preferences", response_model=UserResponse)
def update_preferences(
    payload: UserPreferencesUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Met à jour les préférences de l'utilisateur (actifs suivis, activation notifs)."""
    if payload.notifications_enabled is not None:
        current_user.notifications_enabled = payload.notifications_enabled
    if payload.preferred_assets is not None:
        current_user.preferred_assets = payload.preferred_assets

    db.commit()
    db.refresh(current_user)
    return current_user