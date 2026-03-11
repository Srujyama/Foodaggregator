"""
Grubhub scraper - Updated March 2026.

Current status:
- api-gtm.grubhub.com/auth is protected by PerimeterX bot detection.
  All anonymous token requests return 403 {"pxvid": ..., "pxuuid": ...}.
  Server-side requests cannot pass the JS challenge.
- Client ID from live config (grubhub-config JS): beta_UmWlpstzQSFmocLy3h1UieYcVST
- Old client IDs (beta_diners_prod_*) return 403 PerimeterX or 401 Invalid client_id.
- Search endpoint is /restaurants/search/search_listing (changed from /restaurants/search).
- Token is cached and refreshed when valid. Scraper returns [] gracefully when blocked.

Note: Grubhub results will be empty without a valid auth token. To enable Grubhub,
a pre-obtained bearer token can be set via GRUBHUB_BEARER_TOKEN env variable.
"""

import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional

import httpx

from app.models.food import MenuItem, Platform, PlatformResult
from app.services.scraper_base import BaseScraper, geocode

logger = logging.getLogger(__name__)

AUTH_URL = "https://api-gtm.grubhub.com/auth"
# Updated search endpoint path for 2026
SEARCH_URL = "https://api-gtm.grubhub.com/restaurants/search/search_listing"
# Fallback: old path still tried if new one fails
SEARCH_URL_LEGACY = "https://api-gtm.grubhub.com/restaurants/search"
RESTAURANT_URL = "https://api-gtm.grubhub.com/restaurants/{restaurant_id}"

# Client ID from live grubhub-config JS (March 2026)
_CLIENT_ID = "beta_UmWlpstzQSFmocLy3h1UieYcVST"
# Fallback client IDs to try if primary fails
_CLIENT_IDS = [
    _CLIENT_ID,
    "beta_diners_prod_android",
    "beta_diners_prod_ios",
    "beta_diners_prod_web",
]

# Token cache: {access_token, refresh_token, expires_at}
_token_cache: dict = {}


