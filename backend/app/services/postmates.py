"""
Postmates scraper - April 2026.

Postmates was acquired by Uber and now runs on the same backend (getFeedV1 /
getStoreV1) hosted at postmates.com. The response shape is identical to Uber
Eats, so the parsing logic is shared via `uber_shared`.
"""

import json as _json
import logging
import time
import urllib.parse as _up
from typing import Optional

import httpx
from curl_cffi import requests as cffi_requests

from app.models.food import Platform, PlatformResult
from app.services.scraper_base import BaseScraper, geocode
from app.services.uber_shared import parse_feed, parse_store_detail

logger = logging.getLogger(__name__)

PM_BASE = "https://postmates.com"
PM_FEED_URL = "https://postmates.com/_p/api/getFeedV1"
PM_STORE_URL = "https://postmates.com/_p/api/getStoreV1"

_session_cache: tuple[dict, float] = ({}, 0.0)

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "sec-ch-ua": '"Google Chrome";v="131", "Chromium";v="131"',
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
            headers={**_BROWSER_HEADERS, "Accept": "text/html,application/xhtml+xml,*/*"},
            timeout=10.0,
            follow_redirects=True,
        ) as client:
            resp = await client.get(PM_BASE)
            all_cookies = dict(resp.cookies)
            _session_cache = (all_cookies, time.time() + 180)
            return all_cookies
    except Exception as e:
        logger.warning(f"[Postmates] Failed to get session cookies: {e}")

    import asyncio

    def _cffi_cookies():
        try:
            resp = cffi_requests.get(PM_BASE, impersonate="chrome", timeout=10)
            return {k: v for k, v in resp.cookies.items()}
        except Exception:
            return {}

    cookies = await asyncio.to_thread(_cffi_cookies)
    if cookies:
        _session_cache = (cookies, time.time() + 180)
    return cookies


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


class PostmatesScraper(BaseScraper):
    PLATFORM_NAME = "postmates"

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
            "Referer": f"https://postmates.com/feed?diningMode={dining}",
            "Origin": "https://postmates.com",
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
                resp = await client.post(PM_FEED_URL, json=payload)
                resp.raise_for_status()
                data = resp.json()
            results = parse_feed(
                data, Platform.POSTMATES, PM_BASE,
                accept_pickup=(dining == "PICKUP"),
            )
            logger.info(f"[Postmates] {len(results)} results for '{query}' (mode={dining})")
            return results
        except httpx.HTTPStatusError as e:
            logger.warning(f"[Postmates] HTTP {e.response.status_code}: {e.response.text[:200]}")
            if e.response.status_code == 403:
                global _session_cache
                _session_cache = ({}, 0.0)
            return await self._browser_search(query, lat, lng, location, dining)
        except Exception as e:
            logger.warning(f"[Postmates] Search failed: {e}")
            return await self._browser_search(query, lat, lng, location, dining)

    async def _browser_search(
        self, query: str, lat: float, lng: float, location: str, dining: str
    ) -> list[PlatformResult]:
        try:
            from app.services.browser import browser_fetch_api
            from urllib.parse import quote

            url = f"https://postmates.com/search?q={quote(query)}"
            cookies = [
                {"name": "uev2.loc", "value": _build_loc_cookie(lat, lng, location),
                 "domain": ".postmates.com", "path": "/"},
            ]
            json_body = await browser_fetch_api(url, "getFeedV1", cookies=cookies, wait_time=6000)
            if json_body:
                data = _json.loads(json_body)
                return parse_feed(
                    data, Platform.POSTMATES, PM_BASE,
                    accept_pickup=(dining == "PICKUP"),
                )
        except Exception as e:
            logger.warning(f"[Postmates] Browser fallback failed: {e}")
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
            "Referer": "https://postmates.com/",
            "Cookie": cookie_str,
        }
        try:
            async with httpx.AsyncClient(headers=headers, timeout=10.0) as client:
                resp = await client.post(
                    PM_STORE_URL,
                    json={"storeUuid": restaurant_id, "diningMode": dining},
                )
                resp.raise_for_status()
                data = resp.json()
            return parse_store_detail(data, restaurant_id, Platform.POSTMATES, PM_BASE)
        except Exception as e:
            logger.warning(f"[Postmates] get_restaurant failed: {e}")
            return None
