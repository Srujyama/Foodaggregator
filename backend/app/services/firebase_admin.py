import json
import logging
import os
import firebase_admin
from firebase_admin import credentials, firestore

logger = logging.getLogger(__name__)

_db = None


def init_firebase(service_account_path: str = "", service_account_json: str = "", project_id: str = ""):
    global _db

    if firebase_admin._apps:
        _db = firestore.client()
        return _db

    try:
        if service_account_json:
            # Inline JSON (production - Fly.io secret)
            cred_dict = json.loads(service_account_json)
            cred = credentials.Certificate(cred_dict)
            firebase_admin.initialize_app(cred)
        elif service_account_path and os.path.exists(service_account_path):
            # File path (local dev)
            cred = credentials.Certificate(service_account_path)
            firebase_admin.initialize_app(cred)
        elif project_id:
            # Application Default Credentials
            firebase_admin.initialize_app(options={"projectId": project_id})
        else:
            logger.warning("No Firebase credentials found. Firestore caching disabled.")
            return None

        _db = firestore.client()
        logger.info("Firebase initialized successfully.")
        return _db
    except Exception as e:
        logger.error(f"Firebase initialization failed: {e}")
        return None


def get_db():
    return _db
