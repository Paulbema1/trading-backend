"""
Firebase Cloud Messaging (FCM).

Envoie des notifications push aux appareils des utilisateurs.
"""

import logging
from typing import List, Optional

import firebase_admin
from firebase_admin import credentials, messaging

from src.core.config import (
    FIREBASE_PROJECT_ID,
    FIREBASE_CLIENT_EMAIL,
    FIREBASE_PRIVATE_KEY,
)

logger = logging.getLogger(__name__)

# ── Initialisation ───────────────────────────────────────

_firebase_initialized = False


def init_firebase():
    """Initialise Firebase Admin SDK."""
    global _firebase_initialized

    if _firebase_initialized:
        return

    if not FIREBASE_PROJECT_ID or not FIREBASE_CLIENT_EMAIL:
        logger.warning(
            "Firebase non configuré. "
            "Les notifications push seront désactivées."
        )
        return

    try:
        cred = credentials.Certificate({
            "type": "service_account",
            "project_id": FIREBASE_PROJECT_ID,
            "private_key_id": "tradevision-key",
            "private_key": FIREBASE_PRIVATE_KEY,
            "client_email": FIREBASE_CLIENT_EMAIL,
            "client_id": "tradevision-client",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_x509_cert_url": f"https://www.googleapis.com/robot/v1/metadata/x509/{FIREBASE_CLIENT_EMAIL.replace('@', '%40')}"
        })
        firebase_admin.initialize_app(cred)
        _firebase_initialized = True
        logger.info("Firebase initialisé avec succès.")
    except Exception as e:
        logger.error(f"Erreur initialisation Firebase : {e}")


# ── Envoi de notifications ──────────────────────────────

def send_notification_to_token(
    token: str,
    title: str,
    body: str,
    data: Optional[dict] = None,
) -> bool:
    if not _firebase_initialized:
        logger.debug(f"[DEV] Notification simulée → {title}: {body}")
        return False

    try:
        message = messaging.Message(
            notification=messaging.Notification(title=title, body=body),
            data=data or {},
            token=token,
        )
        messaging.send(message)
        return True
    except Exception as e:
        logger.error(f"Erreur envoi FCM (token={token[:20]}...) : {e}")
        return False


def send_notification_to_many(
    tokens: List[str],
    title: str,
    body: str,
    data: Optional[dict] = None,
) -> dict:
    if not _firebase_initialized:
        logger.debug(f"[DEV] Notification multicast simulée → {len(tokens)} appareils | {title}")
        return {"success": 0, "failure": 0, "invalid_tokens": []}

    if not tokens:
        return {"success": 0, "failure": 0, "invalid_tokens": []}

    try:
        message = messaging.MulticastMessage(
            notification=messaging.Notification(title=title, body=body),
            data=data or {},
            tokens=tokens,
        )
        response = messaging.send_each_for_multicast(message)

        invalid_tokens = []
        for idx, result in enumerate(response.responses):
            if not result.success:
                invalid_tokens.append(tokens[idx])

        return {
            "success": response.success_count,
            "failure": response.failure_count,
            "invalid_tokens": invalid_tokens,
        }
    except Exception as e:
        logger.error(f"Erreur envoi multicast FCM : {e}")
        return {"success": 0, "failure": len(tokens), "invalid_tokens": tokens}