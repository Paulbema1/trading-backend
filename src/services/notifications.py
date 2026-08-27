"""
TradeVision AI - Service de Notifications Push.

Responsabilités :
- Cibler les utilisateurs ayant activé les notifications pour l'actif concerné
- Envoyer les notifications push en multicast via Firebase
- Formater un message clair et lisible avec l'Entry, SL, TP1, TP2, TP3 et Timeframe
"""

from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session

from src.models.user import User
from src.schemas.signal import SignalResponse
from src.core.firebase import send_notification_to_many, send_notification_to_token
from src.core.logging import get_logger

logger = get_logger(__name__)


class NotificationService:
    """Service d'envoi et de formatage des alertes push."""

    def _format_signal_body(self, signal: SignalResponse) -> str:
        """Formate le corps du message pour le téléphone."""
        lines = [
            f"Direction : {signal.action.value} ({signal.confidence}%)",
            f"Entrée : {signal.entry_price or 'Marché'}",
            f"SL : {signal.stop_loss} | TP1 : {signal.take_profit_1}",
            f"TF : {signal.main_timeframe.upper()}" + (f" (Conf: {signal.confirmation_timeframe.upper()})" if signal.confirmation_timeframe else ""),
        ]

        if signal.news_used:
            lines.append("📰 Porté par les Actualités")
        else:
            lines.append("⚪ 100% Technique & SMC")

        return "\n".join(lines)

    async def broadcast_signal(self, signal: SignalResponse, db: Session) -> Dict[str, Any]:
        """
        Diffuse le signal à tous les utilisateurs abonnés à l'actif.

        Ne diffuse pas si le signal est un simple "WAIT" (pour ne pas spammer les téléphones).
        """
        if signal.action.value == "WAIT":
            logger.debug(f"Signal WAIT pour {signal.symbol} - Notification publique ignorée.")
            return {"sent": False, "reason": "Signal WAIT non notifié aux utilisateurs"}

        # 1. Recherche des utilisateurs abonnés avec un FCM Token valide
        users: List[User] = db.query(User).filter(
            User.is_active == True,
            User.notifications_enabled == True,
            User.fcm_token.isnot(None),
        ).all()

        target_tokens = []
        for u in users:
            preferred = (u.preferred_assets or "").upper()
            if signal.symbol.upper() in preferred or not preferred:
                if u.fcm_token and len(u.fcm_token.strip()) > 10:
                    target_tokens.append(u.fcm_token.strip())

        if not target_tokens:
            logger.info(f"Aucun utilisateur ciblé avec FCM token pour {signal.symbol}.")
            return {"sent": True, "recipients_count": 0}

        # 2. Construction du message
        action_emoji = "🟢" if signal.action.value == "BUY" else "🔴"
        title = f"{action_emoji} Signal {signal.action.value} — {signal.symbol}"
        body = self._format_signal_body(signal)

        data_payload = {
            "symbol": signal.symbol,
            "action": signal.action.value,
            "confidence": str(signal.confidence),
            "score": str(signal.score),
            "entry": str(signal.entry_price or ""),
            "sl": str(signal.stop_loss or ""),
            "tp1": str(signal.take_profit_1 or ""),
            "tp2": str(signal.take_profit_2 or ""),
            "tp3": str(signal.take_profit_3 or ""),
            "timeframe": signal.main_timeframe,
            "news_used": str(signal.news_used),
        }

        # 3. Envoi multicast via Firebase
        result = send_notification_to_many(tokens=target_tokens, title=title, body=body, data=data_payload)

        # Nettoyage des tokens définitivement invalides.
        invalid = set(result.get("invalid_tokens", []))
        if invalid:
            for user in users:
                if user.fcm_token and user.fcm_token.strip() in invalid:
                    user.fcm_token = None
            db.commit()

        logger.info(
            f"Notification {signal.action.value} {signal.symbol} envoyée à {result.get('success', 0)} appareil(s)."
        )
        return {"sent": True, "result": result}

    async def notify_admin(self, title: str, message: str, db: Session) -> bool:
        """Envoie une notification d'alerte spécifique au compte ADMIN."""
        admin: Optional[User] = db.query(User).filter(
            User.role == "ADMIN",
            User.is_active == True,
            User.fcm_token.isnot(None),
        ).first()

        if not admin or not admin.fcm_token:
            return False

        return send_notification_to_token(
            token=admin.fcm_token,
            title=f"🛡️ ADMIN: {title}",
            body=message,
            data={"type": "ADMIN_ALERT"},
        )


# Instance globale partagée
notification_service = NotificationService()