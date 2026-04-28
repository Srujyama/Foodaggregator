import hashlib
import logging
import time
from typing import Optional, Any

from app.services.firebase_admin import get_db

logger = logging.getLogger(__name__)

_memory_cache: dict[str, tuple[Any, float]] = {}

MEMORY_TTL = 300      # 5 minutes
FIRESTORE_TTL = 1800  # 30 minutes


def _make_key(query: str, location: str, mode: str = "delivery") -> str:
    raw = f"{query.lower().strip()}::{location.lower().strip()}::{(mode or 'delivery').lower().strip()}"
    return hashlib.sha256(raw.encode()).hexdigest()


def get_from_memory(cache_key: str) -> Optional[Any]:
    entry = _memory_cache.get(cache_key)
    if entry is None:
        return None
    data, expires_at = entry
    if time.time() > expires_at:
        del _memory_cache[cache_key]
        return None
    return data


def set_in_memory(cache_key: str, data: Any) -> None:
    _memory_cache[cache_key] = (data, time.time() + MEMORY_TTL)


async def get_from_firestore(cache_key: str) -> Optional[Any]:
    db = get_db()
    if db is None:
        return None
    try:
        doc = db.collection("search_cache").document(cache_key).get()
        if not doc.exists:
            return None
        doc_data = doc.to_dict()
        if doc_data.get("expires_at", 0) < time.time():
            return None
        return doc_data.get("data")
    except Exception as e:
        logger.warning(f"Firestore get failed: {e}")
        return None


async def set_in_firestore(cache_key: str, data: Any) -> None:
    db = get_db()
    if db is None:
        return
    try:
        db.collection("search_cache").document(cache_key).set({
            "data": data,
            "expires_at": time.time() + FIRESTORE_TTL,
            "cached_at": time.time(),
        })
    except Exception as e:
        logger.warning(f"Firestore set failed: {e}")


async def get_cached(query: str, location: str, mode: str = "delivery") -> Optional[Any]:
    key = _make_key(query, location, mode)

    # Tier 1: memory
    data = get_from_memory(key)
    if data is not None:
        return data

    # Tier 2: Firestore
    data = await get_from_firestore(key)
    if data is not None:
        set_in_memory(key, data)
        return data

    return None


async def set_cached(query: str, location: str, data: Any, mode: str = "delivery") -> None:
    key = _make_key(query, location, mode)
    set_in_memory(key, data)
    await set_in_firestore(key, data)


async def track_popular_search(query: str) -> None:
    db = get_db()
    if db is None:
        return
    try:
        ref = db.collection("popular_searches").document(query.lower().strip())
        doc = ref.get()
        if doc.exists:
            ref.update({"count": doc.to_dict().get("count", 0) + 1})
        else:
            ref.set({"term": query, "count": 1})
    except Exception as e:
        logger.warning(f"Failed to track popular search: {e}")
