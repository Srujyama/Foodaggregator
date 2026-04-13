import json
import logging
import os
import firebase_admin
from firebase_admin import credentials, firestore

logger = logging.getLogger(__name__)

_db = None


def init_firebase(service_account_path: str = "", service_account_json: str = "", project_id: str = ""):
    global _db

    try:
        if firebase_admin._apps:
            _db = firestore.client()
            return _db
    except Exception:
        pass

    try:
        if service_account_json:
            cred_dict = json.loads(service_account_json)
            cred = credentials.Certificate(cred_dict)
            firebase_admin.initialize_app(cred)
        elif service_account_path and os.path.exists(service_account_path):
            cred = credentials.Certificate(service_account_path)
            firebase_admin.initialize_app(cred)
        elif project_id:
            firebase_admin.initialize_app(options={"projectId": project_id})
        else:
            logger.info("No Firebase credentials found. Running without Firestore caching.")
            return None

        _db = firestore.client()
        logger.info("Firebase initialized successfully.")
        return _db
    except Exception as e:
        logger.warning(f"Firebase initialization failed (app will work without caching): {e}")
        _db = None
        return None


def get_db():
    return _db
