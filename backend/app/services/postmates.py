"""
Postmates scraper - April 2026.

Postmates is now part of Uber Eats but maintains a separate web presence at
postmates.com. It routes through Uber's backend but can surface different
restaurants, promotions, and pricing in some markets.

Uses the same feed API as Uber Eats but through the Postmates domain, which
sometimes returns different inventory and deals.
"""

import json as _json
import logging
import re
import time
import urllib.parse as _up
from datetime import datetime, timezone
from typing import Optional

import httpx
from curl_cffi import requests as cffi_requests

from app.models.food import MenuItem, Platform, PlatformResult
from app.services.scraper_base import BaseScraper, geocode

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
    """Load postmates.com homepage to get session cookies. Cached 3 min."""
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

    # Fallback: use curl_cffi
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


def _parse_fee_string(text: str) -> float:
    if not text:
        return 0.0
    m = re.search(r'\$?([\d]+(?:\.[\d]+)?)', str(text))
    if m:
        try:
            return round(float(m.group(1)), 2)
        except ValueError:
            pass
    return 0.0


def _parse_eta_minutes(text: str) -> int:
    if not text:
        return 30
    m = re.search(r'(\d+)', str(text))
    return int(m.group(1)) if m else 30


def _cents_to_dollars(value) -> float:
    if value is None:
        return 0.0
    try:
        v = float(value)
        if v == 0:
            return 0.0
        if abs(v) >= 100:
            return round(v / 100, 2)
        if abs(v) >= 10 and v == int(v):
            return round(v / 100, 2)
        return round(v, 2)
    except (ValueError, TypeError):
        return 0.0


