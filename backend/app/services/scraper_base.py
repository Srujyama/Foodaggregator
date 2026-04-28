import asyncio
import logging
import re
from abc import ABC, abstractmethod
from typing import Optional

import httpx

from app.models.food import PlatformResult

logger = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
}

GEOCODE_URL = "https://nominatim.openstreetmap.org/search"

# Cache geocode results to avoid hammering Nominatim
_geocode_cache: dict[str, tuple[float, float]] = {}


async def geocode(location: str) -> tuple[float, float]:
    """Convert a location string to (lat, lng) using Nominatim.

    Handles US ZIP codes by appending ', USA' to disambiguate from international locations.
    """
    location = location.strip()
    if location in _geocode_cache:
        return _geocode_cache[location]

    # If it looks like a bare US zip code, append USA for disambiguation
    query = location
    if re.match(r'^\d{5}(-\d{4})?$', location):
        query = f"{location}, USA"

    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            resp = await client.get(
                GEOCODE_URL,
                params={"q": query, "format": "json", "limit": 1, "countrycodes": "us"},
                headers={"User-Agent": "FoodAggregator/1.0 (contact@foodaggregator.app)"},
            )
            resp.raise_for_status()
            data = resp.json()
            if data:
                result = (float(data[0]["lat"]), float(data[0]["lon"]))
                _geocode_cache[location] = result
                return result
        except Exception as e:
            logger.warning(f"Geocoding failed for '{location}': {e}")

    # Default to NYC if geocoding fails
    _geocode_cache[location] = (40.7128, -74.0060)
    return 40.7128, -74.0060


class BaseScraper(ABC):
    PLATFORM_NAME = "unknown"

    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None

    def _make_client(self, extra_headers: dict = None) -> httpx.AsyncClient:
        headers = {**DEFAULT_HEADERS, **(extra_headers or {})}
        return httpx.AsyncClient(
            headers=headers,
            timeout=10.0,
            follow_redirects=True,
        )

    @abstractmethod
    async def search(
        self, query: str, location: str, mode: str = "delivery"
    ) -> list[PlatformResult]:
        """Search for restaurants/dishes. Must never raise - return [] on failure."""
        ...

    @abstractmethod
    async def get_restaurant(
        self, restaurant_id: str, location: str, mode: str = "delivery"
    ) -> Optional[PlatformResult]:
        """Get detailed data for one restaurant. Returns None on failure."""
        ...

    async def _safe_search(
        self, query: str, location: str, mode: str = "delivery"
    ) -> list[PlatformResult]:
        """Wrapper that catches all exceptions and returns []."""
        try:
            return await self.search(query, location, mode)
        except asyncio.TimeoutError:
            logger.warning(f"[{self.PLATFORM_NAME}] Timeout during search for '{query}'")
            return []
        except Exception as e:
            logger.warning(f"[{self.PLATFORM_NAME}] Search failed: {e}")
            return []
