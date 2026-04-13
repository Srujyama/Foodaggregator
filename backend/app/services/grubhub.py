"""
Grubhub scraper - April 2026.

Grubhub's website is a fully client-rendered SPA behind PerimeterX bot
protection. The public API at api-gtm.grubhub.com requires a valid
session token. We attempt anonymous auth and, if that fails, the scraper
gracefully returns empty results.

To enable Grubhub: set GRUBHUB_BEARER_TOKEN env var to a valid session token.
You can obtain one from your browser's network tab on grubhub.com.
"""

import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Optional

import httpx

from app.models.food import MenuItem, Platform, PlatformResult
from app.services.scraper_base import BaseScraper, geocode

logger = logging.getLogger(__name__)

GH_SEARCH_API = "https://api-gtm.grubhub.com/restaurants/search/search_listing"
GH_SEARCH_LEGACY = "https://api-gtm.grubhub.com/restaurants/search"
GH_RESTAURANT_API = "https://api-gtm.grubhub.com/restaurants/{restaurant_id}"
GH_AUTH_URL = "https://api-gtm.grubhub.com/auth"

_API_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.grubhub.com/",
    "Origin": "https://www.grubhub.com",
}

_token_cache: tuple[str, float] = ("", 0.0)


async def _get_token() -> str:
    """Get a Grubhub API token from env or anonymous auth."""
    global _token_cache
    token, expires_at = _token_cache
    if token and time.time() < expires_at:
        return token

    # Check env var first
    env_token = os.environ.get("GRUBHUB_BEARER_TOKEN", "").strip()
    if env_token:
        _token_cache = (env_token, time.time() + 3600)
        return env_token

    # Try anonymous auth
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(
                GH_AUTH_URL,
                json={
                    "brand": "GRUBHUB",
                    "client_id": "beta_UmWlpsR6GHQhCpmUCk",
                    "device_id": 1,
                    "refresh_token": "",
                },
                headers=_API_HEADERS,
            )
            if resp.status_code == 200:
                data = resp.json()
                token = data.get("session_handle", {}).get("access_token", "")
                if token:
                    _token_cache = (token, time.time() + 1800)
                    return token
    except Exception as e:
        logger.debug(f"[Grubhub] Anonymous auth failed: {e}")

    return ""


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
    """Parse a restaurant dict from the Grubhub API."""
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
    url = f"https://www.grubhub.com/restaurant/{slug}" if slug else f"https://www.grubhub.com/restaurant/{rest_id}"

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

    return MenuItem(
        name=name,
        description=description,
        price=round(price, 2),
        image_url=image_url,
    )


class GrubhubScraper(BaseScraper):
    PLATFORM_NAME = "grubhub"

    async def search(self, query: str, location: str) -> list[PlatformResult]:
        lat, lng = await geocode(location)
        token = await _get_token()

        if not token:
            logger.info("[Grubhub] No API token available. Set GRUBHUB_BEARER_TOKEN to enable.")
            return []

        headers = {**_API_HEADERS, "Authorization": f"Bearer {token}"}
        params = {
            "orderMethod": "delivery",
            "locationMode": "DELIVERY",
            "facetSet": "umaNew",
            "pageSize": 20,
            "hideHateos": "true",
            "queryText": query,
            "latitude": lat,
            "longitude": lng,
        }

        for search_url in [GH_SEARCH_API, GH_SEARCH_LEGACY]:
            try:
                async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
                    resp = await client.get(search_url, params=params, headers=headers)

                    if resp.status_code in (401, 403):
                        logger.warning(f"[Grubhub] API {resp.status_code} - token may be expired")
                        # Invalidate cached token
                        global _token_cache
                        _token_cache = ("", 0.0)
                        break

                    resp.raise_for_status()
                    data = resp.json()

                results_data = (
                    data.get("search_result", {}).get("results", [])
                    or data.get("results", [])
                )

                if not results_data:
                    continue

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
                            platform=Platform.GRUBHUB,
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

                if parsed:
                    logger.info(f"[Grubhub] {len(parsed)} results for '{query}'")
                    return parsed

            except httpx.HTTPStatusError as e:
                logger.warning(f"[Grubhub] API {e.response.status_code}")
            except Exception as e:
                logger.warning(f"[Grubhub] Search error: {e}")

        return []

    async def get_restaurant(self, restaurant_id: str, location: str) -> Optional[PlatformResult]:
        token = await _get_token()
        if not token:
            return None

        headers = {**_API_HEADERS, "Authorization": f"Bearer {token}"}

        try:
            async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
                resp = await client.get(
                    GH_RESTAURANT_API.format(restaurant_id=restaurant_id),
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
                platform=Platform.GRUBHUB,
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
            logger.warning(f"[Grubhub] get_restaurant failed: {e}")
            return None
