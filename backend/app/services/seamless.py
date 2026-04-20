"""
Seamless scraper - April 2026.

Seamless (seamless.com) is owned by Grubhub and shares the same backend API.
As of April 2026 the grubhub.com client_id is rejected when the Origin header
is seamless.com, and Seamless's own client_id is not easily recoverable from
their minified JS bundle. Result: anonymous-session auth yields 401 and the
web-scrape fallback returns []. Seamless is disabled by default (gated on
ENABLE_SECONDARY_PLATFORMS) in app.services.aggregator. It also wraps the
same restaurant inventory as Grubhub, so even when working it mostly duplicates
Grubhub groupings without adding coverage.
"""

import json
import logging
import os
import re
import time
import uuid as _uuid
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote

import httpx
from curl_cffi import requests as cffi_requests

from app.models.food import MenuItem, Platform, PlatformResult
from app.services.scraper_base import BaseScraper, geocode

logger = logging.getLogger(__name__)

SL_SEARCH_API = "https://api-gtm.grubhub.com/restaurants/search/search_listing"
SL_RESTAURANT_API = "https://api-gtm.grubhub.com/restaurants/{restaurant_id}"
SL_AUTH_URL = "https://api-gtm.grubhub.com/auth"
SL_ANON_AUTH_URL = "https://api-gtm.grubhub.com/auth/anon"
SL_WEB_SEARCH = "https://www.seamless.com/search"

# Known Seamless/Grubhub web client_id (April 2026).
SL_DEFAULT_CLIENT_ID = "beta_UmWlpstzQSFmocLy3h1UieYcVST"

_API_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.seamless.com/",
    "Origin": "https://www.seamless.com",
}

_token_cache: tuple[str, float] = ("", 0.0)


