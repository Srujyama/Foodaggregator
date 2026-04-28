"""
Uber Eats scraper - April 2026.

Endpoint: /_p/api/getFeedV1 + /_p/api/getStoreV1.
Auth: real session cookies from www.ubereats.com + a uev2.loc cookie that
encodes the target lat/lng. x-csrf-token: x is fine once cookies are set.

Parsing logic lives in `uber_shared` and is also used by the Postmates
scraper since both surfaces share the same backend.
"""

import json as _json
import logging
import time
import urllib.parse as _up
from typing import Optional

import httpx

from app.models.food import Platform, PlatformResult
from app.services.scraper_base import BaseScraper, geocode
from app.services.uber_shared import parse_feed, parse_store_detail

logger = logging.getLogger(__name__)

BASE_URL = "https://www.ubereats.com"
FEED_URL = "https://www.ubereats.com/_p/api/getFeedV1"
STORE_URL = "https://www.ubereats.com/_p/api/getStoreV1"

_session_cache: tuple[dict, float] = ({}, 0.0)

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "sec-ch-ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
}


async def _get_session_cookies() -> dict:
    global _session_cache
    cookies, expires_at = _session_cache
    if cookies and time.time() < expires_at:
        return cookies
    try:
        async with httpx.AsyncClient(
            headers={
                **_BROWSER_HEADERS,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            },
            timeout=10.0,
            follow_redirects=True,
        ) as client:
            resp = await client.get(BASE_URL)
            all_cookies = dict(resp.cookies)
            _session_cache = (all_cookies, time.time() + 180)
            return all_cookies
    except Exception as e:
        logger.warning(f"[UberEats] Failed to get session cookies: {e}")
        return {}


def _build_loc_cookie(lat: float, lng: float, address: str) -> str:
    loc_data = {
        "latitude": lat,
        "longitude": lng,
        "addressLine1": address,
        "addressLine2": "",
        "city": "",
        "country": "US",
        "postalCode": "",
        "region": "",
        "type": "geocode",
    }
    return _up.quote(_json.dumps(loc_data, separators=(",", ":")))


def _build_cookie_str(session_cookies: dict, lat: float, lng: float, address: str) -> str:
    cookies = {**session_cookies, "uev2.loc": _build_loc_cookie(lat, lng, address)}
    return "; ".join(f"{k}={v}" for k, v in cookies.items())


def _dining_mode(mode: str) -> str:
    return "PICKUP" if (mode or "").lower() == "pickup" else "DELIVERY"


class UberEatsScraper(BaseScraper):
    PLATFORM_NAME = "uber_eats"

    async def search(
        self, query: str, location: str, mode: str = "delivery"
    ) -> list[PlatformResult]:
        lat, lng = await geocode(location)
        session_cookies = await _get_session_cookies()
        cookie_str = _build_cookie_str(session_cookies, lat, lng, location)
        dining = _dining_mode(mode)

        headers = {
            **_BROWSER_HEADERS,
            "Content-Type": "application/json",
            "Accept": "application/json, text/plain, */*",
            "x-csrf-token": "x",
            "Referer": f"https://www.ubereats.com/feed?diningMode={dining}",
            "Origin": "https://www.ubereats.com",
            "Cookie": cookie_str,
        }
        payload = {
            "userQuery": query,
            "pageInfo": {"offset": 0, "pageSize": 80},
            "targetLocation": {"latitude": lat, "longitude": lng},
            "diningMode": dining,
        }
        try:
            async with httpx.AsyncClient(
                headers=headers, timeout=10.0, follow_redirects=True,
            ) as client:
                resp = await client.post(FEED_URL, json=payload)
                resp.raise_for_status()
                data = resp.json()
            results = parse_feed(
                data, Platform.UBER_EATS, BASE_URL,
                accept_pickup=(dining == "PICKUP"),
            )
            logger.info(f"[UberEats] {len(results)} results for '{query}' (mode={dining})")
            return results
        except httpx.HTTPStatusError as e:
            logger.warning(
                f"[UberEats] HTTP {e.response.status_code} for '{query}': "
                f"{e.response.text[:200]}"
            )
            if e.response.status_code == 403:
                global _session_cache
                _session_cache = ({}, 0.0)
            return []
        except Exception as e:
            logger.warning(f"[UberEats] Search failed: {e}")
            return []

    async def get_restaurant(
        self, restaurant_id: str, location: str, mode: str = "delivery"
    ) -> Optional[PlatformResult]:
        lat, lng = await geocode(location)
        session_cookies = await _get_session_cookies()
        cookie_str = _build_cookie_str(session_cookies, lat, lng, location)
        dining = _dining_mode(mode)

        headers = {
            **_BROWSER_HEADERS,
            "Content-Type": "application/json",
            "Accept": "application/json, text/plain, */*",
            "x-csrf-token": "x",
            "Referer": "https://www.ubereats.com/",
            "Cookie": cookie_str,
        }
        try:
            async with httpx.AsyncClient(headers=headers, timeout=10.0) as client:
                resp = await client.post(
                    STORE_URL,
                    json={"storeUuid": restaurant_id, "diningMode": dining},
                )
                resp.raise_for_status()
                data = resp.json()
            return parse_store_detail(data, restaurant_id, Platform.UBER_EATS, BASE_URL)
        except Exception as e:
            logger.warning(f"[UberEats] get_restaurant failed: {e}")
            return None
