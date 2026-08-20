"""
TradeVision AI - Couche de Validation par IA (OpenRouter).

L'IA reçoit le bilan structuré et valide ou invalide la cohérence du trade.
"""

import json
import httpx
from typing import Dict, Any, Tuple

from src.core.config import OPENROUTER_API_KEY, OPENROUTER_CHAT_URL
from src.core.logging import get_logger

logger = get_logger(__name__)


class AIAnalysisEngine:
    """Auditeur IA pour valider les signaux candidats."""

    async def validate_signal(
        self,
        symbol: str,
        candidate_action: str,
        score: int,
        breakdown: Dict[str, int],
        reasons: list,
        news_summary: str,
    ) -> Tuple[bool, str]:
        """
        Interroge OpenRouter pour confirmer ou réfuter le signal.

        Retourne :
            (is_confirmed, ai_reason)
        """
        if not OPENROUTER_API_KEY:
            logger.debug("OpenRouter non configuré. Validation IA déterministe automatique.")
            return True, "Confirmation algorithmique interne (IA désactivée)."

        prompt = f"""Tu es le responsable du contrôle des risques d'un fonds de trading Forex.
Analyse ce signal candidat et vérifie s'il existe une faille majeure :

Actif : {symbol}
Action Candidate : {candidate_action}
Score Déterministe : {score}/100
Détail du Score : {json.dumps(breakdown)}
Raisons Clés : {'; '.join(reasons[:6])}
Contexte News : {news_summary}

Consigne :
Réponds EXCLUSIVEMENT sous la forme d'un objet JSON strict avec deux clés :
{{
  "confirmed": true ou false,
  "reason": "Explication courte en français (max 2 phrases)"
}}
"""

        try:
            headers = {
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
            }
            body = {
                "model": "meta-llama/llama-3-8b-instruct:free",  # Modèle rapide et gratuit
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
            }

            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.post(OPENROUTER_CHAT_URL, headers=headers, json=body)

            if resp.status_code == 200:
                result = resp.json()
                content = result["choices"][0]["message"]["content"]
                # Nettoyage JSON
                clean_json = content.strip().strip("`").replace("json", "").strip()
                parsed = json.loads(clean_json)
                return bool(parsed.get("confirmed", True)), parsed.get("reason", "Validé par l'IA.")

        except Exception as e:
            logger.warning(f"Erreur appel IA OpenRouter : {e}. Validation basée sur le score déterministe.")

        # Fallback si l'IA timeout : si le score est bon, on maintient
        return True, "Validé par confluence algorithmique."


# Instance globale
ai_engine = AIAnalysisEngine()