async def _fetch_anonymous_token() -> dict:
    """Obtain a fresh anonymous bearer token from Grubhub's OAuth endpoint."""
    for client_id in _CLIENT_IDS:
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.post(
                    AUTH_URL,
                    json={
                        "brand": "GRUBHUB",
                        "client_id": client_id,
                        "credentials": {
                            "username": "",
                            "password": "",
                            "grant_type": "anonymous",
                        },
                    },
                    headers={
                        "Content-Type": "application/json",
                        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                        "Referer": "https://www.grubhub.com/",
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    # Grubhub wraps tokens in session_handle OR at top-level
                    sh = data.get("session_handle") or {}
                    access_token = (
                        sh.get("access_token")
                        or data.get("access_token")
                        or data.get("token")
                        or ""
                    )
                    refresh_token = (
                        sh.get("refresh_token")
                        or data.get("refresh_token")
                        or ""
                    )
                    expires_in = sh.get("expires_in") or data.get("expires_in") or 3600
                    if access_token:
                        logger.info(f"[Grubhub] Got anonymous token via client_id={client_id}")
                        return {
                            "access_token": access_token,
                            "refresh_token": refresh_token,
                            "expires_at": time.time() + float(expires_in) - 60,
                        }
                    logger.warning(f"[Grubhub] Auth OK but no access_token. Keys: {list(data.keys())}")
                elif resp.status_code == 403 and "pxuuid" in resp.text:
                    logger.warning(
                        "[Grubhub] Auth blocked by PerimeterX (403). "
                        "Server-side anonymous auth is not possible. "
                        "Set GRUBHUB_BEARER_TOKEN env var with a valid token to enable Grubhub results."
                    )
                    break  # All client IDs will fail the same way
                else:
                    logger.warning(f"[Grubhub] Auth {client_id} returned {resp.status_code}: {resp.text[:300]}")
        except Exception as e:
            logger.debug(f"[Grubhub] Auth attempt {client_id} failed: {e}")

    return {}


async def _refresh_token(refresh_token: str) -> dict:
    """Refresh an existing Grubhub token."""
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(
                AUTH_URL,
                json={
                    "brand": "GRUBHUB",
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                },
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "Mozilla/5.0 AppleWebKit/537.36",
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                access_token = data.get("session_handle", {}).get("access_token") or data.get("access_token", "")
                new_refresh = data.get("session_handle", {}).get("refresh_token") or data.get("refresh_token", refresh_token)
                expires_in = data.get("session_handle", {}).get("expires_in") or 3600
                if access_token:
                    return {
                        "access_token": access_token,
                        "refresh_token": new_refresh,
                        "expires_at": time.time() + float(expires_in) - 60,
                    }
    except Exception as e:
        logger.debug(f"[Grubhub] Token refresh failed: {e}")
    return {}


async def _get_token() -> str:
    """Get a valid Grubhub bearer token, refreshing or re-fetching as needed."""
    global _token_cache

    now = time.time()

    # Check for pre-obtained token from environment variable first
    env_token = os.environ.get("GRUBHUB_BEARER_TOKEN", "").strip()
    if env_token:
        return env_token

    # Still valid
    if _token_cache.get("access_token") and now < _token_cache.get("expires_at", 0):
        return _token_cache["access_token"]

    # Try refresh first (faster than new anonymous auth)
    if _token_cache.get("refresh_token"):
        refreshed = await _refresh_token(_token_cache["refresh_token"])
        if refreshed:
            _token_cache = refreshed
            logger.info("[Grubhub] Token refreshed")
            return _token_cache["access_token"]

    # Get fresh anonymous token (likely blocked by PerimeterX in server environments)
    new_token = await _fetch_anonymous_token()
    if new_token:
        _token_cache = new_token
        return _token_cache["access_token"]

    logger.warning("[Grubhub] Could not obtain auth token")
    return ""


class GrubhubScraper(BaseScraper):
    PLATFORM_NAME = "grubhub"

    async def search(self, query: str, location: str) -> list[PlatformResult]:
        lat, lng = await geocode(location)
        token = await _get_token()

        if not token:
            logger.warning("[Grubhub] No auth token available, skipping search")
            return []

        headers = {
            "Authorization": f"Bearer {token}",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Accept": "application/json",
            "Referer": "https://www.grubhub.com/",
            "Origin": "https://www.grubhub.com",
        }

        base_params = {
            "orderMethod": "delivery",
            "locationMode": "DELIVERY",
            "facetSet": "umaNew",
            "pageSize": 20,
            "hideHateos": "true",
            "sortSetId": "umaSorts",
            "queryText": query,
            "latitude": lat,
            "longitude": lng,
            "timezoneOffset": -300,
        }

        # Try new endpoint first, fall back to legacy path
        for url in [SEARCH_URL, SEARCH_URL_LEGACY]:
            params = dict(base_params)
            if url == SEARCH_URL_LEGACY:
                # Old endpoint used different param names
                params["facetSet"] = "umamiV6"
                params["facet"] = "open_now:true"
                params["searchMetrics"] = "true"
                del params["sortSetId"]

            try:
                async with self._make_client(headers) as client:
                    resp = await client.get(url, params=params)

                if resp.status_code == 401:
                    # Token rejected - clear cache and try once with fresh token
                    logger.warning("[Grubhub] 401 on search, refreshing token")
                    global _token_cache
                    _token_cache = {}
                    token = await _get_token()
                    if token:
                        headers["Authorization"] = f"Bearer {token}"
                        async with self._make_client(headers) as client:
                            resp = await client.get(url, params=params)

                resp.raise_for_status()
                data = resp.json()

                results_data = (
                    data.get("search_result", {}).get("results", [])
                    or data.get("results", [])
                    or data.get("restaurants", [])
                    or []
                )
                parsed = self._parse_results(results_data, query, location)
                logger.info(f"[Grubhub] {len(parsed)} results for '{query}' via {url.split('/')[-1]}")
                return parsed

            except httpx.HTTPStatusError as e:
                logger.warning(f"[Grubhub] HTTP {e.response.status_code} on {url}: {e.response.text[:200]}")
                continue
            except Exception as e:
                logger.warning(f"[Grubhub] Search error on {url}: {e}")
                continue

        return []

    def _parse_results(self, results: list, query: str, location: str) -> list[PlatformResult]:
        parsed = []
        now = datetime.now(timezone.utc).isoformat()

        for item in results:
            try:
                restaurant = item.get("restaurant") or item
                rest_id = str(
                    restaurant.get("id")
                    or restaurant.get("restaurant_id")
                    or restaurant.get("restaurantId")
                    or ""
                )
                name = (
                    restaurant.get("name")
                    or restaurant.get("restaurant_name")
                    or restaurant.get("restaurantName")
                    or ""
                )
                if not name or not rest_id:
                    continue

                # Delivery fee - money object {amount, currency_code} in cents
                fee_obj = restaurant.get("delivery_fee") or {}
                delivery_fee = _cents_to_dollars(
                    fee_obj.get("amount", 0) if isinstance(fee_obj, dict) else fee_obj
                )

                service_fee_obj = restaurant.get("service_fee") or {}
                service_fee = _cents_to_dollars(
                    service_fee_obj.get("amount", 0) if isinstance(service_fee_obj, dict) else service_fee_obj
                )

                eta_min = int(
                    restaurant.get("estimated_delivery_time")
                    or restaurant.get("pickup_estimate")
                    or 35
                )

                rating_data = restaurant.get("ratings") or {}
                rating = float(rating_data.get("actual_rating_value") or 0) or None
                rating_count = int(rating_data.get("rating_count") or 0) or None

                promo_text = None
                promo_info = restaurant.get("promoted_delivery_fee") or restaurant.get("promo_info") or {}
                if isinstance(promo_info, dict):
                    promo_text = promo_info.get("promo_message") or promo_info.get("display_string")

                slug = restaurant.get("slug") or restaurant.get("restaurant_path") or ""
                url = (
                    f"https://www.grubhub.com{slug}"
                    if slug.startswith("/")
                    else f"https://www.grubhub.com/restaurant/{rest_id}"
                )

                min_order_obj = restaurant.get("minimum_order_amount")
                minimum_order = None
                if isinstance(min_order_obj, dict):
                    minimum_order = _cents_to_dollars(min_order_obj.get("amount", 0)) or None

                parsed.append(PlatformResult(
                    platform=Platform.GRUBHUB,
                    restaurant_name=name,
                    restaurant_id=rest_id,
                    restaurant_url=url,
                    delivery_fee=delivery_fee,
                    service_fee=service_fee,
                    estimated_delivery_minutes=eta_min,
                    minimum_order=minimum_order,
                    rating=rating,
                    rating_count=rating_count,
                    promo_text=promo_text,
                    fetched_at=now,
                ))
            except Exception as e:
                logger.debug(f"[Grubhub] Parse error: {e}")
                continue

        return parsed

    async def get_restaurant(self, restaurant_id: str, location: str) -> Optional[PlatformResult]:
        token = await _get_token()
        if not token:
            return None

        headers = {
            "Authorization": f"Bearer {token}",
            "User-Agent": "Mozilla/5.0 AppleWebKit/537.36",
            "Accept": "application/json",
            "Referer": "https://www.grubhub.com/",
        }

        try:
            async with self._make_client(headers) as client:
                resp = await client.get(
                    RESTAURANT_URL.format(restaurant_id=restaurant_id),
                    params={"orderMethod": "delivery"},
                )
                resp.raise_for_status()
                data = resp.json()

            restaurant = data.get("restaurant") or data
            now = datetime.now(timezone.utc).isoformat()

            menu_items = []
            for category in (restaurant.get("menu_category_list") or []):
                for item in (category.get("menu_item_list") or [])[:30]:
                    try:
                        price_obj = item.get("price") or {}
                        price = _cents_to_dollars(
                            price_obj.get("amount", 0) if isinstance(price_obj, dict) else price_obj
                        )
                        menu_items.append(MenuItem(
                            name=item.get("name", ""),
                            description=item.get("description"),
                            price=price,
                            image_url=(
                                (item.get("media_image") or {}).get("base_url")
                                if isinstance(item.get("media_image"), dict)
                                else None
                            ),
                        ))
                    except Exception:
                        continue

            fee_obj = restaurant.get("delivery_fee") or {}
            delivery_fee = _cents_to_dollars(
                fee_obj.get("amount", 0) if isinstance(fee_obj, dict) else fee_obj
            )

            return PlatformResult(
                platform=Platform.GRUBHUB,
                restaurant_name=restaurant.get("name", ""),
                restaurant_id=restaurant_id,
                restaurant_url=f"https://www.grubhub.com/restaurant/{restaurant_id}",
                menu_items=menu_items,
                delivery_fee=delivery_fee,
                service_fee=0.0,
                estimated_delivery_minutes=int(restaurant.get("estimated_delivery_time") or 35),
                fetched_at=now,
            )
        except Exception as e:
            logger.warning(f"[Grubhub] get_restaurant failed: {e}")
            return None


def _cents_to_dollars(value) -> float:
    if value is None:
        return 0.0
    try:
        v = float(value)
        return round(v, 2) if abs(v) < 50 else round(v / 100, 2)
    except (ValueError, TypeError):
        return 0.0