async def _get_token() -> str:
    """Get a Seamless/Grubhub API token via /auth/anon.

    Seamless shares Grubhub's backend and the same /auth/anon endpoint works
    with brand=SEAMLESS. The legacy /auth endpoint only accepts refresh_token
    grants and returns 401 for anon sessions.
    """
    global _token_cache
    token, expires_at = _token_cache
    if token and time.time() < expires_at:
        return token

    import asyncio

    def _try_auth():
        session = cffi_requests.Session(impersonate="chrome")
        try:
            session.get("https://www.seamless.com/", timeout=10)
        except Exception:
            pass

        headers = {**_API_HEADERS, "Content-Type": "application/json;charset=UTF-8"}
        body = {
            "brand": "SEAMLESS",
            "client_id": SL_DEFAULT_CLIENT_ID,
            "device_id": str(_uuid.uuid4()),
        }
        try:
            resp = session.post(SL_ANON_AUTH_URL, json=body, headers=headers, timeout=12)
            if resp.status_code == 200:
                data = resp.json()
                tk = data.get("session_handle", {}).get("access_token", "")
                if tk:
                    logger.info("[Seamless] Got anonymous token via /auth/anon")
                    return tk
            else:
                logger.debug(f"[Seamless] /auth/anon returned {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            logger.debug(f"[Seamless] /auth/anon failed: {e}")
        return ""

    token = await asyncio.to_thread(_try_auth)
    if token:
        _token_cache = (token, time.time() + 1800)
    return token


def _cents_to_dollars(value) -> float:
    if value is None:
        return 0.0
    try:
        v = float(value)
        if v == 0:
            return 0.0
        if abs(v) >= 100:
            return round(v / 100, 2)
        if abs(v) > 10 and v == int(v):
            return round(v / 100, 2)
        return round(v, 2)
    except (ValueError, TypeError):
        return 0.0


def _parse_restaurant(restaurant: dict) -> dict:
    name = restaurant.get("name", "")
    rest_id = str(restaurant.get("restaurant_id", ""))

    fee_obj = restaurant.get("delivery_fee", {})
    if isinstance(fee_obj, dict):
        delivery_fee = _cents_to_dollars(fee_obj.get("amount", 0))
    else:
        delivery_fee = _cents_to_dollars(fee_obj)

    eta = int(restaurant.get("delivery_time_estimate", 0) or 35)
    if eta == 0:
        eta = 35

    ratings = restaurant.get("ratings", {})
    rating = None
    rating_count = None
    if isinstance(ratings, dict):
        try:
            rating = float(ratings.get("actual_rating_value", 0))
            if rating == 0:
                rating = None
        except (ValueError, TypeError):
            pass
        try:
            rating_count = int(ratings.get("rating_count", 0))
            if rating_count == 0:
                rating_count = None
        except (ValueError, TypeError):
            pass

    slug = restaurant.get("restaurant_slug", rest_id)
    url = f"https://www.seamless.com/menu/{slug}" if slug else f"https://www.seamless.com/restaurant/{rest_id}"

    min_obj = restaurant.get("minimum_order_amount", {})
    minimum_order = None
    if isinstance(min_obj, dict):
        minimum_order = _cents_to_dollars(min_obj.get("amount", 0)) or None
    elif min_obj:
        minimum_order = _cents_to_dollars(min_obj) or None

    promo = None
    deals = restaurant.get("deals", [])
    if isinstance(deals, list) and deals:
        first = deals[0] if isinstance(deals[0], dict) else {}
        promo = first.get("description") or first.get("badge_text")

    return {
        "name": name,
        "restaurant_id": rest_id,
        "delivery_fee": delivery_fee,
        "service_fee": 0.0,
        "eta": eta,
        "rating": rating,
        "rating_count": rating_count,
        "promo": promo,
        "slug": slug,
        "url": url,
        "minimum_order": minimum_order,
    }


def _parse_menu_item(item: dict) -> Optional[MenuItem]:
    name = item.get("name", "")
    if not name or len(name) < 2:
        return None
    price_obj = item.get("price", {})
    if isinstance(price_obj, dict):
        price = _cents_to_dollars(price_obj.get("amount", 0))
    else:
        price = _cents_to_dollars(price_obj)
    if price <= 0:
        return None
    description = item.get("description") or None
    if description and len(description) < 3:
        description = None
    image_url = None
    media = item.get("media_image", {})
    if isinstance(media, dict):
        image_url = media.get("base_url") or media.get("url")
    return MenuItem(name=name, description=description, price=round(price, 2), image_url=image_url)


def _scrape_search_page(query: str, lat: float, lng: float) -> list[dict]:
    """Scrape restaurant data from Seamless's search page."""
    try:
        url = (
            f"{SL_WEB_SEARCH}?orderMethod=delivery&locationMode=DELIVERY"
            f"&query={quote(query)}&latitude={lat}&longitude={lng}"
        )
        resp = cffi_requests.get(
            url,
            impersonate="chrome",
            timeout=12,
            headers={
                "Accept": "text/html,application/xhtml+xml,*/*",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        if resp.status_code != 200:
            return []

        html = resp.text
        # Look for __NEXT_DATA__
        next_data_match = re.search(
            r'<script\s+id="__NEXT_DATA__"[^>]*>\s*({.+?})\s*</script>',
            html, re.DOTALL,
        )
        if next_data_match:
            try:
                data = json.loads(next_data_match.group(1))
                return _extract_restaurants(data)
            except json.JSONDecodeError:
                pass

        # JSON-LD fallback
        jsonld = re.findall(
            r'<script\s+type="application/ld\+json"[^>]*>\s*({.+?})\s*</script>',
            html, re.DOTALL,
        )
        results = []
        for match in jsonld:
            try:
                ld = json.loads(match)
                if ld.get("@type") in ("Restaurant", "FoodEstablishment"):
                    results.append({
                        "name": ld.get("name", ""),
                        "restaurant_id": ld.get("url", "").rsplit("/", 1)[-1],
                        "delivery_fee": 0,
                        "delivery_time_estimate": 35,
                        "ratings": {
                            "actual_rating_value": float((ld.get("aggregateRating") or {}).get("ratingValue", 0) or 0),
                            "rating_count": int((ld.get("aggregateRating") or {}).get("reviewCount", 0) or 0),
                        },
                        "restaurant_slug": ld.get("url", "").rsplit("/", 1)[-1],
                    })
            except (json.JSONDecodeError, ValueError):
                continue
        return results

    except Exception as e:
        logger.warning(f"[Seamless] Web scrape failed: {e}")
        return []


def _extract_restaurants(data: dict, depth: int = 0) -> list[dict]:
    if depth > 10:
        return []
    results = []
    if isinstance(data, dict):
        if "restaurant_id" in data and "name" in data:
            results.append(data)
        elif "restaurantId" in data and "name" in data:
            results.append({
                "restaurant_id": data.get("restaurantId"),
                "name": data.get("name"),
                "delivery_fee": data.get("deliveryFee", {}).get("amount", 0)
                if isinstance(data.get("deliveryFee"), dict) else data.get("deliveryFee", 0),
                "delivery_time_estimate": data.get("deliveryTimeEstimate", 35),
                "ratings": {"actual_rating_value": data.get("rating", 0), "rating_count": data.get("ratingCount", 0)},
                "restaurant_slug": data.get("slug", ""),
            })
        for v in data.values():
            results.extend(_extract_restaurants(v, depth + 1))
            if len(results) >= 20:
                break
    elif isinstance(data, list):
        for item in data:
            results.extend(_extract_restaurants(item, depth + 1))
            if len(results) >= 20:
                break
    return results[:20]


class SeamlessScraper(BaseScraper):
    PLATFORM_NAME = "seamless"

    async def search(self, query: str, location: str) -> list[PlatformResult]:
        lat, lng = await geocode(location)
        token = await _get_token()

        if token:
            api_results = await self._api_search(query, lat, lng, token)
            if api_results:
                return api_results

        logger.info("[Seamless] Trying web scraping fallback")
        return await self._web_search(query, lat, lng)

    async def _api_search(self, query: str, lat: float, lng: float, token: str) -> list[PlatformResult]:
        headers = {**_API_HEADERS, "Authorization": f"Bearer {token}"}
        params = {
            "orderMethod": "delivery",
            "locationMode": "DELIVERY",
            "facetSet": "umaNew",
            "pageSize": 50,
            "hideHateos": "true",
            "queryText": query,
            "latitude": lat,
            "longitude": lng,
        }

        try:
            async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
                resp = await client.get(SL_SEARCH_API, params=params, headers=headers)

                if resp.status_code in (401, 403):
                    global _token_cache
                    _token_cache = ("", 0.0)
                    return []

                resp.raise_for_status()
                data = resp.json()

            results_data = (
                data.get("search_result", {}).get("results", [])
                or data.get("results", [])
            )
            if not results_data:
                return []

            parsed = self._build_results(results_data)
            if parsed:
                logger.info(f"[Seamless] API: {len(parsed)} results")
            return parsed

        except Exception as e:
            logger.warning(f"[Seamless] API search error: {e}")
            return []

    async def _web_search(self, query: str, lat: float, lng: float) -> list[PlatformResult]:
        import asyncio
        raw = await asyncio.to_thread(_scrape_search_page, query, lat, lng)
        if not raw:
            return []
        parsed = self._build_results_from_raw(raw)
        if parsed:
            logger.info(f"[Seamless] Web scrape: {len(parsed)} results")
        return parsed

    def _build_results(self, results_data: list) -> list[PlatformResult]:
        parsed = []
        now = datetime.now(timezone.utc).isoformat()
        for item in results_data:
            restaurant = item.get("restaurant") or item
            if not isinstance(restaurant, dict):
                continue
            rd = _parse_restaurant(restaurant)
            if rd["name"] and rd["restaurant_id"]:
                eta = rd["eta"]
                pickup_eta = max(5, int(eta * 0.5)) if eta else 15
                parsed.append(PlatformResult(
                    platform=Platform.SEAMLESS,
                    restaurant_name=rd["name"],
                    restaurant_id=rd["restaurant_id"],
                    restaurant_url=rd["url"],
                    delivery_fee=rd["delivery_fee"],
                    service_fee=rd["service_fee"],
                    estimated_delivery_minutes=eta,
                    pickup_available=True,
                    pickup_fee=0.0,
                    pickup_service_fee=0.0,
                    estimated_pickup_minutes=pickup_eta,
                    minimum_order=rd["minimum_order"],
                    rating=rd["rating"],
                    rating_count=rd["rating_count"],
                    promo_text=rd["promo"],
                    fetched_at=now,
                ))
        return parsed

    def _build_results_from_raw(self, raw_restaurants: list[dict]) -> list[PlatformResult]:
        parsed = []
        now = datetime.now(timezone.utc).isoformat()
        for restaurant in raw_restaurants:
            if not isinstance(restaurant, dict):
                continue
            rd = _parse_restaurant(restaurant)
            if rd["name"]:
                if not rd["restaurant_id"]:
                    rd["restaurant_id"] = rd["name"].lower().replace(" ", "-")[:50]
                eta = rd["eta"]
                pickup_eta = max(5, int(eta * 0.5)) if eta else 15
                parsed.append(PlatformResult(
                    platform=Platform.SEAMLESS,
                    restaurant_name=rd["name"],
                    restaurant_id=rd["restaurant_id"],
                    restaurant_url=rd["url"],
                    delivery_fee=rd["delivery_fee"],
                    service_fee=rd["service_fee"],
                    estimated_delivery_minutes=eta,
                    pickup_available=True,
                    pickup_fee=0.0,
                    pickup_service_fee=0.0,
                    estimated_pickup_minutes=pickup_eta,
                    minimum_order=rd["minimum_order"],
                    rating=rd["rating"],
                    rating_count=rd["rating_count"],
                    promo_text=rd["promo"],
                    fetched_at=now,
                ))
        return parsed

    async def get_restaurant(self, restaurant_id: str, location: str) -> Optional[PlatformResult]:
        token = await _get_token()
        if not token:
            return None

        headers = {**_API_HEADERS, "Authorization": f"Bearer {token}"}

        try:
            async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
                resp = await client.get(
                    SL_RESTAURANT_API.format(restaurant_id=restaurant_id),
                    params={"orderMethod": "delivery", "version": "4"},
                    headers=headers,
                )
                resp.raise_for_status()
                data = resp.json()

            restaurant = data.get("restaurant") or data
            now = datetime.now(timezone.utc).isoformat()

            menu_items = []
            for category in (restaurant.get("menu_category_list") or []):
                for item in (category.get("menu_item_list") or [])[:30]:
                    mi = _parse_menu_item(item)
                    if mi:
                        menu_items.append(mi)
                    if len(menu_items) >= 50:
                        break
                if len(menu_items) >= 50:
                    break

            rd = _parse_restaurant(restaurant)
            eta = rd["eta"]
            pickup_eta = max(5, int(eta * 0.5)) if eta else 15

            return PlatformResult(
                platform=Platform.SEAMLESS,
                restaurant_name=rd["name"] or f"Restaurant {restaurant_id}",
                restaurant_id=restaurant_id,
                restaurant_url=rd["url"],
                menu_items=menu_items,
                delivery_fee=rd["delivery_fee"],
                service_fee=rd["service_fee"],
                estimated_delivery_minutes=eta,
                pickup_available=True,
                pickup_fee=0.0,
                pickup_service_fee=0.0,
                estimated_pickup_minutes=pickup_eta,
                minimum_order=rd["minimum_order"],
                rating=rd["rating"],
                rating_count=rd["rating_count"],
                promo_text=rd["promo"],
                fetched_at=now,
            )
        except Exception as e:
            logger.warning(f"[Seamless] get_restaurant failed: {e}")
            return None
