"""Firebase Cloud Messaging (FCM) côté serveur."""
import logging
from typing import List, Optional
try:
    import firebase_admin
    from firebase_admin import credentials, messaging
except ImportError:  # environnement de test sans dépendance FCM
    firebase_admin = None
    credentials = None
    messaging = None
from src.core.config import FIREBASE_PROJECT_ID, FIREBASE_CLIENT_EMAIL, FIREBASE_PRIVATE_KEY
logger=logging.getLogger(__name__)
_firebase_initialized=False

def init_firebase():
    global _firebase_initialized
    if firebase_admin is None:
        logger.warning("firebase-admin absent : notifications push désactivées dans cet environnement."); return
    if _firebase_initialized or firebase_admin._apps:
        _firebase_initialized=True; return
    if not FIREBASE_PROJECT_ID or not FIREBASE_CLIENT_EMAIL or not FIREBASE_PRIVATE_KEY:
        logger.warning("Firebase non configuré : notifications push désactivées."); return
    try:
        cred=credentials.Certificate({"type":"service_account","project_id":FIREBASE_PROJECT_ID,"private_key_id":"tradevision-key","private_key":FIREBASE_PRIVATE_KEY,"client_email":FIREBASE_CLIENT_EMAIL,"client_id":"tradevision-client","auth_uri":"https://accounts.google.com/o/oauth2/auth","token_uri":"https://oauth2.googleapis.com/token","auth_provider_x509_cert_url":"https://www.googleapis.com/oauth2/v1/certs","client_x509_cert_url":f"https://www.googleapis.com/robot/v1/metadata/x509/{FIREBASE_CLIENT_EMAIL.replace('@','%40')}"})
        firebase_admin.initialize_app(cred); _firebase_initialized=True; logger.info("Firebase initialisé avec succès.")
    except Exception as e: logger.error("Erreur initialisation Firebase : %s",e)

def send_notification_to_token(token:str,title:str,body:str,data:Optional[dict]=None)->bool:
    if not _firebase_initialized or messaging is None: return False
    try:
        messaging.send(messaging.Message(notification=messaging.Notification(title=title,body=body),data=data or {},token=token)); return True
    except Exception as e:
        logger.error("Erreur FCM : %s",e); return False

def send_notification_to_many(tokens:List[str],title:str,body:str,data:Optional[dict]=None)->dict:
    if not _firebase_initialized or messaging is None or not tokens: return {"success":0,"failure":len(tokens),"invalid_tokens":[]}
    success=failure=0; invalid=[]
    # FCM multicast est limité à 500 tokens par appel.
    for start in range(0,len(tokens),500):
        batch=tokens[start:start+500]
        try:
            resp=messaging.send_each_for_multicast(messaging.MulticastMessage(notification=messaging.Notification(title=title,body=body),data=data or {},tokens=batch))
            success += resp.success_count; failure += resp.failure_count
            for idx,result in enumerate(resp.responses):
                if not result.success:
                    exc=result.exception
                    if isinstance(exc, messaging.UnregisteredError) or isinstance(exc, messaging.SenderIdMismatchError):
                        invalid.append(batch[idx])
        except Exception as e:
            logger.error("Erreur multicast FCM : %s",e); failure += len(batch)
    return {"success":success,"failure":failure,"invalid_tokens":invalid}