class PostmatesScraper(BaseScraper):
    PLATFORM_NAME = "postmates"

    async def search(self, query: str, location: str) -> list[PlatformResult]:
        lat, lng = await geocode(location)
        session_cookies = await _get_session_cookies()
        cookie_str = _build_cookie_str(session_cookies, lat, lng, location)

        headers = {
            **_BROWSER_HEADERS,
            "Content-Type": "application/json",
            "Accept": "application/json, text/plain, */*",
            "x-csrf-token": "x",
            "Referer": "https://postmates.com/feed?diningMode=DELIVERY",
            "Origin": "https://postmates.com",
            "Cookie": cookie_str,
        }

        payload = {
            "userQuery": query,
            "pageInfo": {"offset": 0, "pageSize": 20},
            "targetLocation": {"latitude": lat, "longitude": lng},
        }

        try:
            async with httpx.AsyncClient(
                headers=headers, timeout=10.0, follow_redirects=True,
            ) as client:
                resp = await client.post(PM_FEED_URL, json=payload)
                resp.raise_for_status()
                data = resp.json()

            results = self._parse_feed(data)
            logger.info(f"[Postmates] {len(results)} results for '{query}'")
            return results

        except httpx.HTTPStatusError as e:
            logger.warning(f"[Postmates] HTTP {e.response.status_code}: {e.response.text[:200]}")
            if e.response.status_code == 403:
                global _session_cache
                _session_cache = ({}, 0.0)
            # Fallback to headless browser
            return await self._browser_search(query, lat, lng, location)
        except Exception as e:
            logger.warning(f"[Postmates] Search failed: {e}")
            return await self._browser_search(query, lat, lng, location)

    async def _browser_search(self, query: str, lat: float, lng: float, location: str) -> list[PlatformResult]:
        """Fallback: use headless browser to search Postmates."""
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
                return self._parse_feed(data)
        except Exception as e:
            logger.warning(f"[Postmates] Browser fallback failed: {e}")
        return []

    def _parse_feed(self, data: dict) -> list[PlatformResult]:
        results = []
        try:
            top = data.get("data", data)
            feed_items = top.get("feedItems") or []
        except Exception:
            return []

        now = datetime.now(timezone.utc).isoformat()

        for item in feed_items:
            try:
                item_type = item.get("type", "")
                if item_type not in ("REGULAR_STORE", "STORE", "store", "REGULAR", "CAROUSEL_V2"):
                    continue

                store = item.get("store") or {}
                if not store:
                    continue

                uuid = store.get("storeUuid") or store.get("uuid") or store.get("id", "")
                title_val = store.get("title", "")
                name = title_val.get("text", "") if isinstance(title_val, dict) else str(title_val)

                if not name or not uuid:
                    continue

                delivery_fee = 0.0
                service_fee = 0.0
                eta_min = 30
                promo = None

                for meta_item in (store.get("meta") or []):
                    badge_type = meta_item.get("badgeType", "")
                    if badge_type == "FARE":
                        fare_data = (meta_item.get("badgeData") or {}).get("fare") or {}
                        delivery_fee = _parse_fee_string(fare_data.get("deliveryFee", ""))
                        service_fee = _parse_fee_string(fare_data.get("serviceFee", ""))
                    elif badge_type == "ETD":
                        eta_text = meta_item.get("accessibilityText") or meta_item.get("text") or ""
                        eta_min = _parse_eta_minutes(eta_text)

                rating_data = store.get("rating") or {}
                if isinstance(rating_data, dict):
                    rating_str = rating_data.get("text") or rating_data.get("ratingValue") or ""
                else:
                    rating_str = str(rating_data)
                try:
                    rating = float(rating_str) if rating_str else None
                except (ValueError, TypeError):
                    rating = None

                signposts = store.get("signposts") or []
                if signposts and isinstance(signposts[0], dict):
                    promo = signposts[0].get("text")

                action_url = store.get("actionUrl") or ""
                if action_url.startswith("/"):
                    url = f"https://postmates.com{action_url}"
                else:
                    url = f"https://postmates.com/store/{uuid}"

                pickup_eta = max(5, int(eta_min * 0.5)) if eta_min else 15

                results.append(PlatformResult(
                    platform=Platform.POSTMATES,
                    restaurant_name=name,
                    restaurant_id=uuid,
                    restaurant_url=url,
                    delivery_fee=delivery_fee,
                    service_fee=service_fee,
                    estimated_delivery_minutes=eta_min,
                    pickup_available=True,
                    pickup_fee=0.0,
                    pickup_service_fee=0.0,
                    estimated_pickup_minutes=pickup_eta,
                    rating=rating,
                    rating_count=None,
                    promo_text=promo,
                    fetched_at=now,
                ))
            except Exception as e:
                logger.debug(f"[Postmates] Feed item parse error: {e}")
                continue

        return results

    async def get_restaurant(self, restaurant_id: str, location: str) -> Optional[PlatformResult]:
        lat, lng = await geocode(location)
        session_cookies = await _get_session_cookies()
        cookie_str = _build_cookie_str(session_cookies, lat, lng, location)

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
                    json={"storeUuid": restaurant_id, "diningMode": "DELIVERY"},
                )
                resp.raise_for_status()
                data = resp.json()

            store = data.get("data", {})
            now = datetime.now(timezone.utc).isoformat()

            menu_items = []
            seen_names = set()
            for _sid, sections_list in (store.get("catalogSectionsMap") or {}).items():
                if not isinstance(sections_list, list):
                    sections_list = [sections_list]
                for section in sections_list:
                    if not isinstance(section, dict):
                        continue
                    items = (
                        section.get("payload", {})
                        .get("standardItemsPayload", {})
                        .get("catalogItems", [])
                    )
                    for item in items:
                        try:
                            name = item.get("title", "")
                            if not name or name.lower() in seen_names:
                                continue
                            price = _cents_to_dollars(item.get("price") or 0)
                            if price <= 0:
                                continue
                            seen_names.add(name.lower())
                            menu_items.append(MenuItem(
                                name=name,
                                description=item.get("itemDescription"),
                                price=price,
                                image_url=item.get("imageUrl"),
                            ))
                        except Exception:
                            continue
                        if len(menu_items) >= 100:
                            break
                    if len(menu_items) >= 100:
                        break

            fare = store.get("fareInfo") or {}
            slug = store.get("slug") or restaurant_id
            delivery_eta = int((store.get("etaRange") or {}).get("min") or 30)
            return PlatformResult(
                platform=Platform.POSTMATES,
                restaurant_name=store.get("title", ""),
                restaurant_id=restaurant_id,
                restaurant_url=f"https://postmates.com/store/{slug}",
                menu_items=menu_items,
                delivery_fee=_cents_to_dollars(fare.get("deliveryFee") or 0),
                service_fee=_cents_to_dollars(fare.get("serviceFee") or 0),
                estimated_delivery_minutes=delivery_eta,
                pickup_available=True,
                pickup_fee=0.0,
                pickup_service_fee=0.0,
                estimated_pickup_minutes=max(5, int(delivery_eta * 0.5)),
                fetched_at=now,
            )
        except Exception as e:
            logger.warning(f"[Postmates] get_restaurant failed: {e}")
            return None